"""
Export movimenti in formato CSV per Ago Zucchetti.

Supporta due modalita' di export importi:
- Modalita' A: due colonne separate (Dare / Avere)
- Modalita' B: colonna unica con segno (+/-)

Colonna Causale opzionale (Fase 2).
"""

import csv
import io
from typing import Literal

from normalizer import formatta_importo
from templates.base import Movimento


def export_csv(
    movimenti: list[Movimento],
    modalita_importo: Literal["due_colonne", "colonna_unica"] = "due_colonne",
    includi_causale: bool = False,
    separatore: str = ";",
    encoding: str = "utf-8",
) -> str:
    """
    Genera il CSV in formato Ago Zucchetti.

    Args:
        movimenti: lista di movimenti normalizzati
        modalita_importo: "due_colonne" (Dare/Avere) o "colonna_unica" (Importo con segno)
        includi_causale: se True, aggiunge colonna Causale dopo Descrizione
        separatore: separatore campi CSV
        encoding: encoding del file

    Returns: stringa CSV
    """
    output = io.StringIO()
    writer = csv.writer(output, delimiter=separatore, quoting=csv.QUOTE_MINIMAL)

    # Header
    if modalita_importo == "due_colonne":
        header = ["Data Operazione", "Descrizione"]
        if includi_causale:
            header.append("Causale")
        header.extend(["Addebiti", "Accrediti"])
        writer.writerow(header)
    else:
        header = ["Data Operazione", "Descrizione"]
        if includi_causale:
            header.append("Causale")
        header.append("Importo")
        writer.writerow(header)

    for mov in movimenti:
        causale_str = mov.causale or ""

        if modalita_importo == "due_colonne":
            dare_str = formatta_importo(mov.dare) if mov.dare is not None else ""
            avere_str = formatta_importo(mov.avere) if mov.avere is not None else ""
            row = [mov.data_operazione, mov.descrizione]
            if includi_causale:
                row.append(causale_str)
            row.extend([dare_str, avere_str])
            writer.writerow(row)
        else:
            if mov.dare is not None and mov.dare > 0:
                importo_str = "-" + formatta_importo(mov.dare)
            elif mov.avere is not None and mov.avere > 0:
                importo_str = formatta_importo(mov.avere)
            else:
                importo_str = "0,00"
            row = [mov.data_operazione, mov.descrizione]
            if includi_causale:
                row.append(causale_str)
            row.append(importo_str)
            writer.writerow(row)

    return output.getvalue()


def export_csv_to_file(
    movimenti: list[Movimento],
    filepath: str,
    modalita_importo: Literal["due_colonne", "colonna_unica"] = "due_colonne",
    includi_causale: bool = False,
    separatore: str = ";",
    encoding: str = "utf-8",
):
    """Salva il CSV su file."""
    content = export_csv(movimenti, modalita_importo, includi_causale, separatore, encoding)
    with open(filepath, "w", encoding=encoding, newline="") as f:
        f.write(content)
