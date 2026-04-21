from .base import BankTemplate
from .intesa_sanpaolo import IntesaSanpaoloTemplate
from .bnl import BNLTemplate
from .bnl_lista_movimenti import BNLListaMovimentiTemplate

TEMPLATES = {
    "intesa_sanpaolo": IntesaSanpaoloTemplate,
    "bnl": BNLTemplate,
    "bnl_lista_movimenti": BNLListaMovimentiTemplate,
}

# Pattern per auto-detect banca dalla prima pagina OCR.
# ORDINE IMPORTANTE: pattern piu' specifici PRIMA di quelli generici.
# Es: "lista movimenti" + "bnl" va prima di solo "bnl".
_DETECT_PATTERNS = [
    ("bnl_lista_movimenti", ["lista movimenti"]),
    ("intesa_sanpaolo", ["intesa sanpaolo", "c/c n."]),
    ("bnl", ["bnl", "bnp paribas", "banco nazionale del lavoro"]),
]


def get_template(name: str) -> BankTemplate:
    cls = TEMPLATES.get(name)
    if cls is None:
        raise ValueError(f"Template '{name}' non trovato. Disponibili: {list(TEMPLATES.keys())}")
    return cls()


def list_templates() -> list[str]:
    return list(TEMPLATES.keys())


def detect_bank(first_page_text: str) -> str | None:
    """
    Cerca di identificare la banca dal testo della prima pagina OCR.
    Returns il nome del template o None se non riconosciuta.

    I pattern piu' specifici vengono controllati prima (es. "lista movimenti"
    prima di "bnl" generico).
    """
    text_lower = first_page_text.lower()
    for template_name, patterns in _DETECT_PATTERNS:
        for pattern in patterns:
            if pattern in text_lower:
                return template_name
    return None
