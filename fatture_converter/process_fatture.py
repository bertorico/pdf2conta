#!/usr/bin/env python3
"""
Script batch: processa tutte le fatture PDF in e_fatture/ e genera un CSV
importabile in Ago Zucchetti.

Usa pdftotext (poppler-utils) per estrarre il testo dai PDF.
Non richiede server OCR — le fatture sono PDF digitali con testo selezionabile.

Uso:
    python -m fatture_converter.process_fatture [--input-dir e_fatture/] [--output-dir output/e_fatture/]

Variabili d'ambiente:
    CF_CEDENTE    Codice fiscale cedente (obbligatoria)
"""

import argparse
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from fatture_converter.csv_exporter import export_fatture_csv_to_file
from fatture_converter.fattura import parse_fattura

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CF_CEDENTE = os.environ.get("CF_CEDENTE", "")
if not CF_CEDENTE:
    logger.warning("CF_CEDENTE non impostato: imposta la variabile d'ambiente (vedi .env.example)")


def extract_text(pdf_path: str) -> str:
    """Estrae il testo da un PDF usando pdftotext -layout."""
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pdftotext error: {result.stderr}")
    return result.stdout


def process_single_pdf(pdf_path: Path, cf_cedente: str) -> dict:
    """
    Processa un singolo PDF fattura.
    Returns dict con 'fattura' (Fattura) o 'error' (str).
    """
    try:
        text = extract_text(str(pdf_path))
        fattura = parse_fattura(text, cf_cedente)
        return {"fattura": fattura}
    except Exception as e:
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Converti fatture PDF in CSV per Ago Zucchetti")
    parser.add_argument("--input-dir", default="e_fatture/", help="Cartella con i PDF fatture")
    parser.add_argument("--output-dir", default="output/e_fatture/", help="Cartella output CSV")
    parser.add_argument("--output-file", default="fatture.csv", help="Nome file CSV output")
    parser.add_argument("--cf-cedente", default=None, help=f"CF cedente (default: {CF_CEDENTE})")
    args = parser.parse_args()

    cf_cedente = args.cf_cedente or CF_CEDENTE

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    if not input_dir.exists():
        logger.error(f"Cartella input non trovata: {input_dir}")
        sys.exit(1)

    pdf_files = sorted(input_dir.glob("*.pdf"))
    if not pdf_files:
        logger.error(f"Nessun file PDF trovato in {input_dir}")
        sys.exit(1)

    logger.info(f"Trovati {len(pdf_files)} PDF in {input_dir}")

    # Verifica pdftotext
    try:
        subprocess.run(["pdftotext", "-v"], capture_output=True, timeout=5)
    except FileNotFoundError:
        logger.error("pdftotext non trovato. Installare poppler-utils.")
        sys.exit(1)

    # Processa tutti i PDF
    fatture = []
    errori = []
    pdf_processati = []
    for i, pdf_path in enumerate(pdf_files, 1):
        logger.info(f"[{i}/{len(pdf_files)}] Processando: {pdf_path.name}")
        result = process_single_pdf(pdf_path, cf_cedente)

        if "error" in result:
            logger.error(f"  ERRORE: {result['error']}")
            errori.append((pdf_path.name, result["error"]))
        else:
            f = result["fattura"]
            logger.info(
                f"  OK: {f.tipo_documento} | {f.numero_documento} | {f.data_documento} | "
                f"{f.cognome_cessionario} {f.nome_cessionario} | "
                f"{len(f.aliquote)} aliquote"
            )
            fatture.append(f)
            pdf_processati.append(pdf_path)

    # Sposta PDF processati in sottocartella "processate"
    if pdf_processati:
        processate_dir = input_dir / "processate"
        processate_dir.mkdir(exist_ok=True)
        for pdf_path in pdf_processati:
            dest = processate_dir / pdf_path.name
            shutil.move(str(pdf_path), str(dest))
            logger.info(f"  Spostato: {pdf_path.name} -> processate/")

    # Export CSV
    if fatture:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / args.output_file
        export_fatture_csv_to_file(fatture, str(output_path))
        logger.info(f"CSV generato: {output_path} ({len(fatture)} fatture)")
    else:
        logger.warning("Nessuna fattura processata con successo.")

    # Riepilogo
    print(f"\n{'=' * 50}")
    print("RIEPILOGO")
    print(f"{'=' * 50}")
    print(f"PDF trovati:     {len(pdf_files)}")
    print(f"Fatture OK:      {len(fatture)}")
    print(f"Errori:          {len(errori)}")
    if errori:
        print("\nFile con errori:")
        for nome, err in errori:
            print(f"  - {nome}: {err}")
    if fatture:
        print(f"\nCSV salvato in:  {output_dir / args.output_file}")


if __name__ == "__main__":
    main()
