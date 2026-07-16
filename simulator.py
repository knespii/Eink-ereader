"""Webový simulátor čtečky.

Nesimuluje čtečku, ale opravdu ji spouští: drží tutéž třídu Ctecka a kreslí
touž funkcí vykresli() jako produkční hlavni_ctecka.py. Jediné, co je jiné, je
vstup (HTTP místo GPIO) a výstup (PNG místo e-inku). Proto to, co je vidět v
prohlížeči, sedí na pixel s tím, co poletí na displej.

Dřív si simulátor kreslil vlastním kódem do RGB, a tak se s produkcí rozešel —
zobrazoval názvy knih s příponou, měl jinou cestu k fontu a neznal dlouhý
stisk. Testoval tedy hlavně sám sebe.

Skládání dvou vrstev do barevného náhledu je jediná věc navíc: e-ink dostane
dvě jednobitové bitmapy, obrazovka potřebuje RGB.
"""

import io

from flask import Flask, send_file
from PIL import Image, ImageChops

import knihovna
import vykresleni
from stav import Ctecka

app = Flask(__name__)

# Jediný zdroj pravdy, přesně jako na Pi. Ctecka je thread-safe, takže na ni
# smí souběžně sáhnout víc obsluh Flasku najednou.
fonty = vykresleni.nacti_fonty()
ctecka = Ctecka(knihovna.nacti_seznam_knih())

BARVA_INKOUSTU = (0, 0, 0)
BARVA_CERVENE = (220, 0, 0)

TLACITKA = {
    "dalsi": ctecka.dalsi,
    "predchozi": ctecka.predchozi,
    "akce": ctecka.akce,
}


def slozeny_nahled():
    """Vykreslí aktuální stav a složí obě vrstvy do RGB, jak by je viděl člověk."""
    snimek = ctecka.snimek()
    cerna, cervena = vykresleni.vykresli(
        snimek, fonty, knihovna.nacti_obrazek_knihy(snimek.kniha)
    )

    # Ve vrstvách je 0 inkoust a 255 papír, maska pro paste to má opačně.
    nahled = Image.new("RGB", cerna.size, "white")
    nahled.paste(BARVA_INKOUSTU, (0, 0), ImageChops.invert(cerna.convert("L")))
    nahled.paste(BARVA_CERVENE, (0, 0), ImageChops.invert(cervena.convert("L")))
    return nahled


@app.route("/")
def index():
    return f"""
    <!DOCTYPE html>
    <html lang="cs">
    <head>
        <meta charset="UTF-8">
        <title>Simulátor E-ink Čtečky</title>
        <style>
            body {{ text-align: center; font-family: sans-serif; background: #222; color: #eee; margin-top: 30px; }}
            .screen {{
                border: 12px solid #111;
                border-radius: 8px;
                box-shadow: 0 10px 25px rgba(0,0,0,0.5);
                background: white;
            }}
            .controls {{ margin-top: 20px; }}
            button {{
                font-size: 18px; padding: 12px 24px; margin: 0 10px;
                cursor: pointer; border: none; border-radius: 5px;
                background: #555; color: white;
            }}
            button:hover {{ background: #777; }}
        </style>
    </head>
    <body>
        <h2>Simulátor: 7.5" HD Waveshare (Menu + Čtení na výšku)</h2>
        <img src="/screen" class="screen" width="{vykresleni.SIRKA}" height="{vykresleni.VYSKA}"
             id="display" alt="E-ink displej">

        <div class="controls">
            <button onclick="stisk_tlacitka('predchozi')">⬅ Nahoru / Předchozí</button>
            <button onclick="stisk_tlacitka('akce')">Potvrdit / Menu</button>
            <button onclick="stisk_tlacitka('dalsi')">Dolů / Další ➡</button>
        </div>

        <script>
            function stisk_tlacitka(akce) {{
                fetch('/api/stisk/' + akce, {{ method: 'POST' }})
                .then(response => {{
                    if (response.ok) {{
                        document.getElementById('display').src = '/screen?t=' + new Date().getTime();
                    }}
                }});
            }}
        </script>
    </body>
    </html>
    """


@app.route("/screen")
def generate_screen():
    data = io.BytesIO()
    slozeny_nahled().save(data, "PNG")
    data.seek(0)
    return send_file(data, mimetype="image/png")


@app.route("/api/stisk/<tlacitko>", methods=["POST"])
def stisk(tlacitko):
    stisknout = TLACITKA.get(tlacitko)
    if stisknout is None:
        return "Neznámé tlačítko", 404

    # Přesně jako callback na Pi: jen sáhne na stav, nic nenačítá.
    stisknout()

    # A tohle je to, co na Pi udělá hlavní smyčka — načte knihu, uloží pozici.
    knihovna.obsluz(ctecka, fonty)

    # Nové knihy ve složce se tím ukážou samy.
    ctecka.nastav_seznam_knih(knihovna.nacti_seznam_knih())
    return "OK", 200


if __name__ == "__main__":
    # Poslouchá jen na localhostu a bez debuggeru: dřív tu bylo
    # debug=True + host="0.0.0.0", což je Werkzeug konzole otevřená komukoliv
    # na síti, tedy vzdálené spuštění kódu. Pro přístup z jiného počítače
    # změň host, ale debug nech vypnutý.
    print("Spouštím simulátor na http://127.0.0.1:5000")
    app.run(debug=False, host="127.0.0.1", port=5000)
