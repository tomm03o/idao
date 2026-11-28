# 06 - Locomozione appresa (RL) per le creature di Primeva: stato dell'arte e raccomandazioni

Data: 2026-11-28. Autore: ricerca ML (fisica del carattere / robotica a gambe).

## Nota sulle fonti

La ricerca web (WebSearch) è stata effettivamente usata. Gli URL elencati in "Fonti verificate" sono stati restituiti dalla ricerca. Ogni affermazione senza fonte web è marcata **(da memoria, da verificare)**. Le cifre di costo (ore-GPU, parametri, microsecondi) sono stime di ordine di grandezza mie, non misure di Primeva, e vanno validate con il prototipo di sezione 6.

Fonti verificate:
- Rudin et al., Learning to Walk in Minutes: https://arxiv.org/abs/2109.11978
- MuJoCo Playground: https://arxiv.org/abs/2502.08844
- MaskedMimic: https://arxiv.org/html/2409.14393v1
- Isaac Lab licenza: https://isaac-sim.github.io/IsaacLab/main/source/refs/license.html
- Unreal NNE: https://dev.epicgames.com/documentation/en-us/unreal-engine/neural-network-engine-overview-in-unreal-engine
- Unreal Learning Agents (API): https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Plugins/LearningAgents
- One Policy to Control Them All: https://arxiv.org/abs/2007.04976
- URMA (One Policy to Run Them All): https://arxiv.org/pdf/2409.06366v2.pdf
- MetaMorph: https://arxiv.org/abs/2203.11931
- Body Transformer: https://arxiv.org/abs/2408.06316
- Peng et al. 2020, imitating animals: https://arxiv.org/abs/2004.00784
- AMP: https://arxiv.org/abs/2104.02180 ; ASE: https://arxiv.org/abs/2205.01906v1
- PHC: https://arxiv.org/pdf/2305.06456v3.pdf ; PULSE: https://arxiv.org/html/2310.04582v2
- SuperPADL: https://arxiv.org/abs/2407.10481
- InterMimic: https://arxiv.org/abs/2502.20390
- Extreme Parkour: https://arxiv.org/abs/2309.14341 (ANYmal parkour, arXiv 2306.14874, citato nella bibliografia di Extreme Parkour; contenuto non verificato)
- DreamWaQ: https://arxiv.org/abs/2301.10602
- Newton / MuJoCo Warp / Warp: https://developer.nvidia.com/newton-physics ; https://github.com/newton-physics
- Genesis (solo mirror trovati; verificare il repo ufficiale): https://pypi.org/project/genesis-world-nightly/0.0.0/
- MyoSuite: https://pypi.org/project/MyoSuite/2.0.1
- Ubisoft La Forge, Learned Motion Matching: https://www.ubisoft.com/en-us/studio/laforge/news/3NWqwcMU9lMfumgfPAEfka/learned-motion-matching

Non verificati via web (da memoria, da verificare): CALM, Barkour, DeepMimic, Brax, Isaac Gym, Hyfydy/SCONE, Euphoria, Rain World, EA SEED, DReCon (esiste una pagina La Forge, non letta).

---

## Sintesi esecutiva (tesi del report)

1. Per ~80 specie, una policy per specie addestrata con RL "alla legged_gym" (reward di velocità comandata + curriculum di terreno + randomizzazione) è la strada più matura e prevedibile. Costo tipico: da decine di minuti a poche ore-GPU per specie per la locomozione base, qualche decina di ore-GPU per specie con tutte le abilità (salto, nuoto, scavo, relitto, cavalcatura).
2. Non esistono mocap per animali estinti. La soluzione realistica è un ibrido: (a) reward di stile fisici/energetici + vincoli morfologici (gait da contatti, frequenza di passo da scaling allometrico) e (b) prior di moto da animatori (poche clip keyframe) o da retargeting di analoghi viventi (uccelli, coccodrilli, elefanti, rinoceronti, varani) usati con AMP/imitazione. La sola emergenza fisica produce andature funzionali ma spesso innaturali.
3. Per la deployment in gioco, il fattore decisivo non è il costo di inferenza (una MLP piccola costa microsecondi) ma il determinismo cross-CPU e il costo del motore fisico articolato lato server per N creature. Raccomandiamo: inferenza in C++ proprio (non NNE/Unreal) nel core di simulazione, pesi quantizzati e matematica in virgola fissa o float rigorosamente controllato, con LOD (fisica completa vicino ai giocatori, cinematico/motion matching a media distanza, statistico lontano).
4. Interfaccia cervello cognitivo -> motorio: comandi espliciti, bassa dimensionalità e uguali per selvatici e domati (velocità/heading target, gait, look-at, flag di azione, parametri di abilità). I latenti (ASE/PULSE) sono utili internamente al motore ma non dovrebbero essere l'API della utility AI.
5. Esperimento minimo su CPU 4 core senza GPU: possibile solo su un corpo molto piccolo (bipede teropode a ~12-16 DoF, torque-driven) con MuJoCo CPU (o il nostro core C++) e PPO/ES con reti piccole; vedi sezione 6.4. Serve però una GPU a noleggio per la produzione.

---

## 1. Simulatori e gym

### 1.1 Quadro

| Piattaforma | Stato / licenza | Parallelismo | Muscoli | Terreno custom |
|---|---|---|---|---|
| Isaac Gym (Preview, PhysX GPU) | Legacy, sostituito da Isaac Lab (da memoria, da verificare) | migliaia di env su 1 GPU | no (solo coppie/PD) | heightfield e trimesh |
| Isaac Lab (su Isaac Sim) | Framework BSD-3-Clause, con `isaaclab_mimic` Apache-2.0 ([licenza](https://isaac-sim.github.io/IsaacLab/main/source/refs/license.html)); Isaac Sim ha componenti con termini diversi, controllare i file di licenza prima di ridistribuire | 4k-16k+ env | no nativo | heightfield, trimesh, generatori di terreno procedurale |
| legged_gym / rsl_rl | Codice di ricerca ETH/NVIDIA sopra Isaac Gym ([Rudin et al.](https://arxiv.org/abs/2109.11978)) | 4096 env tipici | no | curriculum di terreni (pendenze, scale, ostacoli discreti) |
| MuJoCo (CPU) | Open source Apache-2.0 (da memoria, da verificare) | thread CPU | sì: attuatori muscolari Hill-like, tendini | heightfield (hfield), mesh, SDF plugin |
| MJX (MuJoCo su JAX) | Parte di MuJoCo | migliaia su GPU/TPU | muscoli/tendini supportati con limiti (da memoria, da verificare) | hfield e mesh con limiti di contatto |
| MuJoCo Playground | Framework 2025 sopra MJX, deploy su sei piattaforme robotiche ([arXiv](https://arxiv.org/abs/2502.08844)) | massivo | come MJX | quello di MJX |
| MuJoCo Warp / Newton | MuJoCo Warp è il backend GPU principale di Newton, motore Linux Foundation Apache-2.0 su Warp e OpenUSD, sviluppato da NVIDIA, DeepMind e Disney ([NVIDIA](https://developer.nvidia.com/newton-physics)) | massivo | ereditato da MuJoCo | in evoluzione |
| Brax | Motore JAX di Google, ora affiancato da MJX (da memoria, da verificare) | massivo | no | limitato |
| Genesis | Piattaforma Python con rigid, MPM, SPH, FEM; i risultati trovati sono mirror, verificare il repo ufficiale ([PyPI](https://pypi.org/project/genesis-world-nightly/0.0.0/)) | massivo | non verificato | URDF, MJCF, OBJ, GLB, USD |
| NVIDIA Warp | Libreria per scrivere kernel GPU in Python, base di Newton | sì | a piacere (si scrive il solver) | a piacere |
| MyoSuite | Ambienti muscolo-scheletrici su MuJoCo, licenza Apache ([PyPI](https://pypi.org/project/MyoSuite/2.0.1)) | CPU | sì, ma modelli umani | n/a |

### 1.2 Cosa conta per Primeva

- **Muscoli**. Il supporto muscolare serio vive in MuJoCo (muscoli come attuatori su tendini; MyoSuite lo dimostra, anche se con tendini infinitamente rigidi). Sulle piattaforme PhysX-GPU (Isaac) i muscoli vanno emulati con coppie e limiti di attivazione/forza-velocità calcolati nello stesso passo. Raccomandazione pratica: per i primi anni trattare ogni specie come **torque-driven con PD target di giunto** (modello standard del legged RL) e aggiungere un "livello muscolare" semplice (limite di coppia dipendente dalla velocità, dinamica di attivazione del primo ordine, costo energetico) invece di muscoli Hill completi. Il costo dei muscoli completi aumenta di 3-10x la simulazione e di molto il numero di parametri da randomizzare (stima, da verificare).
- **Parità sim-to-sim**. Il vero rischio è la discrepanza fra il simulatore di training (PhysX/MuJoCo) e il nostro core C++ deterministico. Soluzione: **addestrare con un modello di corpo che il nostro core replica** (stesso URDF/MJCF, stessi gain PD, stessa frequenza di controllo, stesso modello di attrito) e fare un passo di "fine-tuning in-loop" o almeno una suite di test di regressione che confronti traiettorie. In alternativa, **addestrare direttamente nel nostro core C++** (CPU, multi-thread, o portato su GPU) elimina il gap ma non ha l'ecosistema. Vedi 6.1.
- **Terreno voxel (0.125 m)**. Tre rappresentazioni di collisione:
  1. **Heightfield** (griglia di quote). Veloce e supportato ovunque (legged_gym lo usa), ma non rappresenta grotte, strapiombi sporgenti, ponti di roccia, tunnel scavati. Adatto al 90% dell'esterno.
  2. **Trimesh** (mesh estratta con marching cubes/dual contouring dai voxel). Rappresenta tutto, ma le collisioni trimesh sono più costose e con artefatti di contatto sugli spigoli; con piedi sferici/capsule e margini di contatto è sostenibile. Si rigenera per chunk (per esempio 16^3 o 32^3 voxel).
  3. **SDF** (campo di distanza). Il nostro voxel liscio è già un SDF campionato. Una collisione SDF per piedi/capsule è molto robusta e deterministica (query tri-lineare), ed è la scelta più coerente con il nostro core. Costo: supporto limitato nei simulatori esistenti (MuJoCo ha un plugin SDF; da memoria, da verificare).
  - Raccomandazione: **training su terreni procedurali in heightfield + piccoli moduli trimesh (grotte, archi)** per i simulatori esterni; **runtime su SDF dal nostro voxel**. Verificare con un test: stesso terreno rappresentato nei due modi, stessa policy, differenza di successo < pochi punti percentuali.
- **Quanto è grande l'ambiente di training**. Rudin et al. riportano meno di 4 minuti per terreno piano e circa 20 minuti per terreno irregolare su una singola GPU da workstation per ANYmal ([arXiv](https://arxiv.org/abs/2109.11978)). Con corpi 3-10x più pesanti (sauropodi, 40+ DoF con coda) e abilità composte, conviene stimare 1-6 ore-GPU per specie per la sola locomozione robusta su terreno, ordini di grandezza non misurati per il nostro caso.

---

## 2. Controllo fisico del carattere: stato dell'arte e cosa prendere

### 2.1 Mappa dei metodi

- **DeepMimic** (da memoria, da verificare): imitazione di una clip con reward di tracking; una policy per clip. Base concettuale di tutto il resto.
- **Peng et al. 2020, imitazione di animali**: policy di quadrupede (18 DoF) addestrate su mocap di cane e poi adattate a un robot reale ([arXiv](https://arxiv.org/abs/2004.00784)). È il precedente diretto per "animale -> controllore", ed è l'unico flusso che parte esplicitamente da dati animali.
- **AMP**: un discriminatore GAN fornisce una reward di stile da un insieme di clip non annotate, mentre il task reward guida l'obiettivo; soffre di mode collapse ([arXiv](https://arxiv.org/abs/2104.02180)). Per Primeva è lo strumento principale: poche clip di riferimento (di animatore o di analogo vivente) definiscono lo stile, il task reward (seguire la velocità comandata) fa il resto.
- **ASE**: AMP + apprendimento non supervisionato di un embedding latente di abilità, riutilizzabile da una policy di alto livello; addestrato su oltre un decennio di esperienza simulata in un simulatore GPU ([arXiv](https://arxiv.org/abs/2205.01906v1)).
- **CALM** (da memoria, da verificare): modelli latenti condizionati con encoder di movimento, controllabili direzionalmente (steering) da un alto livello; più adatto di ASE a un'interfaccia di gioco.
- **PHC / PULSE**: una policy singola che imita il 98.9% di AMASS senza forze esterne e recupera dalle cadute ([PHC](https://arxiv.org/pdf/2305.06456v3.pdf)); PULSE distilla una rappresentazione latente universale delle abilità ([PULSE](https://arxiv.org/html/2310.04582v2)). Rilevanti per la **ripresa dopo la caduta** e per gli approcci "fail-state recovery".
- **MaskedMimic**: controllo come "inpainting" di moto con input parziali (keyframe, testo, oggetti), pubblicato a SIGGRAPH Asia 2024 ([arXiv HTML](https://arxiv.org/html/2409.14393v1)). Concettualmente è l'API ideale per un cervello cognitivo (si danno obiettivi parziali, il motore li realizza), ma richiede un grande dataset di moto per specie, che non abbiamo.
- **SuperPADL**: distillazione progressiva da molti esperti RL a un controllore unico addestrato su oltre 5000 abilità, in tempo reale su GPU consumer ([arXiv](https://arxiv.org/abs/2407.10481)). Il paradigma "molti esperti -> uno studente" è direttamente riutilizzabile per fondere le abilità di una specie (camminare, correre, saltare, nuotare) in una sola rete.
- **InterMimic**: distillazione teacher-student curricolare per interazioni persona-oggetto con dati imperfetti ([arXiv](https://arxiv.org/abs/2502.20390)). Rilevante per il caso "cavaliere sulla schiena" e "creatura che trasporta/trascina" come oggetto fisico, ma resta ricerca umanoide.
- **Robotica a gambe**: legged_gym ([arXiv](https://arxiv.org/abs/2109.11978)); DreamWaQ, locomozione propriocettiva robusta con "immaginazione implicita del terreno" via actor-critic asimmetrico ([arXiv](https://arxiv.org/abs/2301.10602)); Extreme Parkour, salto di ostacoli 2x l'altezza del robot con sola camera frontale ([arXiv](https://arxiv.org/abs/2309.14341)); ANYmal Parkour (arXiv 2306.14874, riferimento citato, contenuto non verificato); Barkour (Google DeepMind, benchmark di agilità di quadrupedi; da memoria, da verificare).

### 2.2 Lezioni trasferibili

1. **Actor-critic asimmetrico**: il critico vede informazione privilegiata (altezza del terreno, massa, attrito, forze), l'attore solo propriocezione + storia + comando (DreamWaQ, legged_gym). Regola d'oro per poter distribuire una MLP piccola.
2. **Student-teacher / distillazione**: addestrare un teacher con informazione privilegiata, poi distillare in uno student con sola sensorialità realistica (Extreme Parkour, e SuperPADL per il lato abilità).
3. **Curriculum di terreno automatico** (legged_gym): ogni robot avanza di livello se percorre abbastanza distanza, torna indietro se cammina poco.
4. **Stile da dati + task reward** (AMP) è lo standard per ottenere movimento naturale.
5. **Latenti** (ASE/CALM/PULSE) aiutano la composizione gerarchica ma complicano determinismo, debug e bilanciamento di gioco.

### 2.3 Come ottenere prior di moto per animali ESTINTI

Opzioni, in ordine di consigliata priorità:

1. **Animatore + vincoli fisici (consigliato come base)**. Un animatore produce 3-8 clip per specie (camminata, corsa/trotto, giro, salto/attacco). Le clip non devono essere fisicamente perfette: AMP le usa solo come distribuzione di stile, e il task reward corregge la fisica. Costo: pochi giorni-animatore per specie archetipo, riuso per famiglia (stesso rig per tutti gli ornitischi bipedi, adattato).
2. **Retargeting da analoghi viventi**. Mappatura per famiglia:
   - teropodi bipedi: uccelli corridori (struzzo, emù, nandù, casuario), varani per la coda e il tronco;
   - sauropodi: elefanti (andatura a "ambio" e piede colonnare);
   - ceratopsidi e anchilosauri: rinoceronti, ippopotami, armadilli;
   - adrosauri facoltativamente bipedi: cambio di andatura bipede/quadrupede, analogo in canguri e primati (da memoria, da verificare);
   - pterosauri: pipistrelli e uccelli grandi, camminata a quattro zampe di avvoltoi/pipistrelli vampiro;
   - nuotatori: coccodrilli (ondulazione assiale), tartarughe marine, pinnipedi;
   - scavatori: talpe, formichieri, tassi.
   Il retargeting (IK + ottimizzazione di proporzioni, scalatura dinamica con numero di Froude) è lavoro da cinematica; i dati pubblici di mocap animale sono scarsi (cane, cavallo, alcuni lavori di Peng), da verificare quali siano utilizzabili con licenza. Alternativa: video + stima di posa 3D animale (da memoria, da verificare).
3. **Emergenza fisica con reward di energia e stile**. Reward di costo del trasporto (energia per massa per distanza), penalità sugli urti dei piedi, regolarità del duty factor, frequenza di passo vincolata da scaling (ipotesi: f ~ massa^-1/6, da memoria, da verificare), simmetria. Funziona bene per quadrupedi e bipedi semplici (legged_gym lo mostra) e dà meta-andature (trotto, galoppo) quando l'energia lo premia; ma dà spesso andature "robotiche" e sbilanciate per teropodi con coda lunga.
4. **Ottimizzazione evolutiva delle andature** (CMA-ES su parametri di CPG o su keyframe): ottima per **inizializzare** o per produrre un clip di riferimento senza animatore: un CPG con 6-12 parametri per specie ottimizzato su CPU in ore. Questa è la via più adatta al nostro esperimento CPU (6.4).

**Raccomandazione**: pipeline in due stadi. Stadio A: ottimizzazione evolutiva o CPG per generare un clip fisicamente plausibile ("bozza"). Stadio B: un animatore ritocca (o lo stile viene scelto fra più bozze) e AMP/imitazione produce la policy finale robusta con reward di velocità comandata. Le specie "archetipo" ricevono più cura animata e le varianti ereditano.

---

## 3. Architettura della policy per molte specie

### 3.1 Opzioni

1. **Una policy per specie**. Semplice, ottimale per corpo, banale da versionare e bilanciare. ~80 reti; piccole (vedi 3.3), totale <~10 MB. Svantaggio: ogni specie è un training separato e ogni modifica del corpo richiede riaddestramento.
2. **Policy per famiglia morfologica** (circa 8-10 famiglie: teropode bipede con coda, quadrupede pesante, quadrupede corazzato, adrosauro facoltativo bipede, pterosauro, nuotatore, scavatore, ecc.) con **condizionamento sulla morfologia** (vettore di descrittori: masse, lunghezze dei segmenti, limiti di giunto, guadagni PD, massa totale, rapporto gamba/tronco). Compromesso consigliato.
3. **Policy morfologia-agnostica** (una per tutte):
   - **One Policy to Control Them All** (Huang et al.): moduli identici per attuatore con messaggi fra vicini, locomozione per oltre 20 agenti planari, generalizzazione a morfologie non viste ([arXiv](https://arxiv.org/abs/2007.04976)).
   - **MetaMorph**: transformer condizionato sulla struttura, pre-training su molte morfologie e trasferimento efficiente a nuove ([arXiv](https://arxiv.org/abs/2203.11931)).
   - **Body Transformer**: attenzione mascherata che segue la topologia del corpo; migliore di MLP e transformer standard in prestazioni e efficienza ([arXiv](https://arxiv.org/abs/2408.06316)).
   - **URMA** (Unified Robot Morphology Architecture): encoder/decoder agnostici attorno a un controllore condiviso, trasferimento a robot non visti anche nel reale ([arXiv](https://arxiv.org/pdf/2409.06366v2.pdf)).
   Utile come **base di pre-training** e per specie nuove (fine-tuning rapido) e per la **generazione procedurale di specie/varianti** (dimensioni e proporzioni casuali). Costo di inferenza maggiore (attention) e determinismo più difficile; evidenza limitata su corpi con 40+ DoF e creature con code e colli lunghi. Non è una scelta per il rilascio iniziale.

### 3.2 Raccomandazione

- **Rilascio**: policy per specie (o per famiglia + descrittore) con MLP piccola, distillata da teacher privilegiati.
- **R&D parallela**: un modello morfologia-condizionato (stile URMA/Body Transformer) per (a) pre-training che riduce le ore-GPU delle specie successive e (b) varianti individuali (taglia, genetica dei domati). Metrica: ore-GPU per specie nuova con vs senza pre-training; obiettivo ridurre del 50% (ipotesi, da validare).

### 3.3 Dimensioni di rete (stime, da verificare)

| Componente | Dimensioni tipiche | Parametri | Inferenza |
|---|---|---|---|
| Attore MLP locomozione | input 60-200, 3 strati da 256-512, output 12-60 | 150k-800k | 0.1-0.8 MFLOP/passo |
| Encoder di storia/terreno (stile DreamWaQ) | 1D-conv/MLP su 10-50 passi | 50k-300k | ~0.1 MFLOP |
| Policy condizionata sulla morfologia (famiglia) | + vettore 16-64 | +30-100k | trascurabile |
| Transformer (Body Transformer/URMA) | 2-4 strati, d=128, ~una token per giunto | 0.5-3M | 1-10 MFLOP/passo |

Una MLP con 500k parametri è ~1 MFLOP per inferenza, cioè **circa 10-100 microsecondi su un core CPU moderno** in float32 con SIMD, quindi a 50 Hz di controllo ~0.05-0.5% di un core per creatura. 500 creature a 50 Hz in full-physics costano pochi core, ma **il solver fisico articolato** (non la rete) domina (stima 20-200 microsecondi per passo per creatura articolata con contatti, da verificare).

### 3.4 Interfaccia di comando

Per un game AI conviene un vettore di comando **esplicito** (e quindi testabile e bilanciabile):

- `v_target` (vx, vy nel frame del corpo), `yaw_rate` o `heading`, quota di velocità massima;
- `gait_id` o parametri di andatura (passo, trotto, galoppo; frequenza target, duty factor);
- `look_at` (direzione testa/collo, per animazione e sensing);
- `action` one-hot + parametri: morso (bersaglio, direzione), colpo di coda (angolo), carica (direzione, durata), scavo (direzione, profondità), salto (direzione, altezza target), nuoto (profondità), beccata;
- `posture` (accucciato, in guardia, sdraiato/riposo), `rider_mass_hint`;
- per formazione: vettore verso lo slot di formazione (offset in frame del leader) e velocità del leader.

I **latenti** (ASE/CALM/PULSE) servono internamente al motor brain, per esempio come spazio in cui un piccolo "skill selector" mappa `gait_id`+`action` in un `z`. Non vanno esposti alla utility AI: sono opachi, non versionabili, e rendono impossibile tarare il gioco.

---

## 4. Deployment in gioco

### 4.1 Chi lo fa (precedenti)

- **Ubisoft La Forge**: Learned Motion Matching (Holden et al.) sostituisce il database di moto con reti piccole per ridurre la memoria ([La Forge](https://www.ubisoft.com/en-us/studio/laforge/news/3NWqwcMU9lMfumgfPAEfka/learned-motion-matching)); il rilascio in Far Cry 6 riguarda Choreograph con motion matching, non la variante appresa, secondo le fonti trovate. DReCon (controllore fisico via RL) è un progetto La Forge; non è emerso se sia stato distribuito.
- **NaturalMotion Euphoria** (da memoria, da verificare): animazione procedurale con reti neurali evolute offline usata in GTA IV/V, Red Dead; i controllori sono distribuiti come grafi fissi, non come policy RL moderne. È il precedente più forte che "fisica attiva appresa" è stata spedita su scala.
- **EA SEED**: ricerca su RL per agenti e per animazione (da memoria, da verificare); nessuna conferma di produzione.
- **Rain World** (da memoria, da verificare): creature con locomozione procedurale (IK e fisica), non apprese.
- **Exoprimal**: non ho trovato fonti; non fare affidamento.
- Conclusione: i controllori **RL fisici con muscoli e terreno arbitrario spediti su scala commerciale sono rari**; Primeva sarebbe ricerca applicata, con rischio ma anche differenziazione. Mitigazione: fallback cinematico per ogni creatura.

### 4.2 Costo di inferenza per frame

- Piccola MLP (0.3-1 MFLOP) a 30-60 Hz: 10-100 microsecondi per creatura per passo di controllo; con 100 creature in full-physics, 1-10 ms per tick su un core, parallelizzabile per creatura.
- Il **passo fisico** (sub-stepping a 120-240 Hz con PD) è il vero costo: tipicamente 2-8 sub-passi per passo di controllo (stima, da verificare).
- Budget server: 30-60 Hz di simulazione per N creature. Ipotesi di capacità: ~100-300 creature in "fisica completa" per server a 8-16 core; il resto in LOD inferiori. Da misurare col prototipo.

### 4.3 Determinismo cross-CPU

Il server è autoritativo e deterministico; il rischio è che reti neurali in float riproducano risultati diversi su CPU diverse (ordine di somma con SIMD/FMA, `tanh`/`exp` di librerie diverse, flush-to-zero). Contromisure:

1. **Server-autoritativo** significa che il determinismo bit-esatto è richiesto solo se si fa replay/rollback o lockstep; con snapshot di stato dal server ai client basta il determinismo **per macchina** e fra build (per test e replay).
2. Se serve determinismo cross-macchina: implementare la rete in C++ con **ordine di somma fisso, senza FMA, senza intrinseci non deterministici, funzioni di attivazione approssimate con tabelle/polinomi propri** (per esempio ELU/ReLU/softsign al posto di tanh), compilando con `-ffp-contract=off` e `-fno-fast-math`.
3. **Quantizzazione**: pesi int8 con accumulo int32 e riscalatura in virgola fissa rende l'inferenza **bit-esatta per costruzione** (da memoria, da verificare la perdita di qualità, tipicamente piccola per MLP di controllo se si fa quantization-aware fine-tuning). Attivazioni ReLU o clamp lineari evitano le trascendenti. È la strada più sicura.
4. Il solver fisico stesso deve essere deterministico (ordine fisso dei contatti, niente thread con riduzioni non ordinate). Il core C++ proprietario ha vantaggio rispetto a Chaos (vedi 4.5).
5. Test di regressione notturni: stesso seme, hash dello stato ogni N tick su 2+ architetture (x86 AVX2 e ARM, se si prevede).

### 4.4 LOD di simulazione

| Livello | Distanza (esempio) | Metodo | Costo per creatura (stima) |
|---|---|---|---|
| L0 | < 50-80 m dai giocatori, o creature con cavaliere/in combattimento | Fisica articolata completa + policy RL | 50-300 microsecondi per passo |
| L1 | 80-250 m | Cinematico: motion matching / state machine con IK su terreno, guidato dalla stessa velocità/heading comandata; fisica semplice di corpo rigido | 5-20 microsecondi |
| L2 | 250 m-1 km | Particella con velocità e navmesh, animazione "ghost" campionata | ~1 microsecondo |
| L3 | oltre / chunk non caricati | Statistico: popolazioni e posizioni aggiornate ad intervalli (ecologia) | trascurabile |

Punti critici: (a) **continuità** nel passaggio L0 <-> L1 (stato corpo: posa, velocità di giunto); si può "iniettare" la posa cinematica come stato iniziale della fisica e lasciar convergere per 0.2-0.5 s; (b) **la coerenza dei combattimenti**: danni e hitbox devono essere gli stessi in tutti i livelli (hitbox cinematiche come autorità, non la fisica articolata, salvo L0 con cavaliere); (c) i **cavalcabili** restano in L0 finché c'è un giocatore sopra.

Le gerarchie motion matching si possono addestrare **dai rollout della policy RL** (distillazione di una libreria di clip da simulazione, in stile Learned Motion Matching), così l'L1 ha lo stesso aspetto dell'L0 senza animatori aggiuntivi. Idea, non validata.

### 4.5 Integrazione con Unreal Engine 5

- **NNE (Neural Network Engine)**: API comune per runtime di inferenza, importa modelli come asset NNE Model Data; marcato Beta con avvertenza di cautela per la spedizione ([doc](https://dev.epicgames.com/documentation/en-us/unreal-engine/neural-network-engine-overview-in-unreal-engine)). Esiste un runtime sperimentale IREE.
- **Learning Agents**: plugin sperimentale (percorso API Plugins/LearningAgents) per addestrare agenti RL dentro Unreal, con asset di rete neurale basati su NNE ([API](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Plugins/LearningAgents)). Utile per prototipi e per l'AI lato client, ma non ha né terreno voxel né fisica articolata deterministica server-side.
- **Chaos physics vs nostro motore**: Chaos non è pensato per determinismo cross-piattaforma né per simulare migliaia di articolazioni su server dedicato; il nostro core C++ è la scelta già fatta. Raccomandazione: **UE5 come puro livello di rendering/animazione**: riceve dal server lo stato (posa di giunti, quantizzata e interpolata), pilota lo scheletro con Control Rig/IK per il piede; **nessuna fisica creature in Chaos**, salvo ragdoll cosmetici lato client alla morte.
- Il client **non esegue la policy**: riceve pose. Eccezione facoltativa: predizione locale per la propria cavalcatura con la stessa rete in C++ (non NNE) per lo stesso risultato numerico. NNE resta utile per feature cosmetiche (secondary motion, animazione facciale).

---

## 5. Curriculum di terreno e robustezza per il nostro mondo

### 5.1 Curriculum

Livelli, con avanzamento automatico (stile legged_gym: promozione se distanza percorsa > soglia, retrocessione se < metà di quanto richiesto):

1. Piano con attrito variabile.
2. Pendenze 0-35 gradi (parametrizzate per specie: sauropodi più basse, ceratopsidi più alte), rugosità voxel 0.125 m (rumore di altezza in scala voxel).
3. Scale e gradini (altezza fino a 0.3-0.5 x altezza dell'anca) e terrazze.
4. Gap e fossati (fino a ~1 x lunghezza del corpo per i teropodi saltatori), cornici.
5. Fango/sabbia/neve: attrito ridotto e **resistenza viscosa** e affondamento (terreno deformabile approssimato con piedi che affondano e forza di resistenza).
6. Acqua: profondità crescente (galleggiamento, resistenza, nuoto), fiumi con corrente (forza laterale), entrata/uscita su sponda.
7. Grotte: soffitto basso, tunnel stretti, pavimento irregolare (trimesh), buio non rilevante per la policy.
8. Scavo (specie scavatrici): il terreno cambia durante l'episodio (voxel rimossi); training con terreno dinamico minimo (rimuovere voxel nel passo) o l'abilità viene resa cinematica/parametrica e la fisica del corpo vi si adatta. Soluzione pragmatica: scavo come "azione scriptata con policy di postura", da valutare.
9. Pendii con ostacoli casuali (massi), alberi come ostacoli sottili, vegetazione.
10. Combinazioni randomizzate tra moduli (terreno composto).

Curriculum su due assi: **difficoltà del terreno** e **difficoltà del comando** (velocità massima, accelerazioni, cambi di direzione).

### 5.2 Randomizzazione di dominio (valori di partenza, da validare)

- Massa del corpo +-20-30%, distribuzione di massa (baricentro +-5 cm scalati), massa aggiuntiva casuale sul dorso (vedi cavaliere).
- Attrito 0.2-1.5; restituzione piccola; compliance del terreno.
- Forza muscolare/limiti di coppia +-20% (anche **per-giunto**, per simulare ferite e fatica), guadagni PD +-20%, ritardo di attuazione 0-30 ms, rumore sensori.
- Gravità fissa, ma pendenze globali variabili; attrito dei piedi diverso fra sinistra e destra.
- Spinte casuali (velocità impulsiva) ogni 5-15 s: robustezza a urti/morsi.
- Cambio casuale di comando (per forzare transizioni).

### 5.3 Spinte, morsi, cadute e rialzarsi

- **Spinte e morsi**: forze esterne casuali sul corpo (impulsi diretti, applicati anche a un punto) durante il training; per i morsi di predatori, **forza di trascinamento** sulla zona del bersaglio (collo, fianco) con durata.
- **Rialzarsi** (recovery): curriculum con stati iniziali caduti (posa a terra casuale) e reward per ritorno in piedi; PHC mostra il recupero dallo stato fallito con una singola policy ([PHC](https://arxiv.org/pdf/2305.06456v3.pdf)). Per grandi corpi (sauropodi) il rialzarsi può essere troppo faticoso e conviene un'abilità dedicata, o dichiarare quel corpo "non cadibile" e usare un'animazione di recupero scriptata.
- **Cadute a morte e danno**: la policy non deve minimizzare l'impatto per sé; il danno da caduta lo calcola il gioco dai dati di contatto.

### 5.4 Creature cavalcabili (giocatore sulla schiena)

Questo è il caso più delicato di Primeva:

- Il cavaliere è un **carico dinamico** variabile: massa (45-120 kg più equipaggiamento), posizione del baricentro sulla sella, movimento (inclinazione del busto). Training con **massa e posizione del carico randomizzate sul dorso** e carico che oscilla, per creature adulte della classe "mount". Per creature grandi (sauropodi con piattaforma) la massa relativa è piccola; per teropodi bipedi (tipo raptor) è significativa.
- **Dato sensoriale**: l'attore non deve necessariamente conoscere la massa; con storia di osservazioni (DreamWaQ-like) la stima è implicita. Per sicurezza includere un input facoltativo `payload_mass`.
- **Controllo del cavaliere**: i comandi del giocatore (stick) diventano `v_target`/`yaw_rate`/`action` come per l'AI; la **stessa interfaccia** vale per selvatici, domati e cavalcati (cfr. 6.3).
- **Il cavaliere come corpo**: scelta di design con compromessi. (a) Cavaliere cinematico incollato a un punto sella con offset animato (nessun feedback sul corpo): semplice, robusto, determinismo facile; richiede di iniettare nella fisica la massa e il momento del cavaliere come carico equivalente. (b) Cavaliere con fisica articolata: costoso e fragile. Raccomandiamo (a) per la prima versione.
- **Test di accettazione**: a velocità massima su pendenza 25 gradi con carico 120 kg la creatura non cade in 1000 episodi consecutivi di 20 s.

### 5.5 Coordinamento di branco

- **Livello cognitivo, non motorio**: formazione e coordinazione sono compito della utility AI (assegnazione di slot, leader, ruoli di accerchiamento). La policy motoria riceve solo un `v_target` verso lo slot e un comando di evitamento collisioni.
- **Evitamento fra creature**: nel training includere altre creature (anche cinematiche) come ostacoli mobili, con inputs di vicini (posizioni relative, velocità, raggio) a bassa dimensione, e penalità di collisione. Cattura il comportamento "stare in branco" senza policy multi-agente.
- **Multi-agente RL** (policy di coordinazione appresa) è possibile ma fuori budget per il rilascio iniziale; i branchi si ottengono bene con regole + steering.

---

## 6. Raccomandazione concreta per Primeva

### 6.1 Pipeline di training

1. **Corpo**: definizione unificata per specie (MJCF/URDF generato dal nostro asset): segmenti, giunti, limiti, masse da densità + volume, guadagni PD, limiti di coppia stimati con scalatura allometrica. Stesso file letto dal training e dal core C++.
2. **Simulatore di training**:
   - Fase 0 (ora, CPU): MuJoCo CPU o il nostro core, per prototipo e per validare i gain.
   - Fase 1 (produzione): Isaac Lab (PhysX GPU) o MuJoCo Playground/MJX o MuJoCo Warp/Newton, terreni procedurali heightfield + moduli trimesh. Scelta dopo un benchmark di due giorni con un corpo di test (steps/s con 4096 env, qualità dei contatti sui nostri piedi). Isaac Lab ha la comunità legged più ampia; MuJoCo/Warp ha il vantaggio di licenza permissiva e di muscoli/tendini; entrambe sono opzioni credibili (Newton è giovane, da verificare la maturità).
   - Fase 2: **validazione nel core C++** (sim-to-sim): suite automatica di terreni, tasso di successo, differenze di traiettoria.
3. **Algoritmo**: PPO con attore-critico asimmetrico, 4096 env, passo di controllo 50 Hz (o 30 Hz per corpi pesanti), con:
   - reward: tracking di velocità lineare/angolare, costo energetico, regolarità dei piedi (duty factor, altezza di passo), posa del tronco/coda, penalità di coppia e di jerk, **reward di stile AMP** (peso 0.3-0.7) dove ci sono clip di riferimento;
   - per le specie con riferimento: imitazione + AMP; per le altre: sola emergenza con reward di stile fisici.
4. **Teacher -> student**: teacher con terreno privilegiato; student con propriocezione + storia + (per grotte/gap) una piccola griglia di altezza locale o un campionamento SDF (ad esempio 8x8 o 16 raggi), distillato in una MLP finale.
5. **Abilità**: policy base (locomozione) + abilità addestrate separatamente (salto, morso/colpo di coda, carica, scavo, nuoto), poi **distillate** in una sola rete condizionata dal comando (stile SuperPADL: esperti -> studente).
6. **Quantizzazione e export**: quantization-aware fine-tuning, esportazione di pesi int8 e tabelle di scala in un formato binario versionato, caricato dal core C++ (non ONNX/NNE nel server).
7. **CI di regressione**: per ogni specie, una suite di 20-50 scenari (pendenze, scale, acqua, spinte, carico) con soglie di successo; ogni versione del corpo o del simulatore la rilancia.

### 6.2 Budget di calcolo (stime di ordine di grandezza, da validare)

| Fase | Per specie | Note |
|---|---|---|
| Locomozione base con curriculum | 1-6 ore-GPU | 4096 env, 10^8-10^9 campioni; Rudin et al. riportano minuti su ANYmal ([arXiv](https://arxiv.org/abs/2109.11978)); i nostri corpi sono più complessi |
| Stile AMP con riferimenti | +2-8 ore-GPU | discriminatore e dati di riferimento |
| Abilità (salto, morso, coda, scavo, nuoto) | +5-20 ore-GPU | 3-6 abilità ognuna con ~1-4 ore |
| Distillazione in una rete | +1-3 ore-GPU | supervisionata |
| Cavaliere / carico, recovery | +2-6 ore-GPU | |
| Iterazioni di tuning (3-5 volte) | x3-5 | la parte costosa è il tempo umano |
| **Totale per specie** | **circa 30-150 ore-GPU** | **80 specie: 2.400-12.000 ore-GPU** |

A 1-2 USD/ora per una GPU consumer-class a noleggio (stima, da verificare), il totale grezzo è nell'ordine di 3-25 mila USD per un ciclo completo, più iterazioni. Risparmio: pre-training per famiglia riduce il costo delle specie successive (ipotesi da misurare). Campioni: 10^8-10^9 passi per policy base; 2-5x10^9 per policy composta.

### 6.3 Interfaccia cervello cognitivo / motorio (selvatici e domati)

- **Un solo contratto**: la utility AI scrive un `MotorCommand` (sezione 3.4) a 10-20 Hz; il motor brain lo legge a 30-60 Hz e produce target di giunto (PD) o coppie. Il motor brain non conosce lo stato di domesticazione.
- **Selvatico vs domato**: differiscono solo in **chi produce il comando** e in **parametri di personalità** (soglie di aggressività, raggio di fuga): stessa policy, stessi comandi. La diversità comportamentale è nella utility AI e nelle Tecniche apprese, non nel motore.
- **Domato e cavalcato**: il giocatore sostituisce la utility AI come sorgente del comando (stick -> velocità/heading; pulsanti -> morso/carica/salto). L'AI può comunque mediare (collision avoidance, rifiuto di entrare in lava), come in "assistenza di guida".
- **Feedback verso il cognitivo**: il motor brain restituisce **stato di esecuzione**: `fatica/energia`, `stabilità` (margine di caduta), `contatto/terreno`, `comando raggiunto`, `abilità in corso/terminata/fallita`. Il cervello cognitivo usa questi valori nelle utility (un teropode zoppo smette di inseguire). Questo canale è piccolo (8-16 float) ed è l'unico accoppiamento di ritorno.
- **Tecniche** (apprese dal cervello cognitivo) restano sequenze di comandi motori + condizioni; il motor brain non apprende Tecniche.
- **Fallback**: se la policy fallisce (instabilità rilevata), il core passa a un controllore cinematico di emergenza con ragdoll attenuato e riprende.
- **Formazione**: v. 5.5; offset di slot in frame del leader via comando.

### 6.4 Esperimento minimo su CPU (4 core, nessuna GPU)

Obiettivo: provare la pipeline end-to-end con un costo di giorni, non settimane.

- **Corpo**: un teropode bipede semplificato (~14-18 DoF: 2x(anca 3, ginocchio 1, caviglia 1... più 2-3 giunti di coda e 1-2 collo) in torque-driven con PD, massa ~80 kg, in MuJoCo CPU o nel nostro core C++.
- **Terreno**: piano + heightfield con pendenza 0-15 gradi e rugosità voxel (0.125 m) generato dal nostro generatore.
- **Algoritmo**: PPO a rete piccola (2x128 o 3x256) con ~64-256 env su 4 core, ~5-20 mila passi/s (stima, da misurare). Alternative più adatte a CPU: **ES/CMA-ES su un CPG a 12-30 parametri** (convergenza in ore sul solo CPU) per ottenere una prima camminata e un clip di riferimento, poi PPO partendo da quella.
- **Budget**: 50-200 milioni di passi in 6-24 ore. Aspettativa realistica: camminata stabile su piano e lievi pendenze con comando di velocità e heading, non il curriculum completo. Rudin et al. dimostrano che 20 minuti di GPU danno terreni irregolari ([arXiv](https://arxiv.org/abs/2109.11978)); su 4 core aspettarsi due-tre ordini di grandezza più lento (stima).
- **Metriche di successo**: (1) cammina a 3 velocità e 8 direzioni senza cadere in 95% di 100 episodi; (2) esportazione int8 e inferenza nel core C++ con differenza trascurabile; (3) due run stesso seme -> stati identici (determinismo); (4) tempo di inferenza < 50 microsecondi per passo di controllo; (5) il comando `MotorCommand` guidato da uno stub di utility AI.
- **Deliverable**: validare la catena: asset corpo -> training -> pesi quantizzati -> runtime C++ -> test di regressione. Il giorno in cui arriva una GPU a noleggio, la stessa catena si sposta su Isaac Lab/MJX senza ridisegni.

### 6.5 Piano a tappe e rischi

| Tappa | Contenuto | Esito atteso |
|---|---|---|
| T0 (2-3 settimane) | Prototipo CPU 6.4, inferenza int8 nel core | Pipeline dimostrata |
| T1 (1-2 mesi) | Noleggio GPU, benchmark Isaac Lab vs MJX/Warp, 3 archetipi (teropode, quadrupede pesante, adrosauro facoltativo) | Scelta del simulatore, costi reali |
| T2 (2-4 mesi) | Terreni voxel, cavaliere, recovery, abilità; animatori per archetipi | Policy giocabili in alpha |
| T3 | Pre-training per famiglia, tutte le specie, LOD completo | Rilascio con fallback |

Rischi principali: (1) discrepanza sim-to-sim (mitigare: stesso modello e test); (2) andature poco naturali per specie estinte (mitigare: animatore + AMP); (3) determinismo (quantizzazione int8); (4) costo del solver articolato su server (LOD e budget); (5) terreno deformabile e scavo in training (rendere l'abilità parametrica); (6) bilanciamento di gioco con policy opache (interfaccia esplicita, nessun latente nella AI).

---

## Appendice: punti aperti da verificare

- Maturità e licenza attuali di Isaac Sim/Isaac Lab per la ridistribuzione di checkpoint e terreni; Genesis (repo ufficiale) e Newton in produzione.
- Supporto reale di muscoli/tendini e contatti heightfield/SDF in MJX e MuJoCo Warp per i nostri corpi.
- Disponibilità di dataset di mocap animale con licenza utilizzabile (cane, cavallo, uccelli corridori, coccodrilli, elefanti).
- CALM, Barkour, DReCon, Euphoria, EA SEED, Rain World: leggere i paper/postmortem originali prima di citarli in documenti esterni.
- Tutte le cifre di ore-GPU, microsecondi e parametri vanno misurate sul nostro prototipo.
