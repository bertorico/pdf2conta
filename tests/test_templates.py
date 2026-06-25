"""Tests for ``ec_converter/templates/``: bank detection, template registry
and movement extraction from OCR-produced HTML tables.

Each template parses positional HTML columns produced by dots.ocr. Tests use
small synthetic HTML fragments (not full OCR dumps) that exercise the documented
behavior: column mapping, totali/saldo row skipping, continuation rows,
causale ABI extraction, signed amounts (BNL lista movimenti) and the
``titolare_conto`` extra-replace hook of the Intesa "ufficiale" template.

Module roots are exposed via the pytest ``pythonpath`` in ``pyproject.toml``,
so we import flat: ``from templates import ...``.
"""

import pytest

from templates import detect_bank, get_template, list_templates

# ---------------------------------------------------------------------------
# Registry: list_templates / get_template / detect_bank
# ---------------------------------------------------------------------------


def test_list_templates_restituisce_i_cinque_template():
    assert set(list_templates()) == {
        "intesa_sanpaolo_ufficiale",
        "intesa_sanpaolo",
        "bnl",
        "bnl_lista_movimenti",
        "bnl_pos",
    }


def test_get_template_restituisce_istanza_corretta():
    t = get_template("bnl")
    assert t.name == "bnl"


def test_get_template_nome_non_valido_solleva_value_error():
    with pytest.raises(ValueError, match="non trovato"):
        get_template("banana")


def test_get_template_ufficiale_accetta_titolare_conto():
    t = get_template("intesa_sanpaolo_ufficiale", titolare_conto="Rossi Mario")
    assert t.titolare_conto == "Rossi Mario"


def test_get_template_generico_ignora_kwargs_sconosciuti():
    """Templates without __init__ kwargs fall back to no-arg construction."""
    t = get_template("intesa_sanpaolo", titolare_conto="Rossi Mario")
    assert t.name == "intesa_sanpaolo"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Lista Movimenti C/C  Periodo", "bnl_lista_movimenti"),
        ("Dettaglio movimenti del conto corrente", "intesa_sanpaolo_ufficiale"),
        ("Riepilogo conto corrente", "intesa_sanpaolo_ufficiale"),
        ("Intesa Sanpaolo - estratto conto", "intesa_sanpaolo"),
        ("C/C n. 12345", "intesa_sanpaolo"),
        ("BNL banca", "bnl"),
        ("Banco Nazionale del Lavoro", "bnl"),
        ("Banca Sconosciuta", None),
        ("", None),
    ],
)
def test_detect_bank(text, expected):
    assert detect_bank(text) == expected


def test_detect_bank_pattern_specifici_vengono_prima():
    """'lista movimenti' wins over a generic 'bnl' if both appear."""
    assert detect_bank("BNL - Lista Movimenti") == "bnl_lista_movimenti"


# ---------------------------------------------------------------------------
# Intesa Sanpaolo (generic) — 5 columns: data_op, data_val, desc, dare, avere
# ---------------------------------------------------------------------------


INTESA_HTML = """
<table>
<tr><th>Data op.</th><th>Data val.</th><th>Descrizione</th><th>Addebiti</th><th>Accrediti</th></tr>
<tr><td>05.03.2026</td><td>06.03.2026</td><td>Pagamento POS</td><td>50,00</td><td></td></tr>
<tr><td>06.03.2026</td><td>07.03.2026</td><td>Accredito bonifico</td><td></td><td>1.000,00</td></tr>
<tr><td></td><td></td><td>Totali</td><td>50,00</td><td>1.000,00</td></tr>
</table>
"""


def test_intesa_generico_estrae_movimenti_escludendo_totali():
    t = get_template("intesa_sanpaolo")
    movs = t.estrai_movimenti([INTESA_HTML])
    assert len(movs) == 2
    assert movs[0].data_operazione == "05.03.2026"
    assert movs[0].data_valuta == "06.03.2026"
    assert movs[0].dare == pytest.approx(50.0)
    assert movs[0].avere is None
    assert movs[1].avere == pytest.approx(1000.0)
    assert movs[1].dare is None
    assert movs[0].pagina == 1


def test_intesa_generico_pagina_senza_tabella_viene_ignorata():
    t = get_template("intesa_sanpaolo")
    movs = t.estrai_movimenti(["<html><body>nessuna tabella qui</body></html>"])
    assert movs == []


def test_intesa_generico_riga_continuzione_appende_descrizione():
    """A row with no dates appends its description to the previous movement."""
    html = """
    <table>
    <tr><th>Data</th><th>Val</th><th>Descrizione</th><th>Dare</th><th>Avere</th></tr>
    <tr><td>05.03.2026</td><td>06.03.2026</td><td>Bonifico a favore</td><td></td><td>500,00</td></tr>
    <tr><td></td><td></td><td>Rossi Mario</td><td></td><td></td></tr>
    </table>
    """
    movs = get_template("intesa_sanpaolo").estrai_movimenti([html])
    assert len(movs) == 1
    assert "Rossi Mario" in movs[0].descrizione


def test_intesa_generico_saldo_iniziale_viene_ignorato():
    html = """
    <table>
    <tr><th>Data</th><th>Val</th><th>Descrizione</th><th>Dare</th><th>Avere</th></tr>
    <tr><td>01.01.2026</td><td></td><td>Saldo iniziale</td><td></td><td>5.000,00</td></tr>
    <tr><td>05.03.2026</td><td>06.03.2026</td><td>Spesa</td><td>10,00</td><td></td></tr>
    </table>
    """
    movs = get_template("intesa_sanpaolo").estrai_movimenti([html])
    assert len(movs) == 1
    assert movs[0].data_operazione == "05.03.2026"


# ---------------------------------------------------------------------------
# BNL — 6 columns: data_op, data_val, causale ABI, desc, dare, avere
# ---------------------------------------------------------------------------


BNL_HTML = """
<table>
<tr><th>Data contabile</th><th>Valuta</th><th>Caus. ABI</th><th>Descrizione</th><th>Uscita</th><th>Entrata</th></tr>
<tr><td>05/03/2026</td><td>06/03/2026</td><td>048</td><td>Bonifico ricevuto</td><td></td><td>25.586,87 €</td></tr>
<tr><td>06/03/2026</td><td>07/03/2026</td><td>066</td><td>Spese commiss. conto</td><td>8,70 €</td><td></td></tr>
<tr><td></td><td></td><td></td><td>Saldo iniziale</td><td></td><td>5.000,00 €</td></tr>
</table>
"""


def test_bnl_estrae_movimenti_con_causale_abi():
    t = get_template("bnl")
    movs = t.estrai_movimenti([BNL_HTML])
    assert len(movs) == 2
    assert movs[0].data_operazione == "05.03.2026"
    assert movs[0].causale == "048"
    assert movs[0].avere == pytest.approx(25586.87)
    assert movs[1].causale == "066"
    assert movs[1].dare == pytest.approx(8.70)


def test_bnl_date_con_slash_vengono_normalizzate_in_punti():
    movs = get_template("bnl").estrai_movimenti([BNL_HTML])
    assert "/" not in movs[0].data_operazione
    assert movs[0].data_operazione == "05.03.2026"


def test_bnl_causale_non_numerica_viene_nulla():
    html = """
    <table>
    <tr><th>Data contabile</th><th>Valuta</th><th>Caus. ABI</th><th>Descrizione</th><th>Uscita</th><th>Entrata</th></tr>
    <tr><td>05/03/2026</td><td>06/03/2026</td><td>ABC</td><td>Operazione</td><td></td><td>100,00 €</td></tr>
    </table>
    """
    movs = get_template("bnl").estrai_movimenti([html])
    assert len(movs) == 1
    assert movs[0].causale is None


# ---------------------------------------------------------------------------
# BNL Lista Movimenti — 9 columns, single signed amount
# ---------------------------------------------------------------------------


BNL_LISTA_HTML = """
<table>
<tr><th>Rag.Soc.</th><th>ABI</th><th>CAB</th><th>Conto</th><th>Operazione</th><th>Valuta</th><th>Importo</th><th>Causale</th><th>Descrizione</th></tr>
<tr><td>Farmacia</td><td>01000</td><td>03200</td><td>12345</td><td>05/03/2026</td><td>06/03/2026</td><td>-7.460,00</td><td>031</td><td>Pagamento disposiz. elettroniche</td></tr>
<tr><td>Farmacia</td><td>01000</td><td>03200</td><td>12345</td><td>06/03/2026</td><td>07/03/2026</td><td>4.000,00</td><td>048</td><td>Bonifico ricevuto</td></tr>
</table>
"""


def test_bnl_lista_movimenti_importo_negativo_va_in_dare():
    movs = get_template("bnl_lista_movimenti").estrai_movimenti([BNL_LISTA_HTML])
    assert len(movs) == 2
    assert movs[0].dare == pytest.approx(7460.0)
    assert movs[0].avere is None
    assert movs[0].causale == "031"


def test_bnl_lista_movimenti_importo_positivo_va_in_avere():
    movs = get_template("bnl_lista_movimenti").estrai_movimenti([BNL_LISTA_HTML])
    assert movs[1].avere == pytest.approx(4000.0)
    assert movs[1].dare is None


@pytest.mark.parametrize(
    "raw,expected_dare,expected_avere",
    [
        ("-7.460,00", 7460.0, None),
        ("4.000,00", None, 4000.0),
        ("-1,55", 1.55, None),
        ("", None, None),
        ("N/D", None, None),
    ],
)
def test_bnl_lista_parse_importo_con_segno(raw, expected_dare, expected_avere):
    t = get_template("bnl_lista_movimenti")
    dare, avere = t._parse_importo_con_segno(raw)
    if expected_dare is None:
        assert dare is None
    else:
        assert dare == pytest.approx(expected_dare)
    if expected_avere is None:
        assert avere is None
    else:
        assert avere == pytest.approx(expected_avere)


# ---------------------------------------------------------------------------
# Intesa Sanpaolo Ufficiale — titolare_conto + skip competenze/totali
# ---------------------------------------------------------------------------


INTESA_UFF_HTML = """
<table>
<tr><th>Data operazione</th><th>Valuta</th><th>Descrizione</th><th>Addebiti</th><th>Accrediti</th></tr>
<tr><td>05.03.2026</td><td>06.03.2026</td><td>Accredito POS al netto esente ROSSI MARIO</td><td></td><td>1.725,57</td></tr>
<tr><td></td><td></td><td>Totali</td><td></td><td>1.725,57</td></tr>
</table>
"""


def test_intesa_ufficiale_rimuove_titolare_conto():
    t = get_template("intesa_sanpaolo_ufficiale", titolare_conto="ROSSI MARIO")
    movs = t.estrai_movimenti([INTESA_UFF_HTML])
    assert len(movs) == 1
    assert "ROSSI MARIO" not in movs[0].descrizione


def test_intesa_ufficiale_salta_pagina_competenze():
    """Pages with 'Dettaglio competenze di chiusura' are not movement pages."""
    competenze_html = """
    <table>
    <tr><th>Data operazione</th><th>Valuta</th><th>Descrizione</th><th>Addebiti</th><th>Accrediti</th></tr>
    <tr><td>05.03.2026</td><td>06.03.2026</td><td>Competenza</td><td>5,00</td><td></td></tr>
    </table>
    <p>Dettaglio competenze di chiusura</p>
    """
    t = get_template("intesa_sanpaolo_ufficiale")
    assert t.estrai_movimenti([competenze_html]) == []


def test_intesa_ufficiale_salta_righe_totali_estese():
    html = """
    <table>
    <tr><th>Data operazione</th><th>Valuta</th><th>Descrizione</th><th>Addebiti</th><th>Accrediti</th></tr>
    <tr><td></td><td></td><td>Totale accrediti</td><td></td><td>1.725,57</td></tr>
    <tr><td></td><td></td><td>A vostro credito</td><td></td><td>1.725,57</td></tr>
    <tr><td>05.03.2026</td><td>06.03.2026</td><td>Spesa</td><td>10,00</td><td></td></tr>
    </table>
    """
    movs = get_template("intesa_sanpaolo_ufficiale").estrai_movimenti([html])
    assert len(movs) == 1
    assert movs[0].data_operazione == "05.03.2026"
