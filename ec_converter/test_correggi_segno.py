"""
Test rapido per correggi_segno_per_causale.
Eseguire da: /mnt/sdb/ai/ai_ocr/ec_converter/
"""
import sys
sys.path.insert(0, "/mnt/sdb/ai/ai_ocr/ec_converter")

from templates.base import Movimento
from normalizer import correggi_segno_per_causale

# 1. POS (04) con valore in dare → deve finire in avere, corretto=True
pos_dare = Movimento("01.01.2026", None, "Accredito POS al netto", "Accredito POS al netto",
                     dare=1725.57, avere=None, causale="04")

# 2. POS (04) già corretto in avere → nessuno swap
pos_avere = Movimento("01.01.2026", None, "Accredito POS al netto", "Accredito POS al netto",
                      dare=None, avere=1511.42, causale="04")

# 3. Bonifico emesso (27) con valore in avere → deve finire in dare, corretto=True
bon_emesso = Movimento("02.01.2026", None, "Bonifico a favore di Rossi", "Bonifico a favore di Rossi",
                       dare=None, avere=500.00, causale="27")

# 4. Spese bancarie (66) con valore in avere → deve finire in dare, corretto=True
spese = Movimento("03.01.2026", None, "Canone spese", "Canone spese",
                  dare=None, avere=8.70, causale="66")

# 5. Causale None con valore in avere → nessuno swap
nessuna = Movimento("04.01.2026", None, "Movimento generico", "Movimento generico",
                    dare=None, avere=100.00, causale=None)

movimenti = [pos_dare, pos_avere, bon_emesso, spese, nessuna]
count = correggi_segno_per_causale(movimenti)

# Verifica conteggio
assert count == 3, f"Atteso 3 correzioni, ottenuto {count}"

# 1: POS invertito → avere valorizzato, dare=None, corretto=True
assert pos_dare.avere == 1725.57, f"pos_dare.avere atteso 1725.57, got {pos_dare.avere}"
assert pos_dare.dare is None, f"pos_dare.dare atteso None, got {pos_dare.dare}"
assert pos_dare.corretto is True

# 2: POS già corretto → invariato
assert pos_avere.avere == 1511.42
assert pos_avere.dare is None
assert pos_avere.corretto is False

# 3: Bonifico emesso invertito → dare valorizzato, avere=None
assert bon_emesso.dare == 500.00, f"bon_emesso.dare atteso 500.00, got {bon_emesso.dare}"
assert bon_emesso.avere is None
assert bon_emesso.corretto is True

# 4: Spese invertite → dare valorizzato, avere=None
assert spese.dare == 8.70, f"spese.dare atteso 8.70, got {spese.dare}"
assert spese.avere is None
assert spese.corretto is True

# 5: Causale None → invariato
assert nessuna.avere == 100.00
assert nessuna.dare is None
assert nessuna.corretto is False

print("Tutti i 5 assert passati correttamente.")
print(f"  Correzioni applicate: {count}")
print(f"  pos_dare   → avere={pos_dare.avere}, dare={pos_dare.dare}, corretto={pos_dare.corretto}")
print(f"  pos_avere  → avere={pos_avere.avere}, dare={pos_avere.dare}, corretto={pos_avere.corretto}")
print(f"  bon_emesso → dare={bon_emesso.dare}, avere={bon_emesso.avere}, corretto={bon_emesso.corretto}")
print(f"  spese      → dare={spese.dare}, avere={spese.avere}, corretto={spese.corretto}")
print(f"  nessuna    → avere={nessuna.avere}, dare={nessuna.dare}, corretto={nessuna.corretto}")
