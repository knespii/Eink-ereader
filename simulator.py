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
aktualni_kniha = "epuby/Alliances.epub"  # Tvoje cesta ke knize
aktualni_stranka = 0
kniha_stranky = []

FONT_PATH = "DejaVuSans.ttf"


# --- POMOCNÉ FUNKCE ---
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


# --- INICIALIZACE KNIHY ---
print(f"Načítám knihu: {aktualni_kniha}...")

try:
    font_text = ImageFont.truetype(FONT_PATH, 32)
    font_info = ImageFont.truetype(FONT_PATH, 20)
except IOError:
    print(f"POZOR: Font {FONT_PATH} nenalezen! Používám výchozí.")
    font_text = ImageFont.load_default()
    font_info = ImageFont.load_default()

# NA VÝŠKU: Displej má 528 na šířku a 880 na výšku.
# Předáváme modulům nové maximální rozměry pro formátování (s odečtením okrajů).
# Obrázky zmenšíme max na šířku 488 (528 - okraje) a výšku 820.
obsah_knihy = zpracovani_epub.nacti_epub_obsah(
    aktualni_kniha, max_sirka=488, max_vyska=820
)

# Text zalamujeme na šířku 488 a výšku 820 (aby zbylo 60 pixelů dole na stavovou lištu).
kniha_stranky = zpracovani_textu.zformatuj_a_rozdel(obsah_knihy, font_text, 488, 820)

aktualni_stranka = nacti_pozici(aktualni_kniha)
if aktualni_stranka >= len(kniha_stranky):
    aktualni_stranka = max(0, len(kniha_stranky) - 1)


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
        <h2>Simulátor: 7.5" HD Waveshare (Na výšku - 528x880)</h2>
        <img src="/screen" class="screen" width="528" height="880" id="display" alt="E-ink displej">
        
        <div class="controls">
            <button onclick="stisk_tlacitka('predchozi')">⬅ Předchozí</button>
            <button onclick="stisk_tlacitka('akce')">Menu / Akce</button>
            <button onclick="stisk_tlacitka('dalsi')">Další ➡</button>
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
    # NA VÝŠKU: Vytváříme plátno 528x880
    img = Image.new("RGB", (528, 880), "white")
    draw = ImageDraw.Draw(img)

    if not kniha_stranky:
        draw.text(
            (20, 20),
            "Kniha je prázdná nebo se ji nepodařilo načíst.",
            font=font_text,
            fill=(0, 0, 0),
        )
    else:
        stranka = kniha_stranky[aktualni_stranka]

        if stranka["typ"] == "obrazek":
            img_obrazek = stranka["obsah"].convert("RGB")
            # Centrování obrázku na novém rozměru
            x = (528 - img_obrazek.width) // 2
            y = (820 - img_obrazek.height) // 2
            img.paste(img_obrazek, (x, y))

        elif stranka["typ"] == "text":
            y_pozice = 20
            for radek in stranka["obsah"]:
                draw.text((20, y_pozice), radek, font=font_text, fill=(0, 0, 0))
                y_pozice += 37

        # Spodní stavová lišta
        # Červená čára nyní končí na souřadnici X=508 (šířka 528 - 20)
        # Y pozice je 840 (výška 880 - 40)
        draw.line((20, 880 - 40, 528 - 20, 880 - 40), fill=(220, 0, 0), width=2)
        info_text = f"Strana {aktualni_stranka + 1} / {len(kniha_stranky)}"

        # Text lišty (zarovnáno doprava: 528 - 200 = 328)
        draw.text((528 - 200, 880 - 35), info_text, font=font_info, fill=(220, 0, 0))

    img_io = io.BytesIO()
    img.save(img_io, "PNG")
    img_io.seek(0)
    return send_file(img_io, mimetype="image/png")


@app.route("/api/stisk/<tlacitko>", methods=["POST"])
def stisk(tlacitko):
    global aktualni_stranka

    if kniha_stranky:
        if tlacitko == "dalsi" and aktualni_stranka < len(kniha_stranky) - 1:
            aktualni_stranka += 1
            uloz_pozici(aktualni_kniha, aktualni_stranka)
        elif tlacitko == "predchozi" and aktualni_stranka > 0:
            aktualni_stranka -= 1
            uloz_pozici(aktualni_kniha, aktualni_stranka)
        elif tlacitko == "akce":
            print("Stisknuto tlačítko Menu/Akce")

    return "OK", 200


if __name__ == "__main__":
    print("Spouštím simulátor na http://127.0.0.1:5000")
    app.run(debug=True, host="0.0.0.0", port=5000)
