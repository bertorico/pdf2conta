"""
Validatori fiscali — logica di dominio pura, senza LangGraph.

Queste funzioni non sanno nulla di grafi o stati: ricevono un oggetto Fattura e
restituiscono una lista di problemi. Tenerle separate dal grafo rende semplice
testarle e riusarle in contesti diversi.
"""

from fatture_converter.fattura import Fattura


def controlla_coerenza_iva(fattura: Fattura) -> list[str]:
    """Controlla che l'IVA dichiarata sia coerente con imponibile e aliquota.

    Per ogni riga della tabella aliquote verifica:
        iva_attesa = round(netto * aliquota / 100, 2)

    Se la differenza supera 0.02 €, segnala l'incongruenza.
    Aliquota 0 (esente): l'IVA attesa è 0, qualsiasi valore positivo è un errore.

    Args:
        fattura: oggetto Fattura già estratto dal PDF.

    Returns:
        Lista di stringhe leggibili (una per aliquota in errore).
        Lista vuota = tutto coerente.
    """
    errori = []

    for a in fattura.aliquote:
        # Calcolo IVA teorica in base ad aliquota e imponibile
        iva_attesa = round(a.netto * a.aliquota / 100, 2)

        # Tolleranza di 2 centesimi per arrotondamenti nei PDF
        if abs(a.iva - iva_attesa) > 0.02:
            errori.append(
                f"aliquota {a.aliquota}%: IVA dichiarata {a.iva:.2f} "
                f"ma attesa {iva_attesa:.2f} (imponibile {a.netto:.2f})"
            )

    return errori
