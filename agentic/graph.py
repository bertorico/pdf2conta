"""
Grafo LangGraph a 2 nodi per l'estrazione e validazione di fatture PDF.

LangGraph fa esattamente 3 cose in questo modulo:
  1. Definisce la "scatola" (lo stato) tramite il TypedDict FatturaState.
  2. Registra le funzioni Python come nodi con add_node().
  3. Decide l'ordine di esecuzione con add_edge().

Le funzioni dentro i nodi (estrai, valida) sono Python normale: nessuna classe
speciale, nessun decoratore magico. LangGraph le chiama passando lo stato corrente
e fonde (merge) il dict che restituiscono nella scatola condivisa.

Flusso:
    estrai → valida → ┬─ (se errori)  → correggi → END
                      └─ (se tutto ok) ──────────→ END

La scelta del ramo è fatta da una FRECCIA CONDIZIONALE (add_conditional_edges):
una funzione di instradamento legge la scatola e restituisce il nome del prossimo
nodo. È la prima cosa che un semplice script in fila non sa fare.
"""

import os
import sys
from glob import glob

from langgraph.graph import StateGraph, END

from fatture_converter.process_fatture import extract_text
from fatture_converter.fattura import parse_fattura
from agentic.state import FatturaState
from agentic.validators import controlla_coerenza_iva

# CF cedente: default documentato nel repo (Azienda Esempio SRL).
# Può essere sovrascritto con la variabile d'ambiente CF_CEDENTE.
CF_CEDENTE = os.environ.get("CF_CEDENTE", "00000000000")


# ---------------------------------------------------------------------------
# Nodi del grafo
# Ogni nodo riceve l'intera scatola (state) e restituisce SOLO i campi che
# aggiorna. LangGraph si occupa di fondere il dict restituito nello stato globale.
# ---------------------------------------------------------------------------

def estrai(state: FatturaState) -> dict:
    """Nodo 1 — estrazione.

    Legge il PDF indicato in state["pdf_path"], estrae il testo con pdftotext
    e ne fa il parsing in una dataclass Fattura.
    """
    testo = extract_text(state["pdf_path"])
    fattura = parse_fattura(testo, CF_CEDENTE)
    # Restituisce solo i campi che questo nodo popola; LangGraph li fonde nella scatola.
    return {"testo": testo, "fattura": fattura}


def valida(state: FatturaState) -> dict:
    """Nodo 2 — validazione fiscale.

    Controlla la coerenza IVA della fattura già estratta e imposta il flag valida.
    """
    errori = controlla_coerenza_iva(state["fattura"])
    # Restituisce solo i campi di sua competenza.
    return {"errori": errori, "valida": not errori}


def correggi(state: FatturaState) -> dict:
    """Nodo 3 — gestione delle fatture con errori.

    PER ORA è un segnaposto: non corregge nulla, marca soltanto la fattura come
    "da revisionare" (human-in-the-loop manuale). Il passo successivo sostituirà
    questo corpo con una chiamata all'LLM (Qwen via vLLM/LiteLLM) che prova a
    ri-estrarre i campi sbagliati, con un loop di retry verso "valida".
    """
    return {"da_revisionare": True}


# ---------------------------------------------------------------------------
# Funzione di instradamento (la "freccia condizionale")
# Non è un nodo: non modifica la scatola. Legge lo stato e restituisce il NOME
# del prossimo nodo verso cui andare. LangGraph la usa in add_conditional_edges.
# ---------------------------------------------------------------------------

def instrada(state: FatturaState) -> str:
    """Dopo 'valida', decide il ramo: 'correggi' se ci sono errori, altrimenti 'fine'."""
    if state["errori"]:
        return "correggi"
    return "fine"


# ---------------------------------------------------------------------------
# Costruzione e compilazione del grafo
# ---------------------------------------------------------------------------

def costruisci_grafo():
    """Assembla il grafo LangGraph e lo compila in un'applicazione invocabile."""
    g = StateGraph(FatturaState)

    # Registra le funzioni come nodi (nome → funzione)
    g.add_node("estrai", estrai)
    g.add_node("valida", valida)
    g.add_node("correggi", correggi)

    # Punto di ingresso: il grafo parte sempre da "estrai"
    g.set_entry_point("estrai")

    # Edge sequenziale: estrai → valida
    g.add_edge("estrai", "valida")

    # FRECCIA CONDIZIONALE: dopo "valida", instrada() sceglie il ramo.
    # Il dict mappa il valore restituito da instrada() → nodo di destinazione.
    g.add_conditional_edges(
        "valida",
        instrada,
        {"correggi": "correggi", "fine": END},
    )

    # Dopo aver marcato la fattura, il ramo "correggi" termina anch'esso.
    g.add_edge("correggi", END)

    return g.compile()


# Grafo compilato a livello di modulo: importabile da altri script.
app = costruisci_grafo()


# ---------------------------------------------------------------------------
# Entry point: python -m agentic.graph
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Cerca un PDF di esempio nelle cartelle standard del repo.
    # Prima scelta: fatture già processate; seconda: fatture in attesa.
    pdf_files = sorted(glob("fatture_converter/e_fatture/processate/*.pdf"))
    if not pdf_files:
        pdf_files = sorted(glob("fatture_converter/e_fatture/*.pdf"))

    if not pdf_files:
        print(
            "Nessun PDF trovato in fatture_converter/e_fatture/ "
            "né in fatture_converter/e_fatture/processate/.\n"
            "Aggiungi almeno un file PDF fattura e riprova."
        )
        sys.exit(1)

    pdf = pdf_files[0]
    print(f"PDF selezionato: {pdf}\n")

    # Invoca il grafo con lo stato iniziale (solo pdf_path è obbligatorio).
    # LangGraph esegue estrai → valida e restituisce lo stato finale completo.
    stato_finale = app.invoke({"pdf_path": pdf})

    # --- Stampa risultati in formato leggibile ---
    f = stato_finale["fattura"]

    print(f"{'='*55}")
    print(f"FATTURA — {pdf}")
    print(f"{'='*55}")
    print(f"  Tipo documento  : {f.tipo_documento}")
    print(f"  Numero          : {f.numero_documento}")
    print(f"  Data            : {f.data_documento}")
    print(f"  Cessionario     : {f.cognome_cessionario} {f.nome_cessionario}")
    print()
    print("  Aliquote IVA:")
    for a in f.aliquote:
        print(f"    aliquota {a.aliquota:>2}%  netto {a.netto:.2f}  IVA {a.iva:.2f}")
    print()

    # Esito validazione
    valida_flag = "✅ valida" if stato_finale["valida"] else "❌ non valida"
    print(f"  Esito fiscale   : {valida_flag}")

    errori = stato_finale.get("errori", [])
    if errori:
        print("  Errori:")
        for e in errori:
            print(f"    - {e}")
    else:
        print("  Errori          : nessuno")

    # Ramo scelto dalla freccia condizionale
    if stato_finale.get("da_revisionare"):
        print("  Ramo            : valida → correggi (marcata DA REVISIONARE)")
    else:
        print("  Ramo            : valida → fine (nessuna correzione necessaria)")

    print()
    # Questo è lo stato LangGraph completo in uscita dal grafo (tutti i campi della scatola).
    print(f"[stato LangGraph completo] chiavi presenti: {list(stato_finale.keys())}")
