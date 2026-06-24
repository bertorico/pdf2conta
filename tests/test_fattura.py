"""Tests for ``fatture_converter/fattura.py``: paper-invoice parsing from
``pdftotext -layout`` text output.

``parse_fattura`` extracts document type, number, date, buyer CF / name /
surname (excluding the configurable cedente), and per-VAT-rate rows (both
taxed ``ALIQUOTA n%`` and exempt ``Esenti``). Tests use synthetic text blocks
modeled on the real pdftotext -layout layout and assert on verified behavior.

Module roots are exposed via the pytest ``pythonpath`` in ``pyproject.toml``:
``fatture_converter`` is on the path, so we import flat.
"""

import pytest

from fattura import AliquotaIVA, Fattura, _normalizza_importo, parse_fattura

# ---------------------------------------------------------------------------
# _normalizza_importo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("3,38", 3.38),
        ("3.420,00", 3420.0),
        ("154", 154.0),
        ("1.234.567,89", 1234567.89),
        ("0,00", 0.0),
    ],
)
def test_normalizza_importo_casi_validi(raw, expected):
    assert _normalizza_importo(raw) == pytest.approx(expected)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "abc",
        "--",
        "N/D",
    ],
)
def test_normalizza_importo_casi_non_validi_restituisce_zero(raw):
    """Unlike ec_converter.normalizza_importo (which returns None), the invoice
    variant returns 0.0 on failure: invoice amounts default to zero rather than
    missing, so downstream CSV columns are always populated."""
    assert _normalizza_importo(raw) == 0.0


# ---------------------------------------------------------------------------
# parse_fattura — full document
# ---------------------------------------------------------------------------


SAMPLE_TEXT = """FATTURA DIFFERITA
MARZUOLI FERNANDA C/O RSA VILL
N.Documento  3 / PF/V   Data 05/03/2026
P.IVA 01234567890
Cod.fis. 01234567890
Cod.fis. MRZFNC50A01F205X
3,38 ALIQUOTA 10%   0,34
45,00 Esenti   0,00
"""


@pytest.fixture
def sample_fattura(monkeypatch):
    """parse_fattura on SAMPLE_TEXT with NOME_CEDENTE set so the cedente line
    is skipped during buyer-name detection."""
    monkeypatch.setenv("NOME_CEDENTE", "FARMACIA ESEMPIO SRL")
    return parse_fattura(SAMPLE_TEXT, "01234567890")


def test_parse_fattura_tipo_documento_fattura(sample_fattura):
    assert sample_fattura.tipo_documento == "TD01"


def test_parse_fattura_tipo_documento_nota_credito(monkeypatch):
    monkeypatch.setenv("NOME_CEDENTE", "FARMACIA ESEMPIO SRL")
    text = SAMPLE_TEXT.replace("FATTURA DIFFERITA", "NOTA DI CREDITO")
    f = parse_fattura(text, "01234567890")
    assert f.tipo_documento == "TD04"


def test_parse_fattura_tipo_documento_nota_vince_su_fattura(monkeypatch):
    """NOTA DI CREDITO is more specific than FATTURA and is checked first."""
    monkeypatch.setenv("NOME_CEDENTE", "FARMACIA ESEMPIO SRL")
    text = SAMPLE_TEXT.replace("FATTURA DIFFERITA", "NOTA DI CREDITO FATTURA")
    f = parse_fattura(text, "01234567890")
    assert f.tipo_documento == "TD04"


def test_parse_fattura_numero_documento(sample_fattura):
    assert sample_fattura.numero_documento == "3/PF/V"


def test_parse_fattura_data_documento(sample_fattura):
    assert sample_fattura.data_documento == "05/03/2026"


def test_parse_fattura_cf_cessionario_esclude_cedente(sample_fattura):
    """The cedente CF (first match) is excluded; the second CF is the buyer."""
    assert sample_fattura.cf_cedente == "01234567890"
    assert sample_fattura.cf_cessionario == "MRZFNC50A01F205X"


def test_parse_fattura_nome_cognome_cessionario(sample_fattura):
    assert sample_fattura.cognome_cessionario == "MARZUOLI"
    assert sample_fattura.nome_cessionario == "FERNANDA"


def test_parse_fattura_aliquote_tassate_ed_esenti(sample_fattura):
    assert len(sample_fattura.aliquote) == 2
    a1 = sample_fattura.aliquote[0]
    assert a1.netto == pytest.approx(3.38)
    assert a1.iva == pytest.approx(0.34)
    assert a1.aliquota == 10
    a2 = sample_fattura.aliquote[1]
    assert a2.netto == pytest.approx(45.0)
    assert a2.iva == pytest.approx(0.0)
    assert a2.aliquota == 0  # exempt


def test_parse_fattura_nome_cedente_viene_saltato(monkeypatch):
    """A line matching NOME_CEDENTE keywords must not be taken as the buyer."""
    monkeypatch.setenv("NOME_CEDENTE", "FARMACIA ESEMPIO SRL")
    text = SAMPLE_TEXT.replace(
        "MARZUOLI FERNANDA C/O RSA VILL",
        "FARMACIA ESEMPIO SRL\nMARZUOLI FERNANDA C/O RSA VILL",
    )
    f = parse_fattura(text, "01234567890")
    assert f.cognome_cessionario == "MARZUOLI"


def test_parse_fattura_tronca_a_c_o(monkeypatch):
    """Anything from 'C/O' onward is dropped from the buyer name."""
    monkeypatch.setenv("NOME_CEDENTE", "FARMACIA ESEMPIO SRL")
    f = parse_fattura(SAMPLE_TEXT, "01234567890")
    assert "C/O" not in f.nome_cessionario
    assert "RSA" not in f.nome_cessionario
    assert "VILL" not in f.nome_cessionario


def test_parse_fattura_senza_aliquote_restituisce_lista_vuota(monkeypatch):
    monkeypatch.setenv("NOME_CEDENTE", "FARMACIA ESEMPIO SRL")
    text = "FATTURA\nROSSI MARIO\nN.Documento  1 / PF/V   Data 01/01/2026\nCod.fis. 01234567890\nCod.fis. RSSMRA80A01F205X\n"
    f = parse_fattura(text, "01234567890")
    assert f.aliquote == []


def test_parse_fattura_cedente_senza_nome_env_ancora_funziona(monkeypatch):
    """Without NOME_CEDENTE the buyer name detection still works on a clean
    layout where the cedente line is excluded by the structural-line regex."""
    monkeypatch.delenv("NOME_CEDENTE", raising=False)
    f = parse_fattura(SAMPLE_TEXT, "01234567890")
    assert f.cognome_cessionario == "MARZUOLI"


def test_parse_fattura_testo_vuoto_restituisce_fattura_vuota():
    f = parse_fattura("", "01234567890")
    assert isinstance(f, Fattura)
    assert f.tipo_documento == ""
    assert f.numero_documento == ""
    assert f.data_documento == ""
    assert f.cf_cessionario == ""
    assert f.aliquote == []
    assert f.cf_cedente == "01234567890"


def test_aliquota_iva_dataclass_default_factory():
    """The Fattura dataclass initializes aliquote to an empty list by default."""
    f = Fattura(
        tipo_documento="TD01",
        numero_documento="1",
        data_documento="01/01/2026",
        cf_cedente="X",
        cf_cessionario="Y",
        nome_cessionario="N",
        cognome_cessionario="C",
    )
    assert f.aliquote == []


def test_aliquota_iva_campi():
    a = AliquotaIVA(netto=10.0, iva=2.0, aliquota=20)
    assert a.netto == 10.0
    assert a.iva == 2.0
    assert a.aliquota == 20
