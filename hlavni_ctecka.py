"""Hlavní program čtečky pro Raspberry Pi Zero W.

Drží pohromadě ostatní moduly a nic víc: stav je ve stav.py, kreslení ve
vykresleni.py, hardware v displej.py, práce se soubory v knihovna.py.

Rozdělení práce mezi vlákna je tu to podstatné. Callbacky gpiozero běží ve
vlastních vláknech a smějí jen sáhnout na stav — parsování EPUBu, stránkování,
zápis na SD i zápis na e-ink dělá výhradně tahle smyčka. Callback, který by
stránkoval, by na Pi Zero W na dvacet sekund zablokoval další tlačítka.
"""

import logging

from gpiozero import Button

import displej
import knihovna
import vykresleni
from stav import Ctecka, Stav

PIN_DALSI = 21
PIN_PREDCHOZI = 26
PIN_AKCE = 19

DOBA_ZAKMITU = 0.1
DOBA_DRZENI = 2.0

# Po kolika překresleních panel vybílit kvůli duchům. Vypnuto (0), protože
# na tomhle panelu se to nevyplácí: naměřeno Clear() 91 s a display() 99 s,
# takže čištění není o něco pomalejší — je to celé další čekání navíc. A jde
# hlavně o to, že tříbarevný panel jede při každém display() plnou křivkou,
# takže obraz přepíše celý a duchy po sobě prakticky nenechává.
#
# Kdyby se duchové přesto objevili, dej sem třeba 20: čistit se pak bude při
# startu a po každých 20 překresleních, za cenu +91 s pokaždé.
PERIODA_CISTENI = 0


def zobraz(obrazovka, ctecka, fonty):
    snimek = ctecka.snimek()
    cerna, cervena = vykresleni.vykresli(
        snimek, fonty, knihovna.nacti_obrazek_knihy(snimek.kniha)
    )
    obrazovka.zobraz(cerna, cervena)


def pripoj_tlacitka(ctecka):
    """Naváže tlačítka na stav. Volající si vrácený seznam musí podržet —
    zapomenuté Button objekty sebere garbage collector a tlačítka umlknou.

    Callbacky jen mění stav a budí smyčku. Žádný z nich nic nenačítá.
    """
    dalsi = Button(PIN_DALSI, bounce_time=DOBA_ZAKMITU)
    predchozi = Button(PIN_PREDCHOZI, bounce_time=DOBA_ZAKMITU)
    akce = Button(PIN_AKCE, bounce_time=DOBA_ZAKMITU, hold_time=DOBA_DRZENI)

    dalsi.when_pressed = ctecka.dalsi
    predchozi.when_pressed = ctecka.predchozi

    # Krátký stisk se vyhodnotí až při uvolnění. Kdyby visel na when_pressed,
    # dlouhý stisk by nejdřív otevřel knihu (stisk přijde okamžitě) a teprve
    # za dvě sekundy ukončil program — vypnutí čtečky by tak pokaždé spustilo
    # stránkování celé knihy.
    drzeno = False

    def na_stisku():
        nonlocal drzeno
        drzeno = False

    def na_drzeni():
        nonlocal drzeno
        drzeno = True
        ctecka.ukonci()

    def na_uvolneni():
        if not drzeno:
            ctecka.akce()

    akce.when_pressed = na_stisku
    akce.when_held = na_drzeni
    akce.when_released = na_uvolneni

    return [dalsi, predchozi, akce]


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")

    fonty = vykresleni.nacti_fonty()
    ctecka = Ctecka(knihovna.nacti_seznam_knih())
    obrazovka = displej.vytvor_displej()
    tlacitka = pripoj_tlacitka(ctecka)

    # Panel sice drží obraz i bez napájení, ale první display() ho celý
    # přepíše, takže vybílit ho předtím jen zdvojuje čekání na první stránku.
    if PERIODA_CISTENI:
        obrazovka.vycisti()
    od_cisteni = 0

    try:
        while not ctecka.konec:
            # Vlajku shodí cekej_na_prekresleni() ještě před renderem. Stisk,
            # který přijde během zápisu na e-ink, ji tak nastaví znovu a smyčka
            # překreslí ještě jednou, místo aby se ztratil.
            if ctecka.cekej_na_prekresleni(timeout=1.0):
                if PERIODA_CISTENI and od_cisteni >= PERIODA_CISTENI:
                    obrazovka.vycisti()
                    od_cisteni = 0
                zobraz(obrazovka, ctecka, fonty)
                od_cisteni += 1

            # Drahá práce patří sem, ne do callbacku tlačítka.
            knihovna.obsluz(ctecka, fonty)

            # Nové knihy ve složce se tím ukážou samy, bez restartu.
            if ctecka.snimek().stav is Stav.MENU:
                ctecka.nastav_seznam_knih(knihovna.nacti_seznam_knih())

    except KeyboardInterrupt:
        pass
    finally:
        logging.info("Ukončuji čtečku, vypínám displej...")
        for tlacitko in tlacitka:
            tlacitko.close()
        obrazovka.vypni()


if __name__ == "__main__":
    main()
