"""
Template per estratti conto Intesa Sanpaolo.

Struttura colonne (posizionale, non basata su header):
  0: Data Operazione
  1: Data Valuta
  2: Descrizione
  3: Addebiti (Dare)
  4: Accrediti (Avere)

Problemi noti gestiti:
  - Header OCR variabili (Addebita/Addebiti, Accreditati/Accrediti)
  - Importi con spazi spuri (3,420, 00)
  - Righe di continuazione (date vuote = continua riga precedente)
  - Tag HTML nelle descrizioni (<br>, <ul><li>)
  - Riga "Totali" da escludere
  - Saldo iniziale nell'header da ignorare
"""

from bs4 import BeautifulSoup

from normalizer import normalizza_data, normalizza_importo, pulisci_descrizione
from templates.base import BankTemplate, Movimento


class IntesaSanpaoloTemplate(BankTemplate):
    name = "intesa_sanpaolo"
    display_name = "Intesa Sanpaolo"

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

                    # Ignora righe di header (<th>)
                    if cells[0].name == "th":
                        continue

                    # Serve almeno 5 colonne (o gestisci colspan)
                    if len(cells) < 3:
                        continue

                    # Estrai campi per posizione
                    data_op_raw = self._get_plain_text(cells[0]) if len(cells) > 0 else ""
                    data_val_raw = self._get_plain_text(cells[1]) if len(cells) > 1 else ""
                    desc_html = self._get_text(cells[2]) if len(cells) > 2 else ""
                    dare_raw = self._get_plain_text(cells[3]) if len(cells) > 3 else ""
                    avere_raw = self._get_plain_text(cells[4]) if len(cells) > 4 else ""

                    # Escludi riga "Totali"
                    desc_plain = self._get_plain_text(cells[2]) if len(cells) > 2 else ""
                    if desc_plain.strip().lower() in (
                        "totali",
                        "totale",
                        "saldo finale",
                        "saldo iniziale",
                    ):
                        continue

                    # Escludi righe "Saldo iniziale" (spesso in thead con colspan)
                    if "saldo inizial" in desc_plain.lower():
                        continue

                    data_op = normalizza_data(data_op_raw)
                    data_val = normalizza_data(data_val_raw)
                    dare = normalizza_importo(dare_raw)
                    avere = normalizza_importo(avere_raw)

                    # Riga di continuazione: date vuote
                    is_continuation = data_op is None and data_val is None

                    if is_continuation and movimenti_raw:
                        # Appendi descrizione al movimento precedente
                        prev = movimenti_raw[-1]
                        prev.descrizione_raw += " " + desc_html
                        prev.descrizione = pulisci_descrizione(prev.descrizione_raw)
                        # Se la riga di continuazione ha importi, aggiornali
                        if dare is not None and prev.dare is None:
                            prev.dare = dare
                        if avere is not None and prev.avere is None:
                            prev.avere = avere
                        continue

                    # Riga senza data operazione e senza importi = skip
                    if data_op is None and dare is None and avere is None:
                        continue

                    # Riga con data ma senza importi = possibile continuazione
                    # se la descrizione non sembra un movimento autonomo
                    if data_op is not None and dare is None and avere is None:
                        if movimenti_raw:
                            prev = movimenti_raw[-1]
                            # Se la data corrisponde al movimento precedente,
                            # probabilmente e' una continuazione
                            if prev.data_operazione == data_op:
                                prev.descrizione_raw += " " + desc_html
                                prev.descrizione = pulisci_descrizione(prev.descrizione_raw)
                                continue

                    mov = Movimento(
                        data_operazione=data_op or "",
                        data_valuta=data_val,
                        descrizione_raw=desc_html,
                        descrizione=pulisci_descrizione(desc_html),
                        dare=dare,
                        avere=avere,
                        pagina=page_idx,
                    )
                    movimenti_raw.append(mov)

        return movimenti_raw
