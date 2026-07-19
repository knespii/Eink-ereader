"""Webový simulátor čtečky.

Nesimuluje čtečku, ale opravdu ji spouští: drží tutéž třídu Ctecka a kreslí
touž funkcí vykresli() jako produkční hlavni_ctecka.py. Jediné, co je jiné, je
vstup (HTTP místo GPIO) a výstup (PNG místo e-inku). Proto to, co je vidět v
prohlížeči, sedí na pixel s tím, co poletí na displej.

Dřív si simulátor kreslil vlastním kódem do RGB, a tak se s produkcí rozešel —
zobrazoval názvy knih s příponou, měl jinou cestu k fontu a neznal dlouhý
stisk. Testoval tedy hlavně sám sebe.

Prostřední tlačítko na stránce zastupuje jediné tlačítko čtečky, to v rotačním
kodéru, včetně rozdílu mezi krátkým klikem a podržením. Otáčení kodéru vlastní
tlačítko nemá — v menu dělá totéž co „nahoru/dolů".

Skládání dvou vrstev do barevného náhledu je jediná věc navíc: e-ink dostane
dvě jednobitové bitmapy, obrazovka potřebuje RGB.
"""

import io
from string import Template

from flask import Flask, send_file
from PIL import Image, ImageChops

import knihovna
import vykresleni
from hlavni_ctecka import DOBA_DRZENI_ENKODER
from stav import Ctecka

app = Flask(__name__)

# Jediný zdroj pravdy, přesně jako na Pi. Ctecka je thread-safe, takže na ni
# smí souběžně sáhnout víc obsluh Flasku najednou.
fonty = vykresleni.nacti_fonty()
ctecka = Ctecka(knihovna.nacti_strom())

BARVA_INKOUSTU = (0, 0, 0)
BARVA_CERVENE = (220, 0, 0)

def naveste_tlacitka(ctecka):
    """Vstupní události webu → metody Ctecky.

    Jmenují se podle toho, co udělá ruka, ne podle toho, co z toho vyjde —
    o tom rozhoduje stav uvnitř Ctecky. Jsou to tytéž metody, které
    pripoj_tlacitka() a pripoj_enkoder() navěšují na piny, takže se web
    s železem nemůže rozejít: "akce" v menu potvrdí položku, při čtení otevře
    menu, "dlouhy_stisk" se vrátí do rozečtené knihy.

    Funkce, ne rovnou slovník: testy si přepínají na vlastní instanci Ctecky
    a bez tohohle by si mapování opisovaly a zapomněly na nově přidanou
    událost.
    """
    return {
        "dalsi": ctecka.dalsi,
        "predchozi": ctecka.predchozi,
        "akce": ctecka.akce,
        "dlouhy_stisk": ctecka.zpet_do_cteni,
    }


TLACITKA = naveste_tlacitka(ctecka)


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


# string.Template místo f-stringu: v JS je složených závorek plno a zdvojovat
# je všechny je cesta k překlepu, který se pozná až v prohlížeči.
SABLONA = Template(
    """
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
                user-select: none; -webkit-user-select: none;
            }
            button:hover { background: #777; }
            #enkoder.drzeno { background: #a33; }
            .napoveda { margin-top: 14px; font-size: 13px; color: #999; }
        </style>
    </head>
    <body>
        <h2>Simulátor: 7.5" HD Waveshare (Menu + Čtení na výšku)</h2>
        <img src="/screen" class="screen" width="$sirka" height="$vyska"
             id="display" alt="E-ink displej">

        <div class="controls">
            <button onclick="posli('predchozi')">⬅ Nahoru / Předchozí</button>
            <button id="enkoder">Tlačítko kodéru</button>
            <button onclick="posli('dalsi')">Dolů / Další ➡</button>
        </div>
        <p class="napoveda">
            Prostřední tlačítko je jediné tlačítko čtečky: klik potvrdí položku
            (při čtení otevře menu), podržení nad $drzeni&nbsp;s se vrátí do knihy.
        </p>

        <script>
            const PRAH_DRZENI = $drzeni_ms;

            function posli(udalost) {
                return fetch('/api/stisk/' + udalost, { method: 'POST' })
                    .then(odpoved => {
                        if (odpoved.ok) {
                            document.getElementById('display').src =
                                '/screen?t=' + new Date().getTime();
                        }
                    });
            }

            // Napodobuje gpiozero: when_held se na železe ozve už v okamžiku,
            // kdy držení překročí hold_time — ne až při puštění. Proto se
            // dlouhý stisk odesílá z časovače a uvolnění už jen uklidí.
            const enkoder = document.getElementById('enkoder');
            let casovac = null;
            let drzeno = false;

            function na_stisku(e) {
                e.preventDefault();
                if (casovac !== null) return;   // opakované pointerdown ignoruj
                drzeno = false;
                casovac = setTimeout(() => {
                    drzeno = true;
                    enkoder.classList.add('drzeno');
                    posli('dlouhy_stisk');
                }, PRAH_DRZENI);
            }

            function na_uvolneni() {
                if (casovac === null) return;   // uvolnění bez stisku (myš přišla zvenčí)
                clearTimeout(casovac);
                casovac = null;
                enkoder.classList.remove('drzeno');
                if (!drzeno) posli('akce');
            }

            enkoder.addEventListener('pointerdown', na_stisku);
            enkoder.addEventListener('pointerup', na_uvolneni);
            // Vytažení kurzoru mimo tlačítko bere jako puštění, jinak by
            // časovač běžel dál a escape by přišel, i když už uživatel odjel.
            enkoder.addEventListener('pointerleave', na_uvolneni);
            enkoder.addEventListener('pointercancel', na_uvolneni);
            // Klávesnice: Enter/mezera na zaostřeném tlačítku dělá krátký stisk.
            enkoder.addEventListener('keyup', e => {
                if (e.key === 'Enter' || e.key === ' ') posli('akce');
            });
        </script>
    </body>
    </html>
    """
)


@app.route("/")
def index():
    return SABLONA.substitute(
        sirka=vykresleni.SIRKA,
        vyska=vykresleni.VYSKA,
        drzeni=DOBA_DRZENI_ENKODER,
        drzeni_ms=int(DOBA_DRZENI_ENKODER * 1000),
    )


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

    # Nové knihy a složky se tím ukážou samy.
    ctecka.nastav_seznam_knih(knihovna.nacti_strom())
    return "OK", 200


if __name__ == "__main__":
    # Poslouchá jen na localhostu a bez debuggeru: dřív tu bylo
    # debug=True + host="0.0.0.0", což je Werkzeug konzole otevřená komukoliv
    # na síti, tedy vzdálené spuštění kódu. Pro přístup z jiného počítače
    # změň host, ale debug nech vypnutý.
    print("Spouštím simulátor na http://127.0.0.1:5000")
    app.run(debug=False, host="127.0.0.1", port=5000)
