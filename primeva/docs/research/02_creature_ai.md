# Primeva — Sistema di IA delle creature (ricerca e progetto)

Documento 02 della serie di ricerca. Stato: bozza di progetto per revisione. Lingua: italiano; gli identificativi (assi di istinto, categorie di abilità, strutture sociali) restano in inglese/snake_case per coincidere con i file dati.

Nota sulle fonti: le citazioni (sezione 11) provengono dalla conoscenza dell'autore, non sono state riaperte durante la stesura. Gli URL vanno verificati prima di essere usati in documenti pubblici.

---

## 0. Sintesi esecutiva e verdetto di fattibilità

Il cliente chiede creature che (a) apprendono combinando istinto e tecniche, (b) imparano l'una dall'altra e dal giocatore, (c) in natura mostrano molta più agenzia del solito, (d) con 70+ specie, migliaia di creature attive, server autoritativo, mondo voxel e core C++20 deterministico.

Verdetto: fattibile, **a condizione di non fare apprendimento "libero"**. Le tre decisioni portanti:

1. **Il decisore è deterministico e basato su Utility AI** (IAUS, Dave Mark) che sceglie tra *Tecniche* parametrizzate. I piani a più passi sono metodi HTN autorizzati nei dati. Non c'è rete neurale per creatura a runtime.
2. **L'apprendimento modifica dati, non codice**: per ogni creatura una piccola tabella di padronanza per tecnica, stime di valore per contesto (bandit contestuale discretizzato) e abilità per categoria. Sono poche centinaia di byte e si aggiornano con equazioni a costo O(1).
3. **La trasmissione sociale è un evento discreto** (osservazione → familiarità → emulazione → imitazione), regolato da attenzione, legame, compatibilità morfologica e livello cognitivo della specie. Non esiste "imitazione di movimento" a partire dal gesto fisico.

Dove l'idea del cliente non regge, e cosa proponiamo:

| Idea | Problema | Alternativa |
|---|---|---|
| Le creature inventano comportamenti nuovi | Non verificabile, non testabile, non bilanciabile, non legibile | **Scoperta guidata**: libreria di Tecniche autorate; l'invenzione è la scoperta di una combinazione/parametrizzazione già esistente (sez. 3.7) |
| Rete neurale o RL online per ogni creatura | Costo, non determinismo, comportamenti non spiegabili, deriva incontrollata, impossibile fare replay/rollback | Bandit contestuali tabellari + pesi di utilità apprendibili (sez. 3.3). RL **offline** solo come strumento di tuning dei designer |
| Imitazione "vera" dall'osservazione | Richiede inferenza di intenzioni da traiettorie | L'osservatore riceve un **evento semantico** emesso dal dimostratore (`TechniqueObserved{id, goal, outcome}`); la fedeltà è simulata con probabilità |
| Migliaia di cervelli completi per sempre | 200.000 creature dormienti non sono simulabili | LOD statistico: cohort per cella + individui "notevoli" persistenti (sez. 6) |
| Apprendimento sociale senza limiti | Esplosione di bug/exploit, catene di insegnamento infinite | Fedeltà che decade per generazione, tetto per stadio, cooldown (sez. 7) |

---

## 1. Architettura a strati

Pipeline per creatura, ogni strato con frequenza propria (vedi sez. 6):

```
Percezione -> Memoria -> Drive/Bisogni -> Decisione -> Motore/Animazione
 (5-10 Hz)    (eventi)    (1-2 Hz)         (2-4 Hz)      (20-30 Hz)
```

Lo stato fluisce in una sola direzione per tick; l'apprendimento è una fase *seriale di commit* a fine tick (sez. 6.5) che garantisce determinismo.

### 1.1 Percezione

Ogni specie ha un profilo sensoriale in dati. I sensi sono *query* su strutture spaziali del server, non raycast per creatura per frame.

| Senso | Modello | Costo |
|---|---|---|
| `vision` | cono (FOV, portata per specie), occlusione tramite sample di visibilità voxel a LOD, modulato da luce/notte e dalla skill `stealth` del bersaglio | griglia spaziale + 1-3 ray voxel per candidato |
| `smell` | campo di scie: ogni entità deposita *scent puff* in una griglia sparsa 2 m, decadimento esponenziale, trasporto da vento (vettore per regione) | lettura di celle, nessun ray |
| `hearing` | eventi sonori puntuali (`SoundEvent{pos, loudness, class}`) propagati nel raggio r = f(loudness) con attenuazione per occlusione voxel approssimata | push dal produttore, ordinato per id |
| `tremor` | eventi sismici (passi di megafauna, scavo, impatti) trasmessi nel terreno solido; amplificati in cavità; essenziale per creature sotterranee | come hearing, canale separato |
| `thermal` | calore corporeo come tag per entità + sorgenti ambientali (lava, fuochi); portata corta, ignora la luce | query a griglia |
| `echolocation` | impulso attivo: costa stamina, restituisce una mappa a bassa risoluzione dei voxel solidi/aperti (utile in grotte); rivela anche chi lo emette | campionamento voxel limitato, budget per creatura |

Output: una lista limitata (max 16) di **percetti** `Percept{entity, kind, confidence, last_pos, sense_mask, t}` ordinati per salienza, con rumore deterministico (PRNG per creatura). Soglie di rilevamento: `detect = sense_gain * signal / (distance^k) - masking`, con isteresi per evitare flicker.

### 1.2 Memoria

Quattro memorie, tutte a dimensione fissa e ridotta (≈ 1-2 KB per creatura attiva):

1. **Spaziale**: nodi di interesse (cibo, acqua, tana, nido, pericolo, rifugio, percorso di caccia). Max 24 voci con `value`, `last_seen`, `reliability`; decadimento `reliability *= 0.5^(dt/H)` con H dipendente dalla specie (pazienza/curiosità allungano H).
2. **Episodica**: ring buffer di 16 eventi significativi `{type, actor, place, t, valence, intensity}` (attacco subito, pasto riuscito, compagno morto). Alimenta le *stime di valore* e la memoria di minacce. Gli eventi con `|valence|` alta sono *pinned* più a lungo.
3. **Relazioni sociali**: tabella di max 12 individui conosciuti con `bond` (−1..1), `trust`, `familiarity`, `rank_estimate`, `last_interaction`. Il giocatore è un individuo come gli altri.
4. **Mappa delle minacce** (threat map): griglia 16 m locale, valore per cella `threat[c]` aggiornato da percetti e memoria episodica, con decadimento: `threat *= exp(-dt/τ_threat)`, τ ≈ 6 ore di gioco (modulato da `fear` e `patience`). Alimenta la considerazione di utilità "rischio sul percorso".

Principio (Shadow of Mordor, Rain World): la memoria dev'essere **piccola ma conseguente**: poche cose ricordate, ma che cambiano davvero il comportamento e che il giocatore può notare.

### 1.3 Drive/bisogni

Vettore di bisogni normalizzati 0..1 (1 = urgente): `hunger, thirst, fatigue, safety, social, reproduction, temperature`. Dinamiche: `need += rate_species * dt * mod`, azioni che soddisfano riducono. L'urgenza passa per una **curva di risposta** (logistica o quadratica) prima di entrare nella decisione, per ottenere i comportamenti tipici dell'Utility AI: ignorare un bisogno basso, saltare sul bisogno critico.

```
urgency(n) = n^2 * (3 - 2n)          // smoothstep, default
urgency_crit(n) = 1 / (1 + e^(-12(n - 0.75)))   // per safety, thirst
```

Gli assi di istinto non sono bisogni: sono **parametri della persona** che spostano pesi e curve (sez. 3.4).

### 1.4 Decisione: Utility AI su Tecniche + HTN per i piani

Confronto sintetico (rilevante per migliaia di agenti):

| Approccio | Pro | Contro | Verdetto |
|---|---|---|---|
| Behavior Tree | autorabile, prevedibile, economico | rigido, esplosione di rami con 70 specie, apprendimento non naturale | Solo per il livello di *esecuzione* di un singolo passo |
| FSM | semplicissimo | non scala | Solo nel motore (animazione) |
| GOAP (F.E.A.R.) | emergenza, riuso azioni | pianificazione A* per agente costosa, difficile da rendere deterministica/limitare, poca leggibilità del "perché" | Scartato come decisore principale |
| **HTN** | piani multi-passo autorati, controllabili, ripianificazione cheap | meno emergente | **Sì**, per tecniche multi-step e di gruppo |
| **Utility AI / IAUS** | continuità, curve parametriche = punto naturale in cui l'istinto e l'apprendimento intervengono, leggibile ("perché") | richiede tuning; rischio oscillazioni | **Sì, decisore principale** |
| Rete neurale per creatura (Norns, Creatures 1996) | emergenza vera | costo, non spiegabile, non testabile, non deterministico facilmente | Scartato a runtime |
| Perceptron/decision tree di Black & White | apprendimento da feedback del giocatore, spiegabile (decision tree) | per un solo "creature" | Ispirazione: usare feedback del giocatore come reward sui pesi di utilità (sez. 3.5) |
| RL online | adattivo | instabile, non determinista, non debuggabile | Scartato; RL/ottimizzazione **offline** per calibrare i dati di specie |
| Bandit contestuale tabellare | economico, convergente, spiegabile | spazio contesto discretizzato | **Sì**, motore dell'apprendimento per rinforzo |

**Schema di decisione** (ogni 250-500 ms per creatura, sfalsato):

1. *Generazione candidati*: dalla libreria di tecniche conosciute dalla creatura (`known_techniques`, tipicamente 8-40) si filtrano quelle le cui **precondizioni** sono vere nel mondo attuale (sensing + memoria).
2. *Punteggio*: per ciascun candidato (Technique, target) si calcola l'utilità IAUS:

```
U(t, x) = ( Π_i  c_i(f_i) )^(1/n) · compensation · w_t · (1 + m_inertia)
```
   dove `c_i` sono considerazioni (curve su bisogni, distanza, rischio, valore atteso `Q`, stima di successo), con la compensazione di Dave Mark per correggere il calo dovuto al numero di fattori: `c' = c + (1-c)·(1-1/n)·c`. `w_t` è il peso base della tecnica dal profilo di specie, modulato dall'istinto. `m_inertia` aggiunge un bonus (default +0.15) alla tecnica in corso per evitare oscillazioni, decadente nel tempo (*commitment*).
3. *Selezione*: soft-argmax tra le prime K (K=3) con temperatura T (sez. 3.3), usando PRNG per creatura. T→0 per creature sotto stress (bisogno critico).
4. *Esecuzione*: la tecnica scelta istanzia un **piano HTN** (sequenza di passi) o un solo task primitivo. Il piano ha monitor di invalidazione (bersaglio perso, minaccia salita sopra soglia, bisogno critico) che causano *interruzione con riparazione* o ritorno al decisore.

L'utilità dà *cosa* fare; l'HTN dà *come*, con sub-tecniche e ruoli.

### 1.5 Motore/animazione

Il motore sa solo eseguire **task primitivi parametrici**: `MoveTo(pos, gait)`, `Follow(entity, offset)`, `Face`, `Strike(target, kind)`, `Grab`, `Dig(dir)`, `Call(kind)`, `Wait`, ecc. Steering (separazione, evitamento) a 20-30 Hz; navigazione su voxel con grafo gerarchico (chunk → regioni → nodi); creature volanti/sotterranee usano nav-volumes. La libreria produce **intenti motori** (velocità desiderata, orientamento, evento d'azione); il wrapper UE5 li traduce in animazione/Motion Matching. Nessuna logica decisionale in UE: l'animazione può solo restituire eventi di conferma (`StrikeHit`, `GrabSuccess`) ammessi nella simulazione tramite coda ordinata.

Per mondi voxel *modificabili*: percorsi invalidati da eventi di modifica di chunk (versione chunk); le creature che scavano (`digging_burrowing`) sono autorizzate a modificare voxel tramite comandi alla simulazione, soggetti a budget e permessi di terreno.

---

## 2. Dati: persona, istinto, abilità

```cpp
enum class InstinctAxis : uint8_t { aggression, fear, curiosity, territoriality,
                                    sociability, patience, playfulness, COUNT };

enum class SkillCategory : uint8_t { hunting_ambush, hunting_pursuit, hunting_cooperative,
  fishing, digging_burrowing, foraging, harvesting, defense_guarding, defense_herd_circle,
  combat_melee, combat_ranged, evasion, stealth, tracking, scouting_aerial,
  transport_hauling, construction, climbing, swimming_diving, capture_nonlethal,
  communication, territory_patrol, retrieval_rescue, COUNT };

enum class SocialStructure : uint8_t { solitary, pair, pack, herd, colony, swarm };

struct Personality {
  float innate[7];     // 0..1, dal genoma/specie + varianza individuale (determinata dal seme)
  float drift[7];      // -0.25..+0.25, deriva appresa (solo tamed, vedi 3.9)
  float value(InstinctAxis a) const { return clamp01(innate[a] + drift[a]); }
};

struct SpeciesCognition {
  uint8_t  tier;              // 0 riflesso, 1 enhancement locale, 2 emulazione, 3 imitazione, 4 insegnamento attivo
  float    learn_rate_base;   // α0 di specie
  float    memory_half_life_h;
  float    social_learning_gain; // 0..1
  uint16_t technique_slots;   // capienza della "mente" (default 12..40)
};
```

Livelli cognitivi esemplificativi (derivati dalla letteratura: sez. 11): `tier 1` rettili/piccoli erbivori, `tier 2` la maggior parte dei predatori e mammiferi, `tier 3` canidi sociali, primati-simili, corvidi, `tier 4` solo poche specie (animale "insegnante" con tutoraggio attivo; gli orche/cetacei reali mostrano insegnamento nella caccia).

### 2.1 Abilità (skill)

```cpp
struct SkillState {
  float level[23];       // 0..1 per categoria
  float xp_pressure[23]; // accumulo breve termine (per rendere visibile "sta migliorando")
  uint32_t last_used_tick[23];
};
```

**Crescita (practice)**, per ogni episodio di pratica in una categoria `c` con qualità `q ∈ [0,1]`:

```
Δlevel_c = η_c · (1 − level_c)^γ · q · g_inst(c) · fatigue_factor · novelty
η_c      = 0.02  (default per episodio utile)       // ~50 episodi per arrivare a ~0.6
γ        = 1.4   (rendimenti decrescenti)
q        = 1.0 successo; 0.35 fallimento "istruttivo"; 0.1 fallimento grave/ignorato
fatigue_factor = 1 − 0.7·fatigue_need            // pratica stanca rende meno
novelty  = 1 / (1 + n_same_context_last_hour/4)  // anti-grind
```
`g_inst(c)` è la modulazione d'istinto (3.4). Un cap giornaliero: Σ Δlevel_c per giorno ≤ 0.08 (anti-farm).

Il livello abilità entra nella probabilità fisica di successo (e nelle precondizioni): `p_success = sigmoid(k·(level_c + mastery_t·0.5 + phys_adv − difficulty_t))`.

---

## 3. Il modello di apprendimento

### 3.1 La Tecnica come template parametrizzato

Una *Tecnica* è un asset dati (non codice) con identificativo stabile:

```cpp
struct TechniqueParamDef { StringId name; float min, max, default_value; };

struct TechniqueStep {            // un nodo di metodo HTN
  enum Kind : uint8_t { Primitive, SubTechnique, RoleSplit, WaitFor, Branch };
  Kind kind; StringId task_or_ref;
  RoleMask roles;                 // quali ruoli lo eseguono
  float    param_binding[4];      // mappa parametri di tecnica -> parametri di task
  uint16_t timeout_ms;
  StepId   on_fail;               // ripara/abbandona
};

struct RoleDef { StringId role; uint8_t min_count, max_count;
                 SkillCategory key_skill; float min_skill; };

struct TechniqueDef {
  StringId id;                            // "ambush_from_cover"
  SkillCategory category;                 // una delle 23
  uint8_t  min_cognition_tier;            // chi può impararla
  float    difficulty;                    // 0..1
  float    instinct_gate[7];              // soglia minima/affinità (0 = indifferente)
  float    instinct_weight[7];            // contributo all'utilità e al learn rate
  Precondition preconds[8];               // predicati sul mondo/stato
  TechniqueParamDef params[6];
  TechniqueStep steps[16];
  RoleDef  roles[6];                      // 1 ruolo = individuale, >1 = gruppo
  uint8_t  group_min, group_max;
  StringId prerequisites[3];              // altre tecniche (albero di conoscenza)
  Discoverability discover;               // vedi 3.7
  float    risk;                          // per la valutazione rischio/beneficio
  StringId body_requirements;             // tag morfologici (mordere, scavare, volare…)
};

struct KnownTechnique {                   // stato per creatura, ~28 byte
  TechniqueId id;
  float mastery;            // 0..1
  float params[6];          // valori "personali" ottimizzati (es. distanza di attacco)
  uint16_t uses, successes;
  uint32_t last_used_tick;
  uint8_t  source;          // innate / own_discovery / observed / taught_player / taught_peer
  CreatureId teacher;       // per l'albero genealogico della conoscenza
  uint8_t  generation;      // distanza dalla fonte originaria
};
```

**Innate vs. appreso**: ogni specie ha una lista `innate_techniques` (mastery iniziale 0.15-0.35, già nel genoma: il *cucciolo di leopardo sa appostarsi grossolanamente*), e un insieme `learnable_techniques`. L'**istinto** quindi fornisce i comportamenti base e la direzione; la **tecnica appresa** li raffina e ne aggiunge di nuovi. In pratica ogni tecnica base ha una controparte "grezza" innata e una "raffinata" (mastery).

### 3.2 Padronanza (mastery) della tecnica

Ogni uso produce un esito `r ∈ [-1, 1]` (calcolato a fine episodio: preda catturata, ferite subite, tempo, risorse). Aggiornamento:

```
Δmastery = η_t · (1 − mastery)^γ · max(r_eff, 0.0) · g_inst + (−λ_f) · max(−r, 0)·mastery·0.15
η_t = 0.05 (individuale), 0.03 (di gruppo; più lenta ma condivisa dal gruppo)
r_eff = r + 0.25 per "fallimento istruttivo" (non letale, con feedback chiaro)
```
La mastery sblocca anche *parametri*: l'accuratezza della tecnica interpola tra un comportamento grezzo e uno rifinito (tempi più corti, bersagli migliori).

### 3.3 Stime di valore per contesto (bandit contestuale)

Il contesto è **discretizzato** in una chiave piccola: `ctx = hash(specie_bersaglio, terreno, ora_del_giorno (4), gruppo (1/2-3/4+), stato_bisogno_dominante, meteo_bit)` → max 256 contesti per tecnica con politica LRU. Valore per (tecnica, contesto):

```cpp
struct QEntry { uint16_t ctx; uint8_t n; float q; };   // 7 byte
```

Aggiornamento *incrementale a passo con rimbalzo*:

```
q ← q + α_n · (r − q)
α_n = max( α_min, α0 / (1 + n/τ) ) · A(instinct)
α0 = 0.30, α_min = 0.05, τ = 6
A  = 0.6 + 0.8·patience_eff   (creature pazienti: aggiornamenti più stabili? vedi sotto)
```
Convenzione: `patience` ↑ ⇒ α ↓ (più prudenza nel cambiare idea) ma maggiore *esplorazione sistematica* (T più alto lungo ambienti sicuri). Per evitare ambiguità: `A = 1.3 − 0.6·patience`.

**Selezione con esplorazione**: candidati ordinati per `U`; il punteggio include `Q` come considerazione, più un bonus di esplorazione tipo UCB scalato dalla curiosità:

```
bonus_explore = β · curiosity · sqrt( ln(N_ctx + 1) / (n_t,ctx + 1) ),   β = 0.25
```
e soft-selection fra i top-K con `T = T0 · (0.5 + curiosity) · (1 − 0.8·stress)`, `T0 = 0.15`. Per i **rischi alti** (tecniche con `risk > 0.6`) l'esplorazione è soppressa se `fear` alta e la salute bassa. Questo realizza il comportamento "gioco/prova" nei giovani (playfulness ↑ ⇒ T ↑ in contesti sicuri).

**Perché non TD con stati?** Gli episodi di caccia sono brevi e con reward quasi terminale: un bandit contestuale cattura il 90% del beneficio. Per piani lunghi (migrazione, nidificazione) il reward è assegnato al *metodo* come un tutto, con credito sui sotto-passi tramite **eligibility trace** semplificata: il passo `k` di `K` riceve `r·λ^(K−k)`, `λ=0.8`. È l'unica componente TD; resta tabellare.

### 3.4 Come l'istinto modula l'apprendimento

Gli istinti agiscono in tre punti distinti:

1. **Scopribilità** (gate): una tecnica è tentabile spontaneamente solo se `Σ_i instinct_weight_i · value_i ≥ gate`. Es.: `ambush_from_cover` richiede `patience ≥ 0.4`; `pack_relay_pursuit` richiede `sociability ≥ 0.5`. Le creature con istinti opposti possono comunque impararla *da altri* ma con penalità (sotto).
2. **Learning rate di categoria**: `g_inst(c) = 0.6 + 0.8 · aff(c)` con `aff(c) = Σ_i w_{c,i}·value_i / Σ_i w_{c,i}` (pesi di affinità per categoria in dati; esempi: `hunting_ambush`: patience 0.5, aggression 0.2, fear −0.1; `scouting_aerial`: curiosity 0.6; `defense_herd_circle`: sociability 0.5, fear 0.3, aggression 0.2; `capture_nonlethal`: patience 0.4, curiosity 0.2, aggression −0.4). L'intervallo `g ∈ [0.6, 1.4]` evita che l'istinto renda impossibile imparare ciò che "non gli è congeniale" ma rende chiaramente più lento il percorso.
3. **Selezione e utilità**: `w_t` e le curve delle considerazioni dipendono dagli assi (es.: `fear` sposta la curva di rischio verso valori più bassi accettabili; `territoriality` alza l'utilità di `territory_patrol`).

### 3.5 Apprendimento dal giocatore (ricompense e comandi)

Tre canali, in ordine di forza:

1. **Rinforzo** (come Black & White, ma tabellare): dopo un'azione eseguita (finestra 8 s), il giocatore può dare `praise` (+), `treat` (++ e soddisfa un bisogno), `scold` (−) o `none`. Il feedback entra come reward `r_p ∈ {+0.6, +1.0, −0.5}` nel bandit della tecnica *in corso o appena conclusa*, moltiplicato per un fattore di legame `bond_p` (0.3 + 0.7·bond con il giocatore) e per `receptivity = 0.5 + 0.5·sociability`. Un `scold` non azzera: riduce `q` e `w_t` in quel contesto; ripetuto abbassa la **disposizione** (non cancella la tecnica).
2. **Comandi**: la UI espone i comandi (`attack`, `guard`, `fetch`, `capture`, `scout`, `forage`, `dig`, `haul`…). Ogni comando mappa a una *categoria* e a un set di tecniche candidate; la creatura sceglie *come* eseguire (utilità sulle sue tecniche conosciute). Eseguire un comando con successo + premio aumenta `obedience[command] ∈ [0,1]` per quella creatura (`+0.04·(1−obedience)`), e **la obbedienza è separata dalla capacità**.
3. **Dimostrazione**: il giocatore usa una modalità "Mostra" (il giocatore esegue l'azione con target segnalato — ad esempio marca una preda, un nodo di scavo, un percorso) che emette un evento di osservazione `Demonstration{technique_hint, target, outcome}` con il giocatore come dimostratore e `teacher_proficiency` = **rank di addestratore** del giocatore (progresso del giocatore, 0..1). Il giocatore non *insegna una tecnica che non esiste*: sceglie tra tecniche note in libreria e *accelera* la scoperta/fedeltà.

Limiti di insegnamento da parte del giocatore: cooldown (max 3 sessioni di dimostrazione/ora di gioco per creatura), quota giornaliera di XP derivata da un sistema di *energia di addestramento* per creatura (anti-grind), e `bond ≥ 0.3` richiesto per tecniche di tier superiore.

### 3.6 Apprendimento sociale tra creature

**Distinzione fondamentale**, ispirata alla letteratura (Hoppitt & Laland; Whiten):

| Meccanismo | Cosa trasmette | Tier minimo | Implementazione |
|---|---|---|---|
| *Local/stimulus enhancement* | l'attenzione verso un luogo/oggetto/risorsa | 1 | l'osservatore incrementa la `salienza` di un nodo spaziale o di un tipo di preda |
| *Social facilitation* | aumenta l'attività/probabilità di una tecnica già nota | 1 | `w_t` temporaneo +0.1 se coetanei la eseguono |
| *Emulation* | l'obiettivo e il risultato, non i mezzi | 2 | l'osservatore ottiene una **ipotesi** `GoalHint` (ad es. "aprire uovo con pietra") e prova le *proprie* tecniche; la tecnica può ricadere su una versione diversa |
| *Imitation* | i mezzi (sequenza e parametri) | 3 | l'osservatore **acquisisce** la tecnica se la sua morfologia lo consente, con mastery iniziale limitata |
| *Active teaching* | il dimostratore adatta il comportamento all'allievo (ripete, rallenta, avvicina la preda) | 4 | l'insegnante emette dimostrazioni ripetute con feedback; fedeltà più alta |

**Evento di osservazione**. Quando una creatura `D` conclude un episodio di tecnica `t` (con esito), il sistema emette un `TechniqueObserved` verso gli osservatori candidati `O` (query alla griglia entro `R_obs`).

Parametri e formule:

```
R_obs(O) = vis_range_species(O) · 0.4        // portata utile di osservazione, default 25 m
visibility(D→O) = occlusion · light · (1 − stealth_D se D vuole nascondersi)
attention(O) = visibility · (0.3 + 0.7·curiosity_O) · (1 − 0.8·fear_state_O)
               · (1 − 0.6·hunger_crit_O) · focus_factor
relevance(O,t) = need_match(O, t) · age_mod(O)    // i giovani apprendono più rapidamente
bond_term     = 0.4 + 0.6 · max(0, bond(O,D))     // chi è affiliato è più osservato
```

Probabilità che l'osservazione produca un'**acquisizione di stadio**:

```
p_obs = clamp01( attention · relevance · bond_term
                 · teacher_factor(D) · compat(sp_D, sp_O, t)
                 · cognition_gain(O) · (1 − known_penalty) )

teacher_factor(D) = 0.3 + 0.7 · mastery_D(t) · fidelity(generation)
fidelity(gen) = 0.85^gen                      // la conoscenza si degrada per generazione di trasmissione
age_mod(O)     = 1.5 (giovane), 1.0 (adulto), 0.6 (anziano)
cognition_gain = {tier1: 0.15, tier2: 0.35, tier3: 0.6, tier4: 0.8}
```

`compat` = prodotto di (a) affinità di **plan corporeo** (matrice `body_compat[bodyplan_D][bodyplan_O]` per la tecnica: ad es. bipede→bipede 1.0, quadrupede→bipede 0.4; "morso" è inutile a un erbivoro), (b) specie (stessa 1.0; stesso genus 0.8; stessa dieta/ordine 0.5; altra 0.25), (c) ruolo di gruppo (i ruoli richiedono competenza chiave). **Penalità cross-specie**: per il tier 3 `compat ≥ 0.25` anche tra specie diverse di tamed che convivono (stesso gruppo del giocatore) per favorire i pack misti; per specie selvatiche diverse, solo emulation, mai imitation (così non diventa un "virus" di tecniche).

**Stadi**. Per ogni coppia (O, t) la creatura O mantiene un contatore `exposure[t]`. Ogni evento riuscito (`rand < p_obs`) avanza lo stadio:

1. `familiar` (≥ 3 esposizioni): alza il prior dell'esplorazione di `t` e abilita *social facilitation*.
2. `emulating`: l'osservatore inserisce `t_hint` tra i candidati con `mastery` virtuale 0.05 e prova *la propria* variante (tier ≥ 2).
3. `acquired`: `KnownTechnique` creata, `mastery_0 = 0.10 + 0.35·teacher_factor·compat` (max 0.45), `source = observed`, `teacher = D`, `generation = D.generation + 1`. Tier ≥ 3 richiesto.

Quindi una tecnica complessa non si impara con un'unica osservazione: servono 3-8 esposizioni e almeno un tentativo pratico con feedback (la mastery cresce poi per pratica, equazione 3.2). Questo mantiene la progressione legibile e anti-exploit.

**Apprendimento di gruppo**: le tecniche con ruoli si imparano *per ruolo*. Il `KnownTechnique` per `pack_relay_pursuit` ha una `role_mask` di ruoli conosciuti; osservare da fuori insegna il ruolo che il creature *è fisicamente in grado* di svolgere (velocità, mole), ed eseguire un ruolo in un gruppo con leader esperto dà `learn bonus ×1.5` (apprendistato). La conoscenza del piano complessivo (protocollo) viene acquisita dal leader / dagli esperti.

**Cultura e tradizioni**: per specie sociali di tier 3-4 le tecniche acquisite per via sociale si diffondono nel branco con `p_obs` e rimangono anche quando il dimostratore originale muore (generazioni). A livello di branco si mantiene `PackCulture{technique_id, adopters_fraction}` — utile alla UI ("il branco conosce..."), ai LOD statistici e a fenomeni in stile *cultural transmission* (orche, cornacchie).

### 3.7 Scoperta (innovazione) vincolata

Non si crea codice nuovo. Una creatura può **scoprire** una tecnica `t` se:
- ha `tier ≥ t.min_cognition_tier`, istinto sopra soglia (3.4), tutti i `prerequisites` con mastery ≥ 0.3;
- si trova in un **contesto-innesco** `t.discover.trigger` (es. "mangiare vicino a rocce + preda dal guscio duro" per `rock_cracking`);
- tira con probabilità per evento di contesto `p_disc = 0.002 · curiosity · (0.5 + playfulness) · tier_factor`, `tier_factor ∈ {0.4, 0.7, 1.0, 1.2}`.

La **combinazione** è l'unica invenzione "vera": due tecniche note con `merge_rule` in dati (es. `ambush_from_cover` + `drive_prey_to_cover` ⇒ `ambush_with_flush`), con `p_merge` basso, solo in gruppo con coordinamento esistente. Esiste un budget globale di scoperte per server/ora (rate limiter) per proteggere la leggibilità.

### 3.8 Dimenticanza (decadimento)

```
mastery(t) ← mastery(t) · 0.5^(Δt / H_t) , ma mai sotto floor = 0.35 · mastery_peak (se source ≠ innate)
H_t = H_species · (0.6 + 0.8·mastery_peak) · (1 + 0.5·patience) , default H_species = 30 giorni di gioco
level_c ← level_c · 0.5^(Δt / H_c)   con H_c = 90 giorni; floor = 0.5·level_peak
```
Il decadimento si applica solo a tecniche **non usate**; ogni uso resetta il timer. Lo schema "peak + floor" garantisce *riaffioramento rapido* (savings effect): dopo l'oblio, rilearning ha `η ×2`. Le tecniche **innate** non si perdono mai sotto la mastery iniziale. Se una tecnica scende sotto 0.12 e non è innata, viene *dimenticata*: la voce è rimossa dai slot (le slot sono limitate: `technique_slots`) con compattazione preferenziale delle meno utili (LRU pesata per `q_avg`).

### 3.9 Deriva della personalità

```
drift_i ← clamp( drift_i + κ · Σ_events (valence_e · salience_i(e)) , −0.25, +0.25 )
κ = 0.002 per evento significativo; decadimento verso 0: drift_i *= 0.5^(Δt/60 giorni)
```
Esempi di mappatura evento→asse: essere attaccati da un predatore ripetutamente → `fear` ↑; aver vinto scontri a ripetizione → `aggression` ↑ (e `fear` ↓ leggermente); lungo tempo di convivenza amichevole col giocatore → `sociability` ↑; giochi/premi di giochi → `playfulness` ↑; fallimenti frequenti nell'attesa → `patience` ↓. Il tetto ±0.25 (±0.15 per le creature selvatiche) mantiene **riconoscibile la specie** e la personalità individuale. Variazioni più grandi richiedono eventi *traumatici* (rari, flag `trauma` che sposta fino a ±0.1 aggiuntivo, reversibile con cure/legame).

### 3.10 Parametri numerici di riepilogo

| Parametro | Default | Note |
|---|---|---|
| `η_c` (skill) | 0.02 | ~50 episodi per 0.6 |
| `η_t` (mastery) | 0.05 / 0.03 gruppo | |
| `α0, α_min, τ` (bandit) | 0.30, 0.05, 6 | |
| `β` esplorazione | 0.25 | × curiosity |
| `T0` | 0.15 | × (0.5+curiosity) × (1−0.8·stress) |
| `R_obs` | 0.4 × portata visiva | ~25 m |
| `fidelity(gen)` | 0.85^gen | max 6 generazioni utili |
| cap guadagno giornaliero skill | 0.08 | |
| `H_t` tecnica | 30 giorni di gioco | floor 35% del picco |
| `drift` max | ±0.25 tamed, ±0.15 wild | |
| slot tecnica | 12-40 per specie | |

I valori vanno **calibrati offline** con simulazioni headless (milioni di episodi sintetici) e un tooling di tuning (grid/Bayesian optimization): è l'unico impiego di RL/ottimizzazione che raccomandiamo. Per le specie di tier 1-2, `learn_rate_base` basso rende il tutto quasi statico, riducendo costi e rischio.

---

## 4. Comportamento di gruppo

### 4.1 Struttura e ruoli

Le `SocialStructure` determinano che cosa è ammesso: `solitary` (nessun piano di gruppo, solo segnali di territorio), `pair` (due ruoli simmetrici/asimmetrici, nidificazione cooperativa), `pack` (gerarchia + ruoli), `herd` (coesione, sentinelle, difesa circolare), `colony` (casta/ruoli persistenti, lavoro, costruzione), `swarm` (regole locali, nessun piano esplicito).

Ruoli standard di tecnica di gruppo: `leader`, `flanker`, `chaser`, `blocker`, `sentinel` (più `hauler`, `digger`, `retriever` per colonie/trasporto).

### 4.2 Protocollo di coordinamento (Group Plan su blackboard)

Niente scambio di messaggi per tick: i gruppi usano un **blackboard condiviso** `GroupPlan` e fasi esplicite:

1. **Proposta**: il leader (o chi ha l'utilità più alta in assenza di leader) calcola `U_group(t, target)` considerando le tecniche *di gruppo* conosciute da almeno `group_min` membri vicini. Emette `PlanProposal{technique, target, roles_needed}`.
2. **Assegnazione ruoli (contract-net semplificato)**: ogni membro candidato calcola un'offerta `bid(role) = key_skill_level · fit(role) · proximity · (1 − fatigue)·role_instinct`. Assegnazione greedy ordinata per `bid` decrescente con tie-break su `creature_id` → deterministica.
3. **Impegno** (commitment): i membri accettano se `U_individual(accept)` supera la soglia; altrimenti rifiutano (esempio: bisogno critico). Servono ≥ `group_min` accettazioni entro 2-3 s, altrimenti il piano si annulla (cooldown 20 s).
4. **Esecuzione sincronizzata**: i passi con `WaitFor` usano condizioni condivise (`all_in_position`, `prey_in_kill_zone`). Le posizioni sono **slot** in un frame di riferimento relativo al bersaglio o al leader (formazione: offset `(dx, dy)` + tolleranza). Il leader emette i segnali (`Call(kind)`) con i *tempi* di fase.
5. **Riparazione**: perdita di ruolo → riassegnazione dalla lista di riserva; fallimento del passo → `on_fail` (abbandono, riformazione). Se il leader muore, il membro con `rank_estimate` migliore diventa leader.
6. **Debrief**: all'esito, tutti ricevono il reward di gruppo `r_g` per la tecnica e per il proprio ruolo (credito per ruolo con `r_role = r_g · contribution_share`); è anche il punto di **insegnamento reciproco** (osservazione intra-gruppo con `bond_term` alto).

### 4.3 Tecniche di gruppo emergenti (esempi di meccanismo)

- **Relay pursuit**: il predatore con velocità massima insegue finché la stamina cala sotto 0.4, poi il `chaser` successivo prende il posto mentre il primo si rimette in posizione. Condizione: ≥ 2 chaser, sensori di leader per la scelta di rotazione. Premia `sociability` e `patience`.
- **Drive into ambush**: `chaser`/`flanker` spingono la preda verso un `blocker`/`ambusher` nascosto (zona di uccisione scelta dal leader tramite scouting). Il tempo di sincronizzazione viene appreso come parametro `lead_time`.
- **Herd circle defense**: erbivori adulti formano un anello con i piccoli al centro; ruoli `sentinel` e `blocker`. Si attiva con minaccia sopra soglia e struttura `herd`.
- **Mixed-species packs di tamed**: il gruppo del giocatore può includere specie diverse. Il leader "di fatto" è il giocatore o la creatura con più `bond`; l'assegnazione dei ruoli per `bid` rende naturale che i volanti facciano `scouting_aerial`, i grossi `blocker`, i veloci `chaser`. La compatibilità di apprendimento cross-specie (3.6) è abilitata nei gruppi tamed. Evitiamo la dipendenza dalla "comunicazione interspecifica": usa un canale **comune** `communication` (richiami semplici: attacco, ritirata, qui) con vocabolario di 8 segnali condiviso nel gruppo.

### 4.4 Coesione senza plan: flocking leggero

Per `herd`/`swarm` bastano regole boids a 5-10 Hz con pesi per specie, più eventi di panico (propagazione di `fear` con velocità finita), per cui l'intelligenza collettiva è emergente e peu costosa.

---

## 5. Agenzia delle creature selvatiche

Una creatura selvatica ha la stessa architettura delle domestiche, ma con (a) sistemi di *routine* più ricchi, (b) memoria sociale/di minacce più ampia ma senza apprendimento "profondo" per le specie tier 1-2, (c) vincolo di budget.

### 5.1 Ecosistema e dinamiche di popolazione

Livello **regionale** (celle da 128-256 m, aggregate in bioma): per specie `s` e cella `c`:

```
dN_s/dt = r_s · N_s · (1 − N_s / K_s(c, season)) − Σ_p  a_{p,s} · N_p · f(N_s)  + migration_in − migration_out
f(N) = N / (h + N)         // risposta funzionale Holling II
```
`K_s` (capacità di carico) dipende da biomassa di risorse (piante, prede) e stagione. Rete trofica in dati (`diet_matrix[pred][prey]` con preferenze) → eviti oscillazioni distruttive con stabilizzatori (rifugi, saturazione). Il "motore ecologico" lavora a 1 Hz *per cella* (distribuito sul tempo) con **spawning budget**: il numero di individui reificati (attivi) è limitato dalla vicinanza ai giocatori; lo statistico copre il resto (sez. 6).

La densità reificata si ottiene campionando individui dal cohort con seme deterministico `(cell, species, epoch)`, dunque ritornare nello stesso posto riproduce, entro tolleranza, lo stesso gruppo. Le morti e nascite *fuori schermo* modificano `N_s` tramite eventi statistici.

### 5.2 Territori

Ogni creatura (o gruppo) con `territoriality` > 0.3 ha un **home range** e un nucleo. Il territorio è un *campo di rivendicazione* su griglia 32 m con valore `claim ∈ [0,1]` che cresce con pattugliamento e marcature (`scent_mark`, ruggiti, graffi) e decade (`claim *= 0.5^(dt/3 giorni)`). Un intruso percepisce `claim` altrui (odore) → modifica il rischio; il proprietario sopra soglia dà `defend_territory` (tecniche: `territory_patrol`, `intimidation_display`). I conflitti sono ritualizzati prima dell'esito letale (display → inseguimento → scontro), con soglie `aggression`/`fear`.

### 5.3 Migrazione

Un campo scalare stagionale `forage_quality(cell, season)` crea gradienti. Quando `K_s` locale scende sotto la domanda e `hunger_trend` è alto, le mandrie (struttura `herd`) selezionano un'**attrattore migratorio** da una lista di rotte (nodi) in dati per specie. Il percorso è una `PlanMigration` HTN: `gather → move_in_stages → rest_at_waypoint → arrive`. Per le zone lontane usa il LOD statistico: la mandria è un oggetto con posizione, velocità e rotta, senza simulazione per individuo.

### 5.4 Routine giorno/notte e stagionali

Ogni specie ha `chronotype` (diurnal/nocturnal/crepuscular) che modula la curva di `fatigue` e la visibilità. I dormitori (tane, nidi, alberi) sono nodi di memoria spaziale. Le stagioni cambiano `K_s`, riproduzione, pelo/temperatura (`temperature` need), disponibilità di acqua e rotte migratorie.

### 5.5 Memoria dei giocatori (Nemesis-lite)

Due livelli per evitare costi esplosivi:

1. **Individuale** (solo creature "notevoli" o con interazione diretta): fino a 6 `PlayerRecord{player_id, aggression_events, flee_events, rewards, last_seen, bond}` nella memoria sociale. `fear_p`, `hostility_p` ∈ [0,1] calcolati da eventi con decadimento (τ_fear ≈ 3 giorni di gioco; il tradimento di fiducia dura di più). Un animale ferito da un cacciatore *riconosce* il suo odore/identificativo e fugge o contrattacca; un animale nutrito si avvicina.
2. **Di specie/regione** (reputazione): `reputation[player][species][region]` ∈ [−1,1] con aggiornamento lento; influenza il comportamento *di default* della popolazione appena reificata (es. un territorio dove un giocatore massacra una specie ha esemplari più sospettosi: `fear_base +0.1·|rep|`). Eventi della cellula statistica usano il riepilogo. Il limite è ±0.2 per evitare il "mondo che odia il giocatore" come punizione opaca.

Tutto resta server-side; il client riceve solo gli effetti (segni in UI: "ti ricorda").

### 5.6 Opportunismo e scavenging

Percetti di **carcasse** e di scontri (suoni, odore di sangue) generano `opportunity` nodi. Un opportunista (basso `fear`, alta `aggression` o fame) può: rubare la preda (`kleptoparasitism`), attendere ai margini (`scavenge_wait`), o attaccare il vincitore ferito (`finish_the_weak`). Calcolo: considerazione `rischio/beneficio = (value_carcass·hunger) / (threat_local + rival_strength)`. Il sistema produce *combattimenti tra scavenger* come emergenza dalla utilità senza script. Hotspot = interessanti per il giocatore, ma bilanciati con limiti (max N creature convergenti per carcassa).

### 5.7 Nidificazione e cura

Stato `breeding_season`: `reproduction` need sale; si cerca partner (struttura `pair`), si sceglie sito (nodo con sicurezza alta, scorte, nascondiglio; scavo per specie `digging_burrowing`), si costruisce il nido, si cova, si caccia per i piccoli. Genitori trasmettono tecniche ai cuccioli con `age_mod=1.5` e `teacher_factor` (tier ≥ 3) o *per esposizione* (tier 1-2). Le uova/nidi sono bersagli e punti d'interesse per il giocatore (taming, ladri). Un nido minacciato fa salire `defense` e `territoriality`.

---

## 6. Prestazioni, LOD, determinismo

### 6.1 Livelli di dettaglio

| LOD | Dove | Rappresentazione | Frequenze |
|---|---|---|---|
| **L0 pieno** | entro ~96 m dai giocatori (+ tamed attivi) | cervello completo, motore, animazione sul client | decision 3-4 Hz, percezione 8 Hz, motore 20 Hz |
| **L1 ridotto** | 96-300 m, entro l'area attiva | decisione 1 Hz, percezione 2 Hz, nessun steering fine (movimento su spline/nav grezza) | |
| **L2 aggregato** | 300 m - area attiva | gruppi/branchi come singolo agente (centroide), azioni astratte (mangia/si sposta/riposa) con esiti probabilistici | 0.2-0.5 Hz |
| **L3 dormiente** | fuori | *cohort* per cella: conteggi, età, stato, tecniche medie, più **individui notevoli** (tamed assenti, capi, nemesi) | 1 tick/minuto (analitico) |

**Transizioni**: avvicinamento → *materializzazione* di individui da cohort con seme deterministico (cella, specie, epoch); allontanamento → *dematerializzazione* che riassume stato (necessità, posizione, ferite, tecniche condivise). Le creature tamed e quelle con *stato persistente rilevante* (cuccioli accuditi, nemesi) sono pinnate.

### 6.2 Budget (esempio quantitativo)

Target: 2.000 attive + 200.000 dormienti, server 4 core a 20 Hz (50 ms per tick). Budget IA complessivo: **≤ 12 ms CPU per tick distribuiti su 3 worker (36 ms-core)** lasciando margine a fisica/rete/voxel.

| Fase | Frequenza | Unità/tick | Costo unitario | ms-core/tick |
|---|---|---|---|---|
| Percezione | 5 Hz medio (L0 8, L1 2) | 500 | 10 µs | 5.0 |
| Aggiornamento bisogni/memoria | 1-2 Hz | 150 | 2 µs | 0.3 |
| Decisione utilità (30 tecniche × 6 considerazioni) | 3 Hz medio | 300 | 18 µs | 5.4 |
| Pianificazione HTN/ripianificazione | 0.5 Hz | 50 | 40 µs | 2.0 |
| Esecuzione task / steering | 20 Hz L0 (≈ 600 agenti) + 5 Hz L1 | 700 | 6 µs | 4.2 |
| Navigazione voxel (async, cache) | on demand | 40 query | 120 µs | 4.8 |
| Apprendimento/osservazioni (commit seriale) | evento | 200 | 3 µs | 0.6 |
| Ecosistema/L2/L3 | 1 Hz per cella, ~800 celle attive | 40 | 15 µs | 0.6 |
| **Totale** | | | | **≈ 23 ms-core** (≈ 8 ms su 3 worker) |

I costi unitari sono stime di ordine di grandezza (da validare con benchmark: ogni valore verrà misurato in CI con scenari sintetici). Margine di 1.5× a spendere su picchi (battaglie, migrazioni).

**Dormienti**: 200.000 individui a 48-64 B = ~10-13 MB come cohort/record compatti; aggiornati con *fast-forward analitico* (delta di tempo) alla lettura o in uno slice a 1 minuto, costo trascurabile. Per memoria: SoA per la parte attiva (≈ 2-3 KB/creatura attiva con memorie ⇒ 6 MB).

### 6.3 Time slicing e scheduler

- Bucket deterministici: `creature_id % N` decide *in quale tick* della finestra una creatura esegue la decisione (sfalsamento). Prioritizzazione dinamica: creature in combattimento/vicino ai giocatori ottengono frequenze più alte, con un tetto globale per tick e *deadline*: se il budget termina, le creature restanti usano la decisione precedente (`stale ≤ 1 s`).
- Percezione push-based per audio/tremori (eventi), pull per vista, con **query raggruppate per cella** (batch per cella condividono il lavoro).
- Pianificazione di path asincrona con risultato applicato al tick *N+k fisso* (non quando "è pronto") per non rompere la determinazione.
- Il costo per decisione cala con *pre-filtro* delle tecniche (bitset di precondizioni coarse per cella).

### 6.4 Struttura dati

SoA (structure-of-arrays) per specie/LOD: `positions[]`, `needs[][7]`, `skill[][23]` quantizzati a `uint8/uint16` (la skill come 0..255). Le tecniche note: `KnownTechnique[]` in arena di slot. La libreria è senza allocazioni a runtime sul ciclo caldo (pool/arena).

### 6.5 Determinismo (essenziale per replay, test, rollback)

1. Tick a passo fisso; nessun uso di tempo reale.
2. PRNG per creatura **a stream**: `rng = pcg32(seed = hash(world_seed, creature_id, stream_id))`; contatori per sotto-stream (percezione, decisione, apprendimento) → riordinare job non cambia l'esito.
3. Iterazione solo su contenitori ordinati/vettori con id; vietato `unordered_map` iterato; tie-break sempre su `creature_id`.
4. Floating point: compilare con `-ffp-contract=off`, no fast-math, nessuna funzione trascendente della libm di sistema (implementazioni proprie `expf/logf` o tabelle). Alternativa più sicura per i valori che influenzano le decisioni *e* si salvano: **fixed-point Q16.16** per bisogni, mastery e Q. Raccomandazione: fixed-point per lo **stato persistente di apprendimento**, float per il calcolo transitorio di utilità, con quantizzazione a una soglia prima di confronti critici.
5. Fasi: `Perceive (parallelo, sola lettura)` → `Decide (parallelo, scrive nel buffer proprio)` → **`Commit (seriale, ordinato per id)`**: applica azioni, eventi di osservazione, apprendimento, inter-creatura. Nessuna scrittura condivisa nelle fasi parallele.
6. Input esterni (comandi giocatore, eventi voxel, esiti animazione) entrano da coda con numero di tick e ordine stabili.
7. Test: snapshot hash per tick, golden replay in CI, confronto tra build (Linux/Windows/Clang/MSVC).

---

## 7. Salvaguardie di game design e anti-frustrazione

### 7.1 Exploit e grind

| Rischio | Contromisura |
|---|---|
| Farm di skill con bersagli innocui (training dummy, animali bloccati) | `novelty` e cap giornaliero; qualità `q` ridotta contro bersagli non pericolosi/senza reazione; reward di mastery richiede *esito significativo* |
| Catene di insegnamento infinite ("laundering") per saltare la progressione | `fidelity = 0.85^gen`; tetto di `mastery_0` acquisibile (0.45); cooldown per osservazione; l'insegnamento non supera la mastery del maestro |
| Duplicazione di creature per moltiplicare conoscenza | tecniche legate a individuo; `cultural` rete limitata; i figli ereditano al massimo un sottoinsieme *non la mastery* |
| Cheese di pathing/voxel (creature intrappolate in buche, nemici scavati) | rilevamento *stuck* + fallback (teletrasporto sicuro al nodo di memoria, rinuncia al target); voxel-edit sottoposti a regole di *terreno protetto* |
| Abuso della memoria delle minacce (kiting infinito) | la minaccia/odio decadono; le creature smettono dopo un budget di inseguimento (`give_up`) e *si riposizionano* |
| Esplosione di creature convergenti / "lag-by-carcass" | limiti per carcassa/area e per cella di spawn |

### 7.2 Griefing in multiplayer

- Gli animali addestrati non attaccano altri giocatori in PvE-flag, tecniche `capture_nonlethal` e `combat_*` verso player richiedono flag PvP/consenso; non si può *addestrare* una creatura a perseguitare un singolo giocatore (nessun tag di target giocatore come parametro appreso).
- I comandi su creature altrui sono disabilitati (proprietà e *trust list* per squadre).
- Limiti sulla densità di creature pericolose nelle basi dei nuovi giocatori; nessun spawn/reputazione punitiva nell'area di spawn iniziale.
- Reputazione regionale con tetto ±0.2 e decadimento (5.5).

### 7.3 Agency vs. controllo: obbedienza

Le creature *non* sono macchine: ma la disobbedienza deve avere **causa mostrata**. Regole: ogni comando rifiutato mostra un'icona di motivazione (`paura`, `fame`, `stanchezza`, `ruolo non noto`, `bond insufficiente`). Soglia minima di affidabilità: con `bond ≥ 0.5` e bisogni sotto 0.7 l'obbedienza è ≥ 90% per comandi appresi. Mai sorprese letali non motivate nei confronti del proprietario.

### 7.4 Leggibilità: UI di abilità e conoscenza

- **Scheda creatura**: radar a 7 assi di istinto (innato vs. deriva), barre per le 23 categorie (solo quelle con `level > 0.05`), elenco tecniche con mastery, stato (`emulating/acquired/innate`), icona dell'origine.
- **Albero genealogico della conoscenza** (knowledge family tree): grafo `teacher → learner` per ogni tecnica con nomi, generazione e fedeltà; "chi ha insegnato a chi", cultura del branco con frazione di adottanti; evidenzia ciò che il giocatore ha insegnato.
- **"Perché l'ha fatto?"**: in modalità ispezione mostra il top-3 della decisione con le considerazioni principali ("fame 0.8, preda a 20 m, `ambush_from_cover` Q alto").
- **Feedback in-world**: segnali visivi/sonori di osservazione (la creatura osserva con la testa orientata; "ding" lieve di acquisizione di stadio), notifica di nuova tecnica con icona.
- **Registro eventi** di apprendimento (ultimi 20) per debug e conforto del giocatore.
- Strumenti per designer: *debug overlay* delle utilità, replay, e dashboard di telemetria (distribuzioni di mastery, tasso di scoperte, tecniche egemoni) per accorgersi di meta-collassi (una tecnica domina tutto).

### 7.5 Rischi di bilanciamento

Monitorare: (1) *monocultura di tecniche* (una sola tecnica ottimale per specie): mitigare con costi di contesto (`Q` per contesto), saturazione (prede imparano la contromisura, `evasion` apprendibile) e *novelty decay*; (2) specie "overpowered" una volta addestrate: i tetti di mastery e stamina; (3) iperprotezione del giocatore: la fauna selvatica deve restare pericolosa.

---

## 8. Catalogo di Tecniche di esempio (34)

Legenda: **Cat** = categoria; **Istinti** = assi che aprono/spingono (soglia indicativa); **Abilità** = skill richieste; **Ruoli**; **Apprendimento**: `I` innata in alcune specie, `D` scoperta, `O` osservazione (tier ≥ 2/3), `P` insegnata dal giocatore, `T` insegnamento attivo (tier 4).

| # | id tecnica | Cat | Istinti | Abilità min | Ruoli | Apprendimento |
|---|---|---|---|---|---|---|
| 1 | `ambush_from_cover` | hunting_ambush | patience ≥0.4, fear ≤0.6 | stealth 0.2 | solo | I, D, O |
| 2 | `ambush_water_edge` | hunting_ambush | patience ≥0.5 | stealth 0.2, swimming_diving 0.2 | solo | I (semiacquatici), O |
| 3 | `burst_chase_flank` | hunting_pursuit | aggression ≥0.4 | hunting_pursuit 0.2 | solo | I, O |
| 4 | `stalk_downwind` | hunting_ambush | patience ≥0.4, curiosity ≥0.3 | stealth 0.3, tracking 0.2 | solo | D, O |
| 5 | `relay_pursuit` | hunting_cooperative | sociability ≥0.5, patience ≥0.3 | hunting_pursuit 0.4 | chaser x2-4, leader | O (tier ≥3), P |
| 6 | `drive_into_ambush` | hunting_cooperative | sociability ≥0.5 | hunting_cooperative 0.4, stealth 0.3 | leader, chaser, ambusher | O, P |
| 7 | `isolate_weakest` | hunting_cooperative | aggression ≥0.4, patience ≥0.3 | tracking 0.3 | leader, flanker x2, chaser | O |
| 8 | `pincer_flank` | hunting_cooperative | sociability ≥0.4 | combat_melee 0.3 | flanker x2, blocker | O |
| 9 | `nonlethal_pin_and_hold` | capture_nonlethal | patience ≥0.4, aggression ≤0.6 | capture_nonlethal 0.3, combat_melee 0.3 | solo/pair | P, D |
| 10 | `net_and_tangle_capture` | capture_nonlethal | patience ≥0.5 | capture_nonlethal 0.4, construction 0.2 | solo | P (tier ≥2) |
| 11 | `herd_prey_to_pen` | capture_nonlethal | sociability ≥0.5, patience ≥0.4 | hunting_cooperative 0.4, capture_nonlethal 0.3 | leader, chaser, blocker | P, O |
| 12 | `gentle_carry_capture` | capture_nonlethal | aggression ≤0.4, playfulness ≥0.3 | transport_hauling 0.3 | solo | P (caninoidi/felini) |
| 13 | `fish_dive_snatch` | fishing | patience ≥0.3 | fishing 0.2, swimming_diving 0.3 | solo | I, O |
| 14 | `fish_shallow_stand` | fishing | patience ≥0.6 | fishing 0.2 | solo | I (aironi-like), D |
| 15 | `burrow_flush_prey` | digging_burrowing | aggression ≥0.3, curiosity ≥0.3 | digging_burrowing 0.3 | solo | I (scavatori), O |
| 16 | `dig_den` | digging_burrowing | territoriality ≥0.3 | digging_burrowing 0.3 | solo/pair | I |
| 17 | `tunnel_ambush_tremor` | hunting_ambush | patience ≥0.5 | digging_burrowing 0.4, tracking 0.3 | solo | I (sotterranee), D |
| 18 | `forage_cache_return` | foraging | curiosity ≥0.3, patience ≥0.3 | foraging 0.2 | solo | I, D, O |
| 19 | `crack_shell_with_rock` | foraging | curiosity ≥0.6, playfulness ≥0.4 | foraging 0.3 | solo | D (tier ≥3), O |
| 20 | `harvest_and_haul` | harvesting | sociability ≥0.3 | harvesting 0.3, transport_hauling 0.3 | solo/colony | P, O |
| 21 | `relay_haul_chain` | transport_hauling | sociability ≥0.5 | transport_hauling 0.4 | hauler x3+ | P, O |
| 22 | `construct_nest_or_barrier` | construction | territoriality ≥0.4, patience ≥0.4 | construction 0.3 | builder, hauler | I (nidificanti), P |
| 23 | `guard_post_hold` | defense_guarding | territoriality ≥0.5, patience ≥0.4 | defense_guarding 0.3 | solo/pair | P, I |
| 24 | `sentinel_scan_alarm` | defense_guarding | fear ≥0.3, sociability ≥0.4 | communication 0.2 | sentinel | I (herd), O |
| 25 | `herd_circle_defense` | defense_herd_circle | sociability ≥0.6, fear ≥0.3 | defense_herd_circle 0.3 | blocker x3+, sentinel | I (herd), O |
| 26 | `shield_the_young` | defense_guarding | sociability ≥0.5 | defense_guarding 0.3 | solo | I, O |
| 27 | `intimidation_display` | combat_melee | aggression ≥0.4, fear ≤0.5 | communication 0.2 | solo | I, O |
| 28 | `charge_and_gore` | combat_melee | aggression ≥0.6 | combat_melee 0.4 | solo | I |
| 29 | `ranged_spit_or_throw` | combat_ranged | aggression ≥0.3 | combat_ranged 0.3 | solo | I (poche), D |
| 30 | `zigzag_break_pursuit` | evasion | fear ≥0.3 | evasion 0.3 | solo | I, O |
| 31 | `decoy_and_distract` | evasion | playfulness ≥0.3, curiosity ≥0.4 | evasion 0.4 | decoy, flanker | O (tier ≥3), P |
| 32 | `still_freeze_hide` | stealth | fear ≥0.4, patience ≥0.4 | stealth 0.2 | solo | I |
| 33 | `follow_scent_trail` | tracking | curiosity ≥0.3, patience ≥0.3 | tracking 0.3 | solo | I, O |
| 34 | `aerial_scout_report` | scouting_aerial | curiosity ≥0.5 | scouting_aerial 0.3, communication 0.3 | scout | P, O (voltatori) |
| 35 | `thermal_ridge_survey` | scouting_aerial | curiosity ≥0.4, patience ≥0.4 | scouting_aerial 0.4 | solo | I (planatori), D |
| 36 | `climb_cliff_ambush` | climbing | patience ≥0.4 | climbing 0.4, stealth 0.3 | solo | I (arrampicatori), D |
| 37 | `dive_current_feed` | swimming_diving | curiosity ≥0.3 | swimming_diving 0.4 | solo | I, O |
| 38 | `boundary_patrol_mark` | territory_patrol | territoriality ≥0.5 | territory_patrol 0.3 | solo/pack | I |
| 39 | `howl_gather_call` | communication | sociability ≥0.5 | communication 0.2 | leader | I, O |
| 40 | `retrieve_and_return` | retrieval_rescue | sociability ≥0.4, playfulness ≥0.3 | retrieval_rescue 0.3 | solo | P, O (caninoidi) |
| 41 | `rescue_drag_to_safety` | retrieval_rescue | sociability ≥0.6, fear ≤0.5 | transport_hauling 0.4, retrieval_rescue 0.3 | solo/pair | P, O |

(41 voci; le prime 12 sono le più rilevanti per il tuning iniziale.) Regole generali di apprendimento: `I` implica mastery iniziale grezza 0.15-0.35; `O` = osservazione con requisiti di 3.6; `P` = dimostrazione/ricompensa del giocatore (3.5); `D` = scoperta (3.7) con innesco contestuale in dati; le tecniche di gruppo richiedono ruoli individuali (sez. 4).

---

## 9. Integrazione con la libreria C++ e piano di implementazione

- **Moduli**: `perception`, `memory`, `needs`, `utility`, `htn`, `learning`, `social`, `ecosystem`, `lod`, `motor_intent`, tutti senza dipendenza da UE. Interfaccia con il mondo tramite `IWorldQuery` (voxel, spaziale) e `ICommandSink`.
- **Dati**: file di specie (`species/*.json|binary`) e di tecniche (`techniques/*.json`) validati da uno schema; il fixed vocabulary (assi, categorie, strutture) è un enum con tabelle di stringhe condivise con gli strumenti.
- **Fasi di sviluppo**: (1) decisore utilità + 5 tecniche individuali, 3 specie; (2) bisogni, memoria e percezione; (3) apprendimento (mastery, bandit); (4) social learning e gruppi; (5) ecosistema + LOD statistico; (6) tooling UI/telemetria; (7) tuning offline e carichi di stress (2.000 attive).
- **Test**: unit test deterministici, simulazioni headless con metriche di convergenza dell'apprendimento, test di regressione per hash di stato, test di carico con 2.000/200.000 e profilazione per sezione.
- **Aperti**: matrici `body_compat`, calibrazione dei pesi d'istinto per 70+ specie (iniziare da archetipi: ~8 archetipi comportamentali e override), rete di sicurezza per il multiplayer (autorità sul server, nessuna fiducia nei client), strategia di salvataggio incrementale della conoscenza individuale.

---

## 10. Rischi principali e mitigazioni

1. **Costo di authoring**: 70+ specie × tecniche. Mitigazione: archetipi + ereditarietà dati, tecniche generiche parametrizzate (la stessa `ambush_from_cover` per molte specie con parametri diversi).
2. **Comportamento illeggibile**: UI e "perché" (7.4), limiti di scoperta.
3. **Oscillazioni di utilità**: inerzia/commitment, isteresi nelle soglie, test di stabilità.
4. **Determinismo cross-platform**: fixed-point per lo stato appreso, golden replay in CI.
5. **Esplosione combinatoria delle tecniche di gruppo**: pochi protocolli HTN generici con ruoli parametrizzabili.
6. **Aspettative del giocatore**: la comunicazione chiara che l'apprendimento è "graduale e osservabile" e non magico.

---

## 11. Fonti e riferimenti

Cognizione animale e apprendimento sociale (citate dalla conoscenza dell'autore; URL da verificare):

- Hoppitt, W. & Laland, K. (2013). *Social Learning: An Introduction to Mechanisms, Methods, and Models*, Princeton University Press (distinzione enhancement/emulation/imitation, modelli di diffusione). https://press.princeton.edu/books/paperback/9780691150703/social-learning
- Whiten, A. & van de Waal, E. (2018). The pervasive role of social learning in primate lifetime development. *Behav Ecol Sociobiol*; Whiten et al. (2009), "Emulation, imitation, over-imitation and the scope of culture for child and chimpanzee", *Phil Trans R Soc B*. https://royalsocietypublishing.org/doi/10.1098/rstb.2009.0069
- Range, F. & Virányi, Z. (2014). Wolves are better imitators of conspecifics than dogs. *PLoS ONE* 9(1): e86559. https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0086559
- Allen, J., Weinrich, M., Hoppitt, W., Rendell, L. (2013). Network-based diffusion analysis reveals cultural transmission of lobtail feeding in humpback whales. *Science* 340. https://www.science.org/doi/10.1126/science.1236281
- Whitehead, H. & Rendell, L. (2015). *The Cultural Lives of Whales and Dolphins*, Univ. of Chicago Press (orche, tradizioni, trasmissione verticale/obliqua). https://press.uchicago.edu/ucp/books/book/chicago/C/bo16832403.html
- Krützen, M. et al. (2005). Cultural transmission of tool use in bottlenose dolphins (sponging). *PNAS* 102. https://www.pnas.org/doi/10.1073/pnas.0500423102
- Holzhaider, J., Hunt, G., Gray, R. (2010). Social learning in New Caledonian crows. *Learning & Behavior* 38. https://link.springer.com/article/10.3758/LB.38.3.206
- Thornton, A. & Raihani, N. (2008). The evolution of teaching. *Animal Behaviour* 75 (criteri funzionali di insegnamento; meerkat). https://doi.org/10.1016/j.anbehav.2007.12.016

Game AI:

- Mark, D. (2009). *Behavioral Mathematics for Game AI*. Cengage. Mark, D. & Dill, K. (2010). "Improving AI Decision Modeling Through Utility Theory", GDC 2010 (IAUS). https://www.gdcvault.com/play/1012410/Improving-AI-Decision-Modeling-Through
- Orkin, J. (2006). "Three States and a Plan: The AI of F.E.A.R.", GDC 2006 (GOAP). https://alumni.media.mit.edu/~jorkin/gdc2006_orkin_jeff_fear.pdf
- Humphreys, T. (2013). "Exploring HTN Planners through Example", *Game AI Pro*; Straatman, R., Verweij, T., Champandard, A. (2009), Killzone 2 multiplayer bots. http://www.gameaipro.com/GameAIPro/GameAIPro_Chapter12_Exploring_HTN_Planners_through_Example.pdf
- Evans, R. (2002). "Varieties of Learning", *AI Game Programming Wisdom* (Black & White: perceptron, decision tree, feedback del giocatore). https://www.gamedeveloper.com/design/the-ai-of-black-white
- Grand, S. (2000). *Creation: Life and How to Make It*; Cliff, D. & Grand, S. (1999), "The Creatures global digital ecosystem", *Artificial Life* 5. https://direct.mit.edu/artl/article/5/1/77/2285
- Jakobsson, J. / Videocult (2017). Rain World AI e ecosistema (talk e articoli di sviluppo). https://www.gdcvault.com/ (ricerca "Rain World")
- Team Ico, *The Last Guardian* (Trico): descrizioni pubbliche sull'IA di Trico e sui sistemi di "desiderio" e obbedienza parziale. https://www.gamedeveloper.com/ (ricerca "Trico AI")
- Monolith (2014). *Middle-earth: Shadow of Mordor*, Nemesis System; talk GDC 2015 di Michael de Plater. https://www.gdcvault.com/ (ricerca "Nemesis System")
- Sutton, R. & Barto, A. (2018). *Reinforcement Learning: An Introduction*, 2ª ed. (TD, eligibility traces, bandit). http://incompleteideas.net/book/the-book-2nd.html
- Li, L. et al. (2010). A Contextual-Bandit Approach to Personalized News Article Recommendation (LinUCB; riferimento per UCB contestuali). https://arxiv.org/abs/1003.0146
- Holling, C. S. (1959). Some characteristics of simple types of predation and parasitism (risposta funzionale). *Canadian Entomologist* 91.
- Reynolds, C. (1999). Steering Behaviors for Autonomous Characters, GDC 1999. https://www.red3d.com/cwr/steer/

Nota finale: dove il documento afferma valori numerici (costi in µs, parametri di apprendimento), essi sono **ipotesi di partenza** da validare con prototipazione e benchmark; non sono misure.
