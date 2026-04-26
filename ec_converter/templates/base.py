"""
Classe base per i template bancari.
Ogni banca ha un template che definisce come estrarre e mappare i dati
dalle tabelle HTML prodotte dall'OCR.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from bs4 import BeautifulSoup, Tag

from normalizer import normalizza_importo, normalizza_data, pulisci_descrizione


@dataclass
class Movimento:
    """Un singolo movimento bancario normalizzato."""
    data_operazione: str  # DD.MM.YYYY
    data_valuta: Optional[str]  # DD.MM.YYYY o None
    descrizione_raw: str  # descrizione originale (pre-pulizia)
    descrizione: str  # descrizione pulita (post-pulizia)
    dare: Optional[float] = None
    avere: Optional[float] = None
    causale: Optional[str] = None  # codice causale (es. "31", "78")
    causale_nome: Optional[str] = None  # nome causale (es. "Pagamento disposiz. elettroniche")
    pagina: int = 0
    corretto: bool = False  # True se dare/avere swappato automaticamente per causale univoca


class BankTemplate(ABC):
    """Template base per l'estrazione movimenti da estratto conto."""

    name: str = "base"
    display_name: str = "Base"

    @abstractmethod
    def estrai_movimenti(self, pages_html: list[str]) -> list[Movimento]:
        """
        Estrae i movimenti da una lista di pagine HTML (output OCR).
        Ogni elemento e' il testo OCR di una singola pagina.
        """
        ...

    def _ha_tabella_movimenti(self, html: str) -> bool:
        """Controlla se la pagina contiene una tabella con movimenti bancari."""
        soup = BeautifulSoup(html, 'html.parser')
        tables = soup.find_all('table')
        for table in tables:
            headers = [th.get_text(strip=True).lower() for th in table.find_all('th')]
            # Cerca header tipici: data + descrizione + importo
            has_data = any('data' in h for h in headers)
            has_desc = any('descri' in h for h in headers)
            has_importo = any(h in ('addebiti', 'addebita', 'accrediti', 'accreditati', 'dare', 'avere')
                            for h in headers)
            if has_data and (has_desc or has_importo):
                return True
        return False

    def _get_text(self, td: Tag) -> str:
        """Estrae testo da un tag <td>, preservando la struttura HTML interna."""
        if td is None:
            return ""
        return str(td.decode_contents())

    def _get_plain_text(self, td: Tag) -> str:
        """Estrae testo puro da un tag <td>."""
        if td is None:
            return ""
        return td.get_text(strip=True)
