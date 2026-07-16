"""Rozvržení textu do stránek a cache hotového stránkování.

Výstupem zformatuj_a_rozdel() je seznam stránek:

    {"typ": "text",    "obsah": ["první řádek", "druhý řádek", …]}
    {"typ": "obrazek", "obsah": "OEBPS/Images/cover.jpeg"}

Řádkování počítá výhradně vyska_radku() z metrik fontu. Tutéž funkci musí volat
i vykreslování — jinak layout plánuje jinou stránku, než jaká se nakreslí.

Stránkování je drahé (na Pi Zero W řádově 16 s i s parsováním EPUBu, přičemž
větší půlku spolkne měření slov), a proto se ukládá do JSON cache. Cache se
musí hledat ještě PŘED parsováním EPUBu, jinak se ušetří jen menší část práce:

    klic = zpracovani_textu.klic_cache(cesta_ke_knize, font, 488, 820)
    stranky = zpracovani_textu.nacti_z_cache(klic)
    if stranky is None:
        obsah = zpracovani_epub.nacti_epub_obsah(cesta_ke_knize)   # drahé
        stranky = zpracovani_textu.zformatuj_a_rozdel(obsah, font, 488, 820)
        zpracovani_textu.uloz_do_cache(klic, stranky)

Do cache jde čistý JSON, ne pickle: obrázky jsou po refaktoru zpracovani_epub
jen cesty v archivu, takže není co serializovat binárně. Pickle by navíc vázal
cache na verzi Pillow a jeho načtení umí spustit libovolný kód.
"""

import hashlib
import json
import os

# Verze celé cesty od EPUBu ke stránkám, ne jen tohohle modulu. Zvyš ji při
# každé změně, která mění výsledné stránky — tedy i při zásahu do extrakce
# textu v zpracovani_epub.py. Promítne se do klíče cache a tím zneplatní
# všechna dosud uložená stránkování.
#   2: zpracovani_epub přestal slévat slova přes hranice vnořených tagů
VERZE_ALGORITMU = 2

ROZESTUP_RADKU = 5


def vyska_radku(font, rozestup_radku=ROZESTUP_RADKU):
    """Výška jednoho řádku v pixelech — jediný zdroj pravdy pro layout i kreslení."""
    ascent, descent = font.getmetrics()
    return ascent + descent + rozestup_radku


def zformatuj_a_rozdel(obsah, font, max_sirka_px, max_vyska_px, rozestup_radku=ROZESTUP_RADKU):
    stranky = []
    radky = []
    radku_na_stranku = max(1, max_vyska_px // vyska_radku(font, rozestup_radku))

    # Změřené šířky slov. Kniha má desítky tisíc slov, ale jen tisíce různých,
    # takže se font.getlength() zavolá zlomkem toho, co by jinak.
    sirka_slova = {}
    sirka_mezery = font.getlength(" ")

    def pridej_radek(text):
        radky.append(text)
        if len(radky) >= radku_na_stranku:
            stranky.append({"typ": "text", "obsah": list(radky)})
            radky.clear()

    for polozka in obsah:
        if polozka["typ"] == "obrazek":
            if radky:
                stranky.append({"typ": "text", "obsah": list(radky)})
                radky.clear()
            stranky.append({"typ": "obrazek", "obsah": polozka["hodnota"]})
            continue

        for odstavec in polozka["hodnota"].split("\n"):
            slova = [s for s in odstavec.split(" ") if s]
            if not slova:
                continue

            radek = []
            sirka = 0
            for slovo in slova:
                if slovo not in sirka_slova:
                    sirka_slova[slovo] = font.getlength(slovo)
                sirka_tohoto = sirka_slova[slovo]
                mezera = sirka_mezery if radek else 0

                # Slovo širší než celý řádek se nedělí a přeteče — ale jen když
                # stojí na řádku samo, jinak by se cyklilo na prázdném řádku.
                if radek and sirka + mezera + sirka_tohoto > max_sirka_px:
                    pridej_radek(" ".join(radek))
                    radek = [slovo]
                    sirka = sirka_tohoto
                else:
                    radek.append(slovo)
                    sirka += mezera + sirka_tohoto

            if radek:
                pridej_radek(" ".join(radek))

        # Odsazení mezi odstavci. Jen když na stránce něco je — prázdný řádek
        # nahoře by odsazoval od horního okraje a ubral by řádek textu.
        if radky:
            pridej_radek("")

    if radky:
        stranky.append({"typ": "text", "obsah": list(radky)})

    return stranky


def klic_cache(cesta_ke_knize, font, max_sirka_px, max_vyska_px, rozestup_radku=ROZESTUP_RADKU):
    """Hash všeho, na čem stránkování závisí. Změna čehokoliv → jiný klíč.

    Kromě jména knihy jde do otisku i její velikost a čas změny: bez toho by
    nová kniha nakopírovaná pod stejným jménem dostala staré stránkování.
    """
    try:
        udaje = os.stat(cesta_ke_knize)
        otisk_knihy = f"{os.path.basename(cesta_ke_knize)}:{udaje.st_size}:{int(udaje.st_mtime)}"
    except OSError:
        otisk_knihy = os.path.basename(cesta_ke_knize)

    # ImageFont.load_default() vrací v .path objekt BytesIO, jehož repr nese
    # adresu v paměti — ta se mění po každém spuštění a cache by nikdy nesedla.
    cesta_fontu = getattr(font, "path", None)
    if not isinstance(cesta_fontu, str):
        cesta_fontu = "vestaveny-font"

    slozky = "|".join([
        f"verze={VERZE_ALGORITMU}",
        f"kniha={otisk_knihy}",
        f"font={cesta_fontu}",
        f"velikost={getattr(font, 'size', '?')}",
        f"displej={max_sirka_px}x{max_vyska_px}",
        f"rozestup={rozestup_radku}",
    ])
    return hashlib.sha256(slozky.encode("utf-8")).hexdigest()[:16]


def nacti_z_cache(klic):
    """Vrátí uložené stránkování, nebo None, pokud použitelné není."""
    try:
        with open(_soubor_cache(klic), "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("verze") != VERZE_ALGORITMU:
            return None
        return data["stranky"]
    except (OSError, ValueError, KeyError):
        # Chybí, je rozbitá nebo z jiné verze — nic se neděje, přepočítá se.
        return None


def uloz_do_cache(klic, stranky):
    soubor = _soubor_cache(klic)
    docasny = f"{soubor}.tmp"
    try:
        os.makedirs(os.path.dirname(soubor), exist_ok=True)
        with open(docasny, "w", encoding="utf-8") as f:
            json.dump({"verze": VERZE_ALGORITMU, "stranky": stranky}, f, ensure_ascii=False)
        # Přejmenování je atomické: výpadek napájení uprostřed zápisu nechá
        # starou cache, ne useknutý JSON.
        os.replace(docasny, soubor)
    except OSError as e:
        print(f"Cache stránkování se nepodařilo uložit: {e}")


def _soubor_cache(klic):
    koren = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(koren, "ctecka", f"{klic}.json")
