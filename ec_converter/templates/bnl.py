"""
Template per estratti conto BNL (Gruppo BNP Paribas).

Struttura colonne (posizionale):
  0: Data Contabile (Data Operazione)
  1: Data Valuta
  2: Causale ABI
  3: Descrizione operazione
  4: Uscita (Dare)
  5: Entrata (Avere)

Differenze rispetto a Intesa Sanpaolo:
  - 6 colonne invece di 5 (causale ABI inclusa)
  - Date in formato DD/MM/YYYY (slash, non punti)
  - Importi con simbolo euro (es. "25.586,87 €")
  - Causale ABI gia' presente nel PDF (colonna 2)
  - Header molto lunghi e descrittivi
  - Riga "SALDO INIZIALE" nella prima tabella
"""

from bs4 import BeautifulSoup

from normalizer import normalizza_data, normalizza_importo, pulisci_descrizione
from templates.base import BankTemplate, Movimento


class BNLTemplate(BankTemplate):
    name = "bnl"
    display_name = "BNL (BNP Paribas)"

    def _ha_tabella_movimenti(self, html: str) -> bool:
        """BNL usa header molto descrittivi, cerco pattern specifici."""
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        for table in tables:
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            header_text = " ".join(headers)
            # Header BNL: "la banca ha registrato..." o "data contabile" o "caus. abi"
            if "caus" in header_text or "contabile" in header_text or "registrato" in header_text:
                return True
            # Oppure tabella con 6 colonne e date nella prima
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) >= 6:
                    first_text = cells[0].get_text(strip=True)
                    # Controlla se sembra una data DD/MM/YYYY
                    if len(first_text) == 10 and first_text[2] == "/" and first_text[5] == "/":
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

                    # BNL ha 6 colonne
                    if len(cells) < 4:
                        continue

                    data_op_raw = self._get_plain_text(cells[0])
                    data_val_raw = self._get_plain_text(cells[1]) if len(cells) > 1 else ""
                    causale_abi = self._get_plain_text(cells[2]) if len(cells) > 2 else ""
                    desc_html = self._get_text(cells[3]) if len(cells) > 3 else ""
                    dare_raw = self._get_plain_text(cells[4]) if len(cells) > 4 else ""
                    avere_raw = self._get_plain_text(cells[5]) if len(cells) > 5 else ""

                    desc_plain = self._get_plain_text(cells[3]) if len(cells) > 3 else ""

                    # Escludi righe non-movimento
                    desc_lower = desc_plain.strip().lower()
                    if desc_lower in (
                        "saldo iniziale",
                        "saldo finale",
                        "totale entrate",
                        "totale uscite",
                        "totale usite",
                    ):
                        continue
                    if "totale" in desc_lower and not data_op_raw:
                        continue

                    data_op = normalizza_data(data_op_raw)
                    data_val = normalizza_data(data_val_raw)
                    dare = normalizza_importo(dare_raw)
                    avere = normalizza_importo(avere_raw)

                    # Riga di continuazione
                    is_continuation = data_op is None and data_val is None

                    if is_continuation and movimenti_raw:
                        prev = movimenti_raw[-1]
                        if desc_plain.strip():
                            prev.descrizione_raw += " " + desc_html
                            prev.descrizione = pulisci_descrizione(prev.descrizione_raw)
                        if dare is not None and prev.dare is None:
                            prev.dare = dare
                        if avere is not None and prev.avere is None:
                            prev.avere = avere
                        continue

                    if data_op is None and dare is None and avere is None:
                        continue

                    # Causale ABI: pulisci (potrebbe essere numero o vuoto)
                    causale = causale_abi.strip() if causale_abi.strip().isdigit() else None

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
