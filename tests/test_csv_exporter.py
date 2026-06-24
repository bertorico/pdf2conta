"""Tests for the two CSV exporters:

- ``ec_converter/csv_exporter.py`` — bank movements -> Ago CSV, two modes
  (``due_colonne`` Dare/Avere, ``colonna_unica`` signed amount) with optional
  causale column.
- ``fatture_converter/csv_exporter.py`` — invoices -> Ago CSV, one row per
  invoice, 3 fixed aliquota groups + Q/R/S duplicate-percentage columns.

Module roots are exposed via the pytest ``pythonpath`` in ``pyproject.toml``:
both ``ec_converter`` and ``fatture_converter`` are on the path. Note the
invoice exporter imports ``fatture_converter.fattura`` (absolute), which works
because the repo root is also on sys.path during collection.
"""

import csv
import io

from csv_exporter import export_csv
from fatture_converter.csv_exporter import export_fatture_csv
from fatture_converter.fattura import AliquotaIVA, Fattura
from templates.base import Movimento

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mov(*, data="05.03.2026", desc="Pagamento POS", dare=None, avere=None, causale=None):
    return Movimento(data, None, desc, desc, dare=dare, avere=avere, causale=causale)


def _parse(csv_text: str, sep=";"):
    return list(csv.reader(io.StringIO(csv_text), delimiter=sep))


# ---------------------------------------------------------------------------
# ec_converter.export_csv — due_colonne mode
# ---------------------------------------------------------------------------


def test_export_csv_due_colonne_header_e_righe():
    out = export_csv([_mov(dare=50.0), _mov(avere=100.0)])
    rows = _parse(out)
    assert rows[0] == ["Data Operazione", "Descrizione", "Addebiti", "Accrediti"]
    assert rows[1][0] == "05.03.2026"
    assert rows[1][2] == "50,00"
    assert rows[1][3] == ""
    assert rows[2][2] == ""
    assert rows[2][3] == "100,00"


def test_export_csv_due_colonne_con_causale_aggiunge_colonna():
    out = export_csv([_mov(dare=50.0, causale="09")], includi_causale=True)
    rows = _parse(out)
    assert rows[0] == ["Data Operazione", "Descrizione", "Causale", "Addebiti", "Accrediti"]
    assert rows[1][2] == "09"


def test_export_csv_lista_vuota_restituisce_solo_header():
    out = export_csv([])
    rows = _parse(out)
    assert len(rows) == 1
    assert rows[0] == ["Data Operazione", "Descrizione", "Addebiti", "Accrediti"]


def test_export_csv_movimento_senza_importi_mostra_zero_in_colonna_unica():
    """In single-column mode, a movement with no dare/avere exports '0,00'."""
    out = export_csv([_mov()], modalita_importo="colonna_unica")
    rows = _parse(out)
    assert rows[1][-1] == "0,00"


# ---------------------------------------------------------------------------
# ec_converter.export_csv — colonna_unica mode (signed)
# ---------------------------------------------------------------------------


def test_export_csv_colonna_unica_dare_negativo_avere_positivo():
    out = export_csv(
        [_mov(dare=50.0), _mov(avere=100.0)],
        modalita_importo="colonna_unica",
    )
    rows = _parse(out)
    assert rows[0] == ["Data Operazione", "Descrizione", "Importo"]
    assert rows[1][-1] == "-50,00"
    assert rows[2][-1] == "100,00"


def test_export_csv_colonna_unica_con_causale():
    out = export_csv(
        [_mov(dare=50.0, causale="66")],
        modalita_importo="colonna_unica",
        includi_causale=True,
    )
    rows = _parse(out)
    assert rows[0] == ["Data Operazione", "Descrizione", "Causale", "Importo"]
    assert rows[1][2] == "66"
    assert rows[1][-1] == "-50,00"


def test_export_csv_separatore_personalizzato():
    out = export_csv([_mov(dare=50.0)], separatore=",")
    rows = _parse(out, sep=",")
    assert len(rows) == 2


def test_export_csv_importi_formattati_italiano():
    """Italian format: thousands '.', decimals ','."""
    out = export_csv([_mov(dare=1234.5)])
    rows = _parse(out)
    assert rows[1][2] == "1.234,50"


# ---------------------------------------------------------------------------
# fatture_converter.export_fatture_csv
# ---------------------------------------------------------------------------


def _fattura(aliquote=None):
    return Fattura(
        tipo_documento="TD01",
        numero_documento="3/PF/V",
        data_documento="05/03/2026",
        cf_cedente="01234567890",
        cf_cessionario="MRZFNC50A01F205X",
        nome_cessionario="FERNANDA",
        cognome_cessionario="MARZUOLI",
        aliquote=aliquote if aliquote is not None else [],
    )


def test_export_fatture_csv_header_ha_3_gruppi_e_colonne_qrs():
    out = export_fatture_csv([])
    rows = _parse(out)
    header = rows[0]
    # a-g (7) + 3 groups x 3 (9) + Q/R/S (3) = 19 columns
    assert len(header) == 19
    assert header[:7] == [
        "Tipo Documento",
        "Numero Documento",
        "Data Documento",
        "CF Cedente",
        "CF Cessionario",
        "Nome",
        "Cognome",
    ]
    assert header[7:10] == ["Imponibile 1", "IVA 1", "Aliquota 1"]
    assert header[10:13] == ["Imponibile 2", "IVA 2", "Aliquota 2"]
    assert header[13:16] == ["Imponibile 3", "IVA 3", "Aliquota 3"]
    assert header[16:] == ["Aliquota Rip. 1", "Aliquota Rip. 2", "Aliquota Rip. 3"]


def test_export_fatture_csv_una_riga_per_fattura():
    f = _fattura([AliquotaIVA(netto=3.38, iva=0.34, aliquota=10)])
    out = export_fatture_csv([f])
    rows = _parse(out)
    assert len(rows) == 2  # header + 1 row
    row = rows[1]
    assert row[0] == "TD01"
    assert row[1] == "3/PF/V"
    assert row[2] == "05/03/2026"
    assert row[3] == "01234567890"
    assert row[4] == "MRZFNC50A01F205X"
    assert row[5] == "FERNANDA"
    assert row[6] == "MARZUOLI"


def test_export_fatture_csv_primo_gruppo_aliquota_popolato():
    f = _fattura([AliquotaIVA(netto=3.38, iva=0.34, aliquota=10)])
    out = export_fatture_csv([f])
    rows = _parse(out)
    row = rows[1]
    assert row[7] == "3,38"
    assert row[8] == "0,34"
    assert row[9] == "10"
    # Second and third groups are empty padding
    assert row[10:13] == ["", "", ""]
    assert row[13:16] == ["", "", ""]


def test_export_fatture_csv_colonne_qrs_duplicano_aliquota():
    f = _fattura([AliquotaIVA(netto=3.38, iva=0.34, aliquota=10)])
    out = export_fatture_csv([f])
    rows = _parse(out)
    row = rows[1]
    # Q,R,S duplicate the aliquota % of groups 1,2,3
    assert row[16] == "10"
    assert row[17] == ""
    assert row[18] == ""


def test_export_fatture_csv_piu_aliquote_riempie_gruppi_successivi():
    f = _fattura(
        [
            AliquotaIVA(netto=3.38, iva=0.34, aliquota=10),
            AliquotaIVA(netto=45.0, iva=0.0, aliquota=0),
        ]
    )
    out = export_fatture_csv([f])
    rows = _parse(out)
    row = rows[1]
    assert row[7:10] == ["3,38", "0,34", "10"]
    assert row[10:13] == ["45,00", "0,00", "0"]
    assert row[16] == "10"
    assert row[17] == "0"


def test_export_fatture_csv_senza_aliquote_riga_con_padding_vuoto():
    f = _fattura([])  # no aliquota rows
    out = export_fatture_csv([f])
    rows = _parse(out)
    row = rows[1]
    assert row[7:16] == ["", "", "", "", "", "", "", "", ""]
    assert row[16:19] == ["", "", ""]


def test_export_fatture_csv_piu_fatture_una_riga_per_ognuna():
    f1 = _fattura([AliquotaIVA(netto=1.0, iva=0.1, aliquota=10)])
    f2 = _fattura([AliquotaIVA(netto=2.0, iva=0.4, aliquota=20)])
    out = export_fatture_csv([f1, f2])
    rows = _parse(out)
    assert len(rows) == 3  # header + 2 rows
    assert rows[1][9] == "10"
    assert rows[2][9] == "20"
