# Kontext projektu: DIY E-ink Čtečka Knih

Ahoj Gemini, pracuji na projektu vlastní čtečky knih postavené na **Raspberry Pi Zero W** a **7.5" HD E-ink displeji od Waveshare** (rozlišení 880x528 pixelů). Čtečka je ovládaná pomocí **3 fyzických tlačítek** připojených na GPIO piny 16, 20 a 21.

Projekt je napsaný v Pythonu 3 a je rozdělený do tří hlavních modulů. Potřebuji, abys pochopil současnou strukturu a pomohl mi s dalším vývojem.

---

## Současná struktura projektu

### 1. Modul: `zpracovani_epub.py`
Tento soubor se stará o otevření e-knihy ve formátu `.epub`, vytažení textu z jednotlivých kapitol a očištění od HTML značek pomocí BeautifulSoup.

```python
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import warnings

warnings.filterwarnings('ignore')

def nacti_epub_text(cesta_k_souboru):
    try:
        kniha = epub.read_epub(cesta_k_souboru)
        seznam_kapitol = []
        for polozka in kniha.get_items():
            if polozka.get_type() == ebooklib.ITEM_DOCUMENT:
                soup = BeautifulSoup(polozka.get_content(), 'html.parser')
                text_kapitoly = soup.get_text(separator='\n')
                seznam_kapitol.append(text_kapitoly)
        return "\n".join(seznam_kapitol)
    except Exception as e:
        return f"Chyba při čtení EPUBu: {e}"