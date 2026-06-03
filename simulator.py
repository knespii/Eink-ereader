import os
import io
import json
from flask import Flask, send_file
from PIL import Image, ImageDraw, ImageFont

# Import tvých vlastních modulů
import zpracovani_epub
import zpracovani_textu

app = Flask(__name__)


# --- GLOBÁLNÍ PROMĚNNÉ ---
PROGRESS_FILE = "progress.json"
FONT_PATH = "DejaVuSans.ttf"

# Stavy aplikace: "MENU" nebo "CTENI"
aktualni_stav = "MENU"

# Proměnné pro MENU
slozka_knih = "epuby"
seznam_knih = []
vybrana_kniha_index = 0

# Proměnné pro CTENI
aktualni_kniha = ""
aktualni_stranka = 0
kniha_stranky = []

# Inicializace fontů
try:
    font_text = ImageFont.truetype(FONT_PATH, 32)
    font_info = ImageFont.truetype(FONT_PATH, 20)
    font_menu_titulek = ImageFont.truetype(FONT_PATH, 40)
except IOError:
    font_text = ImageFont.load_default()
    font_info = ImageFont.load_default()
    font_menu_titulek = ImageFont.load_default()


# --- POMOCNÉ FUNKCE ---
def nacti_seznam_knih():
    """Načte všechny .epub soubory ze složky."""
    global seznam_knih
    if not os.path.exists(slozka_knih):
        os.makedirs(slozka_knih)

    # Vyfiltruje pouze soubory s příponou .epub
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
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def otevri_knihu(nazev_souboru):
    """Inicializuje vybranou knihu pro čtení."""
    global aktualni_kniha, aktualni_stranka, kniha_stranky, aktualni_stav

    aktualni_kniha = os.path.join(slozka_knih, nazev_souboru)
    print(f"Načítám knihu: {aktualni_kniha}...")

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


# Načteme knihy hned při startu serveru
nacti_seznam_knih()


# --- FLASK WEBOVÝ SERVER ---


@app.route("/")
def index():
    html = """
    <!DOCTYPE html>
    <html lang="cs">
    <head>
        <meta charset="UTF-8">
        <title>Simulátor E-ink Čtečky</title>
        <style>
            body { text-align: center; font-family: sans-serif; background: #222; color: #eee; margin-top: 30px; }
            .screen { 
                border: 12px solid #111; 
                border-radius: 8px; 
                box-shadow: 0 10px 25px rgba(0,0,0,0.5); 
                background: white;
            }
            .controls { margin-top: 20px; }
            button { 
                font-size: 18px; padding: 12px 24px; margin: 0 10px; 
                cursor: pointer; border: none; border-radius: 5px; 
                background: #555; color: white;
            }
            button:hover { background: #777; }
        </style>
    </head>
    <body>
        <h2>Simulátor: 7.5" HD Waveshare (Menu + Čtení na výšku)</h2>
        <img src="/screen" class="screen" width="528" height="880" id="display" alt="E-ink displej">
        
        <div class="controls">
            <button onclick="stisk_tlacitka('predchozi')">⬅ Nahoru / Předchozí</button>
            <button onclick="stisk_tlacitka('akce')">Potvrdit / Menu</button>
            <button onclick="stisk_tlacitka('dalsi')">Dolů / Další ➡</button>
        </div>

        <script>
            function stisk_tlacitka(akce) {
                fetch('/api/stisk/' + akce, { method: 'POST' })
                .then(response => {
                    if(response.ok) {
                        document.getElementById('display').src = '/screen?t=' + new Date().getTime();
                    }
                });
            }
        </script>
    </body>
    </html>
    """
    return html


@app.route("/screen")
def generate_screen():
    img = Image.new("RGB", (528, 880), "white")
    draw = ImageDraw.Draw(img)

    # RENDEROVÁNÍ PODLE TOHO, V JAKÉM STAVU SE NACHÁZÍME
    if aktualni_stav == "MENU":
        # Vykreslení záhlaví knihovny
        draw.text((20, 20), "KNIHOVNA", font=font_menu_titulek, fill=(0, 0, 0))
        draw.line((20, 75, 508, 75), fill=(0, 0, 0), width=3)

        if not seznam_knih:
            draw.text(
                (20, 100), "Složka 'epuby' je prázdná.", font=font_text, fill=(0, 0, 0)
            )
        else:
            y_pozice = 110
            for i, kniha in enumerate(seznam_knih):
                # Zkrátíme název souboru, pokud by byl moc dlouhý na displej
                zobrazovany_nazev = kniha if len(kniha) < 25 else kniha[:22] + "..."

                if i == vybrana_kniha_index:
                    # Zvýraznění vybrané knihy (E-ink styl: inverzní obdélník)
                    draw.rectangle(
                        (20, y_pozice - 2, 508, y_pozice + 42), fill=(0, 0, 0)
                    )
                    draw.text(
                        (35, y_pozice),
                        zobrazovany_nazev,
                        font=font_text,
                        fill=(255, 255, 255),
                    )
                else:
                    draw.text(
                        (35, y_pozice),
                        zobrazovany_nazev,
                        font=font_text,
                        fill=(0, 0, 0),
                    )

                y_pozice += 55

        # Spodní stavová lišta pro menu
        draw.line((20, 880 - 40, 528 - 20, 880 - 40), fill=(220, 0, 0), width=2)
        draw.text(
            (20, 880 - 35),
            f"Počet knih: {len(seznam_knih)}",
            font=font_info,
            fill=(220, 0, 0),
        )

    elif aktualni_stav == "CTENI":
        if not kniha_stranky:
            draw.text(
                (20, 20),
                "Chyba při načítání obsahu knihy.",
                font=font_text,
                fill=(0, 0, 0),
            )
        else:
            stranka = kniha_stranky[aktualni_stranka]

            if stranka["typ"] == "obrazek":
                img_obrazek = stranka["obsah"].convert("RGB")
                x = (528 - img_obrazek.width) // 2
                y = (820 - img_obrazek.height) // 2
                img.paste(img_obrazek, (x, y))

            elif stranka["typ"] == "text":
                y_pozice = 20
                for radek in stranka["obsah"]:
                    draw.text((20, y_pozice), radek, font=font_text, fill=(0, 0, 0))
                    y_pozice += 37

        # Spodní stavová lišta pro čtení
        draw.line((20, 880 - 40, 528 - 20, 880 - 40), fill=(220, 0, 0), width=2)
        info_text = f"Strana {aktualni_stranka + 1} / {len(kniha_stranky)}"
        draw.text((528 - 200, 880 - 35), info_text, font=font_info, fill=(220, 0, 0))

    img_io = io.BytesIO()
    img.save(img_io, "PNG")
    img_io.seek(0)
    return send_file(img_io, mimetype="image/png")


@app.route("/api/stisk/<tlacitko>", methods=["POST"])
def stisk(tlacitko):
    global aktualni_stranka, vybrana_kniha_index, aktualni_stav

    # 1. LOGIKA TLAČÍTEK V MENU
    if aktualni_stav == "MENU":
        if seznam_knih:
            if tlacitko == "dalsi" and vybrana_kniha_index < len(seznam_knih) - 1:
                vybrana_kniha_index += 1
            elif tlacitko == "predchozi" and vybrana_kniha_index > 0:
                vybrana_kniha_index -= 1
            elif tlacitko == "akce":
                otevri_knihu(seznam_knih[vybrana_kniha_index])

    # 2. LOGIKA TLAČÍTEK PŘI ČTENÍ
    elif aktualni_stav == "CTENI":
        if tlacitko == "dalsi" and aktualni_stranka < len(kniha_stranky) - 1:
            aktualni_stranka += 1
            uloz_pozici(aktualni_kniha, aktualni_stranka)
        elif tlacitko == "predchozi" and aktualni_stranka > 0:
            aktualni_stranka -= 1
            uloz_pozici(aktualni_kniha, aktualni_stranka)
        elif tlacitko == "akce":
            # Návrat zpět do menu, nejdříve ale aktualizujeme seznam souborů
            nacti_seznam_knih()
            aktualni_stav = "MENU"

    return "OK", 200


if __name__ == "__main__":
    print("Spouštím simulátor na http://127.0.0.1:5000")
    app.run(debug=True, host="0.0.0.0", port=5000)
