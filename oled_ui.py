"""Vykreslení menu na malý I2C OLED 128×32 — čistě PIL, bez vazby na hardware.

Menu se z e-inku stěhuje sem, protože tříbarevný panel potřebuje na každé
překreslení plnou budicí křivku (~10 s) a listování knihovnou je tím
nepoužitelné. OLED se překreslí okamžitě, takže smí reagovat přímo na cvaknutí
kodéru. E-ink zůstává na to, na co je dobrý: na stránku textu.

Na 32 pixelech výšky se vejde jeden řádek, takže UI je carousel — na displeji
je vždy jen aktuálně vybraná položka: ikona (FontAwesome) + název + pořadí.
Vícestránkové menu jako na e-inku by tu nedávalo smysl.

vykresli_oled() vrací PIL.Image mode "1" o rozměru 128×32 a nic nezobrazuje.
Předání do železa dělá zobraz() nad zařízením z luma.oled — díky tomu jde
celý modul testovat bez Pi a bez sběrnice I2C.

Vstupem je Snimek ze stav.py, ne přímo Ctecka: snímek je zmrazený, takže se
vykreslení chová deterministicky a nemůže mu stav pod rukama změnit kodér.
"""

import logging
import os
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from stav import Stav, Typ

# --- ROZMĚRY ---

SIRKA = 128
VYSKA = 32
OKRAJ = 2

_STRED_Y = VYSKA // 2
_IKONA_X = OKRAJ
_IKONA_SIRKA = 16  # sloupec pro ikonu; text začíná až za ním
_TEXT_X = _IKONA_X + _IKONA_SIRKA + 4
_MEZERA_TICKERU = 16  # prodleva mezi koncem a novým začátkem u dlouhého názvu

# --- FONTY ---

FONT_TEXT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# FontAwesome není na PyPI ani v Raspberry Pi OS jistota. Bere se první cesta,
# která existuje — vendorovaná kopie v repozitáři má přednost, aby čtečka
# nezávisela na tom, co je zrovna doinstalované v systému.
#
# Cesta k vendorované kopii se odvozuje od __file__, ne od pracovního
# adresáře: čtečka běží ze systemd, kde je CWD kořen a font by se nenašel.
_KOREN = os.path.dirname(os.path.realpath(__file__))

FONT_IKON_CESTY = (
    os.path.join(_KOREN, "fonts", "FontAwesome.ttf"),
    "/usr/share/fonts/truetype/font-awesome/fontawesome-webfont.ttf",
    "/usr/share/fonts/opentype/font-awesome/FontAwesome.otf",
)

VELIKOST_TEXTU = 12
VELIKOST_IKONY = 13
VELIKOST_DROBNE = 9

# Kódy z privátní oblasti FontAwesome 4. Zapsané escapem schválně: přímý znak
# je v editoru neviditelný a při kopírování souboru se snadno tiše ztratí.
# Když font chybí, vykreslí se náhradní ASCII (_IKONY_NAHRADNI) a menu zůstane
# čitelné i bez ikon.
IKONA_SLOZKA = ""  # fa-folder
IKONA_KNIHA = ""  # fa-book — i pro otevřenou knihu; fa-book-reader
IKONA_ZPET = ""  # fa-arrow-left     je až z FA5 a ve FA4 by byl prázdný
IKONA_NACITANI = ""  # fa-refresh
IKONA_CHYBA = ""  # fa-exclamation-triangle
IKONA_PRAZDNO = ""  # fa-ban

_IKONY_NAHRADNI = {
    IKONA_SLOZKA: "[]",
    IKONA_KNIHA: "*",
    IKONA_ZPET: "<-",
    IKONA_NACITANI: "~",
    IKONA_CHYBA: "!",
    IKONA_PRAZDNO: "-",
}

_IKONY_POLOZEK = {
    Typ.SLOZKA: IKONA_SLOZKA,
    Typ.KNIHA: IKONA_KNIHA,
    Typ.ZPET: IKONA_ZPET,
}


@dataclass(frozen=True)
class FontyOled:
    """Fonty pro OLED. `ikony_jsou` říká, jestli se FontAwesome opravdu našel."""

    text: ImageFont.ImageFont
    ikony: ImageFont.ImageFont
    drobne: ImageFont.ImageFont
    ikony_jsou: bool


def nacti_fonty(cesta_textu=FONT_TEXT, cesty_ikon=FONT_IKON_CESTY):
    """Načte fonty pro OLED. Chybějící font čtečku nepoloží, jen zošklivý menu."""
    try:
        text = ImageFont.truetype(cesta_textu, VELIKOST_TEXTU)
        drobne = ImageFont.truetype(cesta_textu, VELIKOST_DROBNE)
    except OSError:
        logging.warning("Font %s nenalezen, používám vestavěný.", cesta_textu)
        text = drobne = ImageFont.load_default()

    ikony, ikony_jsou = text, False
    for cesta in cesty_ikon:
        try:
            ikony = ImageFont.truetype(cesta, VELIKOST_IKONY)
            ikony_jsou = True
            break
        except OSError:
            continue
    if not ikony_jsou:
        logging.warning("FontAwesome nenalezen, ikony nahrazuji textem.")

    return FontyOled(text=text, ikony=ikony, drobne=drobne, ikony_jsou=ikony_jsou)


# --- VYKRESLENÍ ---


def vykresli_oled(snimek, fonty=None, faze=0):
    """Vrátí obraz 128×32 (mode "1") pro aktuální stav.

    `faze` posouvá dlouhý název doleva, aby se dal přečíst celý. Volající ji
    zvyšuje v čase; při 0 je vidět začátek názvu. Krátké názvy posun ignorují,
    aby menu neposkakovalo.

    Fonty se dají předat zvenčí — načítání TTF trvá a hlavní smyčka je má
    načtené jen jednou.
    """
    if fonty is None:
        fonty = nacti_fonty()

    obraz = Image.new("1", (SIRKA, VYSKA), 0)

    if snimek.chyba:
        _radek(obraz, fonty, IKONA_CHYBA, snimek.chyba, "", faze)
    elif snimek.nacita_se:
        _radek(obraz, fonty, IKONA_NACITANI, "Načítám…", "", faze)
    elif snimek.stav is Stav.CTENI:
        _radek(
            obraz,
            fonty,
            IKONA_KNIHA,
            _bez_pripony(snimek.kniha_nazev or ""),
            f"{snimek.cislo_stranky}/{snimek.pocet_stranek}",
            faze,
        )
    else:
        _menu(obraz, fonty, snimek, faze)

    return obraz


def vykresli_hlaseni(text, fonty=None):
    """Prázdný displej s jedním vodorovně i svisle vycentrovaným řádkem.

    Určeno pro hlášky, které se musí objevit okamžitě a nezávisle na stavu —
    typicky „Načítám…" těsně před parsováním EPUBu, které na Pi Zero W trvá
    ~16 s. Bez toho by displej celou tu dobu ukazoval starý obsah a čtečka
    působila zaseknutě.
    """
    if fonty is None:
        fonty = nacti_fonty()

    obraz = Image.new("1", (SIRKA, VYSKA), 0)
    kresli = ImageDraw.Draw(obraz)
    x = max(OKRAJ, (SIRKA - _sirka(kresli, text, fonty.text)) // 2)
    _text_vlevo(kresli, text, fonty.text, x, _STRED_Y)
    return obraz


def _menu(obraz, fonty, snimek, faze):
    polozky = snimek.polozky
    if not polozky:
        # Nastane jen v prázdném kořeni: uvnitř složky je vždy aspoň "..",
        # takže tam se uživatel neocitne bez cesty ven.
        _radek(obraz, fonty, IKONA_PRAZDNO, "Žádné knihy", "", faze)
        return

    index = max(0, min(snimek.vyber, len(polozky) - 1))
    polozka = polozky[index]

    if polozka.typ is Typ.ZPET:
        # U ".." je jméno nadřazené složky užitečnější než dvě tečky.
        nazev = f"..  {snimek.adresar}" if snimek.adresar else ".."
    elif polozka.typ is Typ.KNIHA:
        nazev = _bez_pripony(polozka.nazev)
    else:
        nazev = polozka.nazev

    # Pořadí bez ".." — uživatele zajímá kolikátá kniha, ne kolikátý řádek.
    posun = 1 if polozky[0].typ is Typ.ZPET else 0
    if polozka.typ is Typ.ZPET:
        pocitadlo = ""
    else:
        pocitadlo = f"{index + 1 - posun}/{len(polozky) - posun}"

    _radek(obraz, fonty, _IKONY_POLOZEK.get(polozka.typ, IKONA_KNIHA), nazev, pocitadlo, faze)


def _radek(obraz, fonty, ikona, nazev, pocitadlo, faze):
    """Jeden řádek: ikona vlevo, název uprostřed, počítadlo vpravo."""
    kresli = ImageDraw.Draw(obraz)
    if not fonty.ikony_jsou:
        ikona = _IKONY_NAHRADNI.get(ikona, "*")
    _text_vlevo(kresli, ikona, fonty.ikony, _IKONA_X, _STRED_Y)

    konec_textu = SIRKA - OKRAJ
    if pocitadlo:
        sirka_pocitadla = _sirka(kresli, pocitadlo, fonty.drobne)
        _text_vlevo(
            kresli, pocitadlo, fonty.drobne, SIRKA - OKRAJ - sirka_pocitadla, _STRED_Y
        )
        konec_textu -= sirka_pocitadla + 4

    _text_ticker(obraz, nazev, fonty.text, _TEXT_X, konec_textu - _TEXT_X, _STRED_Y, faze)


def _text_ticker(obraz, text, font, x, sirka_pruhu, y_stred, faze):
    """Text svisle vystředěný v pruhu. Nevejde-li se, posouvá se podle `faze`.

    Dlouhý název se kreslí do vlastního pruhu a ten se teprve vloží zpět —
    jinak by přetekl přes počítadlo vpravo.
    """
    kresli = ImageDraw.Draw(obraz)
    if sirka_pruhu <= 0 or not text:
        return

    sirka_textu = _sirka(kresli, text, font)
    if sirka_textu <= sirka_pruhu:
        _text_vlevo(kresli, text, font, x, y_stred)
        return

    perioda = sirka_textu + _MEZERA_TICKERU
    odsazeni = faze % perioda

    pruh = Image.new("1", (sirka_pruhu, VYSKA), 0)
    kresli_pruh = ImageDraw.Draw(pruh)
    # Dvakrát za sebou, aby při přetočení najel začátek plynule za konec.
    for opakovani in (0, 1):
        _text_vlevo(kresli_pruh, text, font, opakovani * perioda - odsazeni, y_stred)
    obraz.paste(pruh, (x, 0))


def _text_vlevo(kresli, text, font, x, y_stred):
    """Vykreslí text od `x`, svisle vystředěný na `y_stred`.

    Střed se počítá z ohraničení konkrétního textu, ne z anchoru: vestavěný
    font z fallbacku anchory neumí a ikony FontAwesome mají jiné metriky
    než DejaVu, takže by se na jednom řádku rozešly.
    """
    levy, horni, _, dolni = kresli.textbbox((0, 0), text, font=font)
    # 255 = svítí. Pozadí je 0, tedy zhasnuté pixely — OLED se na rozdíl od
    # papírového e-inku kreslí bílá na černé.
    kresli.text((x - levy, y_stred - (horni + dolni) // 2), text, font=font, fill=255)


def _sirka(kresli, text, font):
    levy, _, pravy, _ = kresli.textbbox((0, 0), text, font=font)
    return pravy - levy


def _bez_pripony(nazev):
    """Z "Duna.epub" udělá "Duna" — na 128 px se počítá každý pixel."""
    return nazev[:-5] if nazev.lower().endswith(".epub") else nazev


# --- HARDWARE (luma.oled) ---


class _DummyOled:
    """Náhrada, když OLED není. Čtečka tak jede i bez něj (e-ink stačí)."""

    def display(self, obraz):
        logging.debug("OLED není, zahazuji obraz %s.", obraz.size)

    def show(self):
        pass

    def hide(self):
        pass

    def cleanup(self):
        pass


def vytvor_oled(port=1, adresa=0x3C):
    """Vrátí zařízení z luma.oled, nebo atrapu, když knihovna či panel chybí.

    luma.oled se importuje až tady, ne na začátku modulu: bez toho by se
    vykreslování nedalo spustit ani otestovat na desktopu, kde I2C není.
    Stejný postup jako u waveshare_epd v displej.py.
    """
    try:
        from luma.core.interface.serial import i2c
        from luma.oled.device import ssd1306

        return ssd1306(i2c(port=port, address=adresa), width=SIRKA, height=VYSKA)
    except Exception as e:  # chybí knihovna, sběrnice i2c, nebo panel neodpovídá
        logging.warning("OLED není dostupný (%s), pokračuji bez něj.", e)
        return _DummyOled()


def zobraz(zarizeni, snimek, fonty=None, faze=0):
    """Vykreslí snímek a pošle ho na OLED. Vrací poslaný obraz."""
    obraz = vykresli_oled(snimek, fonty, faze)
    zarizeni.display(obraz)
    return obraz
