import sys
import os
import time
import logging
import json
import pickle  # <-- Přidáno pro bleskové cachování paměti
from PIL import Image, ImageDraw, ImageFont
from gpiozero import Button

PROGRESS_FILE = "progress.json"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
CACHE_DIR = "cache"  # Složka pro zmrazené knihy

# Vytvoření složek, pokud chybí
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

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
probiha_vykreslovani = False  # <-- Zámek proti vícenásobnému stisku

# Globální instance pro fonty
font_text = None
font_info = None
font_menu_titulek = None


# --- POMOCNÉ FUNKCE PRO UKLÁDÁNÍ A DATA ---
def nacti_seznam_knih():
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
        except Exception:
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
    """Inicializuje knihu - využívá Pickle cache pro bleskové načtení."""
    global aktualni_kniha, aktualni_stranka, kniha_stranky, aktualni_stav, prekreslit_displej

    aktualni_kniha = os.path.join(slozka_knih, nazev_souboru)
    cache_soubor = os.path.join(CACHE_DIR, nazev_souboru + ".pkl")

    if os.path.exists(cache_soubor):
        logging.info(f"Bleskové načítání z cache: {nazev_souboru}")
        with open(cache_soubor, 'rb') as f:
            kniha_stranky = pickle.load(f)
    else:
        logging.info(f"První parsování knihy {nazev_souboru} (tohle chvíli potrvá)...")
        obsah_knihy = zpracovani_epub.nacti_epub_obsah(
            aktualni_kniha, max_sirka=488, max_vyska=820
        )
        kniha_stranky = zpracovani_textu.zformatuj_a_rozdel(
            obsah_knihy, font_text, 488, 820
        )
        
        logging.info("Ukládám zformátovanou knihu do cache pro příště...")
        with open(cache_soubor, 'wb') as f:
            pickle.dump(kniha_stranky, f)

    aktualni_stranka = nacti_pozici(aktualni_kniha)
    if aktualni_stranka >= len(kniha_stranky):
        aktualni_stranka = max(0, len(kniha_stranky) - 1)

    aktualni_stav = "CTENI"
    prekreslit_displej = True


# --- OVLÁDÁNÍ HARDWAROVÝCH TLAČÍTEK ---
def stisk_dalsi():
    global aktualni_stranka, vybrana_kniha_index, prekreslit_displej
    if probiha_vykreslovani: return  # Ignoruj stisk, pokud kreslí
    
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
    if probiha_vykreslovani: return
    
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
    if probiha_vykreslovani: return
    
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
    global kniha_stranky, aktualni_stranka, prekreslit_displej
    global konec_programu, aktualni_kniha, probiha_vykreslovani
    global font_text, font_info, font_menu_titulek

    try:
        font_text = ImageFont.truetype(FONT_PATH, 32)
        font_info = ImageFont.truetype(FONT_PATH, 20)
        font_menu_titulek = ImageFont.truetype(FONT_PATH, 40)
    except IOError:
        logging.warning("Systémový font nenalezen, používám defaultní.")
        font_text = ImageFont.load_default()
        font_info = ImageFont.load_default()
        font_menu_titulek = ImageFont.load_default()

    nacti_seznam_knih()

    epd = epd7in5b_HD.EPD()
    epd.init()

    # Zvýšili jsme bounce_time pro odstranění šumu (dvojitých stisků)
    btn_dalsi = Button(PIN_DALSI, bounce_time=0.2)
    btn_predchozi = Button(PIN_PREDCHOZI, bounce_time=0.2)
    btn_akce = Button(PIN_AKCE, bounce_time=0.2, hold_time=2.0)

    btn_dalsi.when_pressed = stisk_dalsi
    btn_predchozi.when_pressed = stisk_predchozi
    btn_akce.when_pressed = stisk_akce
    btn_akce.when_held = stisk_akce_dlouhy

    try:
        while not konec_programu:
            if prekreslit_displej:
                probiha_vykreslovani = True  # Zamkneme tlačítka
                prekreslit_displej = False
                
                image_black = Image.new("1", (528, 880), 255)
                image_red = Image.new("1", (528, 880), 255)
                draw_black = ImageDraw.Draw(image_black)
                draw_red = ImageDraw.Draw(image_red)

                if aktualni_stav == "MENU":
                    logging.info("Vykresluji knihovnu...")
                    draw_black.text((20, 20), "KNIHOVNA", font=font_menu_titulek, fill=0)
                    draw_black.line((20, 75, 508, 75), fill=0, width=3)

                    if not seznam_knih:
                        draw_black.text((20, 100), "Složka 'epuby' je prázdná.", font=font_text, fill=0)
                    else:
                        y_pozice = 110
                        for i, kniha in enumerate(seznam_knih):
                            nazev_bez_pripony = kniha[:-5]
                            zobrazovany_nazev = nazev_bez_pripony if len(nazev_bez_pripony) < 25 else nazev_bez_pripony[:22] + "..."

                            if i == vybrana_kniha_index:
                                draw_black.rectangle((20, y_pozice - 2, 508, y_pozice + 42), fill=0)
                                draw_black.text((35, y_pozice), zobrazovany_nazev, font=font_text, fill=255)
                            else:
                                draw_black.text((35, y_pozice), zobrazovany_nazev, font=font_text, fill=0)
                            y_pozice += 55

                    draw_red.line((20, 880 - 40, 528 - 20, 880 - 40), fill=0, width=2)
                    draw_red.text((20, 880 - 35), f"Počet knih: {len(seznam_knih)}", font=font_info, fill=0)

                elif aktualni_stav == "CTENI" and kniha_stranky:
                    logging.info(f"Vykresluji text e-knihy, strana {aktualni_stranka + 1}")
                    stranka = kniha_stranky[aktualni_stranka]

                    if stranka["typ"] == "obrazek":
                        x = (528 - stranka["obsah"].width) // 2
                        y = (820 - stranka["obsah"].height) // 2
                        image_black.paste(stranka["obsah"], (x, y))

                    elif stranka["typ"] == "text":
                        y_pozice = 20
                        for radek in stranka["obsah"]:
                            draw_black.text((20, y_pozice), radek, font=font_text, fill=0)
                            y_pozice += 37

                    draw_red.line((20, 880 - 40, 528 - 20, 880 - 40), fill=0, width=2)
                    info_text = f"Strana {aktualni_stranka + 1} / {len(kniha_stranky)}"
                    draw_red.text((528 - 200, 880 - 35), info_text, font=font_info, fill=0)

                image_black_rotated = image_black.rotate(90, expand=True)
                image_red_rotated = image_red.rotate(90, expand=True)

                epd.init()
                epd.display(
                    epd.getbuffer(image_black_rotated),
                    epd.getbuffer(image_red_rotated),
                )
                epd.sleep()
                
                probiha_vykreslovani = False  # Odemkneme tlačítka
            time.sleep(0.1)

    except KeyboardInterrupt:
        pass
    finally:
        logging.info("Ukončování čtečky...")
        epd7in5b_HD.epdconfig.module_exit()


if __name__ == "__main__":
    main()