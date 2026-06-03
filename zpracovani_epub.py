import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import warnings

warnings.filterwarnings("ignore")


def nacti_epub_text(cesta_k_souboru):
    try:
        kniha = epub.read_epub(cesta_k_souboru)
        seznam_kapitol = []

        for polozka in kniha.get_items():
            if polozka.get_type() == ebooklib.ITEM_DOCUMENT:
                soup = BeautifulSoup(polozka.get_content(), "html.parser")
                text_kapitoly = soup.get_text(separator="\n")
                seznam_kapitol.append(text_kapitoly)

        return "\n".join(seznam_kapitol)

    except Exception as e:
        return f"Chyba při čtení EPUBu: {e}"


if __name__ == "__main__":
    test_kniha = "epuby/Alliances.epub"
    print(f"Testuji načítání: {test_kniha}")
    vysledek = nacti_epub_text(test_kniha)
    print(vysledek[:500] if not vysledek.startswith("Chyba") else vysledek)
