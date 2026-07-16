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


def nacti_seznam_knih():
    os.makedirs(SLOZKA_KNIH, exist_ok=True)
    return [f for f in os.listdir(SLOZKA_KNIH) if f.endswith(".epub")]


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
    """Zapíše pozici atomicky. Klíčem je jméno souboru, ne cesta.

    Zapisuje se stranou a přejmenovává: čtečka se vypíná odpojením napájení a
    zápis přímo do progress.json by při smůle nechal useknutý JSON, čímž by se
    ztratily pozice všech knih naráz, ne jen té rozepsané.
    """
    pozice = nacti_pozice()
    pozice[kniha] = stranka

    docasny = f"{SOUBOR_POZIC}.tmp"
    try:
        with open(docasny, "w", encoding="utf-8") as f:
            json.dump(pozice, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())  # bez tohohle může přejmenování předběhnout data
        os.replace(docasny, SOUBOR_POZIC)
    except OSError as e:
        logging.error("Pozici se nepodařilo uložit: %s", e)


def nacti_stranky(nazev, fonty):
    """Vrátí stránkování knihy — z cache, nebo ho spočítá a uloží."""
    cesta = os.path.join(SLOZKA_KNIH, nazev)
    klic = zpracovani_textu.klic_cache(
        cesta, fonty.text, vykresleni.TEXT_SIRKA, vykresleni.TEXT_VYSKA
    )

    stranky = zpracovani_textu.nacti_z_cache(klic)
    if stranky is not None:
        logging.info("Stránkování %s vzato z cache.", nazev)
        return stranky

    logging.info("Stránkuji %s, poprvé to chvíli potrvá...", nazev)
    obsah = zpracovani_epub.nacti_epub_obsah(cesta)
    stranky = zpracovani_textu.zformatuj_a_rozdel(
        obsah, fonty.text, vykresleni.TEXT_SIRKA, vykresleni.TEXT_VYSKA
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

    cesta = os.path.join(SLOZKA_KNIH, nazev)

    def nacti(v_archivu):
        return zpracovani_epub.nacti_obrazek(
            cesta, v_archivu, vykresleni.TEXT_SIRKA, vykresleni.TEXT_VYSKA
        )

    return nacti


def obsluz(ctecka, fonty):
    """Vyřídí, co si stav vyžádal: načte knihu a uloží pozici.

    Tohle je ta drahá práce, která nesmí běžet v callbacku tlačítka. Na Pi ji
    volá hlavní smyčka, v simulátoru obsluha HTTP požadavku.
    """
    nazev = ctecka.vyzvedni_pozadavek()
    if nazev and not ctecka.konec:
        ctecka.dodej_stranky(
            nazev,
            nacti_stranky(nazev, fonty),
            nacti_pozice().get(nazev, 0),
        )

    # Otočení stránek se sem slily, takže je z nich jeden zápis na SD.
    pozice = ctecka.vyzvedni_pozici_k_ulozeni()
    if pozice:
        uloz_pozici(*pozice)
