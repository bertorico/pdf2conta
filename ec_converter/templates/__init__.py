from .base import BankTemplate
from .bnl import BNLTemplate
from .bnl_lista_movimenti import BNLListaMovimentiTemplate
from .bnl_pos import BNLPosTemplate
from .intesa_sanpaolo import IntesaSanpaoloTemplate
from .intesa_sanpaolo_ufficiale import IntesaSanpaoloUfficialeTemplate

TEMPLATES = {
    "intesa_sanpaolo_ufficiale": IntesaSanpaoloUfficialeTemplate,
    "intesa_sanpaolo": IntesaSanpaoloTemplate,
    "bnl": BNLTemplate,
    "bnl_lista_movimenti": BNLListaMovimentiTemplate,
    "bnl_pos": BNLPosTemplate,
}

# Pattern per auto-detect banca dalla prima pagina OCR.
# ORDINE IMPORTANTE: pattern piu' specifici PRIMA di quelli generici.
# Es: "lista movimenti" + "bnl" va prima di solo "bnl".
# "dettaglio movimenti del conto corrente" identifica il layout ufficiale Intesa
# e va prima del pattern generico "intesa sanpaolo".
_DETECT_PATTERNS = [
    # "finanziamenti" e' specifico del rendiconto POS BNL (prima riga del doc).
    # Va prima di "bnl" generico per evitare il fallthrough.
    ("bnl_pos", ["finanziamenti"]),
    ("bnl_lista_movimenti", ["lista movimenti"]),
    (
        "intesa_sanpaolo_ufficiale",
        [
            "dettaglio movimenti del conto corrente",
            "riepilogo conto corrente",
        ],
    ),
    ("intesa_sanpaolo", ["intesa sanpaolo", "c/c n."]),
    ("bnl", ["bnl", "bnp paribas", "banco nazionale del lavoro"]),
]


def get_template(name: str, **kwargs) -> BankTemplate:
    cls = TEMPLATES.get(name)
    if cls is None:
        raise ValueError(f"Template '{name}' non trovato. Disponibili: {list(TEMPLATES.keys())}")
    try:
        return cls(**kwargs)
    except TypeError:
        # Template che non accettano kwargs (retrocompatibilita')
        return cls()


def list_templates() -> list[str]:
    return list(TEMPLATES.keys())


def detect_bank(first_page_text: str) -> str | None:
    """
    Cerca di identificare la banca dal testo della prima pagina OCR.
    Returns il nome del template o None se non riconosciuta.

    I pattern piu' specifici vengono controllati prima (es. "lista movimenti"
    prima di "bnl" generico, "dettaglio movimenti del conto corrente" prima
    di "intesa sanpaolo" generico).
    """
    text_lower = first_page_text.lower()
    for template_name, patterns in _DETECT_PATTERNS:
        for pattern in patterns:
            if pattern in text_lower:
                return template_name
    return None
