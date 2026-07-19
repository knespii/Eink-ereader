"""Hlavní program čtečky pro Raspberry Pi Zero W.

Drží pohromadě ostatní moduly a nic víc: stav je ve stav.py, kreslení ve
vykresleni.py, hardware v displej.py, práce se soubory v knihovna.py.

Rozdělení práce mezi vlákna je tu to podstatné. Callbacky gpiozero běží ve
vlastních vláknech a smějí jen sáhnout na stav — parsování EPUBu, stránkování,
zápis na SD i zápis na displeje dělá výhradně tahle smyčka. Callback, který by
stránkoval, by na Pi Zero W na dvacet sekund zablokoval další tlačítka.

Displeje jsou dva a každý slouží jinému stavu:

    MENU   → OLED 128×32 přes I2C, ovládá se rotačním kodérem. Překreslení
             trvá jednotky milisekund, takže reaguje na každé cvaknutí.
             E-ink se v menu nechává být.
    CTENI  → e-ink přes SPI, ovládá se původními tlačítky. Jedno překreslení
             stojí ~10 s, takže se dělá jen při otočení stránky.

Vykreslují se pořád ze stejného Snimku, takže se nemůžou rozejít. Kreslení
samotné je v oled_ui.py a vykresleni.py — tady je jen smyčka.
"""

import logging
import time

from gpiozero import Button, RotaryEncoder

import displej
import knihovna
import oled_ui
import vykresleni
from stav import Ctecka, Stav

# Tlačítka u e-inku: listování v knize a návrat do menu.
PIN_DALSI = 21
PIN_PREDCHOZI = 26
PIN_AKCE = 19

# Rotační kodér u OLEDu: navigace v knihovně.
PIN_ENKODER_CLK = 5
PIN_ENKODER_DT = 6
PIN_ENKODER_SW = 13

DOBA_ZAKMITU = 0.1
DOBA_DRZENI = 2.0

# Jak dlouho smyčka čeká na probuzení, když se nic neděje. V menu krátce, aby
# se plynule posouval dlouhý název na OLEDu; při čtení nemá co animovat.
TIK_MENU = 0.15
TIK_CTENI = 1.0
# O kolik pixelů posunout název na jeden tik. Při TIK_MENU 0,15 s vychází
# 6 px na 40 px/s. Zrychluje se krokem, ne kratším tikem: víc překreslení za
# sekundu by znamenalo víc provozu na I2C a víc práce pro Pi Zero W úplně zbytečně.
KROK_TICKERU = 6

# Jak často se přehledává složka s knihami. Dřív se skenovalo při každém
# průchodu, což při TIK_MENU 0,15 s znamená sedm výpisů adresáře za sekundu.
PERIODA_SKENU = 2.0

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
    # Uloží se, co je teď na panelu, aby po zapnutí bylo kam navázat. Volá se
    # jen odsud, takže posledni_stav.json pořád popisuje obraz na e-inku —
    # menu na OLEDu do něj nezasahuje, protože OLED je po zapnutí stejně prázdný.
    knihovna.uloz_posledni_stav(snimek)


class VystupOled:
    """Kreslení na OLED s vynecháním zbytečných zápisů na I2C.

    Smyčka se v menu probouzí několikrát za sekundu kvůli posunu dlouhého
    názvu. U krátkého názvu je ale obraz pořád stejný, takže se porovná
    s posledním odeslaným a na sběrnici se nepošle nic.
    """

    def __init__(self, zarizeni, fonty):
        self._zarizeni = zarizeni
        self._fonty = fonty
        self._posledni = None

    def prekresli(self, snimek, faze=0):
        obraz = oled_ui.vykresli_oled(snimek, self._fonty, faze)
        data = obraz.tobytes()
        if data == self._posledni:
            return False
        self._posledni = data
        self._zarizeni.display(obraz)
        return True

    def hlaseni(self, text):
        """Okamžitě promaže displej a vypíše vycentrovanou hlášku.

        Obchází porovnání s posledním obrazem — hláška se musí objevit i
        tehdy, když by shodou okolností vyšla stejně jako to, co už na
        displeji je.
        """
        obraz = oled_ui.vykresli_hlaseni(text, self._fonty)
        self._posledni = obraz.tobytes()
        self._zarizeni.display(obraz)


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


def pripoj_enkoder(ctecka):
    """Naváže rotační kodér na stav. Vrácený seznam si volající musí podržet.

    Kodér obsluhuje jen menu. Při čtení se otáčení i stisk ignorují: stránky
    patří tlačítkům u e-inku a nechtěné cvrnknutí do kodéru by jinak spustilo
    desetisekundové překreslení panelu.

    Chybějící nebo špatně zapojený kodér čtečku nepoloží — menu se pak ovládá
    tlačítky jako dřív. Stejný přístup jako u displeje: nepřítomné železo se
    obejde, ne odnese celý program.
    """
    try:
        kolecko = RotaryEncoder(PIN_ENKODER_CLK, PIN_ENKODER_DT, max_steps=0)
        tlacitko = Button(PIN_ENKODER_SW, bounce_time=DOBA_ZAKMITU)
    except Exception as e:
        logging.warning("Rotační kodér není dostupný (%s), pokračuji bez něj.", e)
        return []

    def jen_v_menu(co_udelat):
        def obsluha():
            if ctecka.snimek().stav is Stav.MENU:
                co_udelat()

        return obsluha

    kolecko.when_rotated_clockwise = jen_v_menu(ctecka.dalsi)
    kolecko.when_rotated_counter_clockwise = jen_v_menu(ctecka.predchozi)
    tlacitko.when_pressed = jen_v_menu(ctecka.akce)

    return [kolecko, tlacitko]


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")

    fonty = vykresleni.nacti_fonty()

    # Obnova posledního stavu bez překreslení: po zapnutí panel drží obraz,
    # kde jsi skončil, a čtečka na něj naváže. Když nic uloženého není (první
    # spuštění), startuje se v menu s běžným překreslením.
    obnovit = knihovna.nacti_posledni_stav() is not None
    ctecka = Ctecka(knihovna.nacti_strom(), prekreslit_na_startu=not obnovit)
    if obnovit and not knihovna.obnov_posledni_stav(ctecka, fonty):
        # Uložený stav neseděl (např. smazaná kniha) — panel drží něco jiného,
        # ať se překreslí, aby displej odpovídal skutečnosti.
        ctecka.vyzadej_prekresleni()

    obrazovka = displej.vytvor_displej()
    oled = VystupOled(oled_ui.vytvor_oled(), oled_ui.nacti_fonty())
    ovladace = pripoj_tlacitka(ctecka) + pripoj_enkoder(ctecka)

    # Panel sice drží obraz i bez napájení, ale první display() ho celý
    # přepíše, takže vybílit ho předtím jen zdvojuje čekání na první stránku.
    if PERIODA_CISTENI:
        obrazovka.vycisti()
    od_cisteni = 0

    # OLED je po zapnutí prázdný, takže se vykreslí rovnou — na rozdíl od
    # e-inku ho to nic nestojí a uživatel hned vidí, kde čtečka stojí.
    oled.prekresli(ctecka.snimek())
    faze_tickeru = 0
    posledni_sken = 0.0

    try:
        while not ctecka.konec:
            v_menu = ctecka.snimek().stav is Stav.MENU

            # Vlajku shodí cekej_na_prekresleni() ještě před renderem. Stisk,
            # který přijde během zápisu na e-ink, ji tak nastaví znovu a smyčka
            # překreslí ještě jednou, místo aby se ztratil.
            if ctecka.cekej_na_prekresleni(TIK_MENU if v_menu else TIK_CTENI):
                snimek = ctecka.snimek()
                faze_tickeru = 0  # nová položka se začne číst od začátku

                if snimek.stav is Stav.MENU:
                    # Menu jede jen po OLEDu. E-ink se schválně nechává být:
                    # jeho refresh trvá ~10 s a při listování knihovnou by byl
                    # k ničemu. Drží dál poslední stránku, což je i to, co
                    # popisuje posledni_stav.json.
                    oled.prekresli(snimek, faze_tickeru)
                else:
                    if PERIODA_CISTENI and od_cisteni >= PERIODA_CISTENI:
                        obrazovka.vycisti()
                        od_cisteni = 0
                    # Stránka jde na e-ink, OLED k ní ukáže jen číslo stránky.
                    oled.prekresli(snimek, faze_tickeru)
                    zobraz(obrazovka, ctecka, fonty)
                    od_cisteni += 1
            elif v_menu:
                # Vypršel tik a nikdo nic nezmáčkl — jen se poposune dlouhý
                # název. Když se celý vejde, prekresli() nepošle na I2C nic.
                faze_tickeru += KROK_TICKERU
                oled.prekresli(ctecka.snimek(), faze_tickeru)

            # Drahá práce patří sem, ne do callbacku tlačítka. Než se do ní
            # smyčka pustí, dostane uživatel odezvu: parsování a stránkování
            # knihy trvá na Pi Zero W ~16 s a po tu dobu se smyčka nevrátí.
            if ctecka.snimek().nacita_se:
                oled.hlaseni("Načítám…")
            knihovna.obsluz(ctecka, fonty)

            # Nové knihy a složky se tím ukážou samy, bez restartu. Skenuje se
            # po PERIODA_SKENU, ne při každém průchodu: v menu se smyčka točí
            # sedmkrát za sekundu a tolik výpisů adresáře je zbytečné.
            ted = time.monotonic()
            if v_menu and ted - posledni_sken >= PERIODA_SKENU:
                posledni_sken = ted
                ctecka.nastav_seznam_knih(knihovna.nacti_strom())

    except KeyboardInterrupt:
        pass
    finally:
        logging.info("Ukončuji čtečku, vypínám displej...")
        for ovladac in ovladace:
            ovladac.close()
        obrazovka.vypni()


if __name__ == "__main__":
    main()
