"""Práce se soubory knih — společná pro produkční čtečku i simulátor.

Sem patří všechno, co sahá na disk: hledání knih, uložené pozice, stránkování
přes cache a načítání obrázků. Stav (stav.py) ani kreslení (vykresleni.py) o
souborech nevědí nic, takže tenhle modul je jediné místo, kde je I/O.

Obojí, hlavni_ctecka.py i simulator.py, používá tytéž funkce. Kdyby si je
každý psal po svém, rozejdou se — přesně to se dřív stalo s vykreslováním,
kde simulátor ukazoval něco jiného, než co šlo na displej.
"""

import json
import logging
import os

import vykresleni
import zpracovani_epub
import zpracovani_textu

# Cesty se odvozují od umístění skriptu, ne od pracovního adresáře — jinak by
# čtečka spuštěná ze systemd hledala knihy někde v kořeni.
KOREN = os.path.dirname(os.path.realpath(__file__))
SLOZKA_KNIH = os.path.join(KOREN, "epuby")
SOUBOR_POZIC = os.path.join(KOREN, "progress.json")
# Poslední zobrazený stav — aby čtečka po zapnutí navázala tam, kde skončila,
# bez zbytečného překreslení (e-ink drží obraz i bez napájení).
SOUBOR_STAVU = os.path.join(KOREN, "posledni_stav.json")


def _zapis_json_atomicky(cesta, data):
    """Zápis stranou a přejmenování: čtečka se vypíná odpojením napájení, takže
    zápis přímo do souboru by při smůle nechal useknutý JSON."""
    docasny = f"{cesta}.tmp"
    try:
        with open(docasny, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())  # bez tohohle může přejmenování předběhnout data
        os.replace(docasny, cesta)
    except OSError as e:
        logging.error("Zápis do %s selhal: %s", cesta, e)


def _bezpecna_cesta(relativni):
    """Složí absolutní cestu z relativní a ověří, že nevede ven ze SLOZKA_KNIH.

    Názvy sice pocházejí z vlastního výpisu adresáře, ale relativní cesta se
    ukládá do progress.json a posledni_stav.json — soubor upravený rukou (nebo
    poškozený) by jinak přes ".." otevřel cokoli na disku.
    """
    cesta = os.path.normpath(os.path.join(SLOZKA_KNIH, relativni))
    if os.path.commonpath([SLOZKA_KNIH, cesta]) != SLOZKA_KNIH:
        raise ValueError(f"Cesta {relativni!r} vede mimo knihovnu.")
    return cesta


def _polozky_adresare(adresar):
    """Obsah jednoho adresáře jako [{"typ", "nazev", "cesta"}, ...].

    `adresar` je relativní cesta uvnitř SLOZKA_KNIH ("" = kořen). Podadresáře
    hlásí jen kořen — zanořování je záměrně jen na jednu úroveň, takže složka
    ve složce se ignoruje (viz [PROJECT_UPDATE_OLED], bod 4).
    """
    absolutni = _bezpecna_cesta(adresar)
    polozky = []
    try:
        jmena = os.listdir(absolutni)
    except OSError as e:
        logging.error("Adresář %s nejde přečíst: %s", absolutni or SLOZKA_KNIH, e)
        return polozky

    for jmeno in jmena:
        relativni = f"{adresar}/{jmeno}" if adresar else jmeno
        if jmeno.endswith(".epub") and os.path.isfile(os.path.join(absolutni, jmeno)):
            polozky.append({"typ": "kniha", "nazev": jmeno, "cesta": relativni})
        elif not adresar and os.path.isdir(os.path.join(absolutni, jmeno)):
            polozky.append({"typ": "slozka", "nazev": jmeno, "cesta": relativni})
    return polozky


def nacti_strom():
    """Celá knihovna naráz: {"": [položky kořene], "slozka": [položky složky]}.

    Ctecka nesmí sahat na disk, takže dostane rovnou celý strom a naviguje v
    něm sama. Při jedné úrovni zanoření je to pár desítek položek, takže se to
    vyplatí víc než dotazovat se na obsah složky až při vstupu do ní — vstup do
    složky pak nečeká na I/O a jde vyřídit rovnou v obsluze encoderu.
    """
    os.makedirs(SLOZKA_KNIH, exist_ok=True)
    strom = {"": _polozky_adresare("")}
    for polozka in strom[""]:
        if polozka["typ"] == "slozka":
            strom[polozka["cesta"]] = _polozky_adresare(polozka["cesta"])
    return strom


def nacti_seznam_knih():
    """Ploché relativní cesty všech knih — kořen i složky.

    Slouží k ověření, že kniha z posledni_stav.json pořád existuje. Pro menu
    použij nacti_strom(), ten nese i složky.
    """
    return [
        polozka["cesta"]
        for polozky in nacti_strom().values()
        for polozka in polozky
        if polozka["typ"] == "kniha"
    ]


def nacti_pozice():
    try:
        with open(SOUBOR_POZIC, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logging.error("Uložené pozice nejdou přečíst, začínám od začátku: %s", e)
        return {}


def uloz_pozici(kniha, stranka):
    """Zapíše pozici atomicky. Klíčem je cesta relativní ke složce knih.

    Dřív stačilo jméno souboru; se složkami by se dvě stejně pojmenované knihy
    v různých složkách přepisovaly navzájem. Cesta je pořád relativní, takže
    zůstává nezávislá na pracovním adresáři.

    Zapisuje se stranou a přejmenovává: čtečka se vypíná odpojením napájení a
    zápis přímo do progress.json by při smůle nechal useknutý JSON, čímž by se
    ztratily pozice všech knih naráz, ne jen té rozepsané.
    """
    pozice = nacti_pozice()
    pozice[kniha] = stranka
    _zapis_json_atomicky(SOUBOR_POZIC, pozice)


def nacti_stranky(nazev, fonty, hlas=None):
    """Vrátí stránkování knihy — z cache, nebo ho spočítá a uloží.

    `nazev` je cesta relativní ke složce knih ("kniha.epub" i "slozka/kniha.epub").

    `hlas` je volitelné callable(podil) s podílem 0→1 za **celé** načtení.
    Obě fáze dostanou půlku škály: parsování EPUBu 0→0,5, stránkování 0,5→1.
    Dělí se napůl schválně, i když poměr časů se kniha od knihy liší — ukazatel
    má dát najevo, že se něco děje, ne měřit čas do sekundy.
    """
    cesta = _bezpecna_cesta(nazev)
    klic = zpracovani_textu.klic_cache(
        cesta, fonty.text, vykresleni.TEXT_SIRKA, vykresleni.TEXT_VYSKA
    )

    stranky = zpracovani_textu.nacti_z_cache(klic)
    if stranky is not None:
        logging.info("Stránkování %s vzato z cache.", nazev)
        return stranky

    logging.info("Stránkuji %s, poprvé to chvíli potrvá...", nazev)

    def faze(od, do):
        """Přepočte podíl dílčí fáze na úsek celkové škály."""
        if hlas is None:
            return None
        return lambda podil: hlas(od + (do - od) * podil)

    obsah = zpracovani_epub.nacti_epub_obsah(cesta, hlas=faze(0.0, 0.5))
    stranky = zpracovani_textu.zformatuj_a_rozdel(
        obsah,
        fonty.text,
        vykresleni.TEXT_SIRKA,
        vykresleni.TEXT_VYSKA,
        hlas=faze(0.5, 1.0),
    )
    if stranky:
        zpracovani_textu.uloz_do_cache(klic, stranky)
    return stranky


def nacti_obrazek_knihy(nazev):
    """Vrátí funkci pro vykresli(), která z cesty v archivu udělá obrázek.

    Vrací None, když žádná kniha otevřená není — vykresli() si s tím poradí.
    """
    if not nazev:
        return None

    cesta = _bezpecna_cesta(nazev)

    def nacti(v_archivu):
        return zpracovani_epub.nacti_obrazek(
            cesta, v_archivu, vykresleni.TEXT_SIRKA, vykresleni.TEXT_VYSKA
        )

    return nacti


def obsluz(ctecka, fonty, hlas=None):
    """Vyřídí, co si stav vyžádal: načte knihu a uloží pozici.

    Tohle je ta drahá práce, která nesmí běžet v callbacku tlačítka. Na Pi ji
    volá hlavní smyčka, v simulátoru obsluha HTTP požadavku.

    `hlas` je volitelné callable(podil) volané během načítání. Vykreslování si
    obstará volající — tenhle modul o displejích nic neví a vědět nesmí, jinak
    by se rozešel se simulátorem, který žádný OLED nemá.
    """
    nazev = ctecka.vyzvedni_pozadavek()
    if nazev and not ctecka.konec:
        ctecka.dodej_stranky(
            nazev,
            nacti_stranky(nazev, fonty, hlas=hlas),
            nacti_pozice().get(nazev, 0),
        )

    # Otočení stránek se sem slily, takže je z nich jeden zápis na SD.
    pozice = ctecka.vyzvedni_pozici_k_ulozeni()
    if pozice:
        uloz_pozici(*pozice)


# --- POSLEDNÍ ZOBRAZENÝ STAV (obnova po zapnutí) ---


def uloz_posledni_stav(snimek):
    """Zapíše, co je právě na displeji, aby se po zapnutí navázalo bez bliknutí."""
    from stav import Stav

    if snimek.stav is Stav.CTENI and snimek.kniha:
        stav = {"typ": "cteni", "kniha": snimek.kniha, "stranka": snimek.cislo_stranky - 1}
    else:
        # Adresář se ukládá taky, jinak by se čtečka po zapnutí probrala v
        # kořeni, i když uživatel usnul uvnitř složky.
        stav = {"typ": "menu", "vyber": snimek.vyber, "adresar": snimek.adresar}
    _zapis_json_atomicky(SOUBOR_STAVU, stav)


def nacti_posledni_stav():
    try:
        with open(SOUBOR_STAVU, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        logging.error("Poslední stav nejde přečíst: %s", e)
        return None


def obnov_posledni_stav(ctecka, fonty):
    """Vrátí čtečku tam, kde skončila. Bez překreslení — panel obraz drží.

    Vrací True, když obnovený stav odpovídá tomu, co panel ukazuje. Vrací
    False, když se kniha nepodařilo obnovit (smazaná) — pak panel drží starou
    stránku a volající si má vyžádat překreslení, ať se displej srovná.
    """
    stav = nacti_posledni_stav()
    if not stav:
        return False

    if stav.get("typ") == "cteni":
        if stav.get("kniha") in nacti_seznam_knih():
            nazev = stav["kniha"]
            stranky = nacti_stranky(nazev, fonty)
            if ctecka.obnov_cteni(nazev, stranky, stav.get("stranka", 0)):
                return True
        return False  # kniha zmizela — panel drží stránku, kterou už neotevřeme

    if stav.get("typ") == "menu":
        ctecka.obnov_menu(stav.get("vyber", 0), stav.get("adresar", ""))
        return True

    return False
