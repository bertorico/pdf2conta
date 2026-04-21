"""
UI Gradio per EC Converter: Estratto Conto PDF -> CSV per Ago Zucchetti.

Flusso:
1. Upload PDF
2. Selezione banca (template)
3. Elaborazione (PDF -> OCR -> parsing)
4. Preview tabella movimenti (editabile) con causali
5. Scelta modalita' importo e causale
6. Download CSV

Tab aggiuntivo: gestione causali (aggiungi/modifica/elimina).
"""

import os
import json
import logging
import tempfile

import gradio as gr
import pandas as pd

from pipeline import process_pdf, check_ocr_server
from csv_exporter import export_csv
from templates import list_templates, TEMPLATES
from templates.base import Movimento
from normalizer import (
    formatta_importo, normalizza_importo,
    carica_causali, salva_causali, match_causale,
    carica_replace, salva_replace,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_current_movimenti: list[Movimento] = []


AUTO_DETECT_LABEL = "Auto-detect"


def get_template_choices() -> list[str]:
    choices = [AUTO_DETECT_LABEL]
    choices.extend(TEMPLATES[k]().display_name for k in list_templates())
    return choices


def get_template_name_from_display(display: str) -> str:
    if display == AUTO_DETECT_LABEL:
        return "auto"
    for key, cls in TEMPLATES.items():
        if cls().display_name == display:
            return key
    return list_templates()[0]


def elabora_pdf(pdf_file, template_display, progress=gr.Progress()):
    """Elabora il PDF e restituisce la tabella di anteprima."""
    global _current_movimenti

    if pdf_file is None:
        return None, "Nessun file caricato."

    if not check_ocr_server():
        return None, "Server OCR (dots-ocr) non raggiungibile. Verificare che il servizio sia attivo."

    template_name = get_template_name_from_display(template_display)

    def progress_cb(step, detail):
        if step == "pdf":
            progress(0.1, desc=detail)
        elif step == "ocr":
            progress(0.5, desc=detail)
        elif step == "parse":
            progress(0.9, desc=detail)
        elif step == "causali":
            progress(0.95, desc=detail)

    try:
        movimenti, used_template = process_pdf(
            pdf_path=pdf_file.name,
            template_name=template_name,
            progress_callback=progress_cb,
        )
    except Exception as e:
        logger.exception("Errore durante l'elaborazione")
        return None, f"Errore: {e}"

    if not movimenti:
        return None, "Nessun movimento trovato nel PDF."

    _current_movimenti = movimenti
    df = _movimenti_to_dataframe(movimenti)

    # Nome banca usata
    bank_display = TEMPLATES.get(used_template, lambda: None)
    if bank_display:
        bank_display = bank_display().display_name
    else:
        bank_display = used_template

    msg = f"Banca: {bank_display} | Estratti {len(movimenti)} movimenti."
    tot_dare = sum(m.dare or 0 for m in movimenti)
    tot_avere = sum(m.avere or 0 for m in movimenti)
    n_causali = sum(1 for m in movimenti if m.causale)
    msg += f"\nTotale Dare: {formatta_importo(tot_dare)} | Totale Avere: {formatta_importo(tot_avere)}"
    msg += f"\nDifferenza: {formatta_importo(tot_avere - tot_dare)}"
    msg += f"\nCausali assegnate: {n_causali}/{len(movimenti)}"

    return df, msg


def _movimenti_to_dataframe(movimenti: list[Movimento]) -> pd.DataFrame:
    rows = []
    for m in movimenti:
        rows.append({
            "Data Operazione": m.data_operazione,
            "Data Valuta": m.data_valuta or "",
            "Descrizione": m.descrizione,
            "Causale": m.causale or "",
            "Addebiti": formatta_importo(m.dare) if m.dare is not None else "",
            "Accrediti": formatta_importo(m.avere) if m.avere is not None else "",
        })
    return pd.DataFrame(rows)


def genera_csv(df_data, modalita_importo, includi_causale):
    """Genera il CSV dalla tabella (eventualmente modificata dall'utente)."""
    global _current_movimenti

    if df_data is None or (isinstance(df_data, pd.DataFrame) and df_data.empty):
        return None, "Nessun dato da esportare."

    if isinstance(df_data, pd.DataFrame):
        movimenti = _dataframe_to_movimenti(df_data)
    else:
        movimenti = _current_movimenti

    if not movimenti:
        return None, "Nessun movimento da esportare."

    modalita = "colonna_unica" if "unica" in modalita_importo.lower() else "due_colonne"

    csv_content = export_csv(
        movimenti,
        modalita_importo=modalita,
        includi_causale=includi_causale,
    )

    tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.csv', prefix='ec_ago_',
        delete=False, encoding='utf-8', newline=''
    )
    tmp.write(csv_content)
    tmp.close()

    n = len(movimenti)
    causale_info = " con causali" if includi_causale else ""
    return tmp.name, f"CSV generato con {n} movimenti{causale_info} ({modalita_importo})."


def _dataframe_to_movimenti(df: pd.DataFrame) -> list[Movimento]:
    """Converte il DataFrame editato dall'utente in lista di Movimento."""
    movimenti = []
    for _, row in df.iterrows():
        data_op = str(row.get("Data Operazione", "")).strip()
        if not data_op:
            continue
        dare_val = normalizza_importo(str(row.get("Addebiti", "")))
        avere_val = normalizza_importo(str(row.get("Accrediti", "")))
        desc = str(row.get("Descrizione", "")).strip()
        causale = str(row.get("Causale", "")).strip() or None
        movimenti.append(Movimento(
            data_operazione=data_op,
            data_valuta=str(row.get("Data Valuta", "")).strip() or None,
            descrizione_raw=desc,
            descrizione=desc,
            dare=dare_val,
            avere=avere_val,
            causale=causale,
        ))
    return movimenti


# --- Tab Gestione Causali ---

def carica_causali_tabella():
    """Carica le causali come DataFrame per la tabella Gradio."""
    causali = carica_causali()
    rows = []
    for c in causali:
        rows.append({
            "Codice": c["codice"],
            "Nome": c["nome"],
            "Pattern": ", ".join(c.get("pattern", [])),
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Codice", "Nome", "Pattern"])


def salva_causali_tabella(df_causali):
    """Salva le causali dalla tabella Gradio al file JSON."""
    if df_causali is None or (isinstance(df_causali, pd.DataFrame) and df_causali.empty):
        return "Nessuna causale da salvare."

    causali = []
    for _, row in df_causali.iterrows():
        codice = str(row.get("Codice", "")).strip()
        nome = str(row.get("Nome", "")).strip()
        pattern_str = str(row.get("Pattern", "")).strip()
        if not codice or not nome:
            continue
        patterns = [p.strip() for p in pattern_str.split(",") if p.strip()]
        causali.append({"codice": codice, "nome": nome, "pattern": patterns})

    salva_causali(causali)
    return f"Salvate {len(causali)} causali."


def build_ui():
    with gr.Blocks(
        title="EC Converter - Estratto Conto PDF -> CSV Ago",
        theme=gr.themes.Soft(),
    ) as app:
        gr.Markdown("# Estratto Conto PDF -> CSV Ago Zucchetti")

        with gr.Tabs():
            # --- Tab Converter ---
            with gr.Tab("Converter"):
                gr.Markdown("Carica un estratto conto PDF, verifica i movimenti estratti e scarica il CSV.")

                with gr.Row():
                    with gr.Column(scale=1):
                        pdf_input = gr.File(
                            label="Carica PDF Estratto Conto",
                            file_types=[".pdf"],
                            type="filepath",
                        )
                        template_choice = gr.Dropdown(
                            label="Banca",
                            choices=get_template_choices(),
                            value=AUTO_DETECT_LABEL,
                        )
                        btn_elabora = gr.Button("Elabora PDF", variant="primary")

                    with gr.Column(scale=1):
                        modalita_importo = gr.Radio(
                            label="Modalita' importo CSV",
                            choices=["Due colonne (Dare/Avere)", "Colonna unica (con segno +/-)"],
                            value="Due colonne (Dare/Avere)",
                        )
                        includi_causale = gr.Checkbox(
                            label="Includi colonna Causale nel CSV",
                            value=False,
                        )
                        btn_csv = gr.Button("Genera CSV", variant="secondary")
                        csv_output = gr.File(label="Download CSV")

                status_msg = gr.Textbox(label="Stato", interactive=False, lines=4)

                gr.Markdown("### Anteprima Movimenti")
                gr.Markdown("*Puoi modificare i dati (inclusa la causale) nella tabella prima di generare il CSV.*")
                preview_table = gr.Dataframe(
                    headers=["Data Operazione", "Data Valuta", "Descrizione", "Causale", "Addebiti", "Accrediti"],
                    interactive=True,
                    wrap=True,
                )

                btn_elabora.click(
                    fn=elabora_pdf,
                    inputs=[pdf_input, template_choice],
                    outputs=[preview_table, status_msg],
                )
                btn_csv.click(
                    fn=genera_csv,
                    inputs=[preview_table, modalita_importo, includi_causale],
                    outputs=[csv_output, status_msg],
                )

            # --- Tab Causali ---
            with gr.Tab("Gestione Causali"):
                gr.Markdown("### Causali Movimento")
                gr.Markdown(
                    "Definisci le causali e i pattern di matching. "
                    "I pattern vengono cercati (case-insensitive) nella descrizione del movimento.\n\n"
                    "**Pattern:** separati da virgola. Es: `pagamento adue, addebito diretto`"
                )

                causali_table = gr.Dataframe(
                    headers=["Codice", "Nome", "Pattern"],
                    interactive=True,
                    wrap=True,
                    value=carica_causali_tabella,
                )

                with gr.Row():
                    btn_salva_causali = gr.Button("Salva Causali", variant="primary")
                    btn_ricarica_causali = gr.Button("Ricarica da file")

                causali_status = gr.Textbox(label="Stato", interactive=False)

                btn_salva_causali.click(
                    fn=salva_causali_tabella,
                    inputs=[causali_table],
                    outputs=[causali_status],
                )
                btn_ricarica_causali.click(
                    fn=carica_causali_tabella,
                    outputs=[causali_table],
                )

            # --- Tab Replace ---
            with gr.Tab("Gestione Replace"):
                gr.Markdown("### Replace Descrizioni")
                gr.Markdown(
                    "Definisci sostituzioni di testo da applicare alle descrizioni dei movimenti.\n\n"
                    "- **Trova**: testo da cercare (case-insensitive)\n"
                    "- **Sostituisci**: testo sostitutivo (vuoto = cancella)\n"
                    "- **Nota**: promemoria opzionale\n\n"
                    "Le regole vengono applicate in ordine dall'alto verso il basso."
                )

                replace_table = gr.Dataframe(
                    headers=["Trova", "Sostituisci", "Nota"],
                    interactive=True,
                    wrap=True,
                    value=carica_replace_tabella,
                )

                with gr.Row():
                    btn_salva_replace = gr.Button("Salva Replace", variant="primary")
                    btn_ricarica_replace = gr.Button("Ricarica da file")

                replace_status = gr.Textbox(label="Stato", interactive=False)

                btn_salva_replace.click(
                    fn=salva_replace_tabella,
                    inputs=[replace_table],
                    outputs=[replace_status],
                )
                btn_ricarica_replace.click(
                    fn=carica_replace_tabella,
                    outputs=[replace_table],
                )

    return app


# --- Funzioni tab Replace ---

def carica_replace_tabella():
    """Carica i replace come DataFrame per la tabella Gradio."""
    replace_list = carica_replace()
    rows = []
    for r in replace_list:
        rows.append({
            "Trova": r.get("trova", ""),
            "Sostituisci": r.get("sostituisci", ""),
            "Nota": r.get("nota", ""),
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Trova", "Sostituisci", "Nota"])


def salva_replace_tabella(df_replace):
    """Salva i replace dalla tabella Gradio al file JSON."""
    if df_replace is None or (isinstance(df_replace, pd.DataFrame) and df_replace.empty):
        return "Nessun replace da salvare."

    replace_list = []
    for _, row in df_replace.iterrows():
        trova = str(row.get("Trova", "")).strip()
        sostituisci = str(row.get("Sostituisci", ""))
        nota = str(row.get("Nota", "")).strip()
        if not trova:
            continue
        entry = {"trova": trova, "sostituisci": sostituisci}
        if nota:
            entry["nota"] = nota
        replace_list.append(entry)

    salva_replace(replace_list)
    return f"Salvati {len(replace_list)} replace."


if __name__ == "__main__":
    app = build_ui()
    app.launch(server_name="0.0.0.0", server_port=7860)
