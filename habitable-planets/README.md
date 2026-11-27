# habscan: ricerca probabilistica di pianeti potenzialmente abitabili

Pipeline che scarica tutti i pianeti confermati e i candidati TESS e Kepler, valuta per ciascuno la
probabilità di abitabilità propagando le incertezze di misura con Monte Carlo, stima con il machine
learning la probabilità che un candidato sia un pianeta reale e produce una classifica validata.

```
NASA Exoplanet Archive (pscomppars, TOI, KOI) ─┐
PHL Habitable Worlds Catalog (solo confronto) ─┤
                                               ▼
                      armonizzazione → tabella unica (≈ 24 000 righe)
                                               │
        ┌──────────────────────────────────────┼───────────────────────────────────────┐
        ▼                                      ▼                                       ▼
 P(roccioso | R, S), P(roccioso | M, S)  P(reale) per i candidati             motore Monte Carlo
 miscela con deconvoluzione (EM)         (LightGBM, RF, HGB, logistica:        2000 campioni per pianeta:
 su ≈ 430 pianeti con M e R misurate     scelta per log-loss in CV             zona abitabile Kopparapu 2014,
                                         raggruppata per stella, poi           composizione Zeng 2016,
                                         calibrazione isotonica)               cosmic shoreline con storia XUV,
                                                                               stella di sequenza principale
        └──────────────────────────────────────┴───────────────────────────────────────┘
                                               ▼
               P(abitabile) × P(reale) → classifica, benchmark, report
```

## Il punto chiave: perché non è un classificatore addestrato su etichette "abitabile"

Non esiste un solo esopianeta osservato come abitabile. Le etichette dei cataloghi, come la colonna
`P_HABITABLE` del PHL, non sono osservazioni: sono l'uscita di una regola (zona abitabile più limiti di
raggio e massa). Un modello di ML addestrato su quelle etichette impara la regola e non aggiunge fisica.
La pipeline lo dimostra a ogni esecuzione: un albero decisionale di profondità 2 sulle colonne del
catalogo stesso le riproduce con AUC ≈ 0,98 (sezione "circolarità" del report).

Il ML si usa quindi dove esiste una verità di riferimento reale:

1. **Vetting dei candidati.** Migliaia di TOI e KOI sono stati risolti dalle osservazioni di follow-up
   come pianeti confermati o falsi positivi. Il modello impara P(pianeta reale | osservabili) e la
   applica ai candidati ancora aperti.
2. **Popolazione rocciosa.** Dai pianeti con massa e raggio entrambi misurati si impara quanto è
   probabile che un pianeta di un certo raggio (o massa) e flusso sia roccioso. Le etichette sono
   fisiche (curva di composizione di Zeng et al. 2016), con l'errore di misura deconvoluto tramite EM.

L'abitabilità si calcola invece con un modello fisico probabilistico, e "il modello migliore" si
sceglie con test che hanno una risposta nota: il Sistema Solare e i vincoli JWST sulle atmosfere.

## Componenti fisici

| Componente | Modello | Riferimento |
|---|---|---|
| Zona abitabile | bordi a polinomio in Teff, bordo interno dipendente dalla massa; probabilità di appartenenza lineare in log S tra limiti conservativi e ottimistici (incertezza sui bordi) | Kopparapu et al. 2014 |
| Flusso | L = R²T⁴ (o L di catalogo), a da Keplero, media orbitale S/√(1−e²) | Williams & Pollard 2002 |
| Composizione | R = (1,07 − 0,21·CMF)·M^(1/3,7); roccioso se volatili assenti | Zeng et al. 2016 |
| Massa ↔ raggio non misurati | condizionati al caso roccioso (Zeng, CMF ~ U(0,15; 0,45)); previsione non condizionata con Chen & Kipping 2017 (inversione bayesiana su griglia) | Chen & Kipping 2017 |
| M sin i | massa vera = M sin i / sin i con orbite isotrope | — |
| Perdita dell'atmosfera | cosmic shoreline I ∝ v_esc⁴ con fluenza XUV cumulativa (saturazione più lunga per le nane M), calibrata su Marte | Zahnle & Catling 2017; Ribas et al. 2005 |
| Blocco mareale | tempo di sincronizzazione (indicativo, non entra nella probabilità) | Gladman et al. 1996 |
| ESI | indice di similarità terrestre (raggio, flusso) | Schulze-Makuch et al. 2011 |

Tutto è calcolato **per campione congiunto** (2000 per pianeta). Le correlazioni, per esempio stella
più calda → più flusso **e** bordo della zona abitabile diverso, sono quindi propagate correttamente.

## Validazione (dall'ultima esecuzione, vedi `outputs/report.md`)

- **Sistema Solare:** Terra ≈ 0,98, Marte ≈ 0,5 (sulla shoreline), Venere, Mercurio e i giganti 0.
  Una Terra osservata solo in transito ≈ 0,98; una Terra osservata solo in velocità radiale ≈ 0,5.
  La sola massa non dice se è rocciosa, ed è un risultato onesto.
- **Atmosfere (JWST/Spitzer):** LHS 3844 b, GJ 1252 b, TRAPPIST-1 b e c, GJ 1132 b e GJ 367 b sono
  previsti senza atmosfera spessa, in accordo con le osservazioni. 55 Cnc e è un errore noto: è un
  oceano di magma con degassamento, fenomeno non modellato.
- **Vetting:** hold-out su stelle mai viste. Kepler AUC ≈ 0,998, TESS AUC ≈ 0,93, entrambi calibrati
  (ECE < 0,03).
- **Ablazioni:** senza propagazione delle incertezze la classifica cambia sensibilmente
  (Spearman ≈ 0,7 sui pianeti rilevanti); con la sola ESI o con la regola PHL gli ordinamenti sono
  molto diversi e l'ESI da sola dà punteggi alti anche a corpi non abitabili del Sistema Solare.
- **Robustezza:** per ogni pianeta, la frazione di 18 varianti del modello in cui resta nella top 20.

## Uso

```bash
cd habitable-planets
pip install -e .            # oppure: pip install -r requirements.txt
habscan fetch               # scarica i cataloghi in data/raw (con hash e timestamp)
habscan run                 # pipeline completa (≈ 15-20 min su 4 core)
habscan run --samples 500 --no-sensitivity   # versione veloce (≈ 4 min)
habscan planet "TRAPPIST-1 e" "Proxima Cen b"  # tutti i numeri per pianeti specifici
pytest                      # 43 test: fisica, campionamento, motore, cataloghi, EM, vetting
```

Output in `outputs/`:

| File | Contenuto |
|---|---|
| `report.md` | report completo con figure e tabelle |
| `top_candidates.csv` | i 100 migliori per P(abitabile) × P(reale) |
| `ranking_all.csv.gz` | tutti i ≈ 13 800 oggetti analizzati, con tutte le componenti |
| `benchmark.json` | metriche di ogni validazione, ricerca del modello, configurazione, provenienza dei dati |
| `figures/` | diagramma della zona abitabile, vetting, modello roccioso, shoreline |

## Colonne principali della classifica

- `p_habitable`: P(roccioso ∧ in zona abitabile ∧ atmosfera trattenuta ∧ stella di sequenza principale | misure)
- `p_real`: 1 per i confermati, probabilità calibrata dal modello di vetting per i candidati
- `p_habitable_and_real`: il prodotto, criterio di ordinamento
- `robust_top_fraction`: stabilità nella top 20 al variare dei parametri incerti
- `case`: A = M e R misurate, B = solo R, C = solo M vera, D = solo M sin i
- `p_rocky`, `p_hz`, `p_atm_retention`, `p_main_sequence`: le componenti, per capire *perché* un pianeta è in alto o in basso

## Limiti noti (dichiarati, non nascosti)

- La shoreline modella solo la fuga atmosferica. Non include il degassamento (55 Cnc e), la fase di
  pre-sequenza principale super-luminosa delle nane M (Luger & Barnes 2015) né la dispersione della
  rotazione iniziale. Le ultime due renderebbero le nane M ancora più sfavorevoli.
- P(roccioso) è appresa su pianeti in gran parte caldi (S mediano ≈ 70). La cross-validation ha scelto
  di **non** estrapolare il trend in flusso oltre il supporto dei dati. Le masse TTV (bassa densità) e
  RV (alta densità) hanno bias opposti, quindi si usa la media dei due modelli.
- Il vetting eredita lo spostamento di popolazione tra candidati risolti e aperti (si risolvono prima
  i segnali brillanti e profondi): l'ordinamento è più affidabile del valore assoluto.
- I cataloghi non sono incrociati tra loro: un KOI candidato osservato anche da TESS può comparire due volte.
- "Abitabile" qui significa condizioni necessarie per acqua liquida in superficie. Non è una
  rilevazione di vita né una prova di abitabilità.
