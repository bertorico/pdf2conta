"""Tests per BNLPosTemplate (ec_converter/templates/bnl_pos.py).

Verifica:
- Estrazione movimenti dai 3 formati colonne prodotti dall'OCR (7/5/6 col)
- Completamento anno per date DD/MM prive di anno
- Normalizzazione date DD/MM/YY a 2 cifre
- Assemblaggio descrizione da colonne multiple
- "da POS" nel campo dare viene accodato alla descrizione, non scartato
- Righe saldo/vuote escluse correttamente
- Tabelle non-movimenti (Riepilogo, Scalare) ignorate
- detect_bank riconosce "finanziamenti" → bnl_pos
"""

import pytest

from templates import detect_bank, get_template, list_templates
from templates.bnl_pos import BNLPosTemplate

# ---------------------------------------------------------------------------
# Fixture HTML — basate sull'output OCR reale, dati anonimizzati
# ---------------------------------------------------------------------------

HTML_PAG1_7COL = """
<table>
  <thead>
    <tr>
      <th>Data</th><th>Valuta</th><th>Saldo iniziale</th>
      <th>Descrizione</th><th>Operazioni</th><th>Dare</th><th>Avere</th>
    </tr>
  </thead>
  <tbody>
    <!-- riga saldo iniziale: descrizione vuota → esclusa -->
    <tr><td>31/12/2025</td><td></td><td></td><td></td><td></td><td>10.000,00</td><td></td></tr>
    <!-- incasso POS: 7 col, descrizione spalmata su 3 celle -->
    <tr><td>07/01/2026</td><td>07/01/26</td><td>incasso pagamento</td><td>eseguiti</td><td>da POS</td><td></td><td>346,95</td></tr>
    <tr><td>07/01/2026</td><td>07/01/26</td><td>incasso pagamento</td><td>eseguiti</td><td>da POS</td><td></td><td>474,85</td></tr>
    <!-- spese lettera: "al 31.12.25" finisce nel campo dare (OCR spill) -->
    <tr><td>16/01/2026</td><td>13/12/25</td><td>Spese</td><td>iniziative</td><td>Lettere cont.</td><td>al 31.12.25</td><td></td></tr>
  </tbody>
</table>
"""

HTML_PAG2_5COL = """
<table>
  <thead>
    <tr><th>Data</th><th>Valuta</th><th>Descrizione Operazioni</th><th>Dare</th><th>Avere</th></tr>
  </thead>
  <tbody>
    <!-- data DD/MM senza anno; "da POS" nel campo dare (spill) -->
    <tr><td>06/02</td><td>06/02/26</td><td>incasso pagamento</td><td>da POS</td><td>1.223,70</td></tr>
    <!-- spese lettera: dare numerico corretto -->
    <tr><td>13/02</td><td>31/01/26</td><td>Spese invio documenti Lettere cont. al 31.01.26</td><td>3,90</td><td></td></tr>
    <!-- Giroconto addebito -->
    <tr><td>16/02</td><td>16/02/26</td><td>Giroconto da nostra APAC F/P per RICHIESTA DI DISP</td><td>45.000,00</td><td></td></tr>
  </tbody>
</table>
"""

HTML_PAG3_6COL = """
<table>
  <thead>
    <tr><th>Data</th><th>Valuta</th><th>Descrizione</th><th>Operazioni</th><th>Dare</th><th>Avere</th></tr>
  </thead>
  <tbody>
    <tr><td>16/03</td><td>16/03/26</td><td>incasso pagamento</td><td>eseguiti da POS</td><td></td><td>1.294,45</td></tr>
    <!-- saldo finale → escluso -->
    <tr><td>31/03</td><td></td><td>Saldo finale</td><td></td><td>80.784,93</td><td></td></tr>
  </tbody>
</table>
"""

HTML_NON_MOVIMENTI = """
<table>
  <thead><tr><th>Saldo Iniziale al:</th><th>Totale Entrate:</th><th>Totale Uscite:</th><th>Saldo Finale al:</th></tr></thead>
  <tbody><tr><td>02/01/2026</td><td></td><td></td><td>31/03/2026</td></tr></tbody>
</table>
<table>
  <thead><tr><th>interessi creditori</th><th>Decorrenza</th><th>Tasso</th></tr></thead>
  <tbody><tr><td></td><td>01/01/26</td><td>4,82</td></tr></tbody>
</table>
"""


# ---------------------------------------------------------------------------
# Test: detect_bank e registry
# ---------------------------------------------------------------------------


def test_detect_bank_riconosce_finanziamenti():
    assert detect_bank("Finanziamenti\nResoconto n. 1 al 31/03/2026") == "bnl_pos"


def test_detect_bank_finanziamenti_non_confonde_bnl_cc():
    # Un estratto conto BNL normale (senza "finanziamenti") → "bnl"
    assert detect_bank("Estratto conto BNL BNP Paribas") == "bnl"


def test_bnl_pos_in_list_templates():
    assert "bnl_pos" in list_templates()


def test_get_template_bnl_pos():
    t = get_template("bnl_pos")
    assert isinstance(t, BNLPosTemplate)
    assert t.name == "bnl_pos"


# ---------------------------------------------------------------------------
# Test: pagina 1 (7 colonne)
# ---------------------------------------------------------------------------


def test_pag1_7col_conta_movimenti():
    t = BNLPosTemplate()
    movs = t.estrai_movimenti([HTML_PAG1_7COL])
    # saldo iniziale (desc vuota) escluso → 3 movimenti (2 incassi + 1 spese)
    assert len(movs) == 3


def test_pag1_7col_incasso_avere():
    t = BNLPosTemplate()
    movs = t.estrai_movimenti([HTML_PAG1_7COL])
    incassi = [m for m in movs if m.avere is not None]
    assert len(incassi) == 2
    assert incassi[0].avere == pytest.approx(346.95)
    assert incassi[1].avere == pytest.approx(474.85)


def test_pag1_7col_incasso_descrizione_assemblata():
    t = BNLPosTemplate()
    movs = t.estrai_movimenti([HTML_PAG1_7COL])
    incasso = movs[0]
    assert "incasso pagamento" in incasso.descrizione_raw.lower()
    assert "da pos" in incasso.descrizione_raw.lower()


def test_pag1_7col_data_formato_completo():
    t = BNLPosTemplate()
    movs = t.estrai_movimenti([HTML_PAG1_7COL])
    assert movs[0].data_operazione == "07.01.2026"


def test_pag1_7col_spese_dare_spill_in_descrizione():
    """'al 31.12.25' che l'OCR mette nel campo Dare finisce nella descrizione."""
    t = BNLPosTemplate()
    movs = t.estrai_movimenti([HTML_PAG1_7COL])
    spese = movs[2]
    assert "al 31.12.25" in spese.descrizione_raw
    assert spese.dare is None
    assert spese.avere is None


# ---------------------------------------------------------------------------
# Test: pagina 2 (5 colonne, date DD/MM)
# ---------------------------------------------------------------------------


def test_pag2_5col_conta_movimenti():
    t = BNLPosTemplate()
    movs = t.estrai_movimenti([HTML_PAG2_5COL])
    assert len(movs) == 3


def test_pag2_5col_data_completata_con_anno_valuta():
    """Data DD/MM viene completata con l'anno estratto dalla data valuta DD/MM/YY."""
    t = BNLPosTemplate()
    movs = t.estrai_movimenti([HTML_PAG2_5COL])
    assert movs[0].data_operazione == "06.02.2026"


def test_pag2_5col_incasso_da_pos_in_descrizione():
    """'da POS' nel campo Dare (spill OCR) viene accodato alla descrizione."""
    t = BNLPosTemplate()
    movs = t.estrai_movimenti([HTML_PAG2_5COL])
    incasso = movs[0]
    assert "da pos" in incasso.descrizione_raw.lower()
    assert incasso.avere == pytest.approx(1223.70)
    assert incasso.dare is None


def test_pag2_5col_spese_dare_numerico():
    t = BNLPosTemplate()
    movs = t.estrai_movimenti([HTML_PAG2_5COL])
    spese = movs[1]
    assert spese.dare == pytest.approx(3.90)
    assert spese.avere is None


def test_pag2_5col_giroconto_dare():
    t = BNLPosTemplate()
    movs = t.estrai_movimenti([HTML_PAG2_5COL])
    giroconto = movs[2]
    assert giroconto.dare == pytest.approx(45000.00)
    assert giroconto.avere is None


# ---------------------------------------------------------------------------
# Test: pagina 3 (6 colonne, saldo finale escluso)
# ---------------------------------------------------------------------------


def test_pag3_6col_conta_movimenti():
    t = BNLPosTemplate()
    movs = t.estrai_movimenti([HTML_PAG3_6COL])
    # saldo finale escluso → 1 movimento
    assert len(movs) == 1


def test_pag3_6col_incasso_avere():
    t = BNLPosTemplate()
    movs = t.estrai_movimenti([HTML_PAG3_6COL])
    assert movs[0].avere == pytest.approx(1294.45)


def test_pag3_6col_descrizione_da_due_celle():
    t = BNLPosTemplate()
    movs = t.estrai_movimenti([HTML_PAG3_6COL])
    desc = movs[0].descrizione_raw.lower()
    assert "incasso pagamento" in desc
    assert "eseguiti da pos" in desc


# ---------------------------------------------------------------------------
# Test: tabelle non-movimenti ignorate
# ---------------------------------------------------------------------------


def test_tabelle_non_movimenti_ignorate():
    t = BNLPosTemplate()
    movs = t.estrai_movimenti([HTML_NON_MOVIMENTI])
    assert movs == []


# ---------------------------------------------------------------------------
# Test: pagine multiple
# ---------------------------------------------------------------------------


def test_pagine_multiple_sommano_movimenti():
    t = BNLPosTemplate()
    movs = t.estrai_movimenti([HTML_PAG1_7COL, HTML_PAG2_5COL, HTML_PAG3_6COL])
    # pag1: 3, pag2: 3, pag3: 1
    assert len(movs) == 7


def test_pagine_multiple_numerazione_pagina():
    t = BNLPosTemplate()
    movs = t.estrai_movimenti([HTML_PAG1_7COL, HTML_PAG2_5COL, HTML_PAG3_6COL])
    pagine = {m.pagina for m in movs}
    assert pagine == {1, 2, 3}
