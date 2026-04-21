"""
Pipeline di elaborazione: PDF -> immagini -> OCR -> parsing -> movimenti.

Riutilizza il servizio dots-ocr (vLLM) gia' in esecuzione.
"""

import os
import base64
import shutil
import tempfile
import logging
from pathlib import Path
from typing import Optional

import requests
from pdf2image import convert_from_path

from templates import get_template, list_templates, detect_bank
from templates.base import Movimento
from normalizer import match_causale, carica_causali

logger = logging.getLogger(__name__)

VLLM_URL = os.environ.get("VLLM_URL", "http://dots-ocr:8000")
MODEL_NAME = os.environ.get("MODEL_NAME", "rednote-hilab/dots.ocr")
DPI = int(os.environ.get("DPI", "200"))
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "4096"))

OCR_PROMPT = "Parse the document and extract all text content with layout information."


def check_ocr_server() -> bool:
    """Verifica che il server vLLM sia raggiungibile."""
    try:
        r = requests.get(f"{VLLM_URL}/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _image_to_base64(image_path: Path) -> str:
    with open(image_path, "rb") as f:
        data = f.read()
    return f"data:image/png;base64,{base64.b64encode(data).decode()}"


def _call_ocr(image_path: Path) -> Optional[str]:
    """Chiama l'API vLLM per una singola immagine."""
    try:
        img_b64 = _image_to_base64(image_path)
        payload = {
            "model": MODEL_NAME,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_PROMPT},
                    {"type": "image_url", "image_url": {"url": img_b64}},
                ],
            }],
            "max_tokens": MAX_TOKENS,
            "temperature": 0.0,
        }
        resp = requests.post(
            f"{VLLM_URL}/v1/chat/completions",
            json=payload,
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Errore OCR pagina {image_path.name}: {e}")
        return None


def pdf_to_images(pdf_path: str, dpi: int = None) -> list[Path]:
    """Converte un PDF in immagini PNG temporanee."""
    if dpi is None:
        dpi = DPI
    temp_dir = Path(tempfile.mkdtemp(prefix="ec_"))
    images = convert_from_path(str(pdf_path), dpi=dpi)
    paths = []
    for i, img in enumerate(images, start=1):
        p = temp_dir / f"page_{i:04d}.png"
        img.save(str(p), "PNG")
        paths.append(p)
    return paths


def ocr_pages(image_paths: list[Path], progress_callback=None) -> list[str]:
    """
    Esegue OCR su una lista di immagini.
    Returns lista di stringhe HTML/testo, una per pagina.
    progress_callback(page_num, total) se fornito.
    """
    results = []
    total = len(image_paths)
    for i, img_path in enumerate(image_paths, start=1):
        if progress_callback:
            progress_callback(i, total)
        text = _call_ocr(img_path)
        results.append(text or "")
        logger.info(f"OCR pagina {i}/{total}: {len(text or '')} caratteri")
    return results


def process_pdf(
    pdf_path: str,
    template_name: str = "intesa_sanpaolo",
    dpi: int = None,
    progress_callback=None,
) -> tuple[list[Movimento], str]:
    """
    Pipeline completa: PDF -> immagini -> OCR -> parsing -> movimenti.

    Args:
        pdf_path: percorso al file PDF
        template_name: nome del template bancario ("auto" per auto-detect)
        dpi: risoluzione per la conversione PDF->immagini
        progress_callback: callback(step, detail) per aggiornamenti UI

    Returns: (lista di Movimento normalizzati, nome template usato)
    """
    # Step 1: PDF -> immagini
    if progress_callback:
        progress_callback("pdf", "Conversione PDF in immagini...")
    image_paths = pdf_to_images(pdf_path, dpi)
    logger.info(f"Convertite {len(image_paths)} pagine da {pdf_path}")

    try:
        # Step 2: OCR
        if progress_callback:
            progress_callback("ocr", f"OCR di {len(image_paths)} pagine...")

        def ocr_progress(page, total):
            if progress_callback:
                progress_callback("ocr", f"OCR pagina {page}/{total}...")

        pages_html = ocr_pages(image_paths, progress_callback=ocr_progress)

        # Step 2.5: Auto-detect banca se richiesto
        if template_name == "auto":
            if progress_callback:
                progress_callback("detect", "Riconoscimento banca...")
            detected = detect_bank(pages_html[0]) if pages_html else None
            if detected:
                template_name = detected
                logger.info(f"Banca riconosciuta: {template_name}")
            else:
                template_name = "intesa_sanpaolo"
                logger.warning("Banca non riconosciuta, uso Intesa Sanpaolo come default")

        template = get_template(template_name)

        # Step 3: Estrazione movimenti con template banca
        if progress_callback:
            progress_callback("parse", "Estrazione movimenti...")
        movimenti = template.estrai_movimenti(pages_html)
        logger.info(f"Estratti {len(movimenti)} movimenti")

        # Step 4: Assegnazione causali automatiche
        if progress_callback:
            progress_callback("causali", "Assegnazione causali...")
        causali = carica_causali()
        for mov in movimenti:
            if mov.causale is None:
                codice, nome = match_causale(mov.descrizione_raw, causali)
                if codice:
                    mov.causale = codice
                    mov.causale_nome = nome

        return movimenti, template_name
    finally:
        # Pulizia immagini temporanee
        if image_paths:
            shutil.rmtree(image_paths[0].parent, ignore_errors=True)
