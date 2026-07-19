"""Vykreslení stavu čtečky do dvou bitmap — čistě PIL, bez vazby na hardware.

vykresli() vrací dvojici obrázků 528×880 (na výšku, tak jak se čte). Otočení do
hardwarových 880×528 je věcí driveru, ne vykreslování — viz displej.py.

Vstupem je Snimek ze stav.py, ne přímo Ctecka: snímek je zmrazený, takže se
funkce chová deterministicky a nemůže jí stav pod rukama změnit stisk tlačítka.

Obrázky se nenačítají zde. Volající předá nacti_obrazek — funkci, která z cesty
v archivu udělá PIL.Image. Díky tomu tenhle modul nezná EPUB ani souborový
systém a jde testovat s libovolnou atrapou.
"""

import logging
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

import zpracovani_textu
from stav import Stav

FONT_CESTA = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# Rozměry plátna na výšku. Zbytek se z nich odvozuje, aby se rozjet nemohly.
SIRKA = 528
VYSKA = 880
OKRAJ = 20

LISTA_Y = VYSKA - 40  # 840 — vodorovná linka nad stavovou lištou
TEXT_SIRKA = SIRKA - 2 * OKRAJ  # 488 — šířka, pro kterou se láme text
TEXT_VYSKA = LISTA_Y - OKRAJ  # 820 — výška, do které se vejde text

_ZAHLAVI_Y = 75
_MENU_Y0 = 110
_ROZTEC_MENU = 55
_MAX_ZNAKU_NAZVU = 25

# Kolik knih se vejde mezi záhlaví a stavovou lištu (vychází 13).
POLOZEK_NA_STRANKU = (LISTA_Y - _MENU_Y0) // _ROZTEC_MENU


@dataclass(frozen=True)
class Fonty:
    text: ImageFont.FreeTypeFont
    info: ImageFont.FreeTypeFont
    titulek: ImageFont.FreeTypeFont


def nacti_fonty(cesta=FONT_CESTA):
    try:
        return Fonty(
            text=ImageFont.truetype(cesta, 32),
            info=ImageFont.truetype(cesta, 20),
            titulek=ImageFont.truetype(cesta, 40),
        )
    except OSError:
        logging.warning("Font %s nenalezen, používám vestavěný.", cesta)
        vychozi = ImageFont.load_default()
        return Fonty(text=vychozi, info=vychozi, titulek=vychozi)


def vykresli(stav, fonty, nacti_obrazek=None):
    """Vrátí (černá, červená) — dvě bitmapy 528×880, neotočené.

    nacti_obrazek: callable(cesta_v_archivu) -> PIL.Image | None. Bez něj se
    místo obrázku vykreslí zástupka; text funguje i tak.
    """
    cerna = Image.new("1", (SIRKA, VYSKA), 255)
    cervena = Image.new("1", (SIRKA, VYSKA), 255)

    if stav.stav is Stav.CTENI:
        # Při čtení jde na panel jen text knihy. Číslo stránky ukazuje OLED,
        # takže by tu lišta jen ubírala místo a nutila k překreslení i tehdy,
        # když se změnilo jen pořadové číslo.
        _vykresli_cteni(cerna, ImageDraw.Draw(cerna), stav, fonty, nacti_obrazek)
    else:
        _vykresli_menu(ImageDraw.Draw(cerna), stav, fonty)
        _vykresli_listu(ImageDraw.Draw(cervena), fonty, _text_listy(stav))

    return cerna, cervena


def _prvni_v_okne(stav):
    """Index první zobrazené knihy.

    Roluje se po celých stránkách, ne o položku: e-ink se překresluje sekundy,
    takže je lepší, když se seznam při každém posunu nehne a přeskočí až na
    hranici stránky.
    """
    return (stav.vyber // POLOZEK_NA_STRANKU) * POLOZEK_NA_STRANKU


def _text_listy(stav):
    if stav.nacita_se:
        return "Načítám…"
    if stav.chyba:
        return stav.chyba

    celkem = len(stav.seznam_knih)
    if celkem > POLOZEK_NA_STRANKU:
        prvni = _prvni_v_okne(stav)
        posledni = min(prvni + POLOZEK_NA_STRANKU, celkem)
        return f"Knihy {prvni + 1}–{posledni} z {celkem}"
    return f"Počet knih: {celkem}"


def _vykresli_menu(kresli, stav, fonty):
    kresli.text((OKRAJ, OKRAJ), "KNIHOVNA", font=fonty.titulek, fill=0)
    kresli.line((OKRAJ, _ZAHLAVI_Y, SIRKA - OKRAJ, _ZAHLAVI_Y), fill=0, width=3)

    if not stav.seznam_knih:
        kresli.text(
            (OKRAJ, _MENU_Y0), "Složka 'epuby' je prázdná.", font=fonty.text, fill=0
        )
        return

    prvni = _prvni_v_okne(stav)
    okno = stav.seznam_knih[prvni : prvni + POLOZEK_NA_STRANKU]

    y = _MENU_Y0
    for posun, kniha in enumerate(okno):
        if prvni + posun == stav.vyber:
            kresli.rectangle((OKRAJ, y - 2, SIRKA - OKRAJ, y + 42), fill=0)
            kresli.text((35, y), _nazev_knihy(kniha), font=fonty.text, fill=255)
        else:
            kresli.text((35, y), _nazev_knihy(kniha), font=fonty.text, fill=0)

        y += _ROZTEC_MENU


def _nazev_knihy(soubor):
    nazev = soubor[:-5] if soubor.endswith(".epub") else soubor
    if len(nazev) < _MAX_ZNAKU_NAZVU:
        return nazev
    return nazev[: _MAX_ZNAKU_NAZVU - 3] + "..."


def _vykresli_cteni(cerna, kresli, stav, fonty, nacti_obrazek):
    stranka = stav.stranka
    if stranka is None:
        kresli.text(
            (OKRAJ, OKRAJ), "Chyba při načítání obsahu knihy.", font=fonty.text, fill=0
        )
        return

    if stranka["typ"] == "obrazek":
        _vykresli_obrazek(cerna, kresli, stranka["obsah"], fonty, nacti_obrazek)
        return

    # Rozestup si bere zpracovani_textu, protože podle něj byla stránka
    # rozvržená. Zadrátovaná konstanta by text zase nahustila.
    rozestup = zpracovani_textu.vyska_radku(fonty.text)
    y = _horni_okraj_textu(fonty, rozestup)
    for radek in stranka["obsah"]:
        kresli.text((OKRAJ, y), radek, font=fonty.text, fill=0)
        y += rozestup


def _horni_okraj_textu(fonty, rozestup):
    """Odsazení shora, aby text vyšel svisle na střed panelu.

    Po zrušení stavové lišty zbylo dole volné místo. Počítá se z **plné**
    stránky, ne z počtu řádků na té aktuální: jinak by poslední, poloprázdná
    stránka kapitoly plavala uprostřed panelu a text by mezi stránkami
    poskakoval.

    Rozšířit rovnou TEXT_VYSKA nemá smysl — 820 i 840 px pojme při rozestupu
    43 px stejných 19 řádků, takže by to jen zneplatnilo cache stránkování.
    """
    radku = TEXT_VYSKA // rozestup
    # Poslední řádek nezabírá celý rozestup, jen výšku písma bez mezery.
    vyska_bloku = (radku - 1) * rozestup + zpracovani_textu.vyska_radku(fonty.text, 0)
    volno = (VYSKA - 2 * OKRAJ) - vyska_bloku
    return OKRAJ + max(0, volno) // 2


def _vykresli_obrazek(cerna, kresli, cesta_v_archivu, fonty, nacti_obrazek):
    obrazek = nacti_obrazek(cesta_v_archivu) if nacti_obrazek else None
    if obrazek is None:
        kresli.text((OKRAJ, OKRAJ), "[obrázek nelze zobrazit]", font=fonty.text, fill=0)
        return

    # Na střed celého panelu, ne jen textové oblasti: při čtení už dole žádná
    # lišta není, takže by se obrázek jinak držel zbytečně vysoko.
    x = (SIRKA - obrazek.width) // 2
    y = (VYSKA - obrazek.height) // 2
    cerna.paste(obrazek, (max(0, x), max(0, y)))


def _vykresli_listu(kresli, fonty, text, x=OKRAJ):
    kresli.line((OKRAJ, LISTA_Y, SIRKA - OKRAJ, LISTA_Y), fill=0, width=2)
    kresli.text((x, VYSKA - 35), text, font=fonty.info, fill=0)
