"""
Normalizzazione importi, date e descrizioni per estratti conto bancari.
Gestisce le anomalie tipiche dell'output OCR di dots.ocr.
"""

import json
import re
from pathlib import Path
from typing import Optional


def normalizza_importo(raw: str) -> Optional[float]:
    """
    Normalizza un importo OCR in float.

    Gestisce i problemi tipici di dots.ocr:
    - Spazi spuri: "3,420, 00" -> 3420.00
    - Virgole al posto dei punti: "7, 244, 87" -> 7244.87
    - Formato corretto: "2.500,00" -> 2500.00
    - Importi piccoli: "154,00" -> 154.00
    - Simbolo euro: "26, 452, 20 €" -> 26452.20

    Returns None se la stringa non contiene un importo valido.
    """
    if not raw or not raw.strip():
        return None

    s = raw.replace("€", "").replace(" ", "").strip()
    if not s:
        return None

    # L'ultimo separatore (virgola o punto) seguito da esattamente 2 cifre finali
    # e' il separatore decimale. Tutto il resto sono migliaia da rimuovere.
    match = re.match(r'^([\d.,]+)([.,])(\d{2})$', s)
    if match:
        parte_intera = match.group(1).replace('.', '').replace(',', '')
        decimali = match.group(3)
        try:
            return float(f"{parte_intera}.{decimali}")
        except ValueError:
            return None

    # Fallback: numero senza decimali (es. "154")
    clean = s.replace('.', '').replace(',', '')
    if clean.isdigit():
        return float(clean)

    return None


def formatta_importo(valore: float, migliaia: str = '.', decimali: str = ',') -> str:
    """
    Formatta un float in stringa con formato italiano: 2.500,00

    Args:
        valore: importo numerico
        migliaia: separatore migliaia (default '.')
        decimali: separatore decimali (default ',')
    """
    # Formatta con 2 decimali e separatore migliaia
    parti = f"{valore:,.2f}"  # es. "2,500.00" (formato US)
    # Sostituisci separatori: US -> italiano
    # Prima: virgola migliaia -> placeholder
    # Poi: punto decimale -> virgola
    # Infine: placeholder -> punto
    parti = parti.replace(',', '#').replace('.', decimali).replace('#', migliaia)
    return parti


def normalizza_data(raw: str) -> Optional[str]:
    """
    Normalizza una data OCR nel formato DD.MM.YYYY.
    Accetta formati: DD.MM.YYYY, DD/MM/YYYY, DD-MM-YYYY.
    Returns None se non e' una data valida.
    """
    if not raw or not raw.strip():
        return None

    s = raw.strip()
    match = re.match(r'^(\d{2})[./-](\d{2})[./-](\d{4})$', s)
    if match:
        giorno, mese, anno = match.groups()
        g, m = int(giorno), int(mese)
        if 1 <= g <= 31 and 1 <= m <= 12:
            return f"{giorno}.{mese}.{anno}"
    return None


def pulisci_descrizione(
    raw: str,
    max_length: int = 100,
    extra_replaces: Optional[list[str]] = None,
) -> str:
    """
    Pulisce e condensa la descrizione di un movimento bancario.

    Ordine di applicazione:
    1. Rimuove tag HTML (<br>, <ul>, <li>, ecc.)
    2. Applica replace configurabili da replace_descrizioni.json
    3. Rimuove asterisco iniziale
    4. Rimuove codici tecnici (IBAN, E2EID, BIC, CRO, TRN, MANDATO, COMM Setefi, ecc.)
    5. Applica extra_replaces (es. nome titolare conto, configurabile da UI)
    6. Collassa spazi multipli
    7. Tronca a max_length caratteri senza spezzare parole

    Args:
        raw: testo da pulire (puo' contenere HTML)
        max_length: lunghezza massima del risultato
        extra_replaces: lista di stringhe da rimuovere (case-insensitive).
            Tipicamente il nome del titolare del conto, che ricorre in tutte
            le descrizioni POS senza aggiungere informazione utile.
    """
    if not raw:
        return ""

    s = raw

    # [1] Rimuovi tag HTML
    s = re.sub(r'<br\s*/?>', ' ', s)
    s = re.sub(r'</?(?:ul|li|ol|p|div|span|table|tr|td|th|thead|tbody)[^>]*>', ' ', s)

    # [2] Applica replace configurabili (case-insensitive, sottostringa)
    s = applica_replace(s)

    # [3] Rimuovi asterisco iniziale
    s = re.sub(r'^\s*\*\s*', '', s)

    # [4] Rimuovi codici tecnici (regex, non configurabili dall'utente)
    # Codici Setefi POS: "COMM:019281252 TC:21 MC /GEST=SETEFI"
    s = re.sub(r'\bCOMM[:.]?\s*\d+\s*TC[:.]?\s*\d+\s*\w*\s*/?\s*GEST\s*=\s*\w+',
               '', s, flags=re.IGNORECASE)
    # COD. DISP. ADUE: "COD. DISP.: 0126031956991360"
    s = re.sub(r'\bCOD\.?\s*DISP\.?[:.]?\s*\d+', '', s, flags=re.IGNORECASE)
    # Mandato ADUE: "MANDATO: B40404091..."
    s = re.sub(r'\bMANDATO[:.]?\s*\S+', '', s, flags=re.IGNORECASE)
    # BIC ORD/CIN
    s = re.sub(r'\bBIC[.: ]+ORD[.: ]+\S+', '', s, flags=re.IGNORECASE)
    # E2EID, NOTPROVIDED
    s = re.sub(r'\bE2E(?:ID)?\S*', '', s)
    s = re.sub(r'\bNOTPROVIDED\b', '', s)
    # NOME: prefisso ADUE (lasciamo il valore, togliamo la label)
    s = re.sub(r'\bNOME\s*:\s*', '', s, flags=re.IGNORECASE)
    # Token tecnici brevi residui
    s = re.sub(r'\bOTH(?:R)?\b', '', s)
    s = re.sub(r'\bSUPP\b', '', s)
    s = re.sub(r'\bCASH\b', '', s)
    # Codici alfanumerici lunghi (IBAN, CRO, codici dispositiva)
    s = re.sub(r'\b[A-Z0-9]{15,}\b', '', s)

    # [5] Extra replaces dinamici (titolare conto, ecc.)
    if extra_replaces:
        for trova in extra_replaces:
            if trova:
                pattern = re.compile(re.escape(trova), re.IGNORECASE)
                s = pattern.sub('', s)

    # [6] Collassa spazi, rimuovi spazi attorno a punteggiatura
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'\s*:\s*$', '', s)
    s = s.strip()

    # [7] Tronca a max_length senza spezzare parole
    if len(s) > max_length:
        troncato = s[:max_length]
        ultimo_spazio = troncato.rfind(' ')
        if ultimo_spazio > max_length * 0.6:
            s = troncato[:ultimo_spazio]
        else:
            s = troncato

    return s.strip()


# --- Replace configurabili ---

_REPLACE_CACHE: Optional[list[dict]] = None
_REPLACE_PATH = Path(__file__).parent / "replace_descrizioni.json"


def carica_replace(filepath: Optional[str] = None) -> list[dict]:
    """
    Carica i replace dal file JSON.
    Ogni replace ha: trova, sostituisci, nota (opzionale).
    """
    global _REPLACE_CACHE
    path = Path(filepath) if filepath else _REPLACE_PATH
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _REPLACE_CACHE = data.get("replace", [])
    return _REPLACE_CACHE


def salva_replace(replace_list: list[dict], filepath: Optional[str] = None):
    """Salva i replace su file JSON."""
    global _REPLACE_CACHE
    path = Path(filepath) if filepath else _REPLACE_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"replace": replace_list}, f, ensure_ascii=False, indent=2)
    _REPLACE_CACHE = replace_list


def applica_replace(testo: str, replace_list: Optional[list[dict]] = None) -> str:
    """
    Applica i replace configurabili al testo.
    Matching case-insensitive come sottostringa.
    Le regole vengono applicate tutte in ordine.
    """
    if replace_list is None:
        if _REPLACE_CACHE is None:
            replace_list = carica_replace()
        else:
            replace_list = _REPLACE_CACHE

    for r in replace_list:
        trova = r.get("trova", "")
        sostituisci = r.get("sostituisci", "")
        if not trova:
            continue
        # Case-insensitive replace
        pattern = re.compile(re.escape(trova), re.IGNORECASE)
        testo = pattern.sub(sostituisci, testo)

    return testo


# --- Causali ---

_CAUSALI_CACHE: Optional[list[dict]] = None
_CAUSALI_PATH = Path(__file__).parent / "causali.json"


def carica_causali(filepath: Optional[str] = None) -> list[dict]:
    """
    Carica le causali dal file JSON.
    Ogni causale ha: codice, nome, pattern (lista di stringhe).
    """
    global _CAUSALI_CACHE
    path = Path(filepath) if filepath else _CAUSALI_PATH
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _CAUSALI_CACHE = data.get("causali", [])
    return _CAUSALI_CACHE


def salva_causali(causali: list[dict], filepath: Optional[str] = None):
    """Salva le causali su file JSON."""
    global _CAUSALI_CACHE
    path = Path(filepath) if filepath else _CAUSALI_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"causali": causali}, f, ensure_ascii=False, indent=2)
    _CAUSALI_CACHE = causali


def match_causale(descrizione: str, causali: Optional[list[dict]] = None) -> tuple[Optional[str], Optional[str]]:
    """
    Cerca una causale corrispondente alla descrizione.

    Returns: (codice, nome) oppure (None, None) se nessun match.
    Il matching e' case-insensitive e cerca i pattern come sottostringhe.
    """
    if causali is None:
        if _CAUSALI_CACHE is None:
            causali = carica_causali()
        else:
            causali = _CAUSALI_CACHE

    desc_lower = descrizione.lower()
    for c in causali:
        for pattern in c.get("pattern", []):
            if pattern.lower() in desc_lower:
                return c["codice"], c["nome"]
    return None, None
