"""
Export fatture in formato CSV per Ago Zucchetti.

Struttura: una riga per fattura, separatore ;, importi con virgola italiana.
Colonne a-j per la prima aliquota IVA, k-m per la seconda, n-p per la terza, ecc.
"""

import csv
import io

from fatture_converter.fattura import Fattura


def _formatta_importo(valore: float) -> str:
    """Formatta un float in stringa con virgola decimale italiana: 3,38"""
    return f"{valore:,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")


def export_fatture_csv(
    fatture: list[Fattura],
    separatore: str = ";",
) -> str:
    """
    Genera il CSV fatture per Ago Zucchetti.

    Colonne:
    a=Tipo doc, b=N.Documento, c=Data, d=CF cedente, e=CF cessionario,
    f=Nome, g=Cognome, h=Netto1, i=IVA1, j=Aliquota1,
    k=Netto2, l=IVA2, m=Aliquota2, ... (per ogni aliquota aggiuntiva)
    """
    output = io.StringIO()
    writer = csv.writer(output, delimiter=separatore, quoting=csv.QUOTE_MINIMAL)

    # Sempre 3 gruppi aliquote (h-p) per mantenere colonne Q, R, S in posizione fissa
    NUM_GRUPPI_ALIQUOTE = 3

    # Header: a-g + h-p (3 gruppi x 3 colonne) + q-s
    header = [
        "Tipo Documento", "Numero Documento", "Data Documento",
        "CF Cedente", "CF Cessionario", "Nome", "Cognome",
    ]
    for i in range(NUM_GRUPPI_ALIQUOTE):
        n = i + 1
        header.extend([f"Imponibile {n}", f"IVA {n}", f"Aliquota {n}"])
    # Colonne Q, R, S — duplicano l'aliquota % (richiesto da formato Ago)
    for i in range(NUM_GRUPPI_ALIQUOTE):
        header.append(f"Aliquota Rip. {i+1}")
    writer.writerow(header)

    # Righe
    for f in fatture:
        row = [
            f.tipo_documento,
            f.numero_documento,
            f.data_documento,
            f.cf_cedente,
            f.cf_cessionario,
            f.nome_cessionario,
            f.cognome_cessionario,
        ]
        # Colonne h-p: 3 gruppi aliquote, padding vuoto se meno di 3
        for i in range(NUM_GRUPPI_ALIQUOTE):
            if i < len(f.aliquote):
                aliq = f.aliquote[i]
                row.extend([
                    _formatta_importo(aliq.netto),
                    _formatta_importo(aliq.iva),
                    str(aliq.aliquota),
                ])
            else:
                row.extend(["", "", ""])
        # Colonne Q, R, S — duplicano l'aliquota %
        for i in range(NUM_GRUPPI_ALIQUOTE):
            if i < len(f.aliquote):
                row.append(str(f.aliquote[i].aliquota))
            else:
                row.append("")
        writer.writerow(row)

    return output.getvalue()


def export_fatture_csv_to_file(
    fatture: list[Fattura],
    filepath: str,
    separatore: str = ";",
):
    """Salva il CSV fatture su file."""
    content = export_fatture_csv(fatture, separatore)
    with open(filepath, "w", encoding="utf-8", newline='') as f:
        f.write(content)
