# GESTIONE EC Converter — Guida Operativa

Questa guida è per chi **utilizza e configura** il sistema EC Converter in produzione: come avviare, configurare causali e regole di pulizia testo, risolvere i problemi più comuni.

## Avvio rapido

Entrare nella directory root del progetto (`/mnt/sdb/ai/ai_ocr/`) e lanciare:

```bash
# Primo avvio (build completo)
docker compose up -d --build

# Avvio successivi (container gia' buildati)
docker compose up -d dots-ocr ec-converter-ui

# Vedere i log del convertitore
docker compose logs -f ec-converter-ui

# Verificare stato servizi
docker compose ps

# Spegnere tutto
docker compose down
```

L'interfaccia EC Converter è disponibile su **http://localhost:8224**. I PDF degli estratti conto vanno caricati nel tab "Converter".

### Dove finiscono i CSV

I file CSV generati restano in memoria fino al download tramite UI. I batch processor (se attivo) salva automaticamente in `/output/` cartella host.

---

## Configurazione causali (`causali.json`)

I codici causale sono il linguaggio contabile del sistema. Ogni movimento OCR viene assegnato a una causale tramite pattern-matching sottostringa sulla descrizione pulita.

### Struttura

File: `ec_converter/causali.json`

```json
{
  "causali": [
    {
      "codice": "04",
      "nome": "Incassi POS al netto",
      "pattern": ["accredito pos al netto", "pos al netto esente", "pos a pagamento"]
    },
    {
      "codice": "27",
      "nome": "Bonifico emesso",
      "pattern": ["bonifico da voi disposto", "bonifico a favore di"]
    }
  ]
}
```

- **codice**: ID numerico 2 cifre (es. "04", "27"). Non deve contenere zeri iniziali.
- **nome**: Descrizione causale (es. "Incassi POS al netto"). Visibile in UI e nel CSV finale.
- **pattern**: Lista di sottostringhe (case-insensitive) che triggerano la causale. Match: se UNA sottoscrizione è contenuta nella descrizione, causale assegnata.

### Aggiungere una causale

1. Aprire `ec_converter/causali.json` con un editor di testo.
2. Aggiungere una entry nel vettore `"causali"`:
   ```json
   {
     "codice": "XX",
     "nome": "Nome nuovo movimento",
     "pattern": ["parola1", "parola2 specifica"]
   }
   ```
3. Salvare il file.
4. Se il codice ha un **segno univoco** (es. sempre dare, sempre avere), aggiornare anche [`CAUSALE_SEGNO`](#aggiornare-causale_segno) in `normalizer.py` e fare `docker compose restart ec-converter-ui`.
5. Altrimenti, nessun restart necessario: il JSON viene ricaricato al prossimo PDF.

### Rinominare un codice causale

⚠️ **Critico**: se cambi il codice (es. "04" → "09"), devi **anche**:

1. Aggiornare la chiave in `CAUSALE_SEGNO` in [`normalizer.py`](#aggiornare-causale_segno) se presente (altrimenti la correzione automatica dare/avere smette di funzionare per quella causale).
2. Aggiornare eventuali pattern di replace in `replace_descrizioni.json` che fanno riferimento al codice vecchio (se ce ne sono).
3. Restart: `docker compose restart ec-converter-ui` (solo se hai toccato `normalizer.py`).

### Modificare pattern

Puoi aggiungere/togliere pattern dalla lista senza toccare il codice:

```json
{
  "codice": "48",
  "nome": "Bonifico ricevuto",
  "pattern": ["bonifico a vostro favore", "bonifico ricevuto", "nuova variante ocr"]
}
```

Se il pattern è frequente, aggiungilo qui. Se è un'anomalia OCR isolata (es. typo "disposo" invece di "disposto"), meglio usare un **replace** in `replace_descrizioni.json`.

### Testare le modifiche

Dopo aver salvato:

1. **Modifica pattern**: nessuna azione, viene riletta al prossimo PDF processato.
2. **Modifica codice causale che è in `CAUSALE_SEGNO`**: aggiorna anche `normalizer.py` e fai `docker compose restart ec-converter-ui`.

---

## Configurazione replace descrizioni (`replace_descrizioni.json`)

Le regole di replace correggono anomalie OCR e normalizzano il testo delle descrizioni PRIMA dell'assegnazione causale. Si applicano in ordine, case-insensitive (match come sottostringa).

### Struttura

```json
{
  "replace": [
    {
      "trova": "AccÑ€ÐµÐ´ito POS",
      "sostituisci": "Accredito POS",
      "nota": "Mojibake OCR circillico"
    },
    {
      "trova": "disposo",
      "sostituisci": "disposto",
      "nota": "Typo OCR comune"
    }
  ]
}
```

- **trova**: Stringa esatta da cercare (case-insensitive), match come sottostringa.
- **sostituisci**: Stringa di sostituzione.
- **nota**: Commento per ricordarsi perché la regola esiste (non influisce sul codice).

### ⚠️ Mojibake e problemi di encoding

**Problema frequente**: copi un pattern da una email, un documento web, o un terminale che usa encoding diverso (es. Latin-1 al posto di UTF-8), e finisci con una sequenza di caratteri spuri tipo `AccÑ€ÐµÐ´ito` (è Latin-1 di `Accредito` UTF-8).

**Soluzione**: sempre copiare direttamente dal CSV generato dal sistema (che è UTF-8), **non** da altri editor o fonti. Se devi descrivere il pattern per la nota, usa ASCII puro o spiega l'anomalia.

### Aggiungere una regola

1. Genera il CSV dall'estratto conto.
2. Guarda la colonna Descrizione nel CSV: se vedi una stringa ripetuta che è sbagliata (typo, prefisso, entità HTML), copiala **direttamente dal CSV**.
3. Aggiungi la entry in `replace_descrizioni.json`:
   ```json
   {
     "trova": "[copia letterale dal CSV]",
     "sostituisci": "[stringa corretta]",
     "nota": "[perché correggiamo]"
   }
   ```
4. Salva. Nessuna azione richiesta: il file viene riletto al prossimo PDF processato.

### Varianti OCR comuni (pattern multipli)

Se l'OCR produce varianti diverse della stessa frase (es. "Bonifico a Voi disposto", "Bonifico a Voi disposo", "Bonifico a Vost favore"), aggiungi **una riga per variante**:

```json
{
  "trova": "Bonifico da Voi disposto",
  "sostituisci": "Bonifico emesso",
  "nota": "OCR corretto"
},
{
  "trova": "Bonifico da Voi disposo",
  "sostituisci": "Bonifico emesso",
  "nota": "Variante OCR typo (disposo)"
},
{
  "trova": "Bonifico da Voi disposi",
  "sostituisci": "Bonifico emesso",
  "nota": "Variante OCR typo (disposi)"
}
```

Questo garantisce copertura anche di OCR "sporchi".

### Entità HTML

A volte dots.ocr produce entità HTML (`&gt;`, `&lt;`, `&apos;`, `&quot;`, `&amp;`). Il sistema decodifica automaticamente, ma se noti varianti non coperte, aggiungi un replace:

```json
{
  "trova": "&quot;",
  "sostituisci": "\"",
  "nota": "Decodifica doppio apice HTML"
}
```

---

## Ricostruzione del container vs. Ricarica da UI

> **Nota importante (aggiornamento più recente)**: il `compose.yml` monta ora `./ec_converter:/app` come bind-mount. Le modifiche ai file Python e ai JSON sull'host sono **immediatamente visibili dentro al container** senza bisogno di `--build`. Il `--build` resta necessario solo se cambi `requirements.txt` o `Dockerfile`.

**Problema risolto in parte**: prima i file erano copiati al build, oggi no. Resta solo il problema della **cache in memoria di Python**: una volta caricato un file JSON, Python lo tiene in memoria e non rilegge quello aggiornato finché non viene esplicitamente ricaricato.

**Stato attuale dopo i fix**:
- `causali.json` → ricaricato automaticamente ad ogni elaborazione PDF.
- `replace_descrizioni.json` → ricaricato automaticamente ad ogni elaborazione PDF.
- File Python (`normalizer.py`, `pipeline.py`, ecc.) → caricati all'avvio del processo, serve `docker compose restart ec-converter-ui` per rileggerli.

### Workflow consigliato (Best Practice)

Con il bind-mount attivo, modifiche ai JSON sull'host e modifiche da UI scrivono lo stesso file. Il workflow tipico:

1. **Modifica i JSON** direttamente nell'editor (`causali.json`, `replace_descrizioni.json`) oppure dalla UI: indifferente, è lo stesso file.
2. **Riprocessa un PDF** per testare: il sistema rilegge i JSON ad ogni elaborazione.
3. **Commit** su Git i file JSON (sono la SOURCE OF TRUTH per backup e versionamento).

### Quando servono azioni diverse

| Scenario | Azione |
|----------|--------|
| Modifico pattern causale da UI | Modifica live, salvata nel JSON via bind-mount. Commit per backup. |
| Modifico `causali.json` o `replace_descrizioni.json` sull'host | Nessuna azione: ricaricati al prossimo PDF processato. |
| Cambio `CAUSALE_SEGNO` in `normalizer.py` | `docker compose restart ec-converter-ui` |
| Modifico altro codice Python (template, app, pipeline) | `docker compose restart ec-converter-ui` |
| Modifico `requirements.txt` o `Dockerfile` | `docker compose up -d --build ec-converter-ui` |

---

## Mappatura `CAUSALE_SEGNO` (Segno univoco dare/avere)

File: `ec_converter/normalizer.py`, linee ~288-300.

Questa è una **mappa statica** che dice "per questa causale, il movimento è SEMPRE dare o SEMPRE avere". Usata per la correzione automatica quando OCR mette l'importo nella colonna sbagliata.

```python
CAUSALE_SEGNO: dict[str, str] = {
    "09": "A",  # Incassi POS al netto → AVERE
    "27": "D",  # Bonifico emesso → DARE
    "48": "A",  # Bonifico ricevuto → AVERE
    "05": "D",  # Pagamento ADUE/SDD → DARE
    "31": "D",  # Pagamento disposiz. elettroniche → DARE
    "66": "D",  # Spese bancarie → DARE
    "91": "A",  # Versamento contanti → AVERE
    "78": "D",  # Prelevamento titolare → DARE
    "26": "D",  # Pagamento bolletta → DARE
    "54": "D",  # Premio polizza → DARE
    "37": "D",  # Ricarica utenza → DARE
}
```

**Quando aggiornare**: ogni volta che aggiungi una causale con semantica contabile univoca.

**Come aggiornare**:
1. Apri `ec_converter/normalizer.py`.
2. Vai alla riga ~288.
3. Aggiungi la nuova entry: `"XX": "A"` oppure `"XX": "D"`.
4. Salva e fai `docker compose restart ec-converter-ui` (Python rilegge il file).

**Regola pratica**:
- POS, bonifici ricevuti, versamenti = **AVERE** ("A")
- Bonifici emessi, prelievi, spese, bollette, polizze = **DARE** ("D")

---

## Quadratura saldi (solo template Intesa)

Quando processi un estratto conto Intesa ufficiale, il sistema estrae il **saldo iniziale**, **saldo finale**, **totale accrediti**, **totale addebiti** dal riepilogo della prima pagina e li confronta con il totale calcolato dai movimenti.

### Cosa significa il simbolo ✅ / ⚠️

Nel box "Stato quadratura" dopo l'OCR:

- **✅ Quadratura OK**: la variazione calcolata dai movimenti corrisponde al saldo dichiarato (differenza < 0.01 €).
- **⚠️ Differenza X.XX €**: il totale dei movimenti non pareggia. Cause possibili:
  1. Movimenti saltati dall'OCR.
  2. Importi inversi (colonna dare/avere sbagliata): guardare la colonna "Corretto" — se molti movimenti hanno `⚠`, significa l'OCR ha invertito. L'auto-correzione scatta solo se la causale è in `CAUSALE_SEGNO` e una sola colonna è valorizzata.
  3. Saldo iniziale OCR errato.
  4. Importi anomali (es. spazi OCR sbagliati).

### Azioni

- Se differenza < 0.10 €: può essere arrotondamento OCR. Export a meno che non sia evidente un errore.
- Se differenza > 1 €: controllare il PDF originale, verificare che OCR abbia preso tutti i movimenti, eventualmente editare manualmente la tabella in UI.
- Se molti movimenti hanno `⚠` in "Corretto": aggiungi la causale a `CAUSALE_SEGNO` se manca, oppure usa replace per normalizzare i pattern OCR.

---

## Auto-correzione dare/avere (colonna "Corretto")

Nella tabella anteprima, la colonna **Corretto** mostra:
- Vuoto: il movimento non è stato corretto.
- **⚠**: il dare/avere è stato auto-corretto perché la causale ha segno univoco e l'importo era nella colonna opposta.

### Quando NON scatta

L'auto-correzione non tocca un movimento se:

1. **Causale assente**: nessuna pattern match.
2. **Causale non in `CAUSALE_SEGNO`**: es. aggiungi una causale "XX" ma non la mappe nella lista statica.
3. **Entrambe colonne valorizzate**: il sistema non sa quale è sbagliata (è ambiguo).

In questi casi, **edita manualmente** la riga in tabella (copia l'importo da una colonna all'altra).

---

## Troubleshooting (FAQ)

### "Ho modificato causali.json e non vedo le modifiche"

Dopo i fix recenti (bind-mount + ricarica auto al `process_pdf`), questa situazione non dovrebbe più verificarsi. Se accade ancora:

1. Verifica che il bind-mount sia attivo: `docker compose config | grep -A2 ec-converter-ui` deve mostrare `./ec_converter:/app`.
2. Verifica che il file JSON sia valido: `python -c "import json; json.load(open('ec_converter/causali.json'))"`.
3. Riprocessa il PDF (la cache viene invalidata ad ogni `process_pdf`).
4. Se hai modificato un codice che è in `CAUSALE_SEGNO`, fai anche `docker compose restart ec-converter-ui`.

### "Ho aggiunto un replace ma non viene applicato"

**Cause comuni** in ordine di probabilità:

1. **Encoding mojibake**: hai copiato da una fonte non-UTF-8 e la stringa visibile non corrisponde ai byte reali. Tipico esempio: pattern cirillico mostrato come `AccÑ€ÐµÐ´ito` mentre l'OCR produce `Accредито`. **Soluzione**: copia la stringa direttamente dal CSV generato dal sistema (UTF-8), non da editor web/email.
2. **Pattern troppo specifico**: l'OCR varia leggermente (spazi, maiuscole, typo). Il match è case-insensitive ma deve essere sottostringa esatta. **Soluzione**: aggiungi varianti come righe separate.
3. **JSON malformato**: una virgola mancante o un quote sbagliato impedisce il parsing. **Soluzione**: `python -c "import json; json.load(open('ec_converter/replace_descrizioni.json'))"`.

### "Non riconosce la banca (usa sempre intesa_sanpaolo generico)"

**Causa**: nessun pattern in `_DETECT_PATTERNS` matcha il testo della prima pagina.

**Soluzione**:
- Contattare chi mantiene il sistema per aggiungere il pattern della banca. Nel frattempo: usa il dropdown "Template" in UI e seleziona manualmente il template corretto.

### "Quadratura non torna"

**Cause tipiche** (in ordine di frequenza):
1. **Movimenti saltati**: OCR non ha riconosciuto una riga (es. formato data diverso, riga spezzata).
2. **Importi inversi**: vedi colonna "Corretto". Se molti `⚠`, significa OCR ha confuso dare/avere per quella banca.
3. **Saldo iniziale errato**: dots.ocr ha letto male il saldo iniziale dal riepilogo.
4. **OCR parziale**: la tabella movimenti non è stata riconosciuta completamente.

**Debug**:
- Scarica il CSV e conta manualmente: somma dare + somma avere.
- Guarda il PDF originale: conferma i saldi dichiarati e il numero movimenti.
- Edita le righe sbagliate in tabella UI (movimento per movimento).

### "OCR è molto lento"

Normale. Il modello dots.ocr gira su vLLM con GPU (RTX 3080 10GB). Un estratto conto 3-5 pagine impiega 30-120s. La velocità dipende da: numero pagine, risoluzione, utilizzo GPU da altri servizi, memoria disponibile.

**Ottimizzazione**: ridurre DPI (default 200). Nel compose.yml: `DPI=150`.

### "L'auto-detect sceglie il template sbagliato"

**Causa**: i pattern in `_DETECT_PATTERNS` sono controllati in ordine. Se un pattern generico matcha prima di uno specifico, template sbagliato.

**Soluzione**: usare il dropdown "Template" in UI per forzare il template manualmente. Contattare chi mantiene il sistema per riordenare i pattern (`templates/__init__.py`).

---

## Aggiungere una nuova banca

Rimando alla sezione "Aggiungere un nuovo template bancario" in [`../CLAUDE.md`](../CLAUDE.md). Richiede scrivere una classe Python, non è operazione end-user.

---

## Backup e versionamento

**Source of truth**: i file `causali.json` e `replace_descrizioni.json` sono il vostro "database" di configurazione.

**Best practice**:

1. **Commit su Git** ogni modifica significativa:
   ```bash
   git add ec_converter/causali.json ec_converter/replace_descrizioni.json
   git commit -m "Add causale XX per nuovo tipo movimento"
   ```

2. **Le modifiche da UI scrivono direttamente il file** (bind-mount attivo): committale come ogni altra modifica.

3. **Backup periodico** dei JSON se non usate Git (es. cartella `backup/`).

---

## Sommario delle modifiche principali

| File | Come modificare | Quando ricaricare |
|------|-----------------|-------------------|
| `causali.json` | Editor o UI tab | Auto al prossimo PDF processato |
| `replace_descrizioni.json` | Editor o UI tab | Auto al prossimo PDF processato |
| `normalizer.py` (`CAUSALE_SEGNO`) | Editor Python | `docker compose restart ec-converter-ui` |
| `templates/` (nuovo template) | Nuovo file .py + import in `__init__.py` | `docker compose restart ec-converter-ui` |
| `requirements.txt`, `Dockerfile` | Editor | `docker compose up -d --build ec-converter-ui` |
