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
  → [6] Preview tabella editabile (Gradio Dataframe)
  → [7] Export CSV formato Ago Zucchetti
```

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

### Dataclass Movimento (`templates/base.py`)

Campi: `data_operazione` (DD.MM.YYYY), `data_valuta`, `descrizione_raw`, `descrizione` (pulita), `dare` (float), `avere` (float), `causale` (codice), `causale_nome`, `pagina`.

### Normalizzazione importi (`normalizer.py`)

Gestisce anomalie OCR tipiche: spazi spuri ("3,420, 00"), virgole al posto di punti, simbolo €. L'ultimo separatore seguito da 2 cifre è il decimale, il resto sono migliaia.

### Configurazioni runtime (editabili da UI)

- **`ec_converter/causali.json`**: mappatura codice causale → pattern descrizione. Match case-insensitive come sottostringa. 9 causali preconfigurate (bonifici, ADUE, spese bancarie, ecc.).
- **`ec_converter/replace_descrizioni.json`**: regole sostituzione testo nelle descrizioni. Applicate in ordine, case-insensitive. Gestiscono typo OCR ("disposo" → "disposto"), abbreviazioni, pulizia prefissi. 22 regole preconfigurate.

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
