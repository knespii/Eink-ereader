"""Čtení obsahu EPUBu.

Výstupem nacti_epub_obsah() je seznam položek v pořadí čtení:

    {"typ": "text",    "hodnota": "text odstavce"}
    {"typ": "obrazek", "hodnota": "OEBPS/Images/cover.jpeg"}

Obrázky se záměrně nedekódují — do výstupu jde jen jejich cesta v archivu.
Držet dekódované PIL.Image celé knihy naráz se na 512 MB Pi Zero W nevyplatí,
takže si je volající načte až těsně před vykreslením přes nacti_obrazek().
"""

import io
import posixpath
import warnings
import zipfile
from urllib.parse import unquote
from xml.etree import ElementTree

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub
from PIL import Image

warnings.filterwarnings('ignore')

# Blokové tagy, ze kterých se bere text. Text se odebírá jen z těch, které už
# žádný další blokový tag neobsahují — jinak by se u struktury <div><p>…</p></div>
# tentýž odstavec vydal dvakrát, jednou slepený z divu a jednou z <p>.
BLOKOVE_TAGY = ['p', 'div']


def nacti_epub_obsah(cesta_k_souboru):
    try:
        kniha = epub.read_epub(cesta_k_souboru)

        with zipfile.ZipFile(cesta_k_souboru) as archiv:
            koren = _koren_opf(archiv)
            v_archivu = set(archiv.namelist())

        obsah = []
        # Pořadí čtení určuje spine, ne manifest. get_items() vrací položky tak,
        # jak jsou zapsané v manifestu, což u řady knih není pořadí kapitol.
        for idref, _linear in kniha.spine:
            polozka = kniha.get_item_with_id(idref)
            if polozka is None or polozka.get_type() != ebooklib.ITEM_DOCUMENT:
                continue

            cesta_dokumentu = posixpath.join(koren, polozka.file_name)
            soup = BeautifulSoup(polozka.get_content(), 'html.parser')
            _projdi_dokument(soup, cesta_dokumentu, v_archivu, obsah)

        return obsah
    except Exception as e:
        print(f"Chyba při čtení EPUBu: {e}")
        return []


def nacti_obrazek(cesta_k_souboru, cesta_v_archivu, max_sirka, max_vyska):
    """Načte, zmenší a převede jeden obrázek do e-ink formátu.

    Volá se až těsně před vykreslením, aby v paměti byl vždy nejvýš jeden
    dekódovaný obrázek. Vrací None, pokud obrázek nejde načíst.
    """
    try:
        with zipfile.ZipFile(cesta_k_souboru) as archiv:
            data = archiv.read(cesta_v_archivu)

        with Image.open(io.BytesIO(data)) as img:
            img.thumbnail((max_sirka, max_vyska))
            return img.convert('1')
    except Exception as e:
        print(f"Chyba při načítání obrázku {cesta_v_archivu}: {e}")
        return None


def _koren_opf(archiv):
    """Adresář, vůči kterému jsou relativní cesty uvnitř EPUBu.

    Ve zpracovávaných knihách bývá "OEBPS", ale spoléhat se na to nelze —
    závaznou informaci nese META-INF/container.xml.
    """
    try:
        strom = ElementTree.fromstring(archiv.read('META-INF/container.xml'))
        for prvek in strom.iter():
            if prvek.tag.endswith('rootfile') and prvek.get('full-path'):
                return posixpath.dirname(prvek.get('full-path'))
    except (KeyError, ElementTree.ParseError) as e:
        print(f"Nepodařilo se najít kořen EPUBu, zkouším bez něj: {e}")
    return ''


def _projdi_dokument(soup, cesta_dokumentu, v_archivu, obsah):
    """Vybere z jednoho dokumentu text a obrázky v pořadí, v jakém stojí."""
    for prvek in soup.find_all(BLOKOVE_TAGY + ['img']):
        if prvek.name == 'img':
            cesta = _cesta_obrazku(prvek.get('src'), cesta_dokumentu, v_archivu)
            if cesta:
                obsah.append({"typ": "obrazek", "hodnota": cesta})

        elif not prvek.find(BLOKOVE_TAGY):
            # get_text(strip=True) ostříhá i mezery mezi vnořenými tagy, takže
            # z <em>„Admiral."</em> Krennicův hlas udělá jedno slovo. Tohle
            # mezery mezi tagy zachová a jen slije násobné do jedné — a přitom
            # nerozsekne slovo, které je tagem rozdělené uprostřed.
            text = " ".join(prvek.get_text().split())
            if text:
                obsah.append({"typ": "text", "hodnota": text})


def _cesta_obrazku(src, cesta_dokumentu, v_archivu):
    """Přeloží src z <img> na cestu v archivu; src je relativní k dokumentu."""
    if not src:
        return None

    src = unquote(src.split('#')[0])
    cesta = posixpath.normpath(
        posixpath.join(posixpath.dirname(cesta_dokumentu), src)
    )
    if cesta in v_archivu:
        return cesta

    print(f"Obrázek {src!r} odkazovaný z {cesta_dokumentu} v archivu není.")
    return None
