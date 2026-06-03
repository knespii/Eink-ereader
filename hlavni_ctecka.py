import sys
import os
import time
import logging
import json
from PIL import Image, ImageDraw, ImageFont
from gpiozero import Button

PROGRESS_FILE = "progress.json"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# --- GLOBÁLNÍ PROMĚNNÉ PRO STAV ČTEČKY ---
aktualni_stav = "MENU"
slozka_knih = "epuby"
seznam_knih = []
vybrana_kniha_index = 0

aktualni_kniha = ""
aktualni_stranka = 0
kniha_stranky = []

prekreslit_displej = True
konec_programu = False

# Globální instance pro fonty
font_text = None
font_info = None
font_menu_titulek = None


# --- POMOCNÉ FUNKCE PRO UKLÁDÁNÍ A DATA ---
def nacti_seznam_knih():
    """Načte všechny .epub soubory ze složky."""
    global seznam_knih
    if not os.path.exists(slozka_knih):
        os.makedirs(slozka_knih)
    seznam_knih = [f for f in os.listdir(slozka_knih) if f.endswith(".epub")]
    seznam_knih.sort()


def nacti_pozici(kniha_id):
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get(kniha_id, 0)
        except Exception as e:
            logging.error(f"Chyba při načítání pozice: {e}")
            return 0
    return 0


def uloz_pozici(kniha_id, stranka):
    data = {}
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    data[kniha_id] = stranka
    try:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Chyba při ukládání pozice: {e}")


def otevri_knihu(nazev_souboru):
    """Inicializuje vybranou knihu a přepne do stavu čtení."""
    global \
        aktualni_kniha, \
        aktualni_stranka, \
        kniha_stranky, \
        aktualni_stav, \
        prekreslit_displej

    aktualni_kniha = os.path.join(slozka_knih, nazev_souboru)
    logging.info(f"Načítám knihu: {aktualni_kniha}...")

    obsah_knihy = zpracovani_epub.nacti_epub_obsah(
        aktualni_kniha, max_sirka=488, max_vyska=820
    )
    kniha_stranky = zpracovani_textu.zformatuj_a_rozdel(
        obsah_knihy, font_text, 488, 820
    )

    aktualni_stranka = nacti_pozici(aktualni_kniha)
    if aktualni_stranka >= len(kniha_stranky):
        aktualni_stranka = max(0, len(kniha_stranky) - 1)

    aktualni_stav = "CTENI"
    prekreslit_displej = True


# --- OVLÁDÁNÍ HARDWAROVÝCH TLAČÍTEK ---
def stisk_dalsi():
    global aktualni_stranka, vybrana_kniha_index, prekreslit_displej
    if aktualni_stav == "MENU":
        if seznam_knih and vybrana_kniha_index < len(seznam_knih) - 1:
            vybrana_kniha_index += 1
            prekreslit_displej = True
    elif aktualni_stav == "CTENI":
        if aktualni_stranka < len(kniha_stranky) - 1:
            aktualni_stranka += 1
            prekreslit_displej = True
            uloz_pozici(aktualni_kniha, aktualni_stranka)


def stisk_predchozi():
    global aktualni_stranka, vybrana_kniha_index, prekreslit_displej
    if aktualni_stav == "MENU":
        if vybrana_kniha_index > 0:
            vybrana_kniha_index -= 1
            prekreslit_displej = True
    elif aktualni_stav == "CTENI":
        if aktualni_stranka > 0:
            aktualni_stranka -= 1
            prekreslit_displej = True
            uloz_pozici(aktualni_kniha, aktualni_stranka)


def stisk_akce():
    global aktualni_stav, prekreslit_displej
    if aktualni_stav == "MENU":
        if seznam_knih:
            otevri_knihu(seznam_knih[vybrana_kniha_index])
    elif aktualni_stav == "CTENI":
        nacti_seznam_knih()
        aktualni_stav = "MENU"
        prekreslit_displej = True


def stisk_akce_dlouhy():
    global konec_programu
    konec_programu = True


# --- NASTAVENÍ CESTY K OVLADAČI DISPLEJE ---
current_dir = os.path.dirname(os.path.realpath(__file__))
waveshare_dir = os.path.join(current_dir, "waveshare_epd")
if os.path.exists(waveshare_dir):
    sys.path.append(waveshare_dir)

try:
    from waveshare_epd import epd7in5b_HD
except ImportError as e:
    print(f"Chyba Waveshare ovladače: {e}")
    sys.exit(1)

import zpracovani_epub  # noqa: E402
import zpracovani_textu  # noqa: E402

logging.basicConfig(level=logging.INFO)

# Konfigurace pinů
PIN_DALSI = 21
PIN_PREDCHOZI = 26
PIN_AKCE = 19


def main():
    global \
        kniha_stranky, \
        aktualni_stranka, \
        prekreslit_displej, \
        konec_programu, \
        aktualni_kniha
    global font_text, font_info, font_menu_titulek

    # Inicializace písem
    try:
        font_text = ImageFont.truetype(FONT_PATH, 32)
        font_info = ImageFont.truetype(FONT_PATH, 20)
        font_menu_titulek = ImageFont.truetype(FONT_PATH, 40)
    except IOError:
        logging.warning("Systémový font nenalezen, používám defaultní.")
        font_text = ImageFont.load_default()
        font_info = ImageFont.load_default()
        font_menu_titulek = ImageFont.load_default()

    # Načtení knihovny na začátku
    nacti_seznam_knih()

    # Inicializace displeje
    epd = epd7in5b_HD.EPD()
    epd.init
