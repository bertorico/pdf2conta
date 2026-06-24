# CLAUDE.md

Guida per Claude Code (claude.ai/code) su questa repository.

## Convenzioni di lavoro

- **A ogni richiesta di modifica o intervento sulla repo, invoca la skill `intervento-repo`** (`.claude/skills/intervento-repo/`). Definisce il workflow da seguire.
- **Ogni intervento rilevante va annotato in `.claude/skills/intervento-repo/INTERVENTI.md`** (codice, config, compose/docker, contratti pipeline, doc). In dubbio, annota.
- **Usa sempre l'agente opportuno**: `git-workflow-manager` per ogni operazione git (commit/branch/PR), `python-pro` per il codice Python, `documentation-engineer` per i doc.
- Commit/push/PR **solo su richiesta esplicita**. Dati reali (`e_c/`, `fatture_converter/e_fatture/`) **non committare**.

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
┌─────┴──────┐ ┌───┴────────┐ ┌┴─────────────┐
│dots-ocr-ui │ │ec-converter│ │  processor   │
│  (Gradio)  │ │  (Gradio)  │ │  (batch)     │
│ porta 8223 │ │ porta 8224 │ │  background  │
└────────────┘ └────────────┘ └──────────────┘

┌──────────────────────┐
│  fatture-converter   │ ← Standalone, NO GPU, NO dots-ocr (usa pdftotext)
└──────────────────────┘
```

- **dots-ocr**: server vLLM, API OpenAI-compatible. Richiede GPU. Health check `start_period` 600s.
- **dots-ocr-ui**: OCR interattivo su singole immagini. 5 modalità prompt (full, ocr, layout, tables, ordered).
- **ec-converter-ui**: estratti conto PDF → CSV Ago Zucchetti. 3 tab UI (Converter, Causali, Replace). No GPU.
- **processor**: monitora `input/` ogni 30s, processa PDF → `output/` (md, json, csv), sposta in `input/processed/`.
- **fatture-converter**: batch one-shot fatture cartacee PDF → CSV Ago. Indipendente da dots-ocr (`restart: "no"`).

dots-ocr-ui, ec-converter e processor parlano con dots-ocr via `http://dots-ocr:8000/v1/chat/completions`.

## Comandi

```bash
docker compose up -d --build                  # Avvio completo (primo build)
docker compose up -d dots-ocr ec-converter-ui # Solo backend + ec-converter (uso tipico)
docker compose logs -f ec-converter-ui        # Log specifici (o processor, dots-ocr)
docker compose ps                             # Stato servizi
docker compose down                           # Stop
docker compose run --rm fatture-converter     # Rieseguire fatture manualmente
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
PDF → [1] pdf2image (DPI 200) → [2] OCR via dots-ocr → [3] HTML parsing (template banca)
    → [4] Normalizzazione importi/date/descrizioni → [5] Causali automatiche (pattern matching)
    → [6] Correzione segno dare/avere → [7] Quadratura saldi (solo Intesa)
    → [8] Preview editabile (Gradio) + Export CSV Ago
```

### Contratti pipeline (entry-point)

- `pipeline.process_pdf(pdf_path, template_name="intesa_sanpaolo", dpi=None, progress_callback=None, titolare_conto="") -> (list[Movimento], str, dict)`. Il dict saldi è popolato solo per i template Intesa.
- `templates.get_template(name, **kwargs) -> BankTemplate`. Accetta kwargs (es. `titolare_conto` per `intesa_sanpaolo_ufficiale`).
- `templates.detect_bank(first_page_text: str) -> str | None`. Pattern in ordine (specifici prima, vedi `_DETECT_PATTERNS`).
- `pipeline.estrai_saldi_intesa(pages_html) -> dict`. Estrae saldo iniziale/finale, totale accrediti/addebiti dalle prime 2 pagine.

### Template bancari

Ogni banca ha un template per il parsing posizionale delle colonne HTML prodotte dall'OCR. Auto-detect dalla prima pagina. Registry in `ec_converter/templates/__init__.py` (`TEMPLATES` + `_DETECT_PATTERNS`).

| Template | Colonne | Note |
|---|---|---|
| `intesa_sanpaolo_ufficiale` | 5 | Layout ufficiale Intesa (riepilogo + dettaglio). Detect: "dettaglio movimenti del conto corrente". Pulisce Setefi/ADUE, estrae saldi, supporta `titolare_conto`. |
| `intesa_sanpaolo` | 5: data_op, data_val, desc, dare, avere | Default se auto-detect fallisce |
| `bnl` | 6: +causale ABI (col. 2) | Date DD/MM/YYYY, importi con € |
| `bnl_lista_movimenti` | variante BNL | Detect: "lista movimenti" |

### Aggiungere un nuovo template bancario

1. Creare `ec_converter/templates/nome_banca.py` con classe che estende `BankTemplate`.
2. Implementare `estrai_movimenti(pages_html: list[str]) -> list[Movimento]`.
3. Opzionale: override `_ha_tabella_movimenti()` per header specifici.
4. Registrare in `templates/__init__.py`: entry in `TEMPLATES` + pattern in `_DETECT_PATTERNS` (specifici prima).
5. Aggiungere replace specifici in `ec_converter/replace_descrizioni.json`.
6. Verificare che `causali.json` copra i movimenti tipici; se servono causali con segno univoco, aggiornare `CAUSALE_SEGNO` in `normalizer.py`.
7. Se la banca ha un riepilogo saldi, estendere `pipeline.estrai_saldi_*` per la quadratura.

### Dataclass Movimento (`templates/base.py`)

Campi: `data_operazione` (DD.MM.YYYY), `data_valuta`, `descrizione_raw`, `descrizione`, `dare` (float), `avere` (float), `causale`, `causale_nome`, `pagina`, `corretto` (bool, True se il segno è stato auto-corretto).

### Post-processing (dettaglio in SPECIFICA_TECNICA.md)

- **Normalizzazione importi** (`normalizer.py`): gestisce spazi spuri, virgole/punti, simbolo €.
- **Pulizia descrizioni** (`normalizer.pulisci_descrizione`): 8 step — decode HTML entities, strip tag, replace da JSON, regex codici tecnici (Setefi/ADUE/IBAN), troncamento.
- **Correzione segno dare/avere** (`normalizer.correggi_segno_per_causale`): l'OCR a volte inverte le colonne. Mappa **statica** codice→segno univoco in `CAUSALE_SEGNO` (`normalizer.py`, NON in `causali.json`, perché è semantica contabile invariante). Se aggiungi una causale con segno univoco al JSON, aggiorna anche `CAUSALE_SEGNO`.
- **Quadratura saldi** (Intesa): box UI confronta variazione attesa vs variazione movimenti, ✅/⚠ a `abs(diff) < 0.01 €`. Non blocca l'export.

### Configurazioni runtime (editabili da UI)

- `ec_converter/causali.json`: codice causale → pattern descrizione (match case-insensitive). 11 causali preconfigurate.
- `ec_converter/replace_descrizioni.json`: regole sostituzione testo, in ordine, case-insensitive. ~38 regole.

### Export CSV

Due modalità: **due colonne** (Dare/Avere) o **colonna unica** (importo con segno). Separatore `;`. Colonna Causale opzionale. Struttura dettagliata in `ec_converter/SPECIFICA_TECNICA.md`.

## Fatture Converter — Pipeline fatture cartacee

Servizio standalone PDF digitali → CSV Ago Zucchetti, via `pdftotext` (no GPU, no dots-ocr).

```
PDF in fatture_converter/e_fatture/
  → [1] pdftotext -layout → [2] Parsing regex (tipo doc, numero, data, CF, nome, aliquote IVA)
  → [3] Export CSV Ago → [4] Sposta PDF in e_fatture/processate/
```

Una riga per PDF; colonne a–s (tipo doc, numero, data, CF cedente/cessionario, nome/cognome, imponibile/IVA/aliquota × N). Aliquote percentuali ed esenti (=0). Struttura colonne completa in `SPECIFICA_TECNICA.md`.

File modulo (`fatture_converter/`): `fattura.py` (dataclass + `parse_fattura()`), `csv_exporter.py` (`export_fatture_csv()`), `process_fatture.py` (entry point).

Config: env `CF_CEDENTE` (default `00000000000`).

## Batch Processor (servizio `processor`)

Inserire PDF in `input/` → rilevato ogni `CHECK_INTERVAL`s → immagini → vLLM → `output/` (md+json+csv) → `input/processed/`.

| Variabile (compose.yml) | Default | Descrizione |
|---|---|---|
| `CHECK_INTERVAL` | 30 | Secondi tra scansioni |
| `DPI` | 200 | Risoluzione PDF→immagini |
| `PROMPT_MODE` | full | Modalità OCR (full/ocr/layout/tables/ordered o custom) |
| `MAX_TOKENS` | 4096 | Max token risposta vLLM |

## Directory dati

- `e_c/` — PDF estratti conto reali (non committare)
- `fatture_converter/e_fatture/` — PDF fatture (non committare) · `fatture_converter/output/` — CSV
- `input/` → `output/` — batch processor generico
- `models/` — cache modello dots.ocr HuggingFace

## Configurazione GPU (vLLM)

`gpu-memory-utilization: 0.7`, `max-model-len: 8192`, `enforce-eager`, `mm-processor-kwargs: max_pixels 602112`, `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`.

## Documentazione di dettaglio

- `ec_converter/SPECIFICA_TECNICA.md` — specifica completa EC/fatture converter (pipeline, colonne CSV, post-processing).
- `ec_converter/GESTIONE.md` — guida operativa (gestione, hot-reload config, troubleshooting).
- `README.md` — overview repo · `dots_ocr.md` — setup OCR dots.ocr.
