import gradio as gr
import requests
import base64
import os
import re
import csv
import tempfile
from pathlib import Path

VLLM_URL = os.environ.get("VLLM_URL", "http://dots-ocr:8000")
MODEL_NAME = os.environ.get("MODEL_NAME", "rednote-hilab/dots.ocr")

PROMPT_MODES = {
    "Parsing completo (testo + layout)": "Parse the document and extract all text content with layout information.",
    "Solo OCR (testo grezzo)": "OCR the image and extract all text.",
    "Solo layout (rilevamento blocchi)": "Detect and identify all layout elements in the document.",
    "Tabelle e formule": "Extract all tables and formulas from the document. Output tables in markdown format.",
    "Lettura ordinata": "Extract all text maintaining the correct reading order.",
}

def image_to_base64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        data = f.read()
    ext = Path(image_path).suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"

def check_server():
    try:
        r = requests.get(f"{VLLM_URL}/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False

def extract_markdown_tables(text: str):
    """Estrae tutte le tabelle Markdown dal testo."""
    tables = []
    current_table = []
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('|') and stripped.endswith('|'):
            if re.match(r'^\|[-| :]+\|$', stripped):
                continue
            cells = [c.strip() for c in stripped[1:-1].split('|')]
            current_table.append(cells)
        else:
            if current_table:
                tables.append(current_table)
                current_table = []
    if current_table:
        tables.append(current_table)
    return tables

def run_ocr(image, prompt_label, custom_prompt):
    if image is None:
        return "❌ Carica un'immagine prima di procedere.", "", gr.update(visible=False)
    if not check_server():
        return f"❌ Server vLLM non raggiungibile su {VLLM_URL}", "", gr.update(visible=False)

    prompt_text = custom_prompt.strip() if custom_prompt.strip() else PROMPT_MODES.get(prompt_label, PROMPT_MODES["Parsing completo (testo + layout)"])

    try:
        img_b64 = image_to_base64(image)
    except Exception as e:
        return f"❌ Errore lettura immagine: {e}", "", gr.update(visible=False)

    payload = {
        "model": MODEL_NAME,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {"type": "image_url", "image_url": {"url": img_b64}},
            ],
        }],
        "max_tokens": 1800,
        "temperature": 0.0,
    }

    try:
        resp = requests.post(f"{VLLM_URL}/v1/chat/completions", json=payload, timeout=120)
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        has_table = bool(extract_markdown_tables(text))
        return text, text, gr.update(visible=has_table)
    except requests.exceptions.Timeout:
        return "❌ Timeout: prova con un'immagine più piccola.", "", gr.update(visible=False)
    except requests.exceptions.HTTPError as e:
        return f"❌ Errore HTTP {e.response.status_code}: {e.response.text}", "", gr.update(visible=False)
    except Exception as e:
        return f"❌ Errore: {e}", "", gr.update(visible=False)

def export_csv(raw_text: str):
    if not raw_text or raw_text.startswith("❌"):
        return gr.update(visible=False)
    tables = extract_markdown_tables(raw_text)
    if not tables:
        return gr.update(visible=False)

    tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.csv', delete=False,
        encoding='utf-8-sig', newline=''
    )
    writer = csv.writer(tmp, delimiter=';')
    for i, table in enumerate(tables):
        if i > 0:
            writer.writerow([])
            writer.writerow([f"--- Tabella {i+1} ---"])
        writer.writerows(table)
    tmp.close()
    return gr.update(value=tmp.name, visible=True)

def server_status():
    if check_server():
        try:
            r = requests.get(f"{VLLM_URL}/v1/models", timeout=5)
            models = r.json().get("data", [])
            names = [m["id"] for m in models]
            return f"✅ Server online | Modello: {', '.join(names) if names else MODEL_NAME}"
        except Exception:
            return "✅ Server online"
    return f"❌ Server offline ({VLLM_URL})"

with gr.Blocks(title="dots.ocr UI", theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
    # 🔍 dots.ocr — Document OCR & Layout Parser
    Carica un'immagine di un documento (PDF convertito in immagine, screenshot, foto) e scegli la modalità di analisi.
    """)

    with gr.Row():
        status_box = gr.Textbox(label="Stato server", value=server_status(), interactive=False, scale=3)
        refresh_btn = gr.Button("🔄 Aggiorna", scale=1)

    with gr.Row():
        with gr.Column(scale=1):
            image_input = gr.Image(label="Immagine documento", type="filepath", height=400)
            prompt_dropdown = gr.Dropdown(
                choices=list(PROMPT_MODES.keys()),
                value="Parsing completo (testo + layout)",
                label="Modalità",
            )
            custom_prompt = gr.Textbox(
                label="Prompt personalizzato (opzionale, sovrascrive la modalità)",
                placeholder="Es: Extract all text from tables only.",
                lines=2,
            )
            run_btn = gr.Button("🚀 Avvia OCR", variant="primary", size="lg")

        with gr.Column(scale=1):
            output_rendered = gr.Markdown(label="Risultato (renderizzato)")
            output_raw = gr.Textbox(label="Risultato (testo grezzo)", lines=20, show_copy_button=True)
            csv_btn = gr.Button("📥 Esporta tabelle in CSV", variant="secondary", visible=False)
            csv_file = gr.File(label="📄 File CSV pronto per il download", visible=False)

    run_btn.click(
        fn=run_ocr,
        inputs=[image_input, prompt_dropdown, custom_prompt],
        outputs=[output_rendered, output_raw, csv_btn],
    )
    csv_btn.click(fn=export_csv, inputs=[output_raw], outputs=[csv_file])
    refresh_btn.click(fn=server_status, outputs=status_box)

    gr.Markdown("""
    ---
    **Suggerimenti:**
    - Per PDF: converti prima le pagine in immagini (DPI consigliato: 200)
    - Il pulsante **Esporta CSV** appare automaticamente quando vengono rilevate tabelle
    - Il CSV usa `;` come separatore — compatibile con Excel italiano
    """)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, show_api=False)