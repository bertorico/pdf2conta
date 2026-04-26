"""
Template per estratti conto Intesa Sanpaolo - layout "ufficiale".

Differenze dal template generico intesa_sanpaolo:
  - Riconosce layout con sezione "Dettaglio movimenti del conto corrente"
  - Salta pagine "Dettaglio competenze di chiusura"
  - Gestisce descrizioni multi-riga molto verbose (POS Setefi, Bonifici, ADUE B2B)
  - Supporta titolare_conto configurabile per rimuovere il nome ricorrente
"""

import re
from bs4 import BeautifulSoup

from normalizer import normalizza_importo, normalizza_data, pulisci_descrizione
from templates.base import BankTemplate, Movimento


_PATTERN_COMPETENZE = re.compile(
    r'dettaglio\s+competenze\s+di\s+chiusura|riepilogo\s+competenze\s+di\s+chiusura',
    re.IGNORECASE,
)

_PATTERN_AVVISI = re.compile(
    r'avvertenze\.|per\s+saperne\s+di\s+pi[uù]\.',
    re.IGNORECASE,
)


class IntesaSanpaoloUfficialeTemplate(BankTemplate):

    name = "intesa_sanpaolo_ufficiale"
    display_name = "Intesa Sanpaolo (Ufficiale)"

    def __init__(self, titolare_conto: str = ""):
        self.titolare_conto = titolare_conto.strip()

    def _ha_tabella_movimenti(self, html: str) -> bool:
        if _PATTERN_COMPETENZE.search(html) or _PATTERN_AVVISI.search(html):
            return False

        soup = BeautifulSoup(html, 'html.parser')
        for table in soup.find_all('table'):
            headers = [th.get_text(strip=True).lower() for th in table.find_all('th')]
            header_text = ' '.join(headers)
            if 'data operazione' in header_text:
                return True
            if 'data' in header_text and ('descri' in header_text or 'addebit' in header_text):
                return True
            for row in table.find_all('tr'):
                cells = row.find_all('td')
                if len(cells) >= 5:
                    first = cells[0].get_text(strip=True)
                    if re.match(r'^\d{2}\.\d{2}\.\d{4}$', first):
                        return True
        return False

    def _extra_replaces(self) -> list[str]:
        if self.titolare_conto:
            return [self.titolare_conto]
        return []

    def estrai_movimenti(self, pages_html: list[str]) -> list[Movimento]:
        movimenti_raw: list[Movimento] = []
        extra = self._extra_replaces()

        for page_idx, html in enumerate(pages_html, start=1):
            if not self._ha_tabella_movimenti(html):
                continue

            soup = BeautifulSoup(html, 'html.parser')
            for table in soup.find_all('table'):
                for row in table.find_all('tr'):
                    cells = row.find_all(['td', 'th'])
                    if not cells or cells[0].name == 'th':
                        continue
                    if len(cells) < 3:
                        continue

                    data_op_raw = self._get_plain_text(cells[0])
                    data_val_raw = self._get_plain_text(cells[1]) if len(cells) > 1 else ""
                    desc_html = self._get_text(cells[2]) if len(cells) > 2 else ""
                    dare_raw = self._get_plain_text(cells[3]) if len(cells) > 3 else ""
                    avere_raw = self._get_plain_text(cells[4]) if len(cells) > 4 else ""
                    desc_plain = self._get_plain_text(cells[2]) if len(cells) > 2 else ""

                    desc_lower = desc_plain.strip().lower()
                    if desc_lower in ('totali', 'totale', 'saldo finale', 'saldo iniziale',
                                      'totale accrediti', 'totale addebiti',
                                      'a vostro credito', 'a vostro debito'):
                        continue
                    if 'saldo inizial' in desc_lower or 'saldo final' in desc_lower:
                        continue
                    if desc_lower.startswith('totali') or desc_lower.startswith('totale '):
                        continue

                    data_op = normalizza_data(data_op_raw)
                    data_val = normalizza_data(data_val_raw)
                    dare = normalizza_importo(dare_raw)
                    avere = normalizza_importo(avere_raw)

                    is_continuation = (data_op is None and data_val is None)

                    if is_continuation and movimenti_raw:
                        prev = movimenti_raw[-1]
                        if desc_plain.strip():
                            prev.descrizione_raw += " " + desc_html
                            prev.descrizione = pulisci_descrizione(
                                prev.descrizione_raw, extra_replaces=extra,
                            )
                        if dare is not None and prev.dare is None:
                            prev.dare = dare
                        if avere is not None and prev.avere is None:
                            prev.avere = avere
                        continue

                    if data_op is None and dare is None and avere is None:
                        continue

                    if data_op is not None and dare is None and avere is None:
                        if movimenti_raw:
                            prev = movimenti_raw[-1]
                            if prev.data_operazione == data_op:
                                prev.descrizione_raw += " " + desc_html
                                prev.descrizione = pulisci_descrizione(
                                    prev.descrizione_raw, extra_replaces=extra,
                                )
                                continue

                    mov = Movimento(
                        data_operazione=data_op or "",
                        data_valuta=data_val,
                        descrizione_raw=desc_html,
                        descrizione=pulisci_descrizione(desc_html, extra_replaces=extra),
                        dare=dare,
                        avere=avere,
                        pagina=page_idx,
                    )
                    movimenti_raw.append(mov)

        return movimenti_raw
