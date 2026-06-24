"""
Template per BNL "Lista Movimenti C/C" (export da home banking).

Formato diverso dall'estratto conto BNL standard (bnl.py).

Struttura colonne (posizionale, 9 colonne):
  0: Rag.Soc./Intestatario  (ignorata)
  1: ABI                     (ignorata)
  2: CAB                     (ignorata)
  3: Conto                   (ignorata)
  4: Operazione              (Data Operazione DD/MM/YYYY)
  5: Valuta                  (Data Valuta DD/MM/YYYY)
  6: Importo                 (colonna unica con segno: -7.460,00 / 4.000,00)
  7: Causale                 (codice ABI: 31, 48, 50, 66, 11, 16)
  8: Descrizione             (ultima colonna, contiene codici RIBA, TRN, ecc.)

Differenze vs bnl.py (estratto conto):
  - 9 colonne vs 6
  - Importo unico con segno vs due colonne dare/avere
  - Descrizione come ultima colonna vs colonna 4
  - Colonne 0-3 ripetute e inutili
"""

from bs4 import BeautifulSoup

from normalizer import normalizza_data, normalizza_importo, pulisci_descrizione
from templates.base import BankTemplate, Movimento


class BNLListaMovimentiTemplate(BankTemplate):
    name = "bnl_lista_movimenti"
    display_name = "BNL (Lista Movimenti)"

    def _ha_tabella_movimenti(self, html: str) -> bool:
        """Riconosce il formato Lista Movimenti BNL."""
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text().lower()
        # Pattern specifici di questo formato
        if "lista movimenti" in text:
            return True
        if "rag.soc" in text and "operazione" in text and "causale" in text:
            return True
        # Controlla tabelle con 9+ colonne
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) >= 8:
                    headers = [c.get_text(strip=True).lower() for c in cells]
                    if any("operazione" in h for h in headers) and any(
                        "causale" in h for h in headers
                    ):
                        return True
        return False

    def estrai_movimenti(self, pages_html: list[str]) -> list[Movimento]:
        movimenti_raw: list[Movimento] = []

        for page_idx, html in enumerate(pages_html, start=1):
            if not self._ha_tabella_movimenti(html):
                continue

            soup = BeautifulSoup(html, "html.parser")
            for table in soup.find_all("table"):
                rows = table.find_all("tr")
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if not cells:
                        continue

                    # Ignora header
                    if cells[0].name == "th":
                        continue

                    # Servono almeno 8 colonne (formato 9 col, ma OCR potrebbe unirne)
                    if len(cells) < 7:
                        continue

                    # Mappatura colonne.
                    # Con 9 colonne: 0=Rag.Soc, 1=ABI, 2=CAB, 3=Conto, 4=Operazione,
                    #                5=Valuta, 6=Importo, 7=Causale, 8=Descrizione
                    # Con 8 colonne (OCR potrebbe unire le prime):
                    #   cerchiamo la data nella posizione giusta
                    if len(cells) >= 9:
                        idx_data_op = 4
                        idx_valuta = 5
                        idx_importo = 6
                        idx_causale = 7
                        idx_desc = 8
                    elif len(cells) >= 8:
                        # Potrebbe mancare una colonna: cerchiamo la data
                        idx_data_op = 3
                        idx_valuta = 4
                        idx_importo = 5
                        idx_causale = 6
                        idx_desc = 7
                    else:
                        continue

                    data_op_raw = self._get_plain_text(cells[idx_data_op])
                    data_val_raw = self._get_plain_text(cells[idx_valuta])
                    importo_raw = self._get_plain_text(cells[idx_importo])
                    causale_raw = self._get_plain_text(cells[idx_causale])
                    desc_html = self._get_text(cells[idx_desc]) if len(cells) > idx_desc else ""

                    # Normalizza date
                    data_op = normalizza_data(data_op_raw)
                    data_val = normalizza_data(data_val_raw)

                    # Se non ci sono date valide, potrebbe essere un header o riga vuota
                    if data_op is None and data_val is None:
                        # Riga di continuazione
                        desc_plain = (
                            self._get_plain_text(cells[idx_desc]) if len(cells) > idx_desc else ""
                        )
                        if desc_plain.strip() and movimenti_raw:
                            prev = movimenti_raw[-1]
                            prev.descrizione_raw += " " + desc_html
                            prev.descrizione = pulisci_descrizione(prev.descrizione_raw)
                        continue

                    # Gestione importo con segno
                    dare, avere = self._parse_importo_con_segno(importo_raw)

                    # Causale ABI
                    causale = causale_raw.strip() if causale_raw.strip().isdigit() else None

                    desc_plain = (
                        self._get_plain_text(cells[idx_desc]) if len(cells) > idx_desc else ""
                    )

                    # Escludi righe non-movimento
                    if desc_plain.strip().lower() in (
                        "totale",
                        "totali",
                        "saldo iniziale",
                        "saldo finale",
                    ):
                        continue

                    mov = Movimento(
                        data_operazione=data_op or "",
                        data_valuta=data_val,
                        descrizione_raw=desc_html,
                        descrizione=pulisci_descrizione(desc_html),
                        dare=dare,
                        avere=avere,
                        causale=causale,
                        pagina=page_idx,
                    )
                    movimenti_raw.append(mov)

        return movimenti_raw

    def _parse_importo_con_segno(self, raw: str) -> tuple:
        """
        Gestisce importo con segno: negativo = dare, positivo = avere.

        Esempi:
          "-7.460,00" -> (dare=7460.0, avere=None)
          "4.000,00"  -> (dare=None, avere=4000.0)
          "-1,55"     -> (dare=1.55, avere=None)
        """
        if not raw or not raw.strip():
            return None, None

        s = raw.strip()
        is_negative = s.startswith("-")

        # Rimuovi il segno per la normalizzazione
        s_unsigned = s.lstrip("-+")
        valore = normalizza_importo(s_unsigned)

        if valore is None:
            return None, None

        if is_negative:
            return valore, None  # dare
        else:
            return None, valore  # avere
