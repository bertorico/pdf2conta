# 📄 Italian Document OCR Stack — dots.ocr + vLLM + Ago Zucchetti

[![CI](https://github.com/bertorico/pdf2conta/actions/workflows/ci.yml/badge.svg)](https://github.com/bertorico/pdf2conta/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)

> Repository: [github.com/bertorico/pdf2conta](https://github.com/bertorico/pdf2conta)

A self-hosted document processing pipeline for Italian accounting workflows. Converts bank statements (estratti conto) and paper invoices into structured CSV files ready for import into **Ago Zucchetti**.

Built around [dots.ocr](https://huggingface.co/rednote-hilab/dots.ocr), a specialized OCR model for structured documents, served via vLLM.

---

## What it does

### EC Converter (Estratto Conto)
Converts bank statement PDFs into structured transaction data:

```
PDF → page images → dots.ocr → bank template parser → normalizer → CSV (Ago Zucchetti)
```

- **Auto-detects the bank** from the first page (or select manually)
- **Normalizes OCR output**: handles dots.ocr-specific artifacts like `"3,420, 00"` → `3420.00`
- **Assigns causali automatically** via configurable pattern matching
- **Gradio UI**: preview and edit transactions before exporting
- **Exports**: CSV with Dare/Avere columns or single signed column

### Fatture Converter
Converts paper pharmacy invoices (PDF with selectable text) into structured data:

```
PDF → pdftotext -layout → regex parser → Fattura dataclass → CSV
```

- Extracts: document type (TD01/TD04), document number, date, tax codes, VAT breakdown by rate
- Handles: `FATTURA`, `NOTA DI CREDITO`, multiple VAT rates, exempt amounts
- Batch processing: moves processed PDFs to `processate/` subfolder
- Configurable `CF_CEDENTE` via environment variable

### Batch Processor
Watches an input folder and automatically OCRs any PDF dropped in:

```
/input/*.pdf → vLLM OCR → /output/*.md + *.json + *_tables.csv
```

- Exports to Markdown, JSON, and CSV (tables only)
- Configurable DPI, prompt mode, check interval
- Moves processed files to `/input/processed/`

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Docker Compose                      │
│                                                      │
│  ┌──────────────┐    ┌─────────────────────────┐    │
│  │  dots-ocr    │    │    dots-ocr-ui          │    │
│  │  (vLLM)      │◄───│    (Gradio UI)          │    │
│  │  port 8222   │    │    port 8223            │    │
│  └──────┬───────┘    └─────────────────────────┘    │
│         │                                            │
│         │            ┌─────────────────────────┐    │
│         └───────────►│    ec-converter-ui      │    │
│         │            │    (Gradio UI)          │    │
│         │            │    port 8224            │    │
│         │            └─────────────────────────┘    │
│         │                                            │
│         └───────────►┌─────────────────────────┐    │
│                      │    processor            │    │
│                      │    (batch watcher)      │    │
│                      └─────────────────────────┘    │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │  fatture-converter (standalone batch script) │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

---

## Requirements

- Docker + Docker Compose
- NVIDIA GPU with CUDA (tested on RTX 3080 10GB)
- NVIDIA Container Toolkit
- ~8GB VRAM for dots.ocr model

---

## Quick Start

### 1. Clone and start

```bash
git clone https://github.com/bertorico/ai-ocr-stack
cd ai-ocr-stack
docker compose up -d
```

First startup downloads the `rednote-hilab/dots.ocr` model (~8GB). Wait for the healthcheck to pass before using the UIs.

### 2. Check service status

```bash
docker compose ps
curl http://localhost:8222/health  # dots-ocr vLLM
```

### 3. Access the interfaces

| Service | URL | Description |
|---|---|---|
| dots-ocr-ui | http://localhost:8223 | Generic document OCR |
| ec-converter | http://localhost:8224 | Bank statement → CSV |

---

## EC Converter Usage

### Via UI (recommended)

1. Open http://localhost:8224
2. Upload a bank statement PDF
3. Select bank (or leave "Auto-detect")
4. Click **Elabora PDF**
5. Review and edit the transaction table
6. Select CSV format (two columns or signed single column)
7. Click **Genera CSV** → download

### Supported banks

Add new banks by creating a template class in `ec_converter/templates/`.

Each template implements `estrai_movimenti(pages_html: list[str]) -> list[Movimento]`.

### Causali configuration

Open the **Gestione Causali** tab to define automatic matching rules:

```json
{
  "causali": [
    {
      "codice": "BBAN",
      "nome": "Bonifico bancario",
      "pattern": ["bonifico", "accredito stipendio", "rimessa"]
    }
  ]
}
```

Patterns are matched case-insensitively as substrings of the transaction description.

### Description cleanup

Open **Gestione Replace** to configure text substitutions applied before matching:

```json
{
  "replace": [
    {"trova": "PAGAMENTO TRAMITE POS", "sostituisci": "POS", "nota": "Semplifica descrizioni POS"}
  ]
}
```

---

## Fatture Converter Usage

Place pharmacy invoice PDFs in `fatture_converter/e_fatture/` and run:

```bash
docker compose run --rm fatture-converter

# Or with custom paths:
docker compose run --rm fatture-converter \
  python -m fatture_converter.process_fatture \
  --input-dir /app/e_fatture \
  --output-dir /app/output \
  --output-file fatture.csv
```

### Output CSV format

Compatible with Ago Zucchetti import. Each row contains:
- `tipo_documento`: TD01 (fattura) or TD04 (nota di credito)
- `numero_documento`
- `data_documento` (DD/MM/YYYY)
- `cf_cedente`, `cf_cessionario`
- `nome_cessionario`, `cognome_cessionario`
- One row per VAT rate with `netto`, `iva`, `aliquota`

### Configuration

```bash
# Environment variable for cedente tax code
CF_CEDENTE=YOUR_TAX_CODE docker compose run --rm fatture-converter
```

Or set in `docker-compose.yml`:
```yaml
environment:
  - CF_CEDENTE=YOUR_TAX_CODE
```

---

## Batch Processor Usage

Drop PDFs into the `input/` folder. The processor picks them up automatically.

```bash
cp document.pdf input/
# Wait for CHECK_INTERVAL seconds
ls output/  # document.md, document.json, document_tables.csv
```

### Configuration

| Variable | Default | Description |
|---|---|---|
| `VLLM_URL` | `http://dots-ocr:8000` | vLLM server URL |
| `CHECK_INTERVAL` | `30` | Seconds between folder checks |
| `DPI` | `200` | PDF to image resolution |
| `PROMPT_MODE` | `full` | OCR prompt: full/ocr/layout/tables/ordered |

---

## OCR Normalization

The `normalizer.py` module handles dots.ocr-specific output artifacts:

```python
# dots.ocr commonly produces:
"3,420, 00"   → 3420.00   # spurious spaces
"7, 244, 87"  → 7244.87   # commas as thousands separators
"2.500,00"    → 2500.00   # standard Italian format
"26, 452, 20 €" → 26452.20  # with currency symbol
```

The normalizer uses pattern matching on the last separator + 2 digits to determine decimal vs thousands separators — no heuristics, no locale assumptions.

---

## Privacy

- All OCR inference runs locally via vLLM
- No documents are sent to external services
- The `dots.ocr` model runs entirely on your GPU

---

## Development

Runtime dependencies are pinned per service (each `*/requirements.txt`); the host-side
dev tooling lives in `pyproject.toml`.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

ruff check .          # lint
ruff format .         # format
mypy                  # type-check (scoped)
pytest                # tests
pre-commit install    # run lint/format automatically on every commit
```

CI (GitHub Actions) runs lint, format-check, mypy and pytest on every push and pull request.

---

## License

MIT

---

## Author

[@bertorico](https://github.com/bertorico) — self-hosted AI, Italian fiscal domain, n8n automation.

*Built for real Italian accounting workflows with Ago Zucchetti.*
