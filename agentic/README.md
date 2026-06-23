# agentic — grafo LangGraph con freccia condizionale

## Cos'è

Un piccolo grafo LangGraph che orchestra l'estrazione e la validazione di fatture PDF riusando il package `fatture_converter` già presente nel repo. Tre nodi, nessuna ridondanza: `estrai` chiama `pdftotext` + `parse_fattura`, `valida` controlla la coerenza IVA, `correggi` gestisce le fatture con errori (per ora le marca "da revisionare").

```
estrai → valida → ┬─ (se errori)  → correggi → END
                  └─ (se tutto ok) ──────────→ END
```

Il ramo è scelto da una **freccia condizionale** (`add_conditional_edges`): la funzione `instrada` legge la scatola e restituisce il nome del prossimo nodo.

## Perché

Chiudere il gap "orchestrazione agentica con LangGraph" nel portfolio, con un esempio concreto e minimale su codice di produzione reale.

## Come si esegue

Dal repo root (`/mnt/sdb/ai/ai_ocr`):

```bash
# 1. Creare e attivare un venv
python -m venv .venv
source .venv/bin/activate

# 2. Installare le dipendenze
pip install -r agentic/requirements.txt

# 3. Eseguire il grafo (CF_CEDENTE opzionale, default 00000000000)
CF_CEDENTE=00000000000 python -m agentic.graph
```

Il grafo cerca automaticamente un PDF in `fatture_converter/e_fatture/processate/` o in `fatture_converter/e_fatture/`.

## Prossimi passi

→ Sostituire il corpo segnaposto di `correggi` con una chiamata all'LLM (Qwen via vLLM/LiteLLM) che prova a ri-estrarre i campi sbagliati, con un **loop di retry** verso `valida` (con un contatore di tentativi nello stato).
→ Dopo N tentativi falliti, introdurre un **checkpoint human-in-the-loop** con `interrupt_before` per fermare il grafo e attendere conferma manuale.
