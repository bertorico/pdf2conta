"""
Template per BNL Rendiconto POS (Gruppo BNP Paribas).

Documento: "Finanziamenti" — estratto conto terminali POS BNL.
L'OCR produce strutture con numero di colonne variabile per pagina:

  Pagina 1 (7 col): Data(DD/MM/YYYY) | Valuta(DD/MM/YY) | Desc*3 | Dare | Avere
  Pagina 2 (5 col): Data(DD/MM)      | Valuta(DD/MM/YY) | Desc   | Dare | Avere
  Pagina 3 (6 col): Data(DD/MM)      | Valuta(DD/MM/YY) | Desc*2 | Dare | Avere

Strategia colonne:
  - Col 0: Data operazione (DD/MM/YYYY o DD/MM)
  - Col 1: Data valuta (DD/MM/YY)
  - Col 2..n-3: Descrizione (join delle parti)
  - Col n-2: Dare (se non e' un numero, viene accodato alla descrizione)
  - Col n-1: Avere

Le date DD/MM prive di anno vengono completate con l'anno estratto dalla
data valuta adiacente (formato DD/MM/YY).
"""

import re

from bs4 import BeautifulSoup

from normalizer import normalizza_data, normalizza_importo, pulisci_descrizione
from templates.base import BankTemplate, Movimento


class BNLPosTemplate(BankTemplate):
    name = "bnl_pos"
    display_name = "BNL POS (Rendiconto)"

    def _ha_tabella_movimenti(self, html: str) -> bool:
        soup = BeautifulSoup(html, "html.parser")
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            header_text = " ".join(headers)
            if "data" in header_text and "avere" in header_text:
                return True
        return False

    def _parse_anno_da_valuta(self, raw: str) -> int | None:
        """Estrae l'anno intero da una data valuta DD/MM/YY o DD/MM/YYYY."""
        s = raw.strip() if raw else ""
        m = re.match(r"^\d{2}[/.]\d{2}[/.](\d{2})$", s)
        if m:
            return 2000 + int(m.group(1))
        m = re.match(r"^\d{2}[/.]\d{2}[/.](\d{4})$", s)
        if m:
            return int(m.group(1))
        return None

    def _normalizza_data_pos(self, raw: str, anno_fallback: int | None = None) -> str | None:
        """
        Normalizza date nei formati BNL POS:
          DD/MM/YYYY → DD.MM.YYYY  (via normalizza_data)
          DD/MM/YY   → DD.MM.20YY
          DD/MM      → DD.MM.YYYY  (usa anno_fallback dalla valuta)
        """
        s = raw.strip() if raw else ""
        if not s:
            return None
        result = normalizza_data(s)
        if result:
            return result
        # DD/MM/YY (anno a 2 cifre)
        m = re.match(r"^(\d{2})[/.](\d{2})[/.](\d{2})$", s)
        if m:
            g, mes, yy = m.groups()
            return f"{g}.{mes}.{2000 + int(yy)}"
        # DD/MM senza anno
        m = re.match(r"^(\d{2})[/.](\d{2})$", s)
        if m and anno_fallback:
            g, mes = m.groups()
            return f"{g}.{mes}.{anno_fallback}"
        return None

    def estrai_movimenti(self, pages_html: list[str]) -> list[Movimento]:
        movimenti: list[Movimento] = []

        for page_idx, html in enumerate(pages_html, start=1):
            if not self._ha_tabella_movimenti(html):
                continue

            soup = BeautifulSoup(html, "html.parser")
            for table in soup.find_all("table"):
                headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
                header_text = " ".join(headers)
                if "data" not in header_text or "avere" not in header_text:
                    continue

                for row in table.find_all("tr"):
                    cells = row.find_all(["td", "th"])
                    if not cells or cells[0].name == "th":
                        continue
                    if len(cells) < 4:
                        continue

                    n = len(cells)
                    data_op_raw = self._get_plain_text(cells[0])
                    data_val_raw = self._get_plain_text(cells[1])

                    anno = self._parse_anno_da_valuta(data_val_raw)
                    data_op = self._normalizza_data_pos(data_op_raw, anno)
                    data_val = self._normalizza_data_pos(data_val_raw)

                    avere_raw = self._get_plain_text(cells[n - 1])
                    dare_raw = self._get_plain_text(cells[n - 2])

                    avere = normalizza_importo(avere_raw)
                    dare = normalizza_importo(dare_raw)

                    # Colonne intermedie → descrizione; se dare_raw non e' un numero
                    # (es. "da POS" spill dall'OCR), lo accoda alla descrizione.
                    desc_parts = [self._get_plain_text(cells[i]) for i in range(2, n - 2)]
                    if dare is None and dare_raw.strip():
                        desc_parts.append(dare_raw.strip())
                    desc_raw = " ".join(p for p in desc_parts if p)

                    if not desc_raw.strip():
                        continue
                    if desc_raw.strip().lower().startswith("saldo"):
                        continue
                    if data_op is None and dare is None and avere is None:
                        continue

                    mov = Movimento(
                        data_operazione=data_op or "",
                        data_valuta=data_val,
                        descrizione_raw=desc_raw,
                        descrizione=pulisci_descrizione(desc_raw),
                        dare=dare,
                        avere=avere,
                        pagina=page_idx,
                    )
                    movimenti.append(mov)

        return movimenti
