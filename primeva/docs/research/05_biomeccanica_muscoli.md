# Primeva — Ricerca 05: Biomeccanica, muscoli e locomozione appresa

Data: 2026-11-28. Stato: report di ricerca per la progettazione della pipeline creature.

**Nota sulle fonti.** La ricerca web (WebSearch, modalità standard) è stata effettivamente usata. Gli URL riportati sono quelli restituiti dalle ricerche. Le affermazioni numeriche che non erano nei risultati sono marcate **(da memoria, da verificare)**. Non ho potuto verificare: Unreal ML Deformer e Chaos Flesh (le ricerche hanno restituito solo Ziva), i dettagli numerici di MuJoCo Warp con attuatori muscolari, i tempi di addestramento esatti di Geijtenbeek 2013 e Lee 2019. Su questi punti i numeri sono ordini di grandezza da memoria.

---

## 0. Sintesi esecutiva (le tesi che contraddicono le assunzioni ingenue)

1. **Il muscolo pieno a runtime per migliaia di creature è infattibile.** Nemmeno per decine sullo schermo. Il runtime di gioco deve eseguire una *policy distillata* (rete piccola) che pilota un corpo ridotto, oppure un sistema cinematico/motion matching. Il modello muscolare serve a *addestrare e a produrre dati*, non a girare nel gioco.
2. **Non servono 300 muscoli per specie.** I lavori più convincenti sui bipedi non umani usano poche decine di unità muscolo-tendinee (Geijtenbeek 2013: 40–80 circa, **da memoria, da verificare**). Per un dinosauro bastano 10–16 *gruppi funzionali* per arto posteriore, più coda, più colonna.
3. **La paleobiomeccanica ha incertezza grande.** Massa, posizione del centro di massa (CoM) e forza muscolare hanno incertezze del 20–50% o più. Il realismo "scientifico" è un vincolo di plausibilità, non una verità da riprodurre: ha senso fissare le proporzioni dalla letteratura e lasciare all'RL l'adattamento del controllo.
4. **Il costo dominante è la pipeline di contenuti, non la fisica.** Con 70–90 specie, tutto deve scaturire da un body plan parametrico. La generazione automatica di muscoli (punti di via, PCSA) da regole anatomiche è il punto di maggiore rischio tecnico.
5. **Il muscolo visivo è un problema separato dal muscolo fisico.** Il rendering del volume muscolare (rigonfiamento, scivolamento della pelle) si fa con tecniche di deformazione dedicate (corrective blendshape, ML deformer) pilotate dallo stato dello scheletro, non dalla simulazione muscolare.

---

## 1. Stato dell'arte in paleobiomeccanica

### 1.1 Lavori fondativi e come leggerli

**Hutchinson & Garcia 2002, "Tyrannosaurus was not a fast runner", Nature 415:1018–1021.** Modello biomeccanico che stima la massa minima di muscolo estensore dell'arto necessaria per correre veloci; validato su pollo (*Gallus*) e alligatore, poi applicato a T. rex. Conclusione: per correre veloce servirebbe una frazione irrealistica della massa corporea in estensori, con incertezza fino a un fattore 3 tra i modelli. Esiste un erratum su un valore della Tabella 1. Fonte: https://www.nature.com/nature/journal/v415/n6875/full/4151018a.html

Lezione per Primeva: il criterio utile è la *massa muscolare richiesta / disponibile* in funzione della taglia, perché l'esponente di scala della forza (∝ L²) è diverso da quello del peso (∝ L³). Questo dà un principio di design: la velocità massima relativa decresce con la massa.

**Sellers, Pond, Brassey, Manning & Bates 2017, PeerJ 5:e3420.** Analisi multicorpo vincolata dalle tensioni scheletriche (GaitSym) di T. rex: le andature di vera corsa produrrebbero carichi scheletrici inaccettabili; gli arti lunghi limitano a camminata veloce. Accesso libero (CC-BY): https://peerj.com/articles/3420/ e https://pubmed.ncbi.nlm.nih.gov/28740745/

Lezione: i loro modelli usano muscoli Hill-type con ottimizzazione evolutiva (algoritmo genetico) del pattern di attivazione, con tempi di calcolo di molte ore-core per andatura (**da memoria, da verificare**). È la dimostrazione che il metodo "evolutivo CPU" funziona ma è lento: oggi si usa RL su GPU.

**Hutchinson et al. 2005 (Paleobiology)**, modello musculoscheletrico 3D dell'arto posteriore di T. rex: 10 gradi di libertà articolari dall'anca al piede e 33 gruppi muscolari principali; i bracci di leva muscolari risultano in genere inferiori a quelli previsti dallo scaling dei taxa attuali, e pose più erette massimizzano i momenti muscolari. Fonte: https://www.cambridge.org/core/journals/paleobiology/article/analysis-of-hindlimb-muscle-moment-arms-in-tyrannosaurus-rex-using-a-threedimensional-musculoskeletal-computer-model-implications-for-stance-gait-and-speed/30DD414511DEB56D79A5C6281A284320

**Bishop, Cuff & Hutchinson 2021, "How to build a dinosaur", Paleobiology 47.** È il manuale di flusso di lavoro: come costruire un modello musculoscheletrico di un animale estinto (caso Coelophysis), con enfasi sulla forza muscolare come fonte principale di incertezza. Fonte: https://www.cambridge.org/core/journals/paleobiology/article/how-to-build-a-dinosaur-musculoskeletal-modeling-and-simulation-of-locomotor-biomechanics-in-extinct-animals/CE84BB804E697DF47C0A3A367CC16B22

**Bishop, Falisse, De Groote & Hutchinson 2021, Science Advances, "The critical dynamic role of the tail in bipedal dinosaur locomotion".** Prime simulazioni predittive 3D, guidate da muscoli, di locomozione in un vertebrato terrestre estinto (Coelophysis), con controllo ottimo; prima validato su un tinamo. Risultato: la coda esegue una lateroflessione passiva che regola il momento angolare; senza coda lo sforzo muscolare sale di circa il 18% (dato riportato dalla stampa). Fonte di stampa: https://www.aaas.org/news/some-bipedal-dinosaurs-may-have-wagged-their-tails. Lezione per il gioco: *la coda non è un accessorio*: va modellata con segmenti e rigidezza/smorzamento, perché stabilizza il tronco.

**Persons & Currie 2011, "The tail of Tyrannosaurus", Anat. Rec.** Ricostruzioni digitali con dissezioni di rettili: il caudofemoralis era eccezionalmente grande in molti teropodi non aviani, principale retrattore dell'arto posteriore. Nei tirannosauridi l'espansione è favorita dall'allungamento degli archi emali e dalla posizione alta delle coste caudali. Gli autori stessi avvertono che una massa maggiore non implica automaticamente maggiore velocità. Fonti secondarie: https://www.livescience.com/animals/t-rex-tail-muscles-speed-101118.html e https://www.smithsonianmag.com/science-nature/tyrannosaurus-had-extra-junk-in-the-trunk-86820886/

**Allen, Paxton & Hutchinson 2009, Anat. Rec. 292:1442–1461**, variazione nelle stime del CoM di sauropsidi attuali e implicazioni per gli archosauri estinti: https://rvc-repository.worktribe.com/output/1424748/variation-in-center-of-mass-estimates-for-extant-sauropsids-and-its-importance-for-reconstructing-inertial-properties-of-extinct-archosaurs (nota: la citazione corretta è del 2009, non 2013).

**Allen, Bates, Li & Hutchinson 2013, Nature, "Linking the evolution of body shape and locomotor biomechanics in bird-line archosaurs".** Ricostruzioni digitali dell'intero corpo per quantificare la migrazione del CoM e le proporzioni lungo la linea evolutiva verso gli uccelli. Fonte: https://www.nature.com/articles/nature12059. Dati disponibili su Dryad: https://datadryad.org/stash/dataset/doi:10.5061/dryad.hh74n

Uso per Primeva: il CoM dei teropodi si trova in genere poco davanti al bacino (indicativamente nell'ordine del 40–50% della lunghezza del tronco dall'anca verso l'avanti, ma varia molto, **da memoria, da verificare**), e si è spostato progressivamente verso l'anca nella linea verso gli uccelli con la riduzione della coda. È un parametro del body plan, non una costante.

### 1.2 Stima della massa

| Metodo | Idea | Incertezza tipica | Uso in Primeva |
|---|---|---|---|
| Volumetrico (modelli 3D, convex hull minimo, scultura digitale) | Volume × densità (0,8–1,0 kg/L complessiva) | ±20–30% sul volume; la densità media aggiunge incertezza (Bates et al. 2015 mostrano che masse >40 t di *Dreadnoughtus* richiedono densità implausibili) | Ricavare massa e inerzia dalla mesh generata |
| Scaling dei lunghi arti (Campione & Evans 2012) | Circonferenza minima di omero+femore → massa, relazione conservata in mammiferi e rettili terrestri | Intervalli predittivi ampi, ordine ±25–40% | Calibrare la massa target di una specie dal femore |
| Biped correction (Campione et al. 2014, MEE) | Correzione per bipedi: la sezione di un arto bipede è un cerchio, quella di un quadrupede due | Stesso ordine | Teropodi, ornitischi bipedi |
| Allometrie a più variabili e pacchetto R MASSTIMATE | Implementa le equazioni | — | Strumento di verifica offline |

Equazione della famiglia Campione–Evans (forma, coefficienti da riverificare in MASSTIMATE): log10(M) = a · log10(C_{h+f}) + b, con C in mm e M in g; per quadrupedi a ≈ 2,749 e b ≈ −1,104 (**da memoria, da verificare**). Fonti: https://bmcbiol.biomedcentral.com/track/pdf/10.1186/1741-7007-10-60 e https://search.r-project.org/CRAN/refmans/MASSTIMATE/html/MR.html

Bates et al. 2015 su Dreadnoughtus: https://pmc.ncbi.nlm.nih.gov/articles/PMC4528471 (30–40 t più plausibili di 59 t).

**Posizione da prendere:** nel gioco la massa è un *input di design* (con un range plausibile), non un output della scultura. Si decide la massa per specie e si deriva la densità effettiva; l'inerzia viene dalla distribuzione di volume.

### 1.3 Muscoli che contano per la locomozione

Per un teropode bipede, in ordine di importanza per la propulsione e il sostegno (pattern descritto da Hutchinson et al., valori numerici da trattare come ordine di grandezza):

- **Caudofemoralis longus (CFL):** retrattore principale dell'arto, origina dalle vertebre caudali prossimali e dai chevron, inserisce sul quarto trocantere del femore. Massa elevata, fibre relativamente lunghe, braccio di leva lungo. Cruciale per la fase di spinta.
- **Iliotibiales (IT1–3), ambiens, femorotibiales:** estensori del ginocchio.
- **Flexor tibialis (esterno/interno), iliofibularis:** flessori del ginocchio ed estensori dell'anca.
- **Gastrocnemio, fibulari, tibiale anteriore, flessori e estensori delle dita:** caviglia e piede.
- **Pubo-ischio-femorali:** adduzione/rotazione.
- **Per i quadrupedi e i sauropodi:** muscoli di cingolo scapolare (serrato, trapezio, deltoide), e tendini elastici in generale.

Parametri funzionali di ciascun muscolo:

- **PCSA** (area di sezione trasversale fisiologica): PCSA = (m / ρ) · cos θ / L_f, con m massa muscolare, ρ ≈ 1060 kg/m³, L_f lunghezza delle fibre, θ angolo di pennazione.
- **Forza isometrica massima:** F_max = σ · PCSA, con σ ≈ 0,3 MPa. Il valore 0,3 MPa è usato nei lavori paleobiomeccanici più prudenti (Hutchinson, Sellers); i muscoli attuali arrivano a 0,2–0,4 MPa, con valori più alti in alcuni casi (**da memoria, da verificare**).
- **Lunghezza di fibra ottimale** L_0 e **tendine** (lunghezza a riposo L_s^T): nei teropodi grandi è plausibile un tendine lungo e sottile, ignoto.
- **Bracci di leva** r(θ): determinano il momento τ = F · r. Per le specie estinte si ricavano dal modello 3D e dalla routing del muscolo.

**Esempio numerico.** Un teropode di 500 kg ha un arto posteriore di lunghezza ~1,7 m. Se i muscoli estensori dell'arto sono il 15% della massa per lato (75 kg per lato) con L_f media 0,15 m, allora PCSA ≈ (75/1060)/0,15 ≈ 0,47 m² e F_max ≈ 0,3·10⁶ · 0,47 ≈ 140 kN, valore complessivo ordine-di-grandezza, da distribuire tra i muscoli con bracci di leva diversi. Questo non è un dato di letteratura ma un esempio di calcolo.

---

## 2. Modelli muscolari

### 2.1 Hill-type

Forza del complesso muscolo-tendine:

F_MT = F_T = F_M · cos α, con
F_M = a(t) · F_max · f_L(l̃) · f_V(ṽ) + F_PE(l̃) + b·ṽ

dove l̃ = L_M / L_0, ṽ = v_M / v_max, a è l'attivazione.

**Dinamica di attivazione** (primo ordine): da/dt = (u − a)/τ, con τ = τ_act (≈ 10–15 ms) se u > a, e τ = τ_deact (≈ 40–60 ms) altrimenti (valori tipici di letteratura umana, **da memoria, da verificare**; per animali grandi le costanti crescono con la taglia).

**Relazione forza-lunghezza:** gaussiana o spline centrata su l̃ = 1, f_L = exp(−((l̃−1)/w)²), con w ≈ 0,4–0,5 (forma indicativa).

**Relazione forza-velocità:** Hill, f_V = (1 − ṽ)/(1 + ṽ/k) in contrazione concentrica, con k ≈ 0,25; plateau ~1,4–1,8 in eccentrica.

**Tendine:** elastico non lineare; il modello a tendine rigido evita la dinamica interna, mentre il modello "equilibrio" risolve l'equilibrio fibra-tendine.

**Millard et al. 2013** (J. Biomech. Eng. 135(2), DOI 10.1115/1.4023390) confrontano tre modelli (equilibrio standard, equilibrio smorzato, tendine rigido) per velocità e accuratezza e li implementano in OpenSim 3.1. Il modello smorzato elimina le singolarità quando l'attivazione è zero o l'angolo di pennazione vicino a 90°, rilevanti perché la simulazione non deve bloccarsi. Fonti: https://pmc.ncbi.nlm.nih.gov/articles/PMC3705831 e https://repository.tudelft.nl/record/uuid:4d3220fa-b04f-477f-9f13-888f94141a28

### 2.2 MuJoCo e OpenSim

- **MuJoCo** include l'attuatore `muscle` (modello di tipo Hill con tendine inelastico, dinamica di attivazione non lineare con costanti diverse per attivazione e disattivazione; curve forza-lunghezza e forza-velocità parametrizzate). La documentazione è nel XML Reference (https://mujoco.readthedocs.io/en/3.11.0/XMLreference.html). MuJoCo ha anche tendini spaziali con *site* e *wrapping geoms* (sfere, cilindri) per la routing. Il progetto MuscleMimic (https://cnai.epfl.ch/mm-blog) riporta addestramento con migliaia di ambienti muscolari paralleli su MuJoCo Warp; non ho verificato nel dettaglio la copertura di tutti i tipi di attuatore muscolare in MJX/MJX-Warp: **da verificare nella documentazione di MuJoCo Warp prima di impegnarsi**.
- **OpenSim**: più fedele (Millard, Thelen, tendine elastico), ma lento, CPU-only, non pensato per RL di massa. Serve come *riferimento di validazione* per le specie estinte (il flusso di Bishop et al. è su OpenSim).
- **GaitSym** (Sellers): software open source per multicorpo con muscoli, usato in paleobiomeccanica. Utile per validare, non per RL su GPU.

### 2.3 Costo e numero di muscoli necessari

Costo per passo per muscolo (valutazione di lunghezza/velocità, curve, integrazione dell'attivazione, proiezione della forza sui giunti tramite i bracci di leva): dell'ordine di 0,1–1 µs su CPU moderna per tendine rigido, più alto per equilibrio con soluzione iterativa (**stima da memoria, da verificare**). Il costo più grande è il Jacobiano del tendine (moment arm) con wrapping, che scala col numero di tratti e di giunti attraversati.

Per una simulazione RL: un passo di fisica a 500–1000 Hz con 40–80 muscoli e 20–40 giunti è dominato dal solver dei vincoli di contatto più che dai muscoli, ma il *rapporto* tra spazio d'azione e dimensione ostacola l'esplorazione (vedi §3 DEP-RL).

**Quanti muscoli per una locomozione plausibile?**

| Livello | Unità per specie | Cosa cattura | Uso |
|---|---|---|---|
| L0: motori a coppia (PD) | 0 muscoli, 1 attuatore/giunto | Nessun vincolo di forza specifico | Baseline e runtime |
| L1: coppia con limiti da muscolo | 0 muscoli, ma coppia massima τ_max(θ) = Σ F_max·r(θ) dal modello muscolare | Limiti di forza e dipendenza dalla posa | **Consigliato per il runtime fisico** |
| L2: gruppi funzionali Hill | 10–16 per arto posteriore, 4–6 per coda/tronco, 6–10 per arto anteriore | Biarticolarità, co-contrazione, elasticità | **Consigliato per il training** |
| L3: muscolo completo | 40–80 per arto posteriore (Hutchinson 2005: 33 gruppi per T. rex), 300+ per l'uomo (Lee 2019: 346) | Fedeltà anatomica | Solo ricerca/validazione |

Raccomando L2 per l'addestramento, L1 per il runtime fisico vicino al giocatore, e L0/cinematica per il resto.

---

## 3. Controllo appreso per sistemi muscolo-scheletrici

**Geijtenbeek, van de Panne & van der Stappen 2013, "Flexible muscle-based locomotion for bipedal creatures", ACM TOG 32(6) (SIGGRAPH Asia).** Il lavoro più rilevante: controllo di bipedi con ottimizzazione congiunta di *routing muscolare* e parametri di controllo (controllore basato su reazioni a feedback + generazione di pattern di controllo). L'utente fornisce solo un template grossolano dei punti di attacco; funziona su creature immaginarie (tra cui forme simili a dinosauri/uccelli). Ottimizzazione con CMA-ES, tempi di molte ore su cluster CPU (**da memoria, da verificare**). Il dato fondamentale per noi: *il metodo si generalizza su morfologie non umane senza ridisegnare il controllore*. Limiti: andature quasi periodiche su terreno piano, niente terreno irregolare. Fonte: https://www.cs.ubc.ca/~van/papers/2013-TOG-MuscleBasedBipeds/index.html

**Wampler & Popović 2009, "Optimal gait and form for animal locomotion", SIGGRAPH.** Ottimizzazione a due livelli di andatura e forma del corpo senza dati di mocap; bipedi, quadrupedi e una creatura a cinque zampe. Importante come precedente di *co-ottimizzazione forma-andatura*, utile nel nostro caso per tarare proporzioni plausibili. Fonte: https://grail.cs.washington.edu/projects/animal-morphology/s2009/

**Coros et al. 2011, "Locomotion skills for simulated quadrupeds", SIGGRAPH.** Cane simulato con camminata, trotto, passo, galoppo (trasverso e rotatorio), salti, sedersi, alzarsi; usa gait graph, un modello a "due telai" per gli arti, colonna flessibile e forze virtuali attraverso la trasposta dello Jacobiano; non muscoli, ma attuatori a coppia. Ottimo come guida di design del *prior di andatura*. Fonte: https://www.cs.ubc.ca/~van/papers/2011-TOG-quadruped/index.html

**Lee, Park, Lee & Lee 2019, "Scalable muscle-actuated human simulation and control", SIGGRAPH.** Modello umano a 346 muscoli, algoritmo di imitazione a due livelli (rete che predice l'attivazione per tracciare il movimento di riferimento e rete di coordinazione muscolare); abilitato da PPO. Tempi di addestramento di giorni su cluster CPU (**da memoria, da verificare**). Codice (MASS): https://github.com/lsw9021/MASS. Scheda: https://mrl.snu.ac.kr/research/ProjectScalable/Page.htm

**MyoSuite / MyoChallenge (Caggiano et al. 2022, PMLR).** Ambienti musculoskeletal in MuJoCo con API gym, dal singolo giunto alla mano completa; competizioni NeurIPS annuali. Il modello muscolare è quello semplificato di MuJoCo. Fonte: https://proceedings.mlr.press/v168/caggiano22a/caggiano22a.pdf, repository https://github.com/MyoHub/myosuite

**DEP-RL (Schumacher et al., ICLR 2023).** Il problema chiave: il rumore di esplorazione standard fallisce in sistemi sovraattuati; DEP (differential extrinsic plasticity) genera esplorazione che copre lo spazio degli stati in pochi secondi, alternato alla policy RL; controlla fino a 120 muscoli in compiti di reaching e corsa non risolti da altri. Fonte: https://arxiv.org/abs/2206.00484. *Implicazione operativa:* con più di ~30 attuatori, PPO con rumore gaussiano indipendente funziona male; servono parametrizzazioni a bassa dimensione (sinergie, CPG, DEP) oppure le azioni in spazio muscolare con PD.

**MuscleVAE (Feng, Xu & Liu, SIGGRAPH Asia 2023).** Politica generativa (ControlVAE) per personaggi muscolari con un controllo in spazio muscolare basato su PD e un modello di fatica 3CC-r; apprende embedding di abilità da mocap non strutturata. Fonte: https://arxiv.org/abs/2312.07340. Richiede mocap, che per i dinosauri non esiste: serve un'alternativa (vedi §6, motion prior sintetico).

**Spunto aggiuntivo:** MuscleMimic (EPFL, https://cnai.epfl.ch/mm-blog) usa MuJoCo Warp con migliaia di ambienti paralleli per imitazione muscolare del corpo intero.

**Come addestrare con le GPU.** Rudin et al. 2021, "Learning to walk in minutes using massively parallel deep RL": camminata in meno di 4 minuti su terreno piano e ~20 minuti su terreno irregolare (robot quadrupede, torque/PD, Isaac Gym, migliaia di ambienti). https://arxiv.org/pdf/2109.11978. Isaac Lab (https://arxiv.org/pdf/2511.04831) è il successore; NVIDIA riporta 135.000 FPS per la locomozione di un umanoide con migliaia di ambienti (https://developer.nvidia.com/blog/r2d2-scaling-multimodal-robot-learning-with-nvidia-isaac-lab/). Un caso a 2048 ambienti addestra una politica in meno di 15 minuti su una RTX 3070 portatile (https://arxiv.org/pdf/2510.05001).

**Cosa ha funzionato e cosa no (sintesi onesta):**

| Approccio | Campioni / tempo | Cosa funziona | Limiti |
|---|---|---|---|
| Evolutivo/CMA-ES (Geijtenbeek, Sellers) | ~10⁵–10⁷ valutazioni, ore-giorni CPU (da memoria) | Muscoli e morfologie nuove, nessun dato | Andature periodiche, non robuste a terreno e disturbi |
| RL PD/coppia su GPU (Rudin) | ~10⁸–10⁹ passi, minuti–ore GPU | Robustezza a terreno, push, comandi di velocità | Nessun vincolo muscolare |
| RL muscolare su CPU (Lee 2019) | ~10⁸–10⁹ passi, giorni su cluster | Fedeltà alta per l'umano | Costo, richiede mocap |
| RL muscolare GPU (MuscleMimic, MyoSuite + MJX/Warp) | in rapida maturazione | Scala | Ecosistema giovane, esplorazione difficile (DEP-RL) |

**Posizione:** per Primeva il percorso più rischioso è l'RL muscolare puro. La strada robusta è **RL a coppia/PD con limiti di coppia derivati dai muscoli (L1)** per il gameplay, più un livello **L2 muscolare opzionale** usato per generare *prior di andatura* e per i carichi di tensione (vedi §6).

---

## 4. Generazione procedurale dei corpi

### 4.1 Allometria e similarità dinamica

Le leggi usate (forma generale Y = Y₀ · M^b):

- **Lunghezza dell'arto:** L_leg ∝ M^0,33 (similarità geometrica); i grandi animali tendono a esponenti inferiori nell'allometria reale (≈0,3–0,4 con variabilità, **da memoria, da verificare**).
- **Circonferenza/diametro del femore:** ∝ M^0,38–0,40 per il carico (elastic similarity), ma i risultati di Campione & Evans suggeriscono relazione circonferenza-massa ~M^0,36 (∼1/2,75 dall'equazione logaritmica sopra).
- **Forza muscolare massima:** ∝ PCSA ∝ M^0,67 (similarità geometrica). Il peso scala con M¹, quindi il rapporto forza/peso scala come M^−0,33: *è questa la ragione fisica per cui i giganti sono meno agili*.
- **Frequenza del passo:** ∝ M^−0,33 circa.

**Numero di Froude:** Fr = v² / (g · h), con h altezza dell'anca. La similarità dinamica di Alexander prevede che animali simili con Fr uguale abbiano stesso rapporto lunghezza-passo/altezza-anca e stesso duty factor. Il passaggio da camminata a corsa nei bipedi avviene attorno a Fr ≈ 0,5; la velocità massima di corsa, con Fr ≈ 17 in animali molto efficienti (valori di letteratura, **da memoria, da verificare**). Se v_max fosse proporzionale a √(g h), gli animali grandi sarebbero velocissimi: i dati reali smentiscono (la velocità massima cresce e poi decresce con la taglia), per i vincoli di forza/peso e di tensione ossea.

Stima dalla velocità da orme: l'altezza dell'anca si stima dalla lunghezza del piede (≈ 4× nel metodo di Alexander) e la velocità da v ≈ 0,25 · g^0,5 · SL^1,67 · h^−1,17 (formula di Alexander 1976, **da memoria, da verificare**). Attenzione: il metodo ha incertezze fino a fattore 1,5 e non è convalidato su substrati cedevoli. Fonti: https://pmc.ncbi.nlm.nih.gov/articles/PMC1634776 e https://researchonline.ljmu.ac.uk/id/eprint/26667/1/Speed%20from%20fossil%20trackways%20calculations%20not%20validated%20by%20extant%20birds%20on%20compliant%20substrates.pdf

**Regola di gioco:** invece di far "emergere" la velocità massima di ogni specie dalla fisica (instabile), usare un *budget di prestazione*: v_max target ∈ [Fr_min, Fr_max] per la specie, derivato dalla massa e dal tipo di locomozione, e usarlo come parametro di curriculum nell'RL (la policy deve raggiungerlo con i limiti di coppia dati). Se la policy non lo raggiunge, il corpo non è plausibile: segnale di rigetto del body plan.

### 4.2 Schema del body plan (JSON) e derivazione

Parametri minimi per specie (~25–40 numeri):

- Tassonomia/clade e postura (bipede digitigrado, quadrupede, bipede a coda rigida, ecc.).
- Massa target M, lunghezza totale, altezza all'anca h.
- Proporzioni segmentali (frazioni di L_leg: femore, tibia, metatarso, falange), lunghezza collo, lunghezza coda, numero di vertebre per regione, rapporto testa/tronco.
- Spessori (raggio di sezione) per segmento.
- Densità per regione (tessuto = 1000 kg/m³, polmoni/sacchi aerei bassa densità, ossa pneumatiche).
- Gruppi muscolari: massa frazionaria per gruppo (es. CFL = x% della massa corporea, scalato sulla forma della coda).
- Parametri di locomozione: Fr target di camminata e di corsa, duty factor, frequenza del passo.

Gli *sacchi aerei* e le ossa pneumatiche (sauropodi, teropodi) riducono la densità media: i modelli volumetrici usano densità regionali (polmoni ~0,8 e sacchi aerei vicini a 0,0–0,3 kg/L, **valori indicativi da memoria, da verificare**), che portano la densità complessiva sotto 1,0 (≈0,8–0,9). In pratica, per il motore: ρ_regione × volume_regione → massa, baricentro e tensore d'inerzia per ogni segmento.

**Inerzia da mesh:** per ogni segmento, I = Σ_i m_i (|r_i|² 𝟙 − r_i r_iᵀ) con integrazione su tetraedri (formula di Mirtich o equivalente) di una mesh chiusa; MuJoCo calcola automaticamente massa e inerzia da una mesh convessa (`inertiafromgeom`/mesh) con densità dichiarata. Per le regioni con densità diversa si usano più geom per segmento.

### 4.3 Dal JSON a MuJoCo/Isaac e a Unreal

Pipeline concettuale:

1. **Generatore** (C++ o Python, deterministico dato un seed): body plan → scheletro (catena di segmenti con gradi di libertà), mesh di collisione convesse per segmento, mesh visiva (Blender o procedurale), tabella dei muscoli.
2. **Esportazione fisica:** MJCF per MuJoCo (corpi, giunti con limiti, `geom` con densità, `tendon` spaziali con `site`/`wrapping`, attuatori `muscle` o `motor`); per Isaac Lab, USD tramite l'importatore MJCF/URDF di Isaac Sim. Il file MJCF è anche il formato di scambio verso la verifica in MuJoCo prima dell'import.
3. **Esportazione grafica:** skeleton gerarchico + skinning pesato su FBX/glTF, con gli stessi nomi di osso del modello fisico (retargeting 1:1), importato come Skeletal Mesh in Unreal con un Physics Asset derivato dalle collisioni.
4. **Verifica automatica:** test di stabilità statica (il modello sta in piedi con PD?), controllo massa/CoM contro i target, controllo dei limiti di coppia contro Fr.

**Routing automatica dei muscoli (il punto difficile).** Regole proposte:
- Ogni gruppo ha *origine* e *inserzione* come coordinate in sistema locale dei segmenti (frazioni della lunghezza dell'osso e direzione rispetto a un asse anatomico), definite da un *template per clade* (teropode, sauropode, ornitischio, ecc.).
- *Via points* e superfici di wrapping (cilindri attorno a ginocchio, caviglia, anca) per evitare che il tendine attraversi l'osso; il braccio di leva risultante r(θ) si calcola numericamente e si **verifica** contro intervalli plausibili (momento massimo ≈ F_max · r; il rapporto con il peso deve consentire la stazione eretta con un margine, p.es. ≥2–3×, **soglia di design da validare**).
- Calibrazione: scalare la F_max di ciascun gruppo con un solo parametro per specie fino a soddisfare il requisito di Fr target (ottimizzazione outer-loop).
- Il flusso di Bishop et al. 2021 (Paleobiology) è il riferimento qualitativo per i parametri anatomici di partenza.

**Rischio:** la routing automatica può produrre bracci di leva instabili (cambio di segno, tendini che si "rompono" nel wrapping). Mitigazione: ridurre a L1 (limiti di coppia) quando la verifica fallisce, e *non* bloccare la produzione della specie.

---

## 5. Tessuti molli e muscoli visivi nei giochi

**Ziva Dynamics.** Unity ha annunciato ad aprile 2024 la cessazione di vendita e supporto dei prodotti Ziva (Ziva VFX, Ziva Real-Time, Face Trainer); DNEG ha ottenuto una licenza perpetua esclusiva della proprietà intellettuale Ziva; Unity mantiene la tecnologia. **Conseguenza: non basare Primeva su Ziva.** Fonti: https://unity.com/blog/news/update-about-ziva, https://www.cgchannel.com/2024/04/unity-discontinues-the-ziva-products/

**Unreal ML Deformer e Chaos Flesh.** Le mie ricerche non hanno restituito fonti verificate su queste due tecnologie: quanto segue è **da memoria, da verificare**. L'ML Deformer di Unreal (plugin) apprende un modello (reti neurali o vertex delta) che approssima una deformazione costosa (simulazione muscolare/tessuto offline) in funzione della posa dello scheletro, con costo a runtime di una piccola rete valutata su GPU. Chaos Flesh è un solver di tessuti molli (FEM) in UE5, ancora sperimentale/in evoluzione; è più adatto a pochi personaggi hero che a decine di grandi creature. Prima di decidere, serve una prova su UE 5.x corrente.

**Cosa è fattibile in tempo reale per decine di creature grandi:**

- *Skinning con corrective blendshape / pose-space deformation* pilotati dagli angoli di giunto: costo molto basso, standard per rigonfiamento muscolare e pieghe. **Livello base per tutte le creature.**
- *ML Deformer per creature "hero" in LOD vicino*: addestramento offline con dati di una simulazione (ad esempio la deformazione volumetrica del muscolo); il costo a runtime scala col numero di vertici e con la dimensione della rete.
- *Secondary motion* (oscillazione di sacche di pelle, giogaie, piume, coda): catene di molle e massa (jiggle bones) o Chaos Cloth; poco costose su CPU. Per creature con grandi volumi molli, un LOD che riduce la frequenza e il numero di ossa di jiggle.
- *Muscolo FEM/XPBD in tempo reale* per decine di creature: **non fattibile** con budget da gioco; riservarlo al calcolo offline per addestrare il deformer.

Regola di budget: scaldare la soluzione prima di costruirla. Dedicare (indicativamente) ≤0,3–0,5 ms di GPU per creatura nel LOD alto e zero oltre una certa distanza (**obiettivo di design da misurare**).

---

## 6. Raccomandazione per Primeva

### 6.1 Pipeline

```
body plan JSON (seed + parametri)
   │
   ├─► Generatore scheletro e mesh (C++/Blender headless)
   │       ├─► mesh visiva + skinning ──► Unreal Skeletal Mesh + corrective shapes
   │       └─► collisioni convesse + densità regionali ──► massa/CoM/inerzia
   │
   ├─► Gruppi muscolari (template per clade, routing + wrapping)
   │       └─► verifica bracci di leva ──► tabella τ_max(θ) per giunto  (livello L1)
   │
   ├─► Validazione fisica (MuJoCo CPU): statica, limiti, Fr target
   │
   ├─► Addestramento (Isaac Lab / MuJoCo-Warp, GPU)
   │       - curriculum: stazione → camminata → corsa → terreno → disturbi
   │       - azioni: setpoint PD + limiti di coppia da muscoli (L1)
   │       - opzionale: attuatori Hill a gruppi funzionali (L2) per generare prior
   │       - ricompense: comando di velocità/direzione, stabilità del busto,
   │         energia (Σ attivazione²), simmetria dei piedi, penalità su carichi ossei
   │
   ├─► Distillazione: policy di insegnante → rete studente piccola (MLP 2–3 strati,
   │       64–256 unità) + dati cinematici (clip) per motion matching
   │
   └─► Runtime UE5 + simulazione C++ di gioco:
           LOD0 (vicino al giocatore): policy distillata + fisica semplificata (L1)
           LOD1 (medio): policy cinematica/IK con motion matching sui clip generati
           LOD2 (lontano): animazione scalata nel tempo, nessuna fisica
```

### 6.2 Perché il LOD è necessario (e non è un compromesso)

- Il costo per creatura in fisica articolata con contatti è dell'ordine di decine–centinaia di µs per passo di simulazione (**stima da memoria, da verificare**). Con 100 creature a 120–240 Hz di fisica, il bilancio CPU è già pieno prima della rete neurale. Un mondo con migliaia di creature persistenti è quindi **cinematico per costruzione**: la fisica serve dove il giocatore vede e interagisce.
- Il valore della policy appresa si vede nell'interazione con il terreno voxel (pendii, buche, scalini, urti), nei disturbi (colpi, trascinamento, addomesticamento) e nelle transizioni. A distanza, un clip di motion matching e un'IK sui piedi bastano.
- La policy distillata (MLP piccolo) costa microsecondi; il costo reale resta nella fisica del corpo e nei contatti. Per il LOD0 è ragionevole pensare a un massimo di **10–30 creature simulate con fisica** attorno al giocatore (**budget da misurare in prototipo**).

### 6.3 Tabella costi e fattibilità

| Componente | Costo di sviluppo | Rischio | Costo runtime | Fattibilità |
|---|---|---|---|---|
| Body plan JSON + generatore scheletro/mesh | Medio | Medio | Nessuno (offline) | Alta |
| Massa/CoM/inerzia da densità regionali | Basso | Basso | Nessuno | Alta |
| Limiti di coppia da muscoli (L1) | Medio | Medio (routing) | Trascurabile | Alta |
| Gruppi Hill per training (L2) | Alto | Alto (esplorazione, routing) | Nessuno nel gioco | Media; opzionale |
| Muscolo completo (L3) | Molto alto | Molto alto | Proibitivo | Bassa; solo ricerca |
| RL PD su Isaac Lab per ~8 specie | Medio | Medio | Nessuno | Alta; ore GPU per specie |
| Distillazione in MLP | Medio | Basso | µs per creatura | Alta |
| Fisica articolata a runtime per 10–30 creature | Medio | Medio | Dominante | Media; da misurare |
| Motion matching per LOD intermedio | Medio | Basso | Basso | Alta |
| Corrective shapes + secondary motion | Medio | Basso | Basso | Alta |
| ML Deformer per hero | Alto | Medio (da verificare) | Medio | Media |
| FEM muscolare in tempo reale | Molto alto | Molto alto | Proibitivo | Non fattibile |

### 6.4 Versione minima per la vertical slice (≈8 specie)

Scelta di 8 specie che coprono archetipi *diversi*, per validare la parametrizzazione e non solo la quantità:

1. Teropode bipede piccolo/agile (tipo ornitomimide o piccolo coelurosauro).
2. Teropode bipede grande (tipo tirannosauride): caudofemoralis, coda come contrappeso.
3. Teropode medio (allosauroide).
4. Ornitischio bipede/quadrupede facoltativo (adrosauride).
5. Ceratopside quadrupede.
6. Anchilosauro quadrupede corazzato.
7. Sauropode (gigante lento).
8. Pterosauro terrestre/da decollo *oppure* un marino: un caso che *non* è un camminatore, per saggiare i limiti del framework; un'alternativa a minor rischio è rimandarlo dopo la slice.

Ambito minimo:
- **Livello fisico L1 (PD con limiti di coppia da muscoli)** per tutte; gruppi muscolari L2 solo su 1–2 specie *per ricerca*, per confrontare con L1 e decidere se valga la pena.
- Un template di muscoli per *clade* (teropode, quadrupede), riutilizzato con scalatura.
- Addestramento con curriculum su una gamma di terreni generati dal motore voxel (pendii, gradini, buche) esportati come heightfield/mesh in Isaac Lab.
- Distillazione in MLP; clip cinematici prodotti dalla policy per il motion matching.
- Visuale: skinning con corrective shapes; jiggle bones sulla coda e sulle giogaie; nessun deformer ML nella prima slice.
- Criteri di accettazione per ogni specie: cammina e corre su terreno irregolare senza cadere in N prove; velocità raggiunta entro ±20% del Fr target; nessuna violazione dei limiti articolari; consumo energetico relativo in ordine plausibile (la specie più grande ha il costo di trasporto minore per kg, in linea con l'allometria).

### 6.5 Rischi e come ridurli

1. **Routing automatica fragile.** Si riduce usando L1 e un controllo automatico; i bracci di leva sono validati o scartati.
2. **Quadrupedi grandi e sauropodi.** Stabilità e mancanza di prior di andatura: partire dalle andature "ambling" derivate dalle tracce (Alexander; es. titanosauri, https://pmc.ncbi.nlm.nih.gov/articles/PMC3581443) e da gait graph tipo Coros 2011.
3. **Sim-to-game.** La policy addestrata in Isaac Lab va eseguita nel motore C++ con fisica diversa: mantenere un *ponte di parità* (MuJoCo come motore comune per verificare, oppure addestrare direttamente con lo stesso motore del gioco) e randomizzazione di dominio (attrito, massa, ritardi).
4. **Terreno voxel.** La mesh a gradini genera contatti rumorosi: addestrare su versioni smussate/triangolate della stessa geometria e includere il rumore nel curriculum.
5. **Aspettative scientifiche.** Dichiarare nel design che la plausibilità, non la ricostruzione, è l'obiettivo (le incertezze di massa e forza sono grandi: §1).

### 6.6 Decisioni consigliate (in ordine)

1. Adottare **L1** come standard di corpo fisico, con **L2** come opzione di ricerca.
2. Definire lo **schema JSON** del body plan e il generatore deterministico prima di qualsiasi addestramento.
3. Misurare in un prototipo il **costo di fisica per creatura** nel motore di gioco, per fissare il budget di LOD0.
4. Addestrare **2 specie** end-to-end (un teropode, un quadrupede) prima di scalare a 8.
5. Valutare **Unreal ML Deformer / Chaos Flesh** con una prova su UE5 corrente (informazioni qui non verificate).

---

## Appendice: elenco delle fonti verificate nelle ricerche

- Sellers et al. 2017: https://peerj.com/articles/3420/ ; https://pubmed.ncbi.nlm.nih.gov/28740745/
- Hutchinson & Garcia 2002: https://www.nature.com/nature/journal/v415/n6875/full/4151018a.html
- Hutchinson et al. 2005 (momenti T. rex): https://www.cambridge.org/core/journals/paleobiology/article/analysis-of-hindlimb-muscle-moment-arms-in-tyrannosaurus-rex-using-a-threedimensional-musculoskeletal-computer-model-implications-for-stance-gait-and-speed/30DD414511DEB56D79A5C6281A284320
- Bishop, Cuff, Hutchinson 2021: https://www.cambridge.org/core/journals/paleobiology/article/how-to-build-a-dinosaur-musculoskeletal-modeling-and-simulation-of-locomotor-biomechanics-in-extinct-animals/CE84BB804E697DF47C0A3A367CC16B22
- Bishop et al. 2021 Sci. Adv. (stampa): https://www.aaas.org/news/some-bipedal-dinosaurs-may-have-wagged-their-tails
- Persons & Currie 2011 (fonti secondarie): https://www.livescience.com/animals/t-rex-tail-muscles-speed-101118.html
- Allen et al. 2009: https://rvc-repository.worktribe.com/output/1424748 ; Allen et al. 2013: https://www.nature.com/articles/nature12059
- Campione & Evans 2012: https://bmcbiol.biomedcentral.com/track/pdf/10.1186/1741-7007-10-60 ; MASSTIMATE: https://search.r-project.org/CRAN/refmans/MASSTIMATE/html/MR.html
- Bates et al. 2015 (Dreadnoughtus): https://pmc.ncbi.nlm.nih.gov/articles/PMC4528471
- Millard et al. 2013: https://pmc.ncbi.nlm.nih.gov/articles/PMC3705831
- MuJoCo XML Reference: https://mujoco.readthedocs.io/en/3.11.0/XMLreference.html ; MuscleMimic: https://cnai.epfl.ch/mm-blog
- Geijtenbeek et al. 2013: https://www.cs.ubc.ca/~van/papers/2013-TOG-MuscleBasedBipeds/index.html
- Coros et al. 2011: https://www.cs.ubc.ca/~van/papers/2011-TOG-quadruped/index.html
- Wampler & Popović 2009: https://grail.cs.washington.edu/projects/animal-morphology/s2009/
- Lee et al. 2019: https://mrl.snu.ac.kr/research/ProjectScalable/Page.htm ; https://github.com/lsw9021/MASS
- MyoSuite: https://proceedings.mlr.press/v168/caggiano22a/caggiano22a.pdf ; https://github.com/MyoHub/myosuite
- DEP-RL: https://arxiv.org/abs/2206.00484
- MuscleVAE: https://arxiv.org/abs/2312.07340
- Rudin et al. 2021: https://arxiv.org/pdf/2109.11978 ; Isaac Lab: https://arxiv.org/pdf/2511.04831
- Alexander / similarità dinamica: https://pmc.ncbi.nlm.nih.gov/articles/PMC1634776
- Ziva: https://unity.com/blog/news/update-about-ziva ; https://www.cgchannel.com/2024/04/unity-discontinues-the-ziva-products/
