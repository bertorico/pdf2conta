"""Tests for ``correggi_segno_per_causale``: the OCR sometimes swaps the
dare/avere columns, and movements whose causale has a unique accounting sign
(see ``CAUSALE_SEGNO``) must be corrected back. Module roots are exposed via
pytest ``pythonpath`` in pyproject.toml.

Causali used below are real entries of ``CAUSALE_SEGNO``:
  09 = POS inflow (avere), 48 = incoming transfer (avere),
  66 = bank charges (dare), 26 = outgoing transfer (dare).
"""

from normalizer import correggi_segno_per_causale
from templates.base import Movimento


def _mov(causale, *, dare=None, avere=None):
    return Movimento(
        "01.01.2026",
        None,
        "descrizione",
        "descrizione",
        dare=dare,
        avere=avere,
        causale=causale,
    )


def test_segno_avere_sposta_dare_in_avere():
    """A causale signed 'A' (POS 09) with a value in dare is swapped to avere."""
    mov = _mov("09", dare=1725.57)
    corrette = correggi_segno_per_causale([mov])

    assert corrette == 1
    assert mov.avere == 1725.57
    assert mov.dare is None
    assert mov.corretto is True


def test_segno_dare_sposta_avere_in_dare():
    """A causale signed 'D' (bank charges 66) with a value in avere is swapped to dare."""
    mov = _mov("66", avere=8.70)
    corrette = correggi_segno_per_causale([mov])

    assert corrette == 1
    assert mov.dare == 8.70
    assert mov.avere is None
    assert mov.corretto is True


def test_valore_gia_sul_lato_corretto_resta_invariato():
    """A movement already on its expected side must not be touched."""
    mov = _mov("09", avere=1511.42)  # POS already in avere
    corrette = correggi_segno_per_causale([mov])

    assert corrette == 0
    assert mov.avere == 1511.42
    assert mov.dare is None
    assert mov.corretto is False


def test_causale_non_in_mappa_non_corregge():
    """A causale without a unique sign (e.g. '04') is left as-is."""
    mov = _mov("04", dare=100.00)
    corrette = correggi_segno_per_causale([mov])

    assert corrette == 0
    assert mov.dare == 100.00
    assert mov.corretto is False


def test_causale_assente_non_corregge():
    """Without a causale the sign is ambiguous, so nothing is changed."""
    mov = _mov(None, avere=100.00)
    corrette = correggi_segno_per_causale([mov])

    assert corrette == 0
    assert mov.avere == 100.00
    assert mov.corretto is False


def test_entrambe_le_colonne_valorizzate_non_corregge():
    """Both columns valued is ambiguous: no swap even with a signed causale."""
    mov = _mov("66", dare=5.0, avere=8.70)
    corrette = correggi_segno_per_causale([mov])

    assert corrette == 0
    assert mov.dare == 5.0
    assert mov.avere == 8.70
    assert mov.corretto is False


def test_conteggio_su_lista_mista():
    """The returned count reflects only the movements actually corrected."""
    movimenti = [
        _mov("09", dare=10.0),  # corrected -> avere
        _mov("48", dare=20.0),  # corrected -> avere
        _mov("66", avere=30.0),  # corrected -> dare
        _mov("04", avere=40.0),  # not in map -> untouched
        _mov(None, avere=50.0),  # no causale -> untouched
    ]

    assert correggi_segno_per_causale(movimenti) == 3
