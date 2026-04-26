# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Panoramica

Deployment Docker di **dots.ocr** (rednote-hilab/dots.ocr) per OCR documenti, con pipeline specializzata per la conversione di **estratti conto bancari PDF → CSV Ago Zucchetti**.

## Architettura — 5 servizi

```
┌─────────────────────────────────┐
│   dots-ocr (vLLM)               │ ← Backend AI GPU (porta 8222)
│   POST /v1/chat/completions     │   Immagine: vllm/vllm-openai:v0.11.0
│   GET  /health                  │   Modello: rednote-hilab/dots.ocr
└─────────────────────────────────┘
      ↑            ↑            ↑
      │            │            │
┌─────┴──────┐ ┌───┴────────┐ ┌┴─────────────┐
│dots-ocr-ui │ │ec-converter│ │  processor   │
│  (Gradio)  │ │  (Gradio)  │ │  (batch)     │
│ porta 8223 │ │ porta 8224 │ │  background  │
│ ./ui/      │ │./ec_conv./ │ │ ./processor/ │
└────────────┘ └────────────┘ └──────────────┘

┌──────────────────────┐
│  fatture-converter   │ ← Standalone, NO GPU, NO dots-ocr
│  (batch one-shot)    │   Usa pdftotext (poppler-utils)
│  ./fatture_converter/│
└──────────────────────┘
```

- **dots-ocr**: server vLLM con API OpenAI-compatible. Richiede GPU. Health check con start_period 600s.
- **dots-ocr-ui**: OCR interattivo su singole immagini. 5 modalità prompt (full, ocr, layout, tables, ordered).
- **ec-converter-ui**: conversione estratti conto PDF → CSV per Ago Zucchetti. 3 tab UI (Converter, Causali, Replace). Non richiede GPU.
- **processor**: monitora `input/` ogni 30s, processa PDF automaticamente, output in `output/` (md, json, csv). Sposta PDF processati in `input/processed/`.
- **fatture-converter**: conversione batch fatture cartacee PDF → CSV per Ago Zucchetti. Indipendente da dots-ocr (usa `pdftotext`). Si avvia, processa, e si ferma (`restart: "no"`).

I servizi dots-ocr-ui, ec-converter e processor comunicano con dots-ocr via `http://dots-ocr:8000/v1/chat/completions`. Il fatture-converter non ha dipendenze da altri servizi.

## Comandi

```bash
# Avvio completo (primo build)
docker compose up -d --build

# Solo backend + ec-converter (uso tipico per estratti conto)
docker compose up -d dots-ocr ec-converter-ui

# Log specifici
docker compose logs -f ec-converter-ui
docker compose logs -f processor
docker compose logs -f dots-ocr

# Stato servizi
docker compose ps

# Stop
docker compose down
```

### Accesso

| Servizio | URL |
|---|---|
| OCR generico (Gradio) | http://localhost:8223 |
| EC Converter (Gradio) | http://localhost:8224 |
| API vLLM | http://localhost:8222 |
| Health check | http://localhost:8222/health |
| Modelli disponibili | http://localhost:8222/v1/models |

## EC Converter — Pipeline estratti conto

### Flusso

```
PDF estratto conto
  → [1] pdf2image (DPI 200, poppler-utils)
  → [2] OCR via dots-ocr API (prompt: layout + testo)
  → [3] HTML parsing (BeautifulSoup) con template banca
  → [4] Normalizzazione importi/date/descrizioni
  → [5] Assegnazione causali automatiche (pattern matching)
  → [6] Correzione segno dare/avere per causali univoche (POS, bonifici, spese...)
  → [7] Estrazione saldi e quadratura (solo template Intesa)
  → [8] Preview tabella editabile (Gradio Dataframe) + Export CSV Ago
```

### Contratti pipeline (entry-point principali)

- `pipeline.process_pdf(pdf_path, template_name="intesa_sanpaolo", dpi=None, progress_callback=None, titolare_conto="") -> (list[Movimento], str, dict)`. Il dict saldi è popolato solo per i template Intesa.
- `templates.get_template(name, **kwargs) -> BankTemplate`. Accetta kwargs per i template che li supportano (es. `titolare_conto` per `intesa_sanpaolo_ufficiale`).
- `templates.detect_bank(first_page_text: str) -> str | None`. Pattern controllati in ordine (specifici prima di generici, vedi `_DETECT_PATTERNS`).
- `pipeline.estrai_saldi_intesa(pages_html) -> dict`. Cerca pattern `Saldo iniziale al ...`, `Totale accrediti`, `Totale addebiti`, `Saldo finale al ...` nelle prime 2 pagine.

### Template bancari

Ogni banca ha un template che definisce il parsing posizionale delle colonne HTML prodotte dall'OCR. Auto-detect dalla prima pagina tramite pattern nel testo.

| Template | Colonne | Note |
|---|---|---|
| `intesa_sanpaolo_ufficiale` | 5 (come intesa_sanpaolo) | Layout estratto conto ufficiale Intesa con riepilogo + dettaglio. Pattern detect: "dettaglio movimenti del conto corrente". Pulisce codici Setefi (COMM/TC/GEST), ADUE B2B (COD.DISP./MANDATO). Estrae saldi per quadratura. Supporta `titolare_conto` per rimuovere nome ricorrente dalle descrizioni POS. |
| `intesa_sanpaolo` | 5: data_op, data_val, desc, dare, avere | Default se auto-detect fallisce |
| `bnl` | 6: +causale ABI (colonna 2) | Date DD/MM/YYYY, importi con € |
| `bnl_lista_movimenti` | Variante BNL per "lista movimenti" | Pattern detect: "lista movimenti" |

Registry in `ec_converter/templates/__init__.py`: dizionario `TEMPLATES` + lista `_DETECT_PATTERNS` (ordine importante: pattern specifici prima).

### Aggiungere un nuovo template bancario

1. Creare `ec_converter/templates/nome_banca.py` con classe che estende `BankTemplate`
2. Implementare `estrai_movimenti(pages_html: list[str]) -> list[Movimento]`
3. Opzionale: override di `_ha_tabella_movimenti()` per header specifici della banca
4. Registrare in `ec_converter/templates/__init__.py`:
   - Aggiungere import e entry in `TEMPLATES`
   - Aggiungere pattern in `_DETECT_PATTERNS` (pattern più specifici prima)
5. Aggiungere replace specifici in `ec_converter/replace_descrizioni.json`
6. Verificare che i pattern delle causali in `causali.json` coprano i movimenti tipici della banca; se servono nuove causali con segno univoco, aggiornare anche `CAUSALE_SEGNO` in `normalizer.py`
7. Se la banca ha un riepilogo saldi a inizio estratto, considerare di estendere `pipeline.estrai_saldi_*` per abilitare la quadratura

### Dataclass Movimento (`templates/base.py`)

Campi: `data_operazione` (DD.MM.YYYY), `data_valuta`, `descrizione_raw`, `descrizione` (pulita), `dare` (float), `avere` (float), `causale` (codice), `causale_nome`, `pagina`, `corretto` (bool, True se il segno dare/avere è stato auto-corretto in step [6]).

### Normalizzazione importi (`normalizer.py`)

Gestisce anomalie OCR tipiche: spazi spuri ("3,420, 00"), virgole al posto di punti, simbolo €. L'ultimo separatore seguito da 2 cifre è il decimale, il resto sono migliaia.

### Pulizia descrizioni (`normalizer.pulisci_descrizione`)

Pipeline a 8 step (`raw, max_length=100, extra_replaces=None`):
- **[0]** Decodifica entità HTML (`&gt;` → `>`, `&lt;`, `&amp;`, `&apos;`, `&quot;`). Necessaria perché dots-ocr a volte produce `&gt;` nei codici Setefi (`/GEST=&gt;SETEFI`).
- **[1]** Strip tag HTML (`<br>`, `<ul>`, `<li>`, ecc.).
- **[2]** Replace configurabili (`replace_descrizioni.json`).
- **[3]** Asterisco iniziale rimosso.
- **[4]** Regex pulizia codici tecnici: `COMM:.../GEST=...` (Setefi POS), `COD. DISP.`, `MANDATO`, `BIC ORD`, `E2EID`, `NOTPROVIDED`, `NOME:` (label ADUE), codici alfanumerici 15+ caratteri (IBAN/CRO).
- **[5]** `extra_replaces` dinamici (es. titolare conto passato da UI).
- **[6]** Collasso spazi.
- **[7]** Troncamento intelligente a `max_length` (non spezza parole se possibile).

### Correzione segno dare/avere (`normalizer.correggi_segno_per_causale`)

L'OCR a volte mette l'importo nella colonna sbagliata (rilevato 55% inversione sui POS in `intesa_ufficiale.pdf`). La correzione automatica usa una mappa statica codice causale → segno univoco (`CAUSALE_SEGNO` in `normalizer.py`):

- **AVERE**: 04 (POS), 48 (bonifico ricevuto), 91 (versamento contanti)
- **DARE**: 05 (ADUE/SDD), 26 (pagamento bolletta), 27 (bonifico emesso), 31 (disposiz. elettroniche), 37 (ricarica utenza), 54 (premio polizza), 66 (spese bancarie), 78 (prelevamento)

Trigger swap: causale presente in `CAUSALE_SEGNO` AND solo una colonna valorizzata AND quella colonna è opposta al segno atteso. Imposta `Movimento.corretto = True`. Conteggio mostrato in UI nel box Stato e con `⚠` nella colonna `Corretto` della tabella anteprima.

**Importante**: la mappa è statica nel codice (NON in `causali.json`) perché è semantica contabile invariante. Se aggiungi una causale al JSON e ha segno univoco, aggiorna anche `CAUSALE_SEGNO`.

### Quadratura saldi (template Intesa)

`pipeline.estrai_saldi_intesa(pages_html)` legge dal riepilogo iniziale: `saldo_iniziale`, `saldo_finale`, `totale_accrediti`, `totale_addebiti`, `data_iniziale`, `data_finale`. `process_pdf` ritorna il dict come terzo elemento del tuple (per template non-Intesa contiene chiavi a None).

Box markdown in UI mostra variazione attesa (`saldo_finale - saldo_iniziale`), variazione movimenti (`avere - dare`), differenza, ✅/⚠ in base a `abs(diff) < 0.01 €`. Non blocca l'export.

### Configurazioni runtime (editabili da UI)

- **`ec_converter/causali.json`**: mappatura codice causale → pattern descrizione. Match case-insensitive come sottostringa. **11 causali** preconfigurate (POS 04, bonifici 27/48, ADUE 05, disposiz. 31, ricariche 37, prelievi 78, spese 66, versamenti 91, bollette 26, polizze 54).
- **`ec_converter/replace_descrizioni.json`**: regole sostituzione testo nelle descrizioni. Applicate in ordine, case-insensitive. Gestiscono typo OCR ("disposo" → "disposto"), abbreviazioni, pulizia prefissi. **~38 regole** preconfigurate (incluse le 16 specifiche del layout Intesa ufficiale: POS Setefi, ADUE B2B, RIBA, commissioni, ricariche).

### Export CSV

Due modalità: **due colonne** (Dare/Avere separate) o **colonna unica** (importo con segno +/-). Separatore `;` (compatibile Excel italiano). Colonna Causale opzionale.

## Fatture Converter — Pipeline fatture cartacee

Servizio standalone per convertire fatture cartacee (PDF digitali) in CSV importabile in Ago Zucchetti. Non richiede GPU ne' dots-ocr — usa `pdftotext` (poppler-utils) per l'estrazione testo.

### Flusso

```
PDF fatture in fatture_converter/e_fatture/
  → [1] pdftotext -layout (estrazione testo con layout)
  → [2] Parsing regex (tipo doc, numero, data, CF, nome/cognome, aliquote IVA)
  → [3] Export CSV formato Ago Zucchetti
  → [4] Spostamento PDF processati in e_fatture/processate/
```

### Struttura CSV output

Una riga per PDF. Separatore `;`, importi con virgola italiana, date DD/MM/YYYY.

| Colonne | Campo |
|---------|-------|
| a | Tipo documento (TD01=fattura, TD04=nota credito) |
| b | Numero documento (senza spazi) |
| c | Data documento |
| d | CF cedente (configurabile, default 00000000000) |
| e | CF cessionario |
| f | Nome cessionario |
| g | Cognome cessionario |
| h-j | Imponibile, IVA, Aliquota (1a aliquota) |
| k-m | Imponibile, IVA, Aliquota (2a aliquota, se presente) |
| n-p | 3a aliquota, ecc. |
| q-s | Duplicazione aliquota % (1a, 2a, 3a) — richiesto da formato importazione Ago |

Aliquote supportate: percentuali (es. 10%, 22%) e **esenti** (importate come aliquota 0).

### File del modulo (`fatture_converter/`)

- `fattura.py` — Dataclass `Fattura` + `AliquotaIVA`, funzione `parse_fattura()` con regex per estrazione campi
- `csv_exporter.py` — `export_fatture_csv()` con colonne dinamiche per aliquote multiple
- `process_fatture.py` — Script batch main (entry point del container)
- `e_fatture/` — PDF fatture da processare (non committare)
- `output/e_fatture/` — CSV generato
- `e_fatture/processate/` — PDF gia' processati

### Configurazione

| Variabile d'ambiente | Default | Descrizione |
|---|---|---|
| `CF_CEDENTE` | 00000000000 | Codice fiscale del cedente |

### Comandi

```bash
# Si avvia automaticamente con docker compose up -d
# Processa, genera CSV, sposta PDF in processate/, e si ferma

# Per rieseguire manualmente
docker compose run --rm fatture-converter

# Con CF cedente diverso
docker compose run --rm -e CF_CEDENTE=12345678901 fatture-converter
```

## Batch Processor (servizio `processor`)

Workflow: inserire PDF in `input/` → il processor li rileva ogni `CHECK_INTERVAL` secondi → converte in immagini → chiama vLLM → esporta in `output/` (md + json + csv tabelle) → sposta PDF in `input/processed/`.

### Variabili d'ambiente (compose.yml)

| Variabile | Default | Descrizione |
|---|---|---|
| `CHECK_INTERVAL` | 30 | Secondi tra scansioni cartella |
| `DPI` | 200 | Risoluzione conversione PDF→immagini |
| `PROMPT_MODE` | full | Modalità OCR (full/ocr/layout/tables/ordered o prompt custom) |
| `MAX_TOKENS` | 4096 | Max token risposta vLLM (ec-converter) |

## Directory dati

- **`e_c/`** — PDF estratti conto reali per ec-converter (non committare)
- **`fatture_converter/e_fatture/`** — PDF fatture cartacee da processare (non committare)
- **`fatture_converter/output/`** — CSV fatture generato
- **`input/`** → **`output/`** — batch processor generico
- **`models/`** — cache modello dots.ocr HuggingFace (bind mount su `/root/.cache/huggingface`)

## Configurazione GPU (vLLM)

- `gpu-memory-utilization: 0.7` (lascia spazio per altri processi)
- `max-model-len: 8192`
- `enforce-eager` (disabilita CUDA graphs, più stabile su 10GB)
- `mm-processor-kwargs: max_pixels 602112`
- `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
