# Piano — Layer agentico LangGraph su `ec_converter` (primo step minimo: estrai → valida)

> Documento di pianificazione da riprendere in futuro. Stato: **approvato come direzione, non
> ancora implementato.** Decisioni prese con l'utente: costruire su `ec_converter` (non
> `fatture_converter`); primo step **minimo** a 2 nodi `estrai → valida`.

## Context

Sul branch `feat/agentic-langgraph` esiste già un grafo LangGraph (commit `fe425b7`) che
wrappa `fatture_converter`: `estrai` (pdftotext+regex) → `valida` (coerenza IVA) →
`correggi` (segnaposto). È servito per **capire LangGraph nel concreto** ed è CPU-only.

Obiettivo di carriera ("Scenario C" — Applied AI Engineer remoto): il valore-portfolio di un
layer agentico dipende da **cosa fanno i nodi**, non dal grafo in sé. Le keyword (orchestrazione
LangGraph + **LLM self-hosted in inference** + **eval**) diventano vere su `ec_converter` e
restano cosmetiche su `fatture_converter`, perché:

- **estrai** su ec_converter chiama **dots.ocr (vision-LLM) via vLLM** → modello reale nel loop
  (su fatture è solo regex, nessun modello).
- **valida** su ec_converter usa la **quadratura saldi** (`saldo_iniz + accrediti − addebiti =
  saldo_fin`, tolleranza 0.01€): un invariante a livello documento che fallisce *davvero* quando
  l'OCR sbaglia un importo → segnale reale per la futura freccia condizionale e il retry.

Decisione presa con l'utente: **costruire il grafo portfolio-grade su `ec_converter`**, tenendo
il grafo `fatture_converter` come scaffold-tutorial. **Primo step = minimo**: 2 soli nodi
`estrai → valida`, stampa dello stato finale. Niente freccia condizionale, niente `correggi`,
niente LLM nel mezzo (quelli sono i passi successivi documentati, non in questo step).

## Convenzioni di lavoro (CLAUDE.md repo)

- Invocare la skill `intervento-repo` all'avvio dell'intervento.
- Codice Python tramite agente `python-pro`; eventuali operazioni git tramite `git-workflow-manager`.
- Annotare l'intervento in `.claude/skills/intervento-repo/INTERVENTI.md`.
- **Non committare** dati reali in `e_c/`. Nessun commit/push/PR senza richiesta esplicita.

## Approccio

Replicare lo **stesso pattern** del grafo fatture (stato = "scatola" TypedDict, nodi = funzioni
Python normali, riuso di codice di produzione esistente **senza riscriverlo**), ma sopra
`ec_converter.pipeline.process_pdf`.

### 1. Refactor di riuso — estrarre la quadratura in una funzione pura

Oggi la logica di quadratura (incl. la tolleranza `abs(diff) < 0.01`) vive **dentro la UI**, in
`ec_converter/app.py` → `_formatta_quadratura()` (righe ~121-148). Per non duplicarla nel nodo
`valida`:

- Creare `ec_converter/validators.py` con una funzione **pura** (nessuna dipendenza Gradio):
  `verifica_quadratura(saldi: dict, movimenti: list[Movimento]) -> dict`
  che ritorna `{variazione_attesa, variazione_movimenti, diff, ok: bool, errori: list[str]}`.
  La tolleranza `0.01` vive **solo qui** (unica fonte di verità).
  - Caso "saldi non disponibili" (template non-Intesa → dict con chiavi a `None`): ritornare
    `ok=True`, `errori=[]`, con una nota tipo `quadratura non disponibile per questo template`.
- Refactorare `_formatta_quadratura()` in `app.py` perché **chiami** `verifica_quadratura()` per i
  numeri e l'esito, mantenendo invariato il markdown ✅/⚠️ mostrato in UI (nessun cambiamento
  visibile per l'utente).

### 2. Stato del grafo — `agentic/ec_state.py`

`TypedDict(total=False)` `EstrattoContoState`, stessa metafora "scatola" del file `agentic/state.py`:

```
pdf_path: str            # input (obbligatorio)
template_name: str       # input, default "auto"
titolare_conto: str      # input, opzionale
movimenti: list[Movimento]   # popolato da estrai
template_usato: str          # popolato da estrai
saldi: dict                  # popolato da estrai
quadratura: dict             # popolato da valida (output di verifica_quadratura)
errori: list[str]            # popolato da valida
valida: bool                 # popolato da valida
```

### 3. Grafo a 2 nodi — `agentic/ec_graph.py`

Sullo stampo di `agentic/graph.py`:

- **`estrai(state)`**: chiama
  `ec_converter.pipeline.process_pdf(state["pdf_path"], template_name=state.get("template_name","auto"), titolare_conto=state.get("titolare_conto",""))`
  → ritorna `(movimenti, template_usato, saldi)`; popola lo stato.
  (Questo è il nodo che porta dentro il loop l'OCR vLLM/dots.ocr — la keyword "LLM self-hosted".)
- **`valida(state)`**: chiama `verifica_quadratura(state["saldi"], state["movimenti"])`; popola
  `quadratura`, `errori`, `valida`.
- Grafo: `set_entry_point("estrai")` → `add_edge("estrai","valida")` → `add_edge("valida", END)`.
  **Nessuna** `add_conditional_edges` in questo step (è il passo successivo).
- Blocco `if __name__ == "__main__"` / `python -m agentic.ec_graph`: trova il primo PDF in `e_c/`,
  invoca il grafo, **stampa lo stato finale leggibile**: n. movimenti, saldo iniziale/finale,
  variazione attesa vs movimenti, `diff`, esito `valida` ✅/⚠️, e `list(stato_finale.keys())`.

### 4. Documentazione

- Aggiornare `agentic/README.md` (o nuova sezione) spiegando i due grafi: `graph.py` (fatture,
  tutorial CPU-only) e `ec_graph.py` (estratti conto, richiede vLLM/GPU), e i prossimi passi
  documentati: freccia condizionale → nodo `correggi` (ri-OCR pagina / Qwen via LiteLLM) → loop
  verso `valida` con contatore tentativi → checkpoint `interrupt_before` (human-in-the-loop, che si
  appoggia sul preview editabile + box quadratura già esistenti in `app.py`).
- Annotare in `.claude/skills/intervento-repo/INTERVENTI.md`.

## File toccati

- **Nuovi**: `ec_converter/validators.py`, `agentic/ec_state.py`, `agentic/ec_graph.py`.
- **Modificati**: `ec_converter/app.py` (`_formatta_quadratura` chiama `verifica_quadratura`),
  `agentic/README.md`, `INTERVENTI.md`.
- `agentic/requirements.txt`: `langgraph` già presente. Per eseguire il grafo serve l'ambiente di
  `ec_converter` (pdf2image, requests, ecc.) + il container `dots-ocr` attivo.

## Out of scope (per tenerlo "il più piccolo")

Niente freccia condizionale, niente nodo `correggi`, niente LLM di correzione, niente nuova UI,
niente eval harness, niente riscrittura dell'OCR o di `process_pdf`. Un solo grafo lineare a 2 nodi.

## Verifica end-to-end

1. Avviare il backend OCR: `cd /mnt/sdb/ai/ai_ocr && docker compose up -d dots-ocr` e attendere
   `http://localhost:8222/health` (start_period ~600s).
2. Mettere almeno un PDF estratto conto reale in `e_c/` (non committato).
3. Dal repo root, nel venv con `pip install -r agentic/requirements.txt`:
   `python -m agentic.ec_graph`
4. **Atteso**: lo stato finale stampato mostra n. movimenti > 0, i saldi estratti (per template
   Intesa), `diff` e l'esito `valida` (✅ se `abs(diff) < 0.01`, ⚠️ altrimenti con l'importo della
   differenza). Su un estratto conto con un importo mal letto dall'OCR, `valida` deve risultare ⚠️
   — è la dimostrazione concreta che il nodo `valida` cattura un errore reale.
5. Regressione UI: `docker compose up -d ec-converter-ui`, processare un PDF e verificare che il box
   quadratura mostri lo stesso ✅/⚠️ di prima (il refactor non cambia l'output visibile).
6. (Facoltativo) Verificare che il grafo fatture esistente continui a funzionare:
   `python -m agentic.graph`.

## Roadmap successiva (dopo questo step minimo)

1. Aggiungere la **freccia condizionale** dopo `valida`: se `quadratura.ok` è False → `correggi`,
   altrimenti → END.
2. Nodo **`correggi`** reale: ri-OCR della pagina sospetta a DPI più alto e/o chiamata a **Qwen via
   LiteLLM** per rileggere l'importo incriminato; loop di retry verso `valida` con **contatore
   tentativi** nello stato.
3. **Checkpoint human-in-the-loop** (`interrupt_before`) dopo N tentativi falliti, appoggiandosi al
   preview editabile + box quadratura già presenti in `app.py`.
4. **Eval harness**: cartella di estratti conto reali con ground-truth (saldi + n. movimenti);
   script che stampa accuratezza per campo e **% documenti che quadrano al primo OCR vs dopo
   correzione** → metrica da README per il portfolio.
