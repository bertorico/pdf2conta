#!/usr/bin/env python3
"""
Batch PDF OCR Processor per dots.ocr
Monitora la cartella /input e processa automaticamente i PDF trovati.
"""

import os
import time
import json
import csv
import base64
import re
import tempfile
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

import requests
from pdf2image import convert_from_path
from PIL import Image

# Configurazione da environment variables
VLLM_URL = os.environ.get("VLLM_URL", "http://dots-ocr:8000")
MODEL_NAME = os.environ.get("MODEL_NAME", "rednote-hilab/dots.ocr")
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "30"))
DPI = int(os.environ.get("DPI", "200"))
PROMPT_MODE = os.environ.get("PROMPT_MODE", "full")

# Directory di lavoro
INPUT_DIR = Path("/input")
OUTPUT_DIR = Path("/output")
PROCESSED_DIR = INPUT_DIR / "processed"

# Prompt modes predefiniti (compatibili con app.py)
PROMPT_MODES = {
    "full": "Parse the document and extract all text content with layout information.",
    "ocr": "OCR the image and extract all text.",
    "layout": "Detect and identify all layout elements in the document.",
    "tables": "Extract all tables and formulas from the document. Output tables in markdown format.",
    "ordered": "Extract all text maintaining the correct reading order.",
}


def log(message: str, level: str = "INFO"):
    """Log con timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}", flush=True)


def check_server() -> bool:
    """Verifica che il server vLLM sia raggiungibile"""
    try:
        r = requests.get(f"{VLLM_URL}/health", timeout=5)
        return r.status_code == 200
    except Exception as e:
        log(f"Server non raggiungibile: {e}", "ERROR")
        return False


def image_to_base64(image_path: Path) -> str:
    """Converte immagine in stringa base64 per l'API"""
    with open(image_path, "rb") as f:
        data = f.read()
    ext = image_path.suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def pdf_to_images(pdf_path: Path, dpi: int = 200) -> List[Path]:
    """
    Converte un PDF in una lista di immagini PNG.
    Restituisce la lista dei percorsi delle immagini create.
    """
    log(f"Conversione PDF in immagini: {pdf_path.name} (DPI: {dpi})")

    try:
        # Crea cartella temporanea per le immagini
        temp_dir = Path(tempfile.mkdtemp(prefix="pdf_", dir="/tmp"))

        # Converti PDF in immagini
        images = convert_from_path(str(pdf_path), dpi=dpi)

        image_paths = []
        for i, img in enumerate(images, start=1):
            img_path = temp_dir / f"page_{i:04d}.png"
            img.save(str(img_path), "PNG")
            image_paths.append(img_path)
            log(f"  Pagina {i}/{len(images)} convertita")

        log(f"✓ {len(image_paths)} pagine convertite")
        return image_paths

    except Exception as e:
        log(f"Errore conversione PDF: {e}", "ERROR")
        return []


def call_vllm_api(image_path: Path, prompt: str) -> Optional[str]:
    """
    Chiama l'API vLLM per processare un'immagine.
    Restituisce il testo estratto o None in caso di errore.
    """
    try:
        img_b64 = image_to_base64(image_path)

        payload = {
            "model": MODEL_NAME,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": img_b64}},
                ],
            }],
            "max_tokens": 2048,
            "temperature": 0.0,
        }

        resp = requests.post(f"{VLLM_URL}/v1/chat/completions", json=payload, timeout=120)
        resp.raise_for_status()

        return resp.json()["choices"][0]["message"]["content"]

    except requests.exceptions.Timeout:
        log(f"Timeout durante l'elaborazione di {image_path.name}", "ERROR")
        return None
    except requests.exceptions.HTTPError as e:
        log(f"HTTP error {e.response.status_code}: {e.response.text}", "ERROR")
        return None
    except Exception as e:
        log(f"Errore chiamata API: {e}", "ERROR")
        return None


def extract_markdown_tables(text: str) -> List[List[List[str]]]:
    """Estrae tutte le tabelle Markdown dal testo."""
    tables = []
    current_table = []

    for line in text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('|') and stripped.endswith('|'):
            # Salta righe separatore (|---|---|)
            if re.match(r'^\|[-| :]+\|$', stripped):
                continue
            # Estrai celle
            cells = [c.strip() for c in stripped[1:-1].split('|')]
            current_table.append(cells)
        else:
            if current_table:
                tables.append(current_table)
                current_table = []

    if current_table:
        tables.append(current_table)

    return tables


def export_results(pdf_name: str, pages_data: List[Dict[str, Any]]):
    """
    Esporta i risultati in vari formati:
    - Markdown (.md)
    - JSON (.json)
    - CSV (.csv) se ci sono tabelle
    """
    base_name = OUTPUT_DIR / pdf_name.replace(".pdf", "")

    # 1. Export Markdown
    md_path = base_name.with_suffix(".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# OCR: {pdf_name}\n\n")
        f.write(f"**Data elaborazione**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Totale pagine**: {len(pages_data)}\n\n")
        f.write("---\n\n")

        for page in pages_data:
            f.write(f"## Pagina {page['page_number']}\n\n")
            f.write(page['text'])
            f.write("\n\n---\n\n")

    log(f"✓ Salvato: {md_path.name}")

    # 2. Export JSON
    json_path = base_name.with_suffix(".json")
    json_data = {
        "document": pdf_name,
        "processed_at": datetime.now().isoformat(),
        "total_pages": len(pages_data),
        "pages": pages_data,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    log(f"✓ Salvato: {json_path.name}")

    # 3. Export CSV (solo se ci sono tabelle)
    all_tables = []
    for page in pages_data:
        tables = extract_markdown_tables(page['text'])
        for table in tables:
            all_tables.append({
                'page': page['page_number'],
                'table': table
            })

    if all_tables:
        csv_path = base_name.with_name(base_name.name + "_tables.csv")
        with open(csv_path, "w", encoding="utf-8-sig", newline='') as f:
            writer = csv.writer(f, delimiter=';')

            for i, item in enumerate(all_tables):
                if i > 0:
                    writer.writerow([])
                writer.writerow([f"=== Pagina {item['page']} - Tabella {i+1} ==="])
                writer.writerows(item['table'])

        log(f"✓ Salvato: {csv_path.name} ({len(all_tables)} tabelle)")


def process_pdf(pdf_path: Path) -> bool:
    """
    Processa un singolo PDF:
    1. Converte in immagini
    2. Chiama vLLM per ogni pagina
    3. Aggrega risultati
    4. Esporta in vari formati

    Restituisce True se completato con successo.
    """
    log(f"▶ Inizio elaborazione: {pdf_path.name}")

    # Ottieni prompt
    prompt = PROMPT_MODES.get(PROMPT_MODE, PROMPT_MODES["full"])
    if PROMPT_MODE not in PROMPT_MODES:
        # Se non è una modalità predefinita, usa come custom prompt
        prompt = PROMPT_MODE

    log(f"Prompt: {prompt[:80]}...")

    # Converti PDF in immagini
    image_paths = pdf_to_images(pdf_path, dpi=DPI)
    if not image_paths:
        log(f"✗ Impossibile convertire {pdf_path.name}", "ERROR")
        return False

    # Processa ogni pagina
    pages_data = []
    for i, img_path in enumerate(image_paths, start=1):
        log(f"Elaborazione pagina {i}/{len(image_paths)}...")

        text = call_vllm_api(img_path, prompt)
        if text is None:
            log(f"✗ Errore elaborazione pagina {i}", "ERROR")
            continue

        pages_data.append({
            "page_number": i,
            "text": text,
            "image_file": img_path.name,
        })

        log(f"✓ Pagina {i} completata ({len(text)} caratteri)")

    # Pulizia immagini temporanee
    if image_paths:
        temp_dir = image_paths[0].parent
        shutil.rmtree(temp_dir, ignore_errors=True)

    if not pages_data:
        log(f"✗ Nessuna pagina elaborata con successo per {pdf_path.name}", "ERROR")
        return False

    # Esporta risultati
    export_results(pdf_path.name, pages_data)

    log(f"✓ Completato: {pdf_path.name} ({len(pages_data)}/{len(image_paths)} pagine)")
    return True


def move_to_processed(pdf_path: Path):
    """Sposta il PDF processato nella cartella processed/"""
    try:
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        dest = PROCESSED_DIR / pdf_path.name

        # Se esiste già, aggiungi timestamp
        if dest.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stem = dest.stem
            dest = PROCESSED_DIR / f"{stem}_{timestamp}.pdf"

        shutil.move(str(pdf_path), str(dest))
        log(f"Spostato in: {dest.relative_to(INPUT_DIR)}")

    except Exception as e:
        log(f"Impossibile spostare {pdf_path.name}: {e}", "ERROR")


def watch_folder():
    """
    Loop principale: monitora la cartella input e processa i PDF trovati.
    """
    log("=" * 60)
    log("Batch PDF OCR Processor avviato")
    log(f"URL vLLM: {VLLM_URL}")
    log(f"Modello: {MODEL_NAME}")
    log(f"Intervallo controllo: {CHECK_INTERVAL}s")
    log(f"DPI conversione: {DPI}")
    log(f"Modalità prompt: {PROMPT_MODE}")
    log(f"Cartella input: {INPUT_DIR}")
    log(f"Cartella output: {OUTPUT_DIR}")
    log("=" * 60)

    # Crea cartelle se non esistono
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    # Attendi che il server vLLM sia pronto
    while not check_server():
        log("In attesa del server vLLM...", "WARN")
        time.sleep(10)

    log("✓ Server vLLM raggiungibile")

    # Loop principale
    while True:
        try:
            # Trova tutti i PDF nella cartella input (escludendo sottocartelle)
            pdf_files = sorted(INPUT_DIR.glob("*.pdf"))

            if pdf_files:
                log(f"Trovati {len(pdf_files)} PDF da processare")

                for pdf_path in pdf_files:
                    try:
                        success = process_pdf(pdf_path)

                        if success:
                            move_to_processed(pdf_path)
                        else:
                            log(f"PDF non spostato (errori durante elaborazione): {pdf_path.name}", "WARN")

                    except Exception as e:
                        log(f"Errore durante elaborazione di {pdf_path.name}: {e}", "ERROR")
                        import traceback
                        traceback.print_exc()

            # Attendi prima del prossimo controllo
            log(f"Prossimo controllo tra {CHECK_INTERVAL}s...")
            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            log("Interruzione manuale ricevuta. Arresto...")
            break

        except Exception as e:
            log(f"Errore nel loop principale: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    watch_folder()
