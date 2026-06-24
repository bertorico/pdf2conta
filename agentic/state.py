"""
Lo stato condiviso del grafo — la "scatola".

Metafora: immagina una scatola che passa di mano in mano tra i nodi del grafo.
Ogni nodo la apre, legge quello che gli serve, aggiunge il suo contributo e la
passa al nodo successivo. Nessun nodo cancella il lavoro degli altri: la scatola
cresce ad ogni passo.

LangGraph implementa questa idea con un TypedDict: ogni nodo restituisce un dict
parziale, e LangGraph lo fonde (merge) nello stato globale.
"""

from typing import TypedDict

from fatture_converter.fattura import Fattura


class FatturaState(TypedDict, total=False):
    """Scatola condivisa che percorre l'intero grafo.

    Campi:
        pdf_path:  percorso del PDF in input (fornito dall'utente, non modificato).
        testo:     testo grezzo estratto da pdftotext (popolato dal nodo ``estrai``).
        fattura:   dataclass Fattura con i dati strutturati (popolata da ``estrai``).
        errori:    lista di messaggi di errore fiscale (popolata da ``valida``).
        valida:    True se la fattura non ha errori di coerenza IVA (popolata da ``valida``).
        da_revisionare: True se il grafo ha instradato la fattura al nodo ``correggi``
                        (popolata da ``correggi``).
    """

    pdf_path: str
    testo: str
    fattura: Fattura | None
    errori: list[str]
    valida: bool
    da_revisionare: bool
