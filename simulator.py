import os
import io
import json
from flask import Flask, send_file, request
from PIL import Image, ImageDraw, ImageFont

# Import tvých vlastních modulů
import zpracovani_epub
import zpracovani_textu

app = Flask(__name__)

# --- GLOBÁLNÍ PROMĚNNÉ ---
PROGRESS_FILE = "progress.json"
aktualni_kniha = "epuby/Alliances.epub"
aktualni_stranka = 0
kniha_stranky = []

# Cesta k fontu - uprav si podle svého OS, ideálně měj font uloženy přímo ve složce
FONT_PATH = "DejaVuSans.ttf"


# --- POMOCNÉ FUNKCE (převzato z tvého kódu) ---
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
cisty_text = zpracovani_epub.nacti_epub_text(aktualni_kniha)

try:
    font_text = ImageFont.truetype(FONT_PATH, 32)
    font_info = ImageFont.truetype(FONT_PATH, 20)
except IOError:
    print(
        f"POZOR: Font {FONT_PATH} nenalezen! Používám výchozí font (rozložení se může lišit)."
    )
    font_text = ImageFont.load_default()
    font_info = ImageFont.load_default()

radky = zpracovani_textu.zformatuj_pro_displej(cisty_text, font_text, 840)
kniha_stranky = zpracovani_textu.rozdel_na_stranky(radky, font_text, 468)

aktualni_stranka = nacti_pozici(aktualni_kniha)
if aktualni_stranka >= len(kniha_stranky):
    aktualni_stranka = max(0, len(kniha_stranky) - 1)


# --- FLASK WEBOVÝ SERVER ---


@app.route("/")
def index():
    # Jednoduché HTML rozhraní s obrazovkou a tlačítky
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
        <h2>Simulátor: 7.5" HD Waveshare (880x528)</h2>
        <img src="/screen" class="screen" width="880" height="528" id="display" alt="E-ink displej">
        
        <div class="controls">
            <button onclick="stisk_tlacitka('predchozi')">⬅ Předchozí (Pin 26)</button>
            <button onclick="stisk_tlacitka('akce')">Menu / Akce (Pin 19)</button>
            <button onclick="stisk_tlacitka('dalsi')">Další ➡ (Pin 21)</button>
        </div>

        <script>
            function stisk_tlacitka(akce) {
                // Pošle požadavek na server
                fetch('/api/stisk/' + akce, { method: 'POST' })
                .then(response => {
                    if(response.ok) {
                        // Trik: přidání časového razítka přinutí prohlížeč ignorovat cache a načíst nový obrázek
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
    """Vykreslí aktuální stránku do obrázku a pošle ji do prohlížeče."""
    # V simulátoru kreslíme rovnou RGB (nečleníme na černý a červený buffer)
    img = Image.new("RGB", (880, 528), "white")
    draw = ImageDraw.Draw(img)

    stranka = kniha_stranky[aktualni_stranka]

    # Vykreslení textu knihy (černě)
    y_pozice = 20
    for radek in stranka:
        draw.text((20, y_pozice), radek, font=font_text, fill=(0, 0, 0))
        y_pozice += 37

    # Spodní stavová lišta (červeně)
    draw.line((20, 528 - 40, 880 - 20, 528 - 40), fill=(220, 0, 0), width=2)
    info_text = f"Strana {aktualni_stranka + 1} / {len(kniha_stranky)}"
    draw.text((880 - 250, 528 - 35), info_text, font=font_info, fill=(220, 0, 0))

    # Uložení do paměti a odeslání
    img_io = io.BytesIO()
    img.save(img_io, "PNG")
    img_io.seek(0)
    return send_file(img_io, mimetype="image/png")


@app.route("/api/stisk/<tlacitko>", methods=["POST"])
def stisk(tlacitko):
    """Logika tlačítek."""
    global aktualni_stranka

    if tlacitko == "dalsi" and aktualni_stranka < len(kniha_stranky) - 1:
        aktualni_stranka += 1
        uloz_pozici(aktualni_kniha, aktualni_stranka)
    elif tlacitko == "predchozi" and aktualni_stranka > 0:
        aktualni_stranka -= 1
        uloz_pozici(aktualni_kniha, aktualni_stranka)
    elif tlacitko == "akce":
        print("Stisknuto tlačítko Menu/Akce - zde bude tvoje logika")

    return "OK", 200


if __name__ == "__main__":
    # Spustí server na portu 5000
    print("Spouštím simulátor na http://127.0.0.1:5000")
    app.run(debug=True, host="0.0.0.0", port=5000)
