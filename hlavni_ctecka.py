import sys
import os
import time
import logging
import json
from PIL import Image, ImageDraw, ImageFont
from gpiozero import Button

PROGRESS_FILE = "progress.json"

def nacti_pozici(kniha_id):
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
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
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            pass
    
    data[kniha_id] = stranka
    try:
        with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Chyba při ukládání pozice: {e}")

# Správné nasměrování na ovladače e-inku
current_dir = os.path.dirname(os.path.realpath(__file__))
waveshare_dir = os.path.join(current_dir, 'waveshare_epd')
if os.path.exists(waveshare_dir):
    sys.path.append(waveshare_dir)

try:
    from waveshare_epd import epd7in5b_HD
except ImportError as e:
    print(f"Chyba Waveshare ovladače: {e}")
    sys.exit(1)

# Import našich modulů
import zpracovani_epub  # noqa: E402
import zpracovani_textu  # noqa: E402

logging.basicConfig(level=logging.INFO)

PIN_DALSI = 21
PIN_PREDCHOZI = 26
PIN_AKCE = 19

aktualni_kniha = "test.epub"
aktualni_stranka = 0
kniha_stranky = []
prekreslit_displej = True
konec_programu = False

def stisk_dalsi():
    global aktualni_stranka, prekreslit_displej, aktualni_kniha
    if aktualni_stranka < len(kniha_stranky) - 1:
        aktualni_stranka += 1
        prekreslit_displej = True
        uloz_pozici(aktualni_kniha, aktualni_stranka)

def stisk_predchozi():
    global aktualni_stranka, prekreslit_displej, aktualni_kniha
    if aktualni_stranka > 0:
        aktualni_stranka -= 1
        prekreslit_displej = True
        uloz_pozici(aktualni_kniha, aktualni_stranka)

def stisk_akce_dlouhy():
    global konec_programu
    konec_programu = True

def main():
    global kniha_stranky, aktualni_stranka, prekreslit_displej, konec_programu, aktualni_kniha

    logging.info(f"Načítám a formátuji knihu {aktualni_kniha}...")
    cisty_text = zpracovani_epub.nacti_epub_text(aktualni_kniha)
    
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font_text = ImageFont.truetype(font_path, 32)
    font_info = ImageFont.truetype(font_path, 20)
    
    # Formátování pro displej 880x528 (s okraji)
    radky = zpracovani_textu.zformatuj_pro_displej(cisty_text, font_text, 840)
    kniha_stranky = zpracovani_textu.rozdel_na_stranky(radky, font_text, 468)
    
    aktualni_stranka = nacti_pozici(aktualni_kniha)
    if aktualni_stranka >= len(kniha_stranky):
        aktualni_stranka = max(0, len(kniha_stranky) - 1)
    
    # Inicializace hardwaru
    epd = epd7in5b_HD.EPD()
    epd.init()
    
    btn_dalsi = Button(PIN_DALSI, bounce_time=0.1)
    btn_predchozi = Button(PIN_PREDCHOZI, bounce_time=0.1)
    btn_akce = Button(PIN_AKCE, bounce_time=0.1, hold_time=2.0)

    btn_dalsi.when_pressed = stisk_dalsi
    btn_predchozi.when_pressed = stisk_predchozi
    btn_akce.when_held = stisk_akce_dlouhy

    try:
        while not konec_programu:
            if prekreslit_displej:
                logging.info(f"Kreslím stranu {aktualni_stranka + 1} / {len(kniha_stranky)}")
                
                image_black = Image.new('1', (epd.width, epd.height), 255)
                image_red   = Image.new('1', (epd.width, epd.height), 255)
                draw_black  = ImageDraw.Draw(image_black)
                draw_red    = ImageDraw.Draw(image_red)

                stranka = kniha_stranky[aktualni_stranka]
                
                y_pozice = 20
                for radek in stranka:
                    draw_black.text((20, y_pozice), radek, font=font_text, fill=0)
                    y_pozice += 37 

                # Spodní stavová lišta (červená)
                draw_red.line((20, epd.height - 40, epd.width - 20, epd.height - 40), fill=0, width=2)
                info_text = f"Strana {aktualni_stranka + 1} / {len(kniha_stranky)}"
                draw_red.text((epd.width - 250, epd.height - 35), info_text, font=font_info, fill=0)

                epd.display(epd.getbuffer(image_black), epd.getbuffer(image_red))
                epd.sleep()
                
                prekreslit_displej = False

            time.sleep(0.1)

    except KeyboardInterrupt:
        pass
    finally:
        logging.info("Vypínám modul displeje...")
        epd7in5b_HD.epdconfig.module_exit()

if __name__ == '__main__':
    main()