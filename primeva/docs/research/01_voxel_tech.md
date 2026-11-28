# Primeva – Studio tecnico: tecnologia voxel, scala del mondo, fisica, integrazione Unreal e multiplayer

Autore: ricerca engine (senior engine programmer). Stato: bozza v1 per decisione.

**Avvertenza sulle fonti.** In questa sessione non è stato usato accesso web live. Cifre e link provengono dalla conoscenza dell'autore (talk GDC, blog, paper SIGGRAPH/HPG) e sono indicati con un livello di confidenza: **[A]** alta, **[M]** media, **[B]** bassa (da verificare prima di usarla in un documento contrattuale o di budget). Gli URL vanno ricontrollati. Tutti i calcoli della sezione 2 sono invece derivati da zero e riproducibili.

---

## 0. Sintesi esecutiva (e dove contraddiciamo il cliente)

1. **Un mondo grande come l'Italia (301.000 km²) con voxel da 12,5 cm è infattibile** per storage, authoring, gameplay e popolamento. Un solo strato superficiale di chunk 32³ sarebbe 1,85 PB; l'intero volume con profondità media 500 m supera i 200 PB. Non esiste neppure il "gameplay" da riempire: attraversarlo a piedi richiederebbe ~55 ore in linea retta. Alternativa fattibile: una **mappa a forma d'Italia in scala lineare ~1:25 (~480 km²)**, con editing voxel pieno ovunque, e un **far-field a heightfield fino a ~100 km** per dare l'impressione di vastità.
2. La generazione è **deterministica on-demand**; si persistono solo i **delta delle modifiche dei giocatori**. Questa decisione già presa è corretta ed è l'unica compatibile con le cifre.
3. **Nanite non è utilizzabile per mesh voxel runtime** (stato noto a UE 5.4–5.6; da riverificare sulla versione scelta). Per la terra servono mesh dinamiche; la qualità visiva si ottiene con materiali (triplanar, virtual texturing, parallax/displacement), Lumen in HWRT e asset Nanite per rocce, alberi, props.
4. **Fisica**: voxel -> rigid body per frammenti grandi, CA deterministico per granulari e fluidi locali, acqua "statica" (livelli analitici) per fiumi/laghi/mare, simulazione solo nelle bolle attorno ai giocatori. Niente SPH server-side.
5. **Raccomandazione**: plugin custom UE5 attorno al nostro core C++20, con Voxel Plugin 2.0 usato solo come riferimento/prototipo rapido (non come base di produzione). Vertical slice 4×4 km in ~6–8 mesi con 4–5 ingegneri.

---

## 1. Stato dell'arte

### 1.1 Tabella comparativa

| Titolo / tecnologia | Dimensione voxel | Rappresentazione / rendering | Scala mondo | Fisica / note | Conf. |
|---|---|---|---|---|---|
| **Teardown** (Tuxedo Labs, D. Gustafsson) | 10 cm (scala default 0,1 m; mod possono variare) | Motore custom; ogni oggetto è una o più "shape" con volume 3D di voxel; raycasting/raymarching su texture 3D, illuminazione con raytracing custom | Livelli di ~100–300 m per lato, nessun streaming gigante | Fisica custom: la distruzione ricalcola le componenti connesse (flood fill) e crea nuovi corpi; corpi con budget limitato; nessun multiplayer | [M] |
| **Enshrouded** (Keen Games) | Terreno "smooth voxel" con griglia di ordine decimetrico–mezzo metro (cifra esatta non verificata) | Voxel editabili con mesh lisce e blocchi di costruzione; scavo e costruzione ovunque | Mappa ~24 km² (Embervale), in espansione con update | Edit persistenti per giocatore; server fino a 16 giocatori. Dimostra che 16 player e ~24 km² sono la scala "premium" attuale per voxel editabili con fedeltà alta | [M]/[B] sui dettagli |
| **Voxel Plugin 2.0** (Phyronnaz, UE5) | Configurabile (tipicamente 25 cm–1 m+) | SDF/volume layers, Voxel Graph, stamps non distruttivi, mesh con Marching Cubes/Transvoxel-like, LOD, collisione Chaos, supporto Lumen/Nanite da verificare | Largo ma limitato da float/double e dal tuo budget | Licenza commerciale su Fab: **verificare termini attuali** (Voxel Plugin 1.x era a pagamento; la 2.0 ha avuto early access e modello di pricing diverso). Netcode editing non "chiavi in mano" per 100 player | [M]/[B] |
| **Space Engineers** (Keen) | ~1 m (celle voxel di materiale; LOD con fino a 8 livelli) | Pianeti/asteroidi voxel con mesh (dual-contouring-like) e LOD; blocchi su griglia separata | Pianeti raggio 60 km (default), fino ~120 km | Fisica Havok; terreno voxel non partecipa a rigid body in modo fine; server fino a 16–50 player | [M] |
| **Astroneer** (System Era, UE4) | ~ordine del metro (terreno morbido, deformazione "terrain tool") | Marching cubes sferico; replica di operazioni di deformazione | Pianeti piccoli (raggio dell'ordine di centinaia di metri–pochi km) | Tool di deformazione replicati come operazioni deterministiche; dimostra l'approccio *op-log* | [M] |
| **Seed of Andromeda** (Ben Arnold, Vortex) | ~1 m, chunk 32³ | Terreno a blocchi su pianeti sferici, generazione CPU, chunk 32³ | Pianeti a scala città/regione | Blog dev dettagliati sul chunk management e sul meshing (greedy + LOD); progetto fermo | [M] |
| **Lay of the Land** | **Non verificato**: l'autore non ha dati affidabili su questo titolo; da non usare come riferimento finché non confermato | – | – | – | [B] |
| **John Lin – Voxel Engine** (tech demo) | ~ pochi cm (ordine 1–10 cm) | Rendering path-traced/raytraced custom su volumi 3D, con CA per fluidi/fuoco/crollo | Scene (non mondo aperto) di decine–centinaia di metri | Dimostra che CA 3D (acqua, fuoco, fumo, crolli) a 1–10 cm è fattibile su GPU ma in volumi limitati | [M] |
| **Douglas Dwyer – Voxel Engine** | ~ pochi cm; octree/sparse voxel su GPU | Raymarching di sparse voxel tree | Volumi da centinaia di metri | Esperimenti su "unlimited detail" volume; mostra limite: editing + illuminazione globale difficili | [B] |
| **SVDAG** (Kämpe, Sintorn, Assarsson, "High Resolution Sparse Voxel DAGs", SIGGRAPH 2013) | Risoluzione 128K³ (131.072³) | Octree -> DAG con condivisione di sottoalberi identici | Scena "Epic Citadel" in ~1 GB circa | Sola lettura (statico). Estensioni: Symmetry-aware SVDAG (Villanueva 2016), HashDAG (Careil, Billeter, Eisemann 2020) per DAG **editabili** | [M] |
| **Noita** (Nolla Games) | 1 pixel = 1 "cella" (scala ~ cm) | Automa cellulare su griglia 2D con tutti i materiali; ogni materiale ha regole; chunk 64×64 con checkerboard multithread (talk GDC 2019, Petri Purho) | Mondo 2D di 35k×? pixel generato a chunk (512²) | Tutto è un CA: sabbia, acqua, lava, gas; deterministico se l'ordine di aggiornamento è fisso | [A] |
| **Minecraft** | 1 m, sezioni 16³ | Mesh a blocchi | Bordo mondo ±30M blocchi = 3,6·10⁹ km² (ma generato solo dove si va) | Chunk generati lazy, salvataggio solo chunk modificati/visitati | [A] |
| **No Man's Sky** | ~ordine del metro | Terreno voxel (generazione continua), seed deterministico | 1,8·10¹⁹ pianeti, ma ciascuno è ~ decine di km | GDC 2017 "Continuous World Generation in No Man's Sky" (I. McKendrick): generazione deterministica on demand, nessuno storage per mondo | [M] |

Riferimenti (da ricontrollare):
- Teardown breakdown tecnico (non ufficiale): https://juandiegomontoya.github.io/teardown_breakdown.html
- Blog Tuxedo Labs: https://blog.tuxedolabs.com/
- Noita, GDC 2019 "Exploring the Tech and Design of Noita": https://www.gdcvault.com/play/1025695/Exploring-the-Tech-and-Design
- Kämpe et al., High Resolution Sparse Voxel DAGs: https://research.chalmers.se/en/publication/188718 (pagina di ricerca Chalmers; PDF sul sito dell'autore)
- Careil et al., Interactive Ray Tracing of Large Voxel Scenes with HashDAG (HPG/High Perf Graphics 2020).
- Surface Nets / Dual Contouring: Gibson 1998; Ju et al. 2002; Transvoxel: https://transvoxel.org/ (E. Lengyel).
- Voxel Plugin: https://voxelplugin.com/ e pagina Fab.

### 1.2 Lezioni trasversali

- **Nessun gioco di successo rende modificabile un mondo regionale a 12,5 cm.** Il massimo noto è ~24 km² con voxel decimetrici-mezzo metro (Enshrouded) e il passo "spettacolare" a 10 cm (Teardown, John Lin) è su volumi di poche centinaia di metri.
- **GPU ray-marched voxels vs mesh.** Il raymarching di SVDAG/octree dà densità enorme (128K³ in ~1 GB), ma: (a) l'editing locale richiede DAG editabili (HashDAG), costoso; (b) non si integra con Nanite/Lumen/shadow map di UE5 senza una pipeline di render custom completa; (c) la GI è difficile; (d) l'asset pipeline (Blender -> voxel) si complica. **Per Primeva (UE5, ombre, GI Lumen, asset Nanite) la via mesh è nettamente più sicura.** Il raymarching potrebbe servire solo come tecnica opzionale per il far-field (impostor volumetrico), non per il terreno principale.
- **Suddivisione per ruoli**: Minecraft/NMS/SoA insegnano streaming e determinismo; Teardown/Noita insegnano distruzione e CA; Enshrouded insegna "smooth voxel editabili + server player" oggi.

---

## 2. Matematica di prima mano per un mondo grande come l'Italia

### 2.1 Costanti

- Voxel: 0,125 m, quindi 8 voxel/m e 512 voxel/m³.
- Chunk 32³ = 32.768 voxel = 4 m di lato = 64 m³.
- Dato per voxel: SDF int8 (1 B) + material id 16 bit (2 B) = **3 B/voxel**.
- **Chunk denso = 32.768 × 3 = 98.304 B ≈ 96 KiB.**
- Area Italia: 301.000 km² = 3,01·10¹¹ m².
- Colonne di chunk (4×4 m = 16 m²): 3,01·10¹¹ / 16 = **1,88·10¹⁰ colonne**.
- Risoluzione di precisione SDF: int8 con scala 1/16 di voxel (range ±8 voxel) -> 1/16 × 12,5 cm ≈ **7,8 mm** di risoluzione sub-voxel: ottima per lo smooth meshing.

### 2.2 Cosa succederebbe se lo si memorizzasse

| Scenario | Calcolo | Risultato |
|---|---|---|
| Solo 1 chunk di spessore sulla superficie (4 m) | 1,88·10¹⁰ × 96 KiB | **≈ 1,85 PB** |
| Volume pieno, profondità media 500 m (da quota media a base) | 3,01·10¹¹ m² × 500 m × 512 voxel/m³ × 3 B | 3,01·10¹¹×500 = 1,5·10¹⁴ m³ -> ×512 = 7,7·10¹⁶ voxel -> **2,3·10¹⁷ B ≈ 230 PB** |
| Solo il primo strato di voxel superficiali, 1 B/voxel | 3,01·10¹¹ m² × 64 voxel/m² | 1,9·10¹³ voxel = **19 TB** (senza materiali, senza volume) |
| Pre-generare tutti i chunk superficiali a ~3 ms/chunk/core | 1,88·10¹⁰ × 3 ms | 5,6·10⁷ core-s ≈ **15.700 core-ore** (fattibile sul cloud) **ma** il risultato (anche compresso a 10 KiB/chunk) sarebbe ~190 TB |

**Conclusione**: lo storage "bake" è fuori dal budget. L'unica strada è generare a runtime. La generazione dei volumi interrati è ancora più sparsa perché ~95% dei chunk è uniforme (roccia piena o aria): si usa un bound analitico su altezza/strati per saltarli (non si generano né si memorizzano).

### 2.3 Confronto con Minecraft e con il gameplay

- Minecraft: 60M × 60M blocchi = 3,6·10¹⁵ colonne. Italia a 12,5 cm: 1,93·10¹³ colonne = 0,5% di Minecraft in colonne, ma ciascuna è molto più costosa (smooth SDF + materiali + caverne) e il rendering deve vedere ~100 km, non 16 chunk.
- **Tempo di attraversamento** (lunghezza ~1.200 km da nord a sud lungo l'asse della penisola):
  - Corsa a 6 m/s: 1.200.000 / 6 = 200.000 s = **55,6 ore**.
  - A cavallo/mount 15 m/s: 22 ore. In volo a 40 m/s: 8,3 ore.
- **Densità di giocatori**: 100 giocatori su 301.000 km² = 0,00033 giocatori/km² (un giocatore ogni 3.010 km²). Il mondo sarebbe quasi interamente vuoto: non serve né può essere riempito di creature con design curato (ARK Island: dell'ordine di decine di km²; Rust ~4–16 km²).
- **Contenuto**: a 1 biome-pezzo di 1 km² ogni 4 ore di authoring, 301.000 km² = impossibile. Anche procedurale, un "ambiente elaborato, realistico e bello" non si ottiene senza passate di cura.

### 2.4 Alternativa proposta: mappa "a forma d'Italia" in scala ridotta

| Scala lineare | Area | Lunghezza N-S | Tempo a piedi (6 m/s) | Comment |
|---|---|---|---|---|
| 1:1 | 301.000 km² | 1.200 km | 55 h | Non fattibile |
| 1:10 | 3.010 km² | 120 km | 5,5 h | Possibile come far-field, non popolabile a mano |
| **1:25** | **~480 km²** | **48 km** | **2,2 h** | **Raccomandata**: 10× più grande di ARK Island (~50 km²), 20× Enshrouded |
| 1:50 | ~120 km² | 24 km | 1,1 h | Opzione conservativa |

Con scala 1:25 si mantengono la forma riconoscibile, le grandi unità geologiche (Alpi, Pianura Padana, Appennini, vulcani, Sardegna/Sicilia, Puglia carsica) e si può esagerare il rilievo verticale (indicativamente 1:5–1:8 anziché 1:25, per non appiattire le montagne). Il dato topografico reale (es. DEM Copernicus GLO-30, TINITALY 10 m, CC BY 4.0 – licenze da verificare) viene ridotto e arricchito per erosione e dettaglio procedurale.

**Gli stessi calcoli a 480 km²**: 3,0·10⁷ colonne (4×4 m), 3,0·10⁷ chunk superficiali ≈ 2,9 TB se densi: ancora non si memorizza. Il dataset *macro* (altezza, strati, era, bioma, fiumi, grafo di caverne) a 16 m di cella: 480·10⁶/256 ≈ 1,9·10⁶ celle × ~10 B ≈ 19 MB: **insignificante**.

### 2.5 Schema LOD (clipmap a 8 livelli) e distanza di visione

Livello L ha voxel di 0,125 × 2^L m. Per ogni livello un anello di raggio 512 voxel (1024 voxel di lato = 32 chunk 32³):

| L | Voxel | Raggio anello | Rapporto voxel/distanza al bordo | Pixel a 1080p, FOV 90° (≈0,047°/px) |
|---|---|---|---|---|
| 0 | 0,125 m | 64 m | 1/512 rad = 0,112° | ≈2,4 px |
| 1 | 0,25 m | 128 m | 0,112° | 2,4 px |
| 2 | 0,5 m | 256 m | 0,112° | 2,4 px |
| 3 | 1 m | 512 m | 0,112° | 2,4 px |
| 4 | 2 m | 1.024 m | 0,112° | 2,4 px |
| 5 | 4 m | 2.048 m | 0,112° | 2,4 px |
| 6 | 8 m | 4.096 m | 0,112° | 2,4 px |
| 7 | 16 m | 8.192 m | 0,112° | 2,4 px |

La densità angolare è costante (~2–2,5 px per voxel al bordo di ogni anello), tipica dei clipmap; con smooth meshing e normal-map la qualità è accettabile. Il raggio di 512 voxel è un parametro: ridurlo a 256 dimezza costi e dimezza anche la "distanza di qualità".

**Costi per livello** (anello 1024×1024 voxel di lato, esclusa la parte interna già coperta dal livello più fine ≈ 3/4 di area):
- Colonne di chunk per livello: 32 × 32 = 1.024 (L0 intero) o ~768 (L1–L7).
- Chunk superficiali per colonna (rilievo e cunicoli): ~2–3 -> **~2.300 chunk/livello**, ~**18.000 chunk** su 8 livelli.
- Triangoli per chunk con Surface Nets: ~1,2 quad per voxel di superficie sul piano ~32² = ~1.200 quad = **~2.500 triangoli**. Totale non scartato: 18.000 × 2.500 = **45 M triangoli**, dopo frustum culling (~1/4 del cerchio per un FOV 90°) e occlusione (~-30%) -> **~8 M triangoli visibili**. Senza Nanite questo è al limite per console/PC medio. Mitigazioni: ridurre il raggio degli anelli a 256 voxel (-75% = ~2 M tri), semplificazione quadric decimation sul mesh per i livelli L≥3, e soglie di "chunk piatti" (le zone pianeggianti in superficie producono pochi triangoli utili).
- **Memoria mesh**: vertici quantizzati a 12 B + indici 16 bit: ~30 KB/chunk -> 18.000 × 30 KB = **~540 MB** VRAM/RAM; per questo a runtime non si tengono i dati voxel dei livelli ≥ L3 (si rigenerano o si leggono dalla pila macro + delta).
- **Dati voxel residenti**: L0–L2 (~3 × 2.300 chunk × 96 KiB = ~660 MB raw; con compressione e uniformità, ~150–250 MB).

**Orizzonte reale e far-field**:
- Distanza orizzonte d ≈ 3,57·√h km (h in metri, Terra sferica R = 6.371 km): occhi a 2 m -> 5 km; collina 100 m -> 36 km; cima 1.000 m -> 113 km; cima 3.000 m -> 195 km (calcolati sopra).
- L'anello più lontano voxel (L7) arriva a **8 km**. Oltre servono un **heightfield/clipmap di terreno + impostor**. A 100 km, con 1.920 px per FOV 90°, un pixel è ~104 m: un heightfield a **32–64 m** di cella è più che sufficiente, a 32 m: (200 km)² / 1.024 m² = 3,9·10⁷ campioni × 2 B = **78 MB** per un raggio di 100 km; l'intera Italia (1:1) a 32 m sarebbe ~590 MB, a 16 m ~2,4 GB.
- Il far-field è derivato dalla stessa pila macro del generatore, quindi coerente con il livello L7. Modifiche dei giocatori **non** vengono mostrate oltre L7 (accettabile: una base si "vede" da 8 km, non da 100).
- Nebbia atmosferica/Sky Atmosphere + volumetric clouds di UE mascherano la transizione. Ombre lontane: Virtual Shadow Maps / Cascaded + Distance Field Shadows non disponibile su mesh dinamiche -> far-field senza self-shadow (baked).

### 2.6 Streaming e carico di generazione

Giocatore a piedi, 8 m/s. Anello L0: 32 chunk di lato (4 m ciascuno): attraversare un bordo di chunk (4 m) richiede 0,5 s; ogni attraversamento richiede una fila di 32 colonne × 3 chunk ≈ 100 chunk nuovi -> **~200 chunk/s a L0**. Ogni livello superiore dimezza il tasso (chunk grandi il doppio, stesso numero per anello): somma geometrica ≈ **~400 chunk/s** totale.

- Costo per chunk: generazione ~0,3–1 ms (SIMD, FBM 4 ottave, ~50–200 Mvoxel/s/core) + meshing Surface Nets ~0,3–0,5 ms (~100 Mvoxel/s/core) + upload. ~1,5 ms/chunk con margini -> 400 chunk/s = **0,6 core-s/s** (3–4 thread di lavoro con margine).
- A cavallo (30 m/s): ×3,75 -> 1.500 chunk/s = ~2,3 core; in volo (60 m/s) ~3.000 chunk/s: richiede limitare i livelli fini (non generare L0–L2 se la velocità è alta: LOD adattivo alla velocità).
- **Banda di rete**: i chunk non viaggiano in rete: il client rigenera il terreno deterministico e riceve solo i **delta**. Questo è il vincolo critico: **determinismo bit-esatto cross-piattaforma** del generatore (niente `-ffast-math`, nessuna contrazione FMA non controllata, `sin/cos/exp` della libreria standard proibiti in favore di implementazioni proprie o aritmetica a virgola fissa/interi). Rete: se il client si discosta di 1 LSB sulla SDF, la geometria differisce dal server (collisioni sbagliate al limite).

### 2.7 Storage e banda server per le modifiche

- **Chunk modificato**: SDF+materiali delta compressi (zstd/LZ4 + RLE su zone uniformi) ~ **10–30 KiB** medi (96 KiB raw).
- **Stanza scavata** 20×20×10 m = 4.000 m³ -> 2,05·10⁶ voxel; chunk toccati: 4.000/64 ≈ 63 pieni + ~30 di bordo = **~95 chunk × ~20 KiB ≈ 1,9 MB**.
- Base grande: ~10 stanze + gallerie = **~20 MB**. 100 giocatori con base media di 2.000 chunk modificati = 200.000 chunk × 20 KiB = **4 GB**; worst case 10× = 40 GB per mondo. Su NVMe è banale; il vincolo è il lavoro di caricamento, non lo spazio.
- **Op-log vs snapshot**: una picconata sferica (r = 1 m -> 8 voxel -> ~2.100 voxel, ≤ 8 chunk) si registra come operazione (centro int32×3, raggio, materiale, tick: ~20 B) anziché come 8 chunk: il log compatto è piccolo e rapidissimo da replicare; si **ricompatta periodicamente** in snapshot per chunk (es. quando un chunk supera 64 operazioni o a ogni salvataggio).
- **Esplosione** r = 5 m: 523 m³ / 64 ≈ 8 chunk pieni + ~25 di bordo: ~33 chunk, ~700 KiB di snapshot (non conviene trasmettere snapshot: replicare l'operazione).
- **Banda per client**: edit manuali (3/s × 20 B) = trascurabili; frane/crolli/granulari producono 10⁴–10⁵ delta voxel: a ~2 B/voxel RLE -> 20–200 KB a raffica; con tetto di 64–128 KB/s per client e priorità per distanza.

### 2.8 Cache server e memoria

- 100 giocatori; solo raggio "voxel autoritativo" attorno ad ogni entità attiva: 64 m -> π × 64² = 12.900 m² / 16 = 804 colonne × 3 chunk = **2.400 chunk ≈ 232 MB per giocatore** non compressi, **~23 GB** per 100 giocatori nel caso peggiore (nessuna sovrapposizione); con compressione 4:1 e sovrapposizione clan: **~5–8 GB**. Gestibile con 64 GB di RAM. Per le zone intatte basta tenere la funzione di generazione (non una copia densa) e la cache LRU.

---

## 3. Piano fisica

### 3.1 Principio: tre regimi

| Regime | Rappresentazione | Dove vive | Esempi |
|---|---|---|---|
| **Statico** | SDF/voxel (mondo) | Mondo, tutto | Terreno, rocce, basi |
| **Granulare/fluido locale** | Automa cellulare su voxel attivi | Server, bolle attorno ai giocatori | Sabbia, ghiaia, acqua da scavo, lava |
| **Corpi rigidi** | Rigid body (Chaos) con hull convessi approssimati | Server (autoritativo) | Frammenti di crollo, rocce rotolanti, detriti |

### 3.2 Distruzione e frammenti rigidi

1. Dopo un edit, marcare dirty la regione (chunk + bordo).
2. **Componenti connesse**: flood fill a 6 vicini sulla maschera solido (SDF<0). Costo: ~10 ns/voxel -> 0,33 ms/chunk. Per regioni 3×3×3 chunk, lavorare su **super-voxel 4³** (512 nodi/chunk) con union-find: 27 × 512 ≈ 14.000 nodi -> sub-millisecondo. Si raffina a risoluzione piena solo per le componenti candidate.
3. **Ancoraggio**: nodi "ancora" = bedrock/fondale e, per costruzioni, elementi marcati. Componenti non connesse a un'ancora diventano **frammenti**.
4. **Stabilità strutturale / crolli (cave-in)**: modello semplificato, deterministico e a basso costo, non un FEM. Per ogni cella del soffitto di una cavità, calcolare la distanza orizzontale (EDT/chamfer) dal più vicino pilastro di supporto; se supera **L_max(materiale)** (es. roccia compatta 12 m, arenaria 6 m, terra 2 m, sabbia/ghiaia 0 m, con coefficiente per spessore del soffitto) si innesca un collasso progressivo. Il collasso emette frammenti e riempie la cavità con detriti granulari. Questo dà gameplay di "puntellatura" delle miniere senza risolvere equazioni.
5. **Soglie per tipo di risultato** (dimensione frammento): ≥ 0,5 m³ (256 voxel) -> rigid body; 0,05–0,5 m³ -> corpo rigido semplice (box/sfera) a vita breve; < 0,05 m³ -> particelle visive client-side e deposito CA sul terreno.
6. **Re-voxelizzazione**: un frammento che va in sleep per > 2 s viene re-fuso nel mondo come voxel (reinserito nella SDF) per eliminare corpi rigidi persistenti.
7. **Collisione**: giocatori/creature usano un controllore custom (sweep di capsula contro la SDF, deterministico, nessun cooking di mesh); i corpi rigidi usano Chaos con **trimesh dei soli chunk L0 vicini ai detriti** (cooking asincrono ~3–10 ms/chunk), oppure collisione custom voxel–hull se Chaos si rivela insufficiente (v. rischi).

### 3.3 Materiali granulari

- Automa su voxel attivi: un grano si muove giù; se bloccato prova diagonale se la differenza di quota è sufficiente. Con regola base si ottiene pendenza ~45°. Per ottenere l'**angolo di riposo** fisico (sabbia secca ~34°, ghiaia ~38–40°, terra umida ~45°) si usa una soglia per materiale + dithering deterministico per hash (x,y,z,tick): tan(34°) ≈ 0,67 -> scorre se Δh/Δx > 0,67.
- **Costo**: un franamento di 100 m³ = 51.000 voxel attivi × ~20 ns = ~1 ms/tick. Un franamento di 10.000 m³ (5 M voxel) è troppo: passa a **super-voxel/coarse CA** (blocchi 4³, 0,5 m) con rifinitura solo alla chiusura. Cap di sicurezza: max 200.000 celle attive/tick; oltre, accumulo in coda.
- Multithread con **checkerboard di chunk** (come Noita) e ordine di aggiornamento fisso (per coordinate) -> deterministico.

### 3.4 Fluidi: confronto

| Approccio | Pro | Contro | Giudizio per Primeva |
|---|---|---|---|
| **CA a livelli** (volume 0–255 per cella, stile Minecraft/Noita) | Intero-only, deterministico, economico, integra con voxel; locale | Poca fisica (niente pressione/inerzia), movimento "a gradini" | **Base per acqua/lava locale e allagamenti di scavi** |
| **SPH/FLIP particellare** | Splash e turbolenza realistici | Costosissimo (100k particelle ~ ordine di un volume di pochi m³ a risoluzione sensata), non deterministico su GPU/float, impossibile replicare | **Solo cosmetico client-side (Niagara)** |
| **Heightfield shallow water** (virtual pipes) | Ottimo per fiumi, laghi, inondazioni 2D; GPU 1024² ~1–2 ms | Non volumetrico (no cascate/caverne sommerse) | **Opzionale per fiumi dinamici/piene; non obbligatorio** |
| **Livelli analitici statici** (mare, laghi, fiumi con livello per bacino) | Zero costo, deterministico | Non reagisce allo scavo | **Default per l'acqua del mondo**; reazione a scavo con CA solo quando una breccia connette un volume a una cavità |

Raccomandazione: acqua del mondo statica + **CA a risoluzione 0,5 m (blocchi 4³)** attivato solo per falde/gallerie allagate e lava; la lava ha viscosità (tick 1/4) e si raffredda in roccia (temperatura intera deterministica). Budget fluidi server: 1–2 ms/tick a 10 Hz.

### 3.5 Determinismo e autorità server

- Tutta la logica gameplay-rilevante (voxel, CA, crolli, danni) gira **solo sul server** a tick fisso (30 Hz, CA a 10–15 Hz), con aritmetica intera/fissa, generatori `xoshiro`/hash per (coordinata, tick, seed). Nessuna dipendenza da float non controllati nella simulazione voxel.
- Client: riceve operazioni e delta; applica la stessa edit locale con predizione (ritardo nascosto) e riconcilia sull'ack del server. Corpi rigidi: Chaos server, repliche di transform (con quantizzazione e interpolazione); i client simulano solo cosmetica.
- Replay/debug: l'op-log + seed consente di riprodurre le sessioni (utile per bug di sincronizzazione).

### 3.6 Budget indicativi per frame (server 30 Hz = 33 ms; client 60 fps = 16,6 ms)

| Voce | Server (ms/tick) | Client (ms/frame) |
|---|---|---|
| Edit/CSG voxel e dirty tracking | 2 | 0,5 (predizione locale) |
| Meshing + generazione | — | thread worker (≤ 4 core), upload ≤ 1 ms su game thread, ≤ 8 chunk/frame |
| CA granulare + fluidi | 3–4 | — |
| Rigid body (Chaos) | 5 | 1 (solo interpolazione) |
| IA creature (≈600–2.000 attive) | 8 | 0,5 |
| Rete/serializzazione/relevancy | 5 | 0,5 |
| Reserva/varianza | 8 | — |

---

## 4. Integrazione in Unreal Engine 5: opzioni in ordine di preferenza

Stato versione: le affermazioni su UE 5.4–5.6 sono dalla conoscenza dell'autore; la tabella di sotto va **riverificata sulla versione di UE scelta** (release notes e documentazione Epic).

### 4.1 Opzioni

| # | Opzione | Pro | Contro |
|---|---|---|---|
| **1 (raccomandata)** | **Plugin custom: core C++20 engine-agnostic + modulo UE** che crea mesh con **RealtimeMeshComponent** (RMC) o `UDynamicMeshComponent`/`UProceduralMeshComponent`, con gestione chunk e LOD propria | Controllo totale su determinismo, netcode, rete, persistenza, LOD; nessuna dipendenza da roadmap esterna; core testabile fuori da UE e riusabile (server headless) | Costo di sviluppo alto (6–12 mesi-uomo per un sistema solido); vanno costruiti da zero LOD stitching, materiali, collisione async |
| 2 | **Voxel Plugin 2.0** (Phyronnaz) come base | Time-to-first-pixel rapido (settimane), Voxel Graph, stamps, collisione, editor integrato | Licenza/royalty/termini da verificare; non rispetta il nostro formato dati (int8 SDF + material 16 bit) e il nostro requisito di determinismo cross-piattaforma; netcode editing per 100 giocatori da costruire; rischio di dipendenza da un solo autore; meno controllo sul far-field. Supporto Nanite/Lumen: verificare; per la qualità a 12,5 cm serve comunque lavorare ai materiali |
| 3 | UE **Landscape + Nanite Landscape** per la superficie e voxel solo per sottosuolo/scavo | Ottima resa visiva del terreno aperto, Nanite sul terreno, World Partition nativo | Due sistemi da cucire ("buchi" Landscape per ingressi caverne), editing non uniforme (non si può scavare un fianco di montagna in modo coerente), perdita del concetto "mondo completamente scavabile" |
| 4 | Motore voxel raymarched custom in compute | Densità massima | Fuori dal pipeline UE (Lumen, VSM, Nanite): sostituire il renderer. Scartato |

### 4.2 Tecnologie UE: stato e implicazioni

- **Nanite**: richiede dati di cluster costruiti offline; fino a UE 5.6 **non** supporta mesh generate a runtime con ricostruzione continua (stato noto; riverificare in 5.7+). Impatto: terreno = mesh dinamiche normali (rischio di overdraw/triangoli: vedi §2.5). Nanite resta ideale per rocce, alberi (foliage Nanite), props, rovine: **il terreno voxel viene "vestito" con asset Nanite** per nascondere la geometria uniforme.
- **Lumen**: Software Lumen su mesh dinamiche usa surface cache e il Global Distance Field, quindi la qualità sulla mesh runtime è inferiore (nessun mesh distance field per mesh non statiche); **Hardware RT Lumen** funziona meglio con geometria procedurale ma richiede GPU RT. Piano: HWRT su PC high-end, software + illuminazione "fake" nelle caverne (luci dinamiche, emissive, fog volumetrico) altrove. Le caverne profonde sono un caso difficile per la GI: richiedono attenzione artistica (luci locali, bioluminescenza).
- **Collisione Chaos da mesh runtime**: il cooking di trimesh è asincrono e costa ordine ~3–10 ms per chunk: non lo si fa per tutti i chunk. Strategia: collisione custom SDF per personaggi/creature (nessun cooking), Chaos trimesh solo dove servono rigid body.
- **World Partition**: pensato per cell di attori statici; **non** adatto a gestire chunk voxel dinamici. Si usa il nostro streaming voxel, e World Partition solo per attori hand-placed (landmark, rovine, dungeon authored, insediamenti NPC) e per HLOD di quei contenuti.
- **Large World Coordinates (LWC)**: UE5 usa double per le trasformazioni; 1.200 km = 1,2·10⁸ cm, ben dentro i limiti (~88 milioni di km di range). I nostri int32 voxel coord coprono 2³¹ × 0,125 m = 268.000 km: più che sufficiente. Rendering camera-relative: nessun problema; attenzione agli shader custom (usare `LWC` helper e offset tile).
- **Dedicated server**: compilare il core come libreria statica Linux; il modulo UE server **non** costruisce mesh né materiali (headless). Server UE standard per ARK-style. Il carico dominante è CPU (IA, CA, Chaos): servono CPU con alto clock.
- **Replica dei delta (Iris)**: Iris (nuovo sistema di replica, sperimentale in 5.4, in maturazione in 5.5–5.6: da verificare) è orientato ad attori/proprietà; per i voxel conviene **non** passare per UPROPERTY di attori, ma avere un **sottosistema di streaming voxel dedicato** con (a) sottoscrizione per connessione a regioni di chunk, (b) versione per chunk (contatore monotono), (c) snapshot compresso per l'ingresso nella regione e **delta incrementali** (op-log) dopo, (d) canale affidabile ordinato separato dal traffico di gioco. Iris può restare per attori (creature, giocatori) con relevancy basata sulla nostra griglia spaziale.

---

## 5. Architettura multiplayer

### 5.1 Numeri di riferimento (approssimati)

- **ARK**: server ufficiali ~70 giocatori; tick tipicamente 15–30 Hz con mappe di decine di km²; cluster con trasferimento tra mappe (ogni mappa = processo separato). **Conan Exiles** ~40–70. **Atlas**: griglia di server (~15×15) con confini transitabili ("seamless", con limiti). **Star Citizen/EVE**: server meshing/zone con enorme complessità. [M]

### 5.2 Proposta: "un processo = un mondo" prima, "zone" poi

- **Fase A (consigliata)**: un processo server autoritativo per **istanza di mondo** (480 km²). Il server simula solo "bolle" attorno ai giocatori (raggio ~150–200 m per IA e fisica, 64 m per voxel autoritativo); il resto è congelato (stile ARK) o simulato statisticamente. Capacità ~70–100 giocatori. Scalabilità orizzontale con **shard identici** (mondi paralleli, ciascuno con i propri delta).
- **Fase B (solo se serve oltre ~200 giocatori per mondo)**: partizione in **zone** (griglia 2×2 km o aree geologiche) ciascuna proprietà di un processo; handoff di giocatori e creature ai confini, edit di confine con due fasi (prepare/commit) o con una "fascia di sovrapposizione" di 1 chunk. Complessità alta; il formato dati (chunk con id di regione) va già predisposto, ma non implementato nella v1.
- **Densità**: 100 giocatori su 480 km² ≈ 0,2 giocatori/km². Aree attive massime: 100 × π × 0,2² = 12,6 km² (6% del mondo nel caso peggiore, con nessuna sovrapposizione).

### 5.3 Creature

- Popolazioni **deterministiche per regione** (seed, specie per bioma/era e caverne), istanziate quando una bolla le raggiunge; stato persistente solo per **creature addomesticate** e per quelle uniche/boss.
- Densità ~50 creature/km² attive -> **~600 creature attive** tipiche, picco ~2.000. IA a LOD: <50 m piena, 50–150 m ridotta (tick 5 Hz), >150 m congelata.
- **Navigazione 3D**: navmesh classico non basta (caverne, scavo dinamico). Si usa un **grafo di navigazione a super-voxel** (celle 0,5 m) rigenerato localmente alle modifiche, con A* gerarchico (grafo di chunk + A* a risoluzione fine). Le caverne naturali producono anche un **grafo di caverne** deterministico (nodi/archi) usato dallo spawner per posizionare creature sotterranee.

### 5.4 Edit e consistenza

- Il client invia *intenzioni* (ray, strumento, materiale); il server valida (distanza, cooldown, permessi/clan), applica, assegna numero di versione al chunk e replica l'operazione ai client interessati.
- Priorità e budget: per client 64–128 KB/s; coda prioritaria per distanza e per rilevanza (edit nel frustum vicino -> alta; frane lontane -> bassa). Gli edit più recenti sostituiscono quelli obsoleti.
- **Persistenza**: write-behind su un database a chiave (chunk coord, livello) -> blob compresso (RocksDB/LMDB o SQLite su NVMe) con WAL dell'op-log; snapshot incrementale ogni 5–10 min; backup su object storage.

---

## 6. Raccomandazione, rischi e piano per milestone

### 6.1 Raccomandazione

1. **Mondo**: ~480 km² a forma d'Italia (1:25, rilievo verticale esagerato 1:5–1:8), non 301.000 km². Generazione ibrida: macro-mappe (altezza erosa, strati, era/bioma, fiumi, grafo caverne) dall'editor (Gaea/World Machine/Houdini + Blender per asset) -> **generazione voxel deterministica** a runtime con le macro come input.
2. **Core**: libreria C++20 engine-agnostic con SDF int8 + 16 bit di materiale, chunk 32³, coordinate int32, clipmap a 8 livelli, Surface Nets con stitching/skirts tra livelli, determinismo con aritmetica controllata, op-log + snapshot per i delta.
3. **Unreal**: plugin custom (RealtimeMeshComponent o DynamicMesh) + sottosistema di streaming voxel + collisione SDF custom. Voxel Plugin 2.0 solo per prototipi di materiali/LOD in ambiente di test.
4. **Rendering**: Lumen HWRT dove disponibile, materiali triplanar + virtual texturing + parallax/displacement, asset Nanite per densità visiva, volumetric fog nelle caverne, far-field heightfield + impostor oltre 8 km.
5. **Fisica**: server-authoritative, CA deterministico locale, rigid body per frammenti, crolli con modello di supporto semplificato, acqua del mondo statica con CA locale.
6. **Multiplayer**: un processo per mondo, shard paralleli, bolle di simulazione; zone solo se necessario.

### 6.2 Rischi (probabilità/impatto, mitigazione)

| Rischio | P | I | Mitigazione |
|---|---|---|---|
| Determinismo cross-piattaforma del generatore (Linux server vs Windows/console client) | Alta | Alto | Aritmetica intera/fissa, libm propria, test di regressione hash per chunk su tutte le piattaforme (CI) |
| Triangoli senza Nanite (~8 M a pieno raggio) | Alta | Medio | Raggio anello 256, decimazione per L≥3, impostor, profilo su hardware target (non solo PC top) |
| Illuminazione nelle caverne profonde (Lumen su mesh dinamiche, software) | Media | Alto | HWRT, luci locali, "light probe volume" authored, autoesposizione, requisito GPU RT per ultra |
| Cooking collisione Chaos per frammenti | Media | Medio | Controllore SDF custom, trimesh solo L0 vicino, fallback a collisione voxel custom |
| Costi di generazione a velocità elevate (volo) | Media | Medio | LOD adattivo alla velocità, priorità, cache su disco dei chunk generati (non autoritativa) |
| Scope creep fisica (fluidi/crolli ovunque) | Alta | Alto | Solo bolle locali, budget fissi, feature flag; fluidi volumetrici solo scavi/lava |
| Authoring di un mondo "bello e vario" (ere geologiche) | Alta | Alto | Strategia ibrida: macro-regioni hand-authored + procedurale locale; team ambientale separato; prototipare 1 era prima |
| Licenze dati/tool (DEM, plugin, asset) | Media | Medio | Verificare CC BY/Copernicus/Voxel Plugin prima di commit; preferire dati con licenza chiara |
| Rete: burst di delta per frane/esplosioni | Media | Medio | Replicare operazioni anziché stati dove possibile, rate limit, priorità |
| Dipendenza da feature UE instabili (Iris, Nanite runtime) | Media | Medio | Isolare dietro interfacce; non pianificare nulla che richieda Nanite runtime |

### 6.3 Piano a milestone

Il **vertical slice 4×4 km** = 16 km² = 1,0·10⁶ colonne (4×4 m) ≈ 3 M chunk superficiali nominali (~290 GB se densi: dimostra ancora una volta il generare-a-runtime); macro-dati a 16 m: 62.500 celle ≈ <1 MB.

| Milestone | Durata stimata (4–5 ingegneri) | Deliverable | Criterio di uscita |
|---|---|---|---|
| **M0 – Core** | 6–8 settimane | Chunk 32³, SDF int8/mat16, generazione deterministica (heightfield + 3D noise + caverne), Surface Nets, test di determinismo, benchmark | ≥ 100 Mvoxel/s/core meshing; hash identico su Windows/Linux/console |
| **M1 – Viewer UE** | 6–8 settimane | Plugin UE, clipmap L0–L7, stitching, materiali triplanar, collisione SDF per personaggio | 60 fps a 8 km, ≤ 5 M tri visibili su hardware target |
| **M2 – Edit + persistenza** | 6 settimane | Scavo/costruzione, op-log + snapshot, salvataggio/ricarica, undo | Scavo a 0,125 m a 60 fps; reload identico |
| **M3 – Multiplayer base** | 8 settimane | Server headless, streaming di delta, predizione, 16 giocatori | Banda < 128 KB/s/client in scavo intensivo |
| **M4 – Fisica** | 8–10 settimane | Componenti connesse, frammenti Chaos, crolli, CA granulare/fluido locale | Budget server < 12 ms/tick con 16 giocatori in distruzione |
| **M5 – Vertical slice 4×4 km** | 8–10 settimane | Macro-mappa 4×4 km con 2 ere/biomi, caverne, 8–10 specie, domesticazione base, illuminazione caverne | Demo giocabile 30 min, 16–32 giocatori |
| **M6 – Scale-up** | 4–6 mesi | Mappa ~480 km², far-field, streaming macro, 70–100 giocatori, ottimizzazione | Test di carico 100 bot, persistenza stabile |

Durata complessiva a vertical slice: **~6–8 mesi** (M0–M5); a prodotto scalabile: ~12–15 mesi. Stime da rivedere dopo M0–M1.

### 6.4 Decisioni da prendere subito

1. Approvare scala **1:25 (~480 km²)** al posto di 301.000 km².
2. Fissare la **versione UE** (e verificare lo stato di Nanite runtime, Iris e Lumen su mesh dinamiche in quella versione).
3. Fissare i **target hardware** (CPU/GPU minimi, HWRT sì/no, console sì/no): il budget di triangoli e di thread dipende da qui.
4. Confermare che il **core** adotta aritmetica deterministica sin dall'inizio (costoso da introdurre dopo).

---

## 7. Cosa ho verificato e cosa no

- **Derivato e verificato in questa sessione**: tutte le cifre della sezione 2 (storage, colonne, tempi di attraversamento, orizzonte, heightfield, triangoli, banda).
- **Dalla conoscenza dell'autore, confidenza media**: dettagli di Teardown, Space Engineers, Astroneer, SoA, Noita, Minecraft, NMS, SVDAG, Voxel Plugin 2.0, comportamento di Nanite/Lumen/Iris su mesh runtime.
- **Non verificato**: Lay of the Land (nessun dato affidabile), dimensione voxel di Enshrouded, licenza attuale di Voxel Plugin 2.0, parametri esatti di Douglas Dwyer. Da confermare con ricerca web prima della presentazione al cliente.
