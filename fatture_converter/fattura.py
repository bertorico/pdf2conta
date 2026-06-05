"""
Dataclass Fattura e parser per estrarre dati da testo di fatture cartacee.
Formato atteso: fatture Azienda Esempio SRL (o simili).
Il testo viene estratto con pdftotext -layout.
"""

import re
from dataclasses import dataclass, field


@dataclass
class AliquotaIVA:
    netto: float
    iva: float
    aliquota: int


@dataclass
class Fattura:
    tipo_documento: str  # TD01, TD04
    numero_documento: str
    data_documento: str  # DD/MM/YYYY
    cf_cedente: str
    cf_cessionario: str
    nome_cessionario: str
    cognome_cessionario: str
    aliquote: list[AliquotaIVA] = field(default_factory=list)


# Mapping tipo documento — pattern piu' specifici prima
_TIPO_DOC_PATTERNS = [
    ("NOTA DI CREDITO", "TD04"),
    ("NOTA CREDITO", "TD04"),
    ("FATTURA DIFF", "TD01"),
    ("FATTURA", "TD01"),
]


def _normalizza_importo(raw: str) -> float:
    """Converte importo italiano (es. '3,38' o '3.420,00') in float."""
    s = raw.replace(" ", "").strip()
    match = re.match(r'^([\d.,]+)([.,])(\d{2})$', s)
    if match:
        parte_intera = match.group(1).replace('.', '').replace(',', '')
        decimali = match.group(3)
        return float(f"{parte_intera}.{decimali}")
    clean = s.replace('.', '').replace(',', '')
    if clean.isdigit():
        return float(clean)
    return 0.0


def parse_fattura(text: str, cf_cedente: str) -> Fattura:
    """
    Estrae i dati di una fattura dal testo estratto con pdftotext -layout.

    Args:
        text: testo completo della pagina (pdftotext -layout output)
        cf_cedente: codice fiscale del cedente (configurabile)

    Returns: Fattura con tutti i campi estratti
    """
    # --- Tipo documento ---
    tipo_documento = ""
    for pattern, codice in _TIPO_DOC_PATTERNS:
        if re.search(re.escape(pattern), text, re.IGNORECASE):
            tipo_documento = codice
            break

    # --- Numero documento ---
    # Formati visti: "N.Documento  3 / PF/V   Data ..." oppure "N.   416 / PF/V   Data ..."
    numero_documento = ""
    m = re.search(r'\bN\.?\s*(?:Documento)?\s+(.+?)\s{2,}Data\b', text, re.IGNORECASE)
    if m:
        numero_documento = m.group(1).strip().replace(" ", "")

    # --- Data documento ---
    data_documento = ""
    m = re.search(r'\bData\s+(\d{2}/\d{2}/\d{4})', text)
    if m:
        data_documento = m.group(1)

    # --- Codice fiscale cessionario ---
    # Il testo ha due "Cod.fis." — primo del cedente, secondo del cessionario
    cf_matches = re.findall(r'Cod\.?\s*fis\.?\s+([A-Z0-9]{11,16})', text, re.IGNORECASE)
    cf_cessionario = ""
    for cf in cf_matches:
        cf_upper = cf.upper()
        if cf_upper != cf_cedente.upper():
            cf_cessionario = cf_upper
            break

    # --- Nome e cognome cessionario ---
    # Nel layout pdftotext, il nome e' sulla prima riga (blocco alto a destra):
    # "MARZUOLI FERNANDA C/O RSA VILL"
    # E' una riga tutta maiuscola con almeno 2 parole, che non e' il cedente.
    nome_cessionario = ""
    cognome_cessionario = ""
    lines = text.split('\n')
    # Nomi noti del cedente da ignorare
    cedente_keywords = {"FARMACIA", "ESEMPIO", "ESEMPIO", "SRL"}
    for line in lines:
        candidate = line.strip()
        if not candidate:
            continue
        # Salta righe strutturali
        if re.match(r'^(P\.?\s*IVA|Cod\.?\s*fis|Num\.|Uff\.|Capital|PIAZZA|FATTURA|N\.Doc)', candidate, re.IGNORECASE):
            continue
        # La riga del nome: tutta maiuscola, almeno 2 parole, contiene lettere
        if re.match(r'^[A-Z][A-Z\s/\'\.\-,]+$', candidate) and len(candidate.split()) >= 2:
            # Salta se e' il nome del cedente
            words = set(candidate.split())
            if words & cedente_keywords:
                continue
            # Rimuovi tutto da "C/O" in poi
            name_part = re.split(r'\s+C/O\b', candidate, flags=re.IGNORECASE)[0].strip()
            parts = name_part.split()
            if len(parts) >= 2:
                cognome_cessionario = parts[0]
                nome_cessionario = " ".join(parts[1:])
                break

    # --- Aliquote IVA ---
    # Pattern dalla tabella riepilogativa: "3,38 ALIQUOTA 10%   0,34"
    # oppure aliquota esente: "45,00 Esenti   0,00"
    # Con pdftotext -layout gli spazi multipli separano le colonne
    aliquote = []
    for m in re.finditer(
        r'(\d[\d.,]*)\s+ALIQUOTA\s+(\d+)%\s+(\d[\d.,]*)',
        text, re.IGNORECASE
    ):
        netto = _normalizza_importo(m.group(1))
        aliquota_pct = int(m.group(2))
        iva = _normalizza_importo(m.group(3))
        aliquote.append(AliquotaIVA(netto=netto, iva=iva, aliquota=aliquota_pct))
    # Aliquota esente (0%): "45,00 Esenti   0,00"
    for m in re.finditer(
        r'(\d[\d.,]*)\s+Esenti\s+(\d[\d.,]*)',
        text, re.IGNORECASE
    ):
        netto = _normalizza_importo(m.group(1))
        iva = _normalizza_importo(m.group(2))
        aliquote.append(AliquotaIVA(netto=netto, iva=iva, aliquota=0))

    return Fattura(
        tipo_documento=tipo_documento,
        numero_documento=numero_documento,
        data_documento=data_documento,
        cf_cedente=cf_cedente,
        cf_cessionario=cf_cessionario,
        nome_cessionario=nome_cessionario,
        cognome_cessionario=cognome_cessionario,
        aliquote=aliquote,
    )
