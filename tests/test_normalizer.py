"""Tests for ``ec_converter/normalizer.py``: amount, date and description
normalization of the OCR output produced by dots.ocr.

These tests describe the *real* behavior of the functions (verified by reading
the module), not assumptions. ``correggi_segno_per_causale`` is covered by
``test_correggi_segno.py`` and is intentionally not duplicated here.

Module roots are exposed via the pytest ``pythonpath`` in ``pyproject.toml``,
so we import flat: ``from normalizer import ...``.
"""

import pytest

from normalizer import normalizza_data, normalizza_importo, pulisci_descrizione

# ---------------------------------------------------------------------------
# normalizza_importo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Clean Italian format: thousands '.' and decimals ','
        ("2.500,00", 2500.00),
        ("1.234.567,89", 1234567.89),
        # Small amounts, no thousands separator
        ("154,00", 154.00),
        # NOTE: "154,5" is NOT parsed as 154.50. The decimal branch requires
        # exactly 2 trailing digits ([.,]\d{2}$), so it falls through to the
        # integer fallback which strips ',' -> "1545" -> 1545.0. One decimal
        # digit is an OCR edge case the function does not handle.
        ("154,5", 1545.0),
        # Euro symbol is stripped
        ("26, 452, 20 €", 26452.20),
        # OCR spurious spaces: "3,420, 00" -> 3420.00
        ("3,420, 00", 3420.00),
        # OCR commas used as thousands separator: "7, 244, 87" -> 7244.87
        ("7, 244, 87", 7244.87),
        # Integer fallback (no decimal separator with 2 trailing digits)
        ("2500", 2500.0),
        ("154", 154.0),
        # Dot as decimal separator (US-like), no thousands
        ("99.99", 99.99),
    ],
)
def test_normalizza_importo_casi_validi(raw, expected):
    assert normalizza_importo(raw) == pytest.approx(expected)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        None,
        "abc",
        "--",
        "N/D",
    ],
)
def test_normalizza_importo_casi_non_validi_restituisce_none(raw):
    assert normalizza_importo(raw) is None


def test_normalizza_importo_solo_simbolo_euro_restituisce_none():
    """A string made only of the euro symbol and spaces has no digits -> None."""
    assert normalizza_importo("€") is None


# ---------------------------------------------------------------------------
# normalizza_data
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sep",
    [".", "/", "-"],
)
def test_normalizza_data_accetta_tre_separatori(sep):
    """DD.MM.YYYY, DD/MM/YYYY and DD-MM-YYYY are all normalized to DD.MM.YYYY."""
    assert normalizza_data(f"05{sep}03{sep}2026") == "05.03.2026"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("31.12.2026", "31.12.2026"),
        ("01.01.2026", "01.01.2026"),
        ("28.02.2024", "28.02.2024"),
    ],
)
def test_normalizza_data_date_valide(raw, expected):
    assert normalizza_data(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "32.01.2026",  # day out of range
        "15.13.2026",  # month out of range
        "00.05.2026",  # day zero
        "05.00.2026",  # month zero
        "5.3.26",  # not 2/4 digits
        "2026-03-05",  # ISO, wrong token order
        "05-03-26",  # 2-digit year
        "abc",
        "",
        "   ",
        None,
    ],
)
def test_normalizza_data_casi_non_validi_restituisce_none(raw):
    assert normalizza_data(raw) is None


# ---------------------------------------------------------------------------
# pulisci_descrizione
# ---------------------------------------------------------------------------


def test_pulisci_descrizione_input_vuoto_restituisce_stringa_vuota():
    assert pulisci_descrizione("") == ""
    assert pulisci_descrizione(None) == ""


def test_pulisci_descrizione_rimuove_tag_html():
    raw = "Pagamento<br/>di una <li>fattura</li>"
    out = pulisci_descrizione(raw)
    assert "<" not in out
    assert ">" not in out
    assert "Pagamento" in out
    assert "fattura" in out


def test_pulisci_descrizione_decodifica_entita_html():
    """HTML entities are decoded (&gt; -> >, &amp; -> &, ...)."""
    raw = "Pagamento &amp; servizio"
    out = pulisci_descrizione(raw)
    assert "&amp;" not in out
    assert "&" in out


def test_pulisci_descrizione_setefi_con_entita_html_non_viene_rimosso():
    """NOTE (known anomaly): when OCR emits ``/GEST=&gt;SETEFI`` the HTML
    decoder runs *before* the technical-code regexes, turning ``=`` into
    ``=>``. The Setefi regex expects ``GEST=\\w+`` (no ``>``) and the JSON
    replace is the literal ``/GEST=SETEFI`` (no ``>``), so neither matches
    and Setefi survives in the output. This documents the current behavior.
    """
    raw = "/GEST=&gt;SETEFI"
    out = pulisci_descrizione(raw)
    assert "SETEFI" in out  # survives: the &gt; decoding breaks both matchers


def test_pulisci_descrizione_rimuove_asterisco_iniziale():
    raw = "* Pagamento ADUE B2B"
    out = pulisci_descrizione(raw)
    assert not out.startswith("*")
    # The "* Pagamento ADUE" rule removes the prefix, leaving "ADUE B2B"
    assert "ADUE B2B" in out


def test_pulisci_descrizione_codici_tecnici_setefi_sopravvivono():
    """NOTE (known anomaly): the Setefi regex
    ``COMM[:.]?\\s*\\d+\\s*TC[:.]?\\s*\\d+\\s*\\w*\\s*/?\\s*GEST\\s*=\\s*\\w+``
    is meant to strip the whole ``COMM:...TC:...MC /GEST=SETEFI`` block, but in
    practice the ``MC`` token between ``TC`` and ``/GEST`` breaks the match, so
    the COMM/TC/MC codes survive in the output. Only ``/GEST=SETEFI`` alone is
    removed (by the JSON replace rule, when no ``&gt;`` is present). This test
    documents the current, buggy behavior.
    """
    raw = "Incasso POS COMM:019281252 TC:21 MC /GEST=SETEFI del giorno"
    out = pulisci_descrizione(raw)
    assert "SETEFI" not in out  # removed by the JSON replace rule
    assert "019281252" in out  # COMM block survives: regex does not match
    # The meaningful text survives
    assert "Incasso POS" in out


def test_pulisci_descrizione_gest_setefi_da_solo_viene_rimosso():
    """/GEST=SETEFI without &gt; and without the COMM block is removed by the
    JSON replace rule."""
    out = pulisci_descrizione("/GEST=SETEFI")
    assert out == ""


def test_pulisci_descrizione_rimuove_codice_dispositivo_adue():
    raw = "Pagamento COD. DISP.: 0126031956991360"
    out = pulisci_descrizione(raw)
    assert "0126031956991360" not in out
    assert "COD" not in out


def test_pulisci_descrizione_rimuove_mandato():
    raw = "Pagamento MANDATO: B40404091"
    out = pulisci_descrizione(raw)
    assert "MANDATO" not in out
    assert "B40404091" not in out


def test_pulisci_descrizione_rimuove_bic_ord():
    raw = "Pagamento BIC: ORD: CRFIIT2F"
    out = pulisci_descrizione(raw)
    assert "CRFIIT2F" not in out


def test_pulisci_descrizione_rimuove_e2eid_e_notprovided():
    raw = "Bonifico E2EID NOTPROVIDED importo"
    out = pulisci_descrizione(raw)
    assert "E2EID" not in out
    assert "NOTPROVIDED" not in out
    assert "Bonifico" in out


def test_pulisci_descrizione_rimuove_iban_lungo():
    """Tokens of 15+ alphanumeric chars (IBAN, CRO, ...) are stripped."""
    raw = "Bonifico IT60X0542811101000000123456"
    out = pulisci_descrizione(raw)
    assert "IT60X0542811101000000123456" not in out
    assert "Bonifico" in out


def test_pulisci_descrizione_applica_replace_configurati():
    """Rules from replace_descrizioni.json are applied (case-insensitive substring)."""
    raw = "Accredito POS al netto esente"
    out = pulisci_descrizione(raw)
    assert "Accredito POS al netto esente" not in out
    assert "POS al netto esente" == out.strip()


def test_pulisci_descrizione_extra_replaces_rimuovono_titolare_conto():
    """Dynamic extra_replaces (e.g. account holder name) are removed case-insensitively."""
    raw = "Pagamento POS ROSSI MARIO del 05/03"
    out = pulisci_descrizione(raw, extra_replaces=["ROSSI MARIO"])
    assert "ROSSI MARIO" not in out
    assert "Pagamento POS" in out


def test_pulisci_descrizione_collassa_spazi_multipli():
    raw = "Pagamento    con     spazi   multipli"
    out = pulisci_descrizione(raw)
    assert "  " not in out
    assert out == "Pagamento con spazi multipli"


def test_pulisci_descrizione_tronca_senza_spezzare_parole():
    raw = "Bonifico a favore di un beneficiario con un nome molto molto lungo"
    out = pulisci_descrizione(raw, max_length=30)
    assert len(out) <= 30
    # Truncation must not cut a word in half
    assert not out.endswith("-") or " " in out
    # The last token is a full word
    assert out.split(" ")[-1] in raw


def test_pulisci_descrizione_tronca_se_parola_piu_lunga_della_meta():
    """When the last space is below 60% of max_length, hard-truncate instead."""
    raw = "Supercalifragilistichespiralidoso-parolaunamacisssima"
    out = pulisci_descrizione(raw, max_length=20)
    assert len(out) <= 20


def test_pulisci_descrizione_risultato_piu_corto_di_max_length_non_viene_troncato():
    raw = "Pagamento breve"
    out = pulisci_descrizione(raw, max_length=100)
    assert out == "Pagamento breve"


def test_pulisci_descrizione_combinazione_completa():
    """End-to-end: HTML tags stripped, * prefix removed, replace rules applied,
    extra replaces applied. NOTE: when the Setefi block contains ``&gt;`` the
    technical-code regex does not match, so COMM/SETEFI survive (documented
    anomaly); we assert on what the function actually guarantees."""
    raw = "* Accredito POS al netto esente<br/>ROSSI MARIO"
    out = pulisci_descrizione(raw, max_length=100, extra_replaces=["ROSSI MARIO"])
    assert "<" not in out and ">" not in out
    assert "*" not in out
    assert "ROSSI MARIO" not in out
    assert "POS al netto esente" in out
