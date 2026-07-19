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
    CTENI  → e-ink přes SPI, stránky otáčí dvojice tlačítek. Jedno překreslení
             stojí ~29 s, takže se dělá jen při otočení stránky.

Mezi stavy se přechází tlačítkem v kodéru: krátkým stiskem tam, dlouhým zpátky.
Je to jediné tlačítko čtečky a obsluhuje obojí, takže hlídat stav musí ono, ne
volající.

Vykreslují se pořád ze stejného Snimku, takže se nemůžou rozejít. Kreslení
samotné je v oled_ui.py a vykresleni.py — tady je jen smyčka.
"""

import logging
import subprocess
import threading
import time
from enum import StrEnum

from gpiozero import Button, RotaryEncoder

import displej
import knihovna
import oled_ui
import vykresleni
from stav import Ctecka, Stav

# Tlačítka u e-inku: už jen listování v knize. Třetí tlačítko (přechod do menu
# a zpět, dlouhým stiskem vypnutí) bylo z hardwaru odstraněné — obojí dělá
# tlačítko v kodéru. S ním odešla i jediná cesta, jak čtečku ukončit z GPIO:
# služba běží pořád a vypíná se odpojením napájení. E-ink drží obraz i bez
# proudu, takže se tím nic neztratí; jen se panel neuspí přes epd.sleep().
PIN_DALSI = 21
PIN_PREDCHOZI = 26

# Rotační kodér u OLEDu: navigace v knihovně + jediné tlačítko čtečky.
PIN_ENKODER_CLK = 5
PIN_ENKODER_DT = 6
PIN_ENKODER_SW = 13

DOBA_ZAKMITU = 0.1

# Držení tlačítka v kodéru, po kterém se bere jako dlouhý stisk (útěk do knihy).
DOBA_DRZENI_ENKODER = 1.0

# Jak dlouho smyčka čeká na probuzení, když se nic neděje. V menu krátce, aby
# se plynule posouval dlouhý název na OLEDu; při čtení nemá co animovat.
# Čeká se na threading.Condition, ne přes time.sleep() — cvaknutí kodéru nebo
# stisk tlačítka smyčku probudí okamžitě a nezůstane viset do konce tiku.
TIK_MENU = 0.08
TIK_CTENI = 1.0

# Rychlost posunu dlouhého názvu v pixelech za sekundu. Fáze se odvozuje od
# time.monotonic(), ne od počtu proběhlých tiků: kdyby smyčku zdržel sken
# složky nebo zápis pozice, text by se viditelně zadrhl. Při TIK_MENU 0,08 s
# vychází ~3 px na snímek.
RYCHLOST_TICKERU = 40.0

# Jak dlouho název po přepnutí stojí, než se rozjede. Bez prodlevy odjede
# začátek dřív, než ho oko stihne přečíst.
PRODLEVA_TICKERU = 1.0

# --- ZRYCHLENÉ LISTOVÁNÍ ---
# Točí-li uživatel kodérem svižně, přeskakuje se po deseti stránkách; jednotlivá
# cvaknutí zůstávají po jedné. Prahem je rozestup mezi cvaknutími, ne jejich
# počet: rychlost ruky se pozná hned na druhém cvaknutí a nemusí se čekat, až
# se nasbírá série.
#
# 0,08 s je ~12 cvaknutí za sekundu. Zadání navrhovalo 0,05 s, ale to je na
# běžném 20-pulzním kodéru rychlost, které jde dosáhnout jen trhnutím — práh by
# se v praxi skoro netrefil. Naopak výš než ~0,12 s se do zrychlení spadne i při
# klidném krokování a přestřelovalo by to.
PRAH_ZRYCHLENI = 0.08
KROK_ZRYCHLENY = 10
KROK_ZAKLADNI = 1

# Jak dlouho po posledním cvaknutí zůstanou na OLEDu šipky směru. Kratší by
# blikaly mezi cvaknutími při pomalém krokování, delší by lhaly o tom, že se
# ještě točí.
PRODLEVA_SMERU = 0.6

# Nejkratší rozestup mezi překresleními ukazatele během načítání knihy. Parser
# hlásí postup tisíckrát za knihu; bez omezení by samotné kreslení a zápis na
# I2C načítání znatelně prodloužily.
PERIODA_HLASENI = 0.1

# Jak často se přehledává složka s knihami. Dřív se skenovalo při každém
# průchodu, což by při TIK_MENU 0,08 s znamenalo dvanáct výpisů adresáře
# za sekundu.
PERIODA_SKENU = 2.0

# --- ÚSPORA ENERGIE ---
# Dvě fáze nečinnosti. Měří se od posledního hardwarového vstupu, ne od
# posledního překreslení: čtení stránky je z pohledu programu nečinnost, ale
# uživatel u čtečky sedí, takže by ho deset minut ticha nemělo uspat uprostřed
# odstavce — proto je práh v minutách, ne v sekundách.
DOBA_DO_SPANKU = 600.0  # 10 min → zhasne OLED, jinak běží dál
DOBA_DO_VYPNUTI = 3600.0  # 60 min → ukonci() a vypnutí celého Pi

# Jak dlouho smyčka spí mezi kontrolami, když je čtečka v lehkém spánku. Delší
# než TIK_CTENI: v spánku není co animovat a jediné, na co se čeká, je uplynutí
# hodiny. Vstup smyčku probudí okamžitě přes Condition, takže odezva tím netrpí.
TIK_SPANKU = 5.0

# Vypnutí Pi. Ne `halt`: ten systém jen zastaví a nechá ho pod proudem.
# `poweroff` projde vypínací sekvencí, což je u čtečky na baterii to, oč jde.
# Bez hesla to projde jen s pravidlem v sudoers (viz README) — jinak se
# zaloguje chyba a čtečka běží dál.
PRIKAZ_VYPNUTI = ("sudo", "poweroff")


class Uspora(StrEnum):
    """Ve které fázi úspory energie čtečka je."""

    BDENI = "BDENI"
    SPANEK = "SPANEK"  # OLED zhasnutý, program běží
    VYPNUTI = "VYPNUTI"  # čas zhasnout celé Pi


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


class Hlidac:
    """Kdy naposled sáhla ruka na hardware — a co z toho plyne pro úsporu.

    Fáze je **čistá funkce uplynulého času**, ne vlajka, kterou by nastavovala
    smyčka. Callback tlačítka a smyčka běží v různých vláknech a callback
    potřebuje vědět, jestli se spalo, ještě než se smyčka vůbec probudí; kdyby
    to byla sdílená vlajka, záleželo by na tom, kdo se stihl zeptat dřív.
    Takhle se oba dívají na tytéž hodiny a nemají se na čem rozejít.

    O displejích ani o Ctecce nic neví — jen měří čas. Co s tím, rozhoduje
    hlavní smyčka.
    """

    def __init__(self, do_spanku=DOBA_DO_SPANKU, do_vypnuti=DOBA_DO_VYPNUTI, ted=None):
        self._do_spanku = do_spanku
        self._do_vypnuti = do_vypnuti
        # Zámek jen kvůli čtení a zápisu jednoho floatu z cizích vláken.
        self._zamek = threading.Lock()
        self._posledni = time.monotonic() if ted is None else ted

    def zaznamenej_vstup(self, ted=None):
        """Zapíše hardwarový vstup a řekne, jestli se jím jen procitlo.

        Vrací True, když čtečka spala — pak se vstup **spotřeboval na
        probuzení** a volající s ním nesmí udělat nic dalšího. Bez toho by
        první sáhnutí na tmavý displej naslepo otočilo stránku a čekalo by se
        ~29 s na něco, co nikdo nechtěl.
        """
        ted = time.monotonic() if ted is None else ted
        with self._zamek:
            spalo_se = ted - self._posledni >= self._do_spanku
            self._posledni = ted
            return spalo_se

    def faze(self, ted=None):
        ted = time.monotonic() if ted is None else ted
        with self._zamek:
            necinnost = ted - self._posledni
        if necinnost >= self._do_vypnuti:
            return Uspora.VYPNUTI
        if necinnost >= self._do_spanku:
            return Uspora.SPANEK
        return Uspora.BDENI


def vypni_system(prikaz=PRIKAZ_VYPNUTI):
    """Zhasne celé Pi. Volá se až po úklidu GPIO a I2C, ne místo něj.

    Selhání se jen zaloguje: bez pravidla v sudoers sudo čeká na heslo, které
    u čtečky nemá kdo zadat, a shodit kvůli tomu program by bylo horší než
    zůstat zapnutý.
    """
    logging.info("Hodina nečinnosti — vypínám systém (%s).", " ".join(prikaz))
    try:
        subprocess.run(list(prikaz), check=True, timeout=30)
    except Exception as e:
        logging.error("Vypnutí selhalo (%s). Chybí nejspíš NOPASSWD v sudoers.", e)


class VystupEink:
    """Zápis na e-ink s vynecháním překreslení na obsah, který na panelu už je.

    Totéž, co dělá VystupOled s I2C, jen s jinou cenou: jedno překreslení stojí
    ~29 s. Panel drží obraz i bez napájení, takže si stačí pamatovat, co na něm
    je — dvojice (kniha, číslo stránky) obsah stránky určuje celou.

    Kvůli tomu je návrat z menu do rozečtené knihy zadarmo: stav se přepne,
    smyčka projde větví CTENI, ale zobraz() zjistí, že by psalo tentýž text,
    a nesáhne na panel. Není to vlajka, kterou by šlo zapomenout nastavit —
    je to porovnání s tím, co panel skutečně ukazuje.
    """

    def __init__(self, obrazovka, fonty, otisk=None):
        self._obrazovka = obrazovka
        self._fonty = fonty
        self._posledni = otisk

    def zobraz(self, ctecka):
        snimek = ctecka.snimek()
        otisk = (snimek.kniha, snimek.cislo_stranky)
        if otisk == self._posledni:
            return False
        self._posledni = otisk
        zobraz(self._obrazovka, ctecka, self._fonty)
        return True

    def vycisti(self):
        # Po vybílení na panelu nic není, takže příští stránka musí projít.
        self._posledni = None
        self._obrazovka.vycisti()

    def vypni(self):
        self._obrazovka.vypni()


def otisk_ulozeneho(stav):
    """Co drží panel podle posledni_stav.json, ve tvaru pro VystupEink.

    Bez tohohle by první útěk z menu po zapnutí čtečky překreslil panel tím
    samým textem, který na něm je — 29 s za nic. `stranka` je v souboru index,
    Snimek.cislo_stranky počítá od jedné.
    """
    if not stav or stav.get("typ") != "cteni":
        return None
    return (stav.get("kniha"), stav.get("stranka", 0) + 1)


def hlas_nacitani(oled, perioda=PERIODA_HLASENI):
    """Vrátí callback pro knihovna.obsluz(), který kreslí postup na OLED.

    Parser ho volá po každé kapitole a stránkování po každém bloku, což je u
    velké knihy tisíckrát za načtení. Překreslovat tolikrát by parsování jen
    prodloužilo, takže se propustí nejvýš jedno překreslení za `perioda`
    sekund. Poslední hlášený podíl se dokreslí až tím dalším povoleným — na
    hrubém ukazateli širokém 128 px se to nepozná.
    """
    posledni = [0.0]

    def hlas(podil):
        ted = time.monotonic()
        if ted - posledni[0] < perioda:
            return
        posledni[0] = ted
        oled.hlaseni("Načítám…", podil)

    return hlas


class Akcelerace:
    """Jak velký krok si zaslouží tohle cvaknutí kodéru — podle rychlosti ruky.

    Drží jediný údaj: kdy se cvaklo naposled. Krok se z něj počítá, nikde se
    neakumuluje žádná „rychlost" — stav, který by se musel stárnout a resetovat,
    je u věci řízené hodinami zbytečný a rozchází se, když se ruka zastaví.

    Sáhne na ni callback kodéru (cizí vlákno) i hlavní smyčka, proto zámek.
    Je to jen čtení a zápis jednoho floatu, stejně jako u Hlidace.
    """

    def __init__(self, prah=PRAH_ZRYCHLENI, zrychleny=KROK_ZRYCHLENY):
        self._prah = prah
        self._zrychleny = zrychleny
        self._zamek = threading.Lock()
        self._posledni = None

    def krok(self, ted=None):
        """Zaznamená cvaknutí a vrátí, o kolik stránek se má posunout."""
        ted = time.monotonic() if ted is None else ted
        with self._zamek:
            predchozi = self._posledni
            self._posledni = ted
        # První cvaknutí po pauze je vždy jednotkové: uživatel míří, netočí.
        if predchozi is None or ted - predchozi >= self._prah:
            return KROK_ZAKLADNI
        return self._zrychleny

    def je_klid(self, ted=None, prodleva=PRODLEVA_SMERU):
        """True, když se od posledního cvaknutí nic neděje — šipky můžou zhasnout."""
        ted = time.monotonic() if ted is None else ted
        with self._zamek:
            posledni = self._posledni
        return posledni is None or ted - posledni >= prodleva


def faze_tickeru(polozka_od, ted=None):
    """Posun názvu v pixelech od chvíle, kdy se položka objevila.

    Počítá se z uplynulého času, ne z počtu překreslení — smyčku může zdržet
    sken složky nebo zápis pozice a text by se pak trhal. Prvních
    PRODLEVA_TICKERU sekund stojí, aby se dal přečíst začátek.
    """
    ubehlo = (time.monotonic() if ted is None else ted) - polozka_od
    return max(0, int((ubehlo - PRODLEVA_TICKERU) * RYCHLOST_TICKERU))


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
        self.zhasnuto = False

    def zhasni(self):
        """Vypne panel po deseti minutách nečinnosti.

        luma zná hide()/show(); atrapa v testech nemusí, tak se pro ni pošle
        prázdný obraz — na SSD1306 je černá skoro zadarmo a rozdíl proti
        skutečnému vypnutí segmentu je v mA, ne v jednotkách.
        """
        if self.zhasnuto:
            return
        self.zhasnuto = True
        if hasattr(self._zarizeni, "hide"):
            self._zarizeni.hide()
        else:
            self._zarizeni.display(oled_ui.vykresli_hlaseni("", self._fonty))
        self._posledni = None

    def rozsvit(self):
        """Probuzení. Vyhazuje i porovnávací cache: co panel ukazuje po hide(),
        záleží na knihovně, a hádat to znamená risk, že zůstane tmavý."""
        if not self.zhasnuto:
            return
        self.zhasnuto = False
        if hasattr(self._zarizeni, "show"):
            self._zarizeni.show()
        self._posledni = None

    def prekresli(self, snimek, faze=0):
        # Jediný strážce pro všechna volací místa ve smyčce — ticker i stavový
        # řádek tím při spánku umlknou samy a nikde se na to nemusí myslet.
        if self.zhasnuto:
            return False
        obraz = oled_ui.vykresli_oled(snimek, self._fonty, faze)
        data = obraz.tobytes()
        if data == self._posledni:
            return False
        self._posledni = data
        self._zarizeni.display(obraz)
        return True

    def hlaseni(self, text, podil=None):
        """Okamžitě promaže displej a vypíše vycentrovanou hlášku.

        `podil` (0–1) přikreslí pod text ukazatel postupu.

        Obchází porovnání s posledním obrazem — hláška se musí objevit i
        tehdy, když by shodou okolností vyšla stejně jako to, co už na
        displeji je.
        """
        obraz = oled_ui.vykresli_hlaseni(text, self._fonty, podil)
        self._posledni = obraz.tobytes()
        self._zarizeni.display(obraz)


def pripoj_tlacitka(ctecka, hlidac=None):
    """Naváže listovací tlačítka na stav. Volající si vrácený seznam musí
    podržet — zapomenuté Button objekty sebere garbage collector a tlačítka
    umlknou.

    Zbyla z nich jen dvojice pro otáčení stránek. Do menu a zpátky se chodí
    tlačítkem v kodéru (viz pripoj_enkoder), takže tyhle dvě nemají žádnou
    dlouhostiskovou větev.

    Callbacky jen mění stav a budí smyčku. Žádný z nich nic nenačítá.
    """
    dalsi = Button(PIN_DALSI, bounce_time=DOBA_ZAKMITU)
    predchozi = Button(PIN_PREDCHOZI, bounce_time=DOBA_ZAKMITU)

    dalsi.when_pressed = probouzeci(ctecka, hlidac, ctecka.dalsi)
    predchozi.when_pressed = probouzeci(ctecka, hlidac, ctecka.predchozi)

    return [dalsi, predchozi]


def probouzeci(ctecka, hlidac, co_udelat):
    """Obalí callback hlídačem nečinnosti.

    Ze spánku první vstup jen rozsvítí a **svou akci neprovede** — o tom, jestli
    se spalo, rozhoduje hlídač, ne volající. Probuzení se hlásí smyčce přes
    vyzadej_prekresleni(): callback sám kreslit nesmí a tohle je jediná cesta,
    jak ji hned probudit. Při čtení tím e-ink netrpí — VystupEink pozná, že by
    psal tentýž text, a panel nechá být.

    Bez hlídače (hlidac=None) se chová jako holý callback, aby šlo tlačítka
    navěsit i bez správy napájení.
    """

    def obsluha():
        if hlidac is not None and hlidac.zaznamenej_vstup():
            ctecka.vyzadej_prekresleni()
            return
        co_udelat()

    return obsluha


def pripoj_enkoder(ctecka, hlidac=None, akcelerace=None):
    """Naváže rotační kodér na stav. Vrácený seznam si volající musí podržet.

    Tlačítko v kodéru obsluhuje celé menu samo:

        krátký stisk při čtení  → otevře menu (jen OLED, e-ink se nechává být)
        krátký stisk v menu     → potvrdí položku pod kurzorem
        dlouhý stisk kdekoliv   → útěk zpátky do knihy, taky jen po OLEDu

    Otáčení naopak zůstává hluché při čtení: stránky patří tlačítkům u e-inku
    a nechtěné cvrnknutí do kodéru by jinak spustilo ~29s překreslení panelu.

    Chybějící nebo špatně zapojený kodér čtečku nepoloží — menu se pak ovládá
    tlačítky jako dřív. Stejný přístup jako u displeje: nepřítomné železo se
    obejde, ne odnese celý program.
    """
    try:
        kolecko = RotaryEncoder(PIN_ENKODER_CLK, PIN_ENKODER_DT, max_steps=0)
        tlacitko = Button(
            PIN_ENKODER_SW, bounce_time=DOBA_ZAKMITU, hold_time=DOBA_DRZENI_ENKODER
        )
    except Exception as e:
        logging.warning("Rotační kodér není dostupný (%s), pokračuji bez něj.", e)
        return []

    # Vlastní instance, když ji volající nedodal — kodér musí jít navěsit i
    # samostatně (testy, čtečka bez správy napájení).
    if akcelerace is None:
        akcelerace = Akcelerace()

    # Otáčení smí i při rychlém listování — tam je právě k tomu. Hluché
    # zůstává jen při běžném čtení, kde stránky patří tlačítkům u e-inku.
    #
    # Krok se počítá až tady, po kontrole stavu: cvaknutí, které se má
    # ignorovat, nesmí posunout ani měřený čas, jinak by první platné cvaknutí
    # po chvíli točení při čtení naskočilo rovnou jako zrychlené.
    def jen_po_oledu(co_udelat):
        def obsluha():
            if ctecka.snimek().stav is not Stav.CTENI:
                co_udelat(akcelerace.krok())

        return obsluha

    # Probuzení se řeší až za kontrolou stavu: otáčení má při čtení mlčet,
    # ale ze spánku musí rozsvítit i ono.
    kolecko.when_rotated_clockwise = probouzeci(ctecka, hlidac, jen_po_oledu(ctecka.dalsi))
    kolecko.when_rotated_counter_clockwise = probouzeci(
        ctecka, hlidac, jen_po_oledu(ctecka.predchozi)
    )

    # Krátký stisk se vyhodnotí až při uvolnění a jen tehdy, když mezitím
    # nepřišlo when_held. Kdyby visel na when_pressed, dlouhý stisk by nejdřív
    # potvrdil položku pod kurzorem (stisk přijde okamžitě) a teprve pak utekl
    # do knihy — držení nad knihou by pokaždé spustilo stránkování.
    drzeno = False
    # Probouzecí stisk se nedá obalit jako u ostatních vstupů: jedno stisknutí
    # je tady trojice callbacků a rozhodnout se musí hned na začátku gesta.
    # Kdyby se hlídač ptal až při uvolnění, when_pressed by systém probudilo a
    # uvolnění by pak vidělo bdělou čtečku a potvrdilo položku pod kurzorem —
    # tedy přesně to, čemu má polykání zabránit. Vlajka proto drží celé gesto
    # a shazuje ji až další stisk.
    probouzi = False

    def na_stisku():
        nonlocal drzeno, probouzi
        drzeno = False
        probouzi = hlidac is not None and hlidac.zaznamenej_vstup()
        if probouzi:
            ctecka.vyzadej_prekresleni()

    def na_drzeni():
        nonlocal drzeno
        drzeno = True
        if not probouzi:
            # Větvení podle stavu je uvnitř dlouhy_stisk(), stejně jako u
            # akce() — jinak by ho simulátor musel opsat a rozešel by se
            # s železem.
            ctecka.dlouhy_stisk()

    def na_uvolneni():
        # Větvení podle stavu je uvnitř akce(): v menu potvrdí položku, při
        # čtení otevře menu a při rychlém listování potvrdí vybranou stránku.
        # Díky tomu jede simulátor na téže cestě, i když žádný kodér nemá.
        if not drzeno and not probouzi:
            ctecka.akce()

    tlacitko.when_pressed = na_stisku
    tlacitko.when_held = na_drzeni
    tlacitko.when_released = na_uvolneni

    return [kolecko, tlacitko]


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")

    fonty = vykresleni.nacti_fonty()

    # Obnova posledního stavu bez překreslení: po zapnutí panel drží obraz,
    # kde jsi skončil, a čtečka na něj naváže. Když nic uloženého není (první
    # spuštění), startuje se v menu s běžným překreslením.
    ulozeny = knihovna.nacti_posledni_stav()
    ctecka = Ctecka(knihovna.nacti_strom(), prekreslit_na_startu=ulozeny is None)
    if ulozeny is not None and not knihovna.obnov_posledni_stav(ctecka, fonty):
        # Uložený stav neseděl (např. smazaná kniha) — panel drží něco jiného,
        # ať se překreslí, aby displej odpovídal skutečnosti.
        ctecka.vyzadej_prekresleni()
        ulozeny = None

    obrazovka = VystupEink(displej.vytvor_displej(), fonty, otisk_ulozeneho(ulozeny))
    oled = VystupOled(oled_ui.vytvor_oled(), oled_ui.nacti_fonty())
    # Konstanty se čtou až tady, ne jako výchozí hodnoty parametrů — testy si je
    # tak můžou přenastavit na zlomky sekundy.
    hlidac = Hlidac(DOBA_DO_SPANKU, DOBA_DO_VYPNUTI)
    akcelerace = Akcelerace()
    ovladace = pripoj_tlacitka(ctecka, hlidac) + pripoj_enkoder(
        ctecka, hlidac, akcelerace
    )
    vypnout = False

    # Panel sice drží obraz i bez napájení, ale první display() ho celý
    # přepíše, takže vybílit ho předtím jen zdvojuje čekání na první stránku.
    if PERIODA_CISTENI:
        obrazovka.vycisti()
    od_cisteni = 0

    # OLED je po zapnutí prázdný, takže se vykreslí rovnou — na rozdíl od
    # e-inku ho to nic nestojí a uživatel hned vidí, kde čtečka stojí.
    oled.prekresli(ctecka.snimek())
    # Okamžik, kdy se na OLEDu objevila aktuální položka. Od něj se odvozuje
    # posun názvu, takže rychlost nezávisí na tom, jak často se smyčka protočí.
    polozka_od = time.monotonic()
    posledni_sken = 0.0

    try:
        while not ctecka.konec:
            stav = ctecka.snimek().stav
            v_menu = stav is Stav.MENU
            # Rychlé listování je z pohledu smyčky totéž co menu: kreslí se jen
            # po OLEDu a e-ink se nesmí dotknout, jinak by každé cvaknutí
            # kodéru stálo ~29 s a celý režim by ztratil smysl. Tik je proto
            # taky krátký — displej musí stíhat za rukou.
            jen_oled = v_menu or stav is Stav.RYCHLE_LISTOVANI

            # Šipky směru zhasnou, když ruka pustí kodér. Je to důsledek
            # uplynulého času, ne vstupu, takže to nemá kdo ohlásit — musí se
            # na to ptát smyčka. Překreslení si vyžádá jen skutečná změna.
            if stav is Stav.RYCHLE_LISTOVANI and akcelerace.je_klid():
                ctecka.zklidni_listovani()

            # Úsporu vyhodnocuje smyčka, ne callback: zhasnout a rozsvítit
            # znamená sáhnout na I2C, a to do cizího vlákna nepatří. Srovnává
            # se skutečný stav displeje s fází, takže se nemůže ztratit ani
            # probuzení, které přišlo uprostřed předchozího průchodu.
            faze = hlidac.faze()
            if faze is Uspora.VYPNUTI:
                # Nejdřív se korektně ukončí smyčka; vypnutí přijde až po úklidu
                # GPIO a I2C ve finally, ne odsud.
                vypnout = True
                ctecka.ukonci()
                break
            spi = faze is Uspora.SPANEK
            if spi:
                oled.zhasni()
            elif oled.zhasnuto:
                # Překreslí se rovnou tady, ne až přes vlajku od probouzecího
                # vstupu: tu smyčka spotřebuje ještě v témže průchodu, kdy je
                # displej zhasnutý, takže ji strážce ve VystupOled zahodí. V
                # menu by to zachránil ticker v dalším průchodu, při čtení ale
                # žádný není a OLED by zůstal prázdný až do otočení stránky.
                oled.rozsvit()
                oled.prekresli(ctecka.snimek())

            # Vlajku shodí cekej_na_prekresleni() ještě před renderem. Stisk,
            # který přijde během zápisu na e-ink, ji tak nastaví znovu a smyčka
            # překreslí ještě jednou, místo aby se ztratil.
            tik = TIK_SPANKU if spi else (TIK_MENU if jen_oled else TIK_CTENI)
            if ctecka.cekej_na_prekresleni(tik):
                snimek = ctecka.snimek()
                polozka_od = time.monotonic()  # nová položka se čte od začátku

                if snimek.stav is not Stav.CTENI:
                    # Menu i rychlé listování jedou jen po OLEDu. Tady je to
                    # jediné místo, kde se e-ink obchází, takže podmínka musí
                    # být na "není CTENI", ne výčet stavů — nový stav, který by
                    # se do výčtu zapomněl dopsat, by na panel začal psát.
                    # E-ink se schválně nechává být:
                    # jeho refresh trvá ~10 s a při listování knihovnou by byl
                    # k ničemu. Drží dál poslední stránku, což je i to, co
                    # popisuje posledni_stav.json.
                    oled.prekresli(snimek, 0)
                else:
                    if PERIODA_CISTENI and od_cisteni >= PERIODA_CISTENI:
                        obrazovka.vycisti()
                        od_cisteni = 0
                    # Stránka jde na e-ink, OLED k ní ukáže jen číslo stránky.
                    # Při čtení se název neposouvá — smyčka se sem dostane
                    # jednou za otočení stránky, takže by to stejně jen cukalo.
                    oled.prekresli(snimek, 0)
                    # Útěk z menu zpátky do knihy sem taky spadne, ale panel
                    # už ten text ukazuje, takže zobraz() nic nepošle a čtecí
                    # rozhraní se obnoví jen na OLEDu.
                    if obrazovka.zobraz(ctecka):
                        od_cisteni += 1
            elif v_menu:
                # Vypršel tik a nikdo nic nezmáčkl — jen se poposune dlouhý
                # název. Když se celý vejde, prekresli() nepošle na I2C nic,
                # takže statická položka nestojí ani jeden zápis na sběrnici.
                oled.prekresli(ctecka.snimek(), faze_tickeru(polozka_od))

            # Drahá práce patří sem, ne do callbacku tlačítka. Než se do ní
            # smyčka pustí, dostane uživatel odezvu: parsování a stránkování
            # knihy trvá na Pi Zero W ~16 s a po tu dobu se smyčka nevrátí.
            if ctecka.snimek().nacita_se:
                oled.hlaseni("Načítám…", 0.0)
                knihovna.obsluz(ctecka, fonty, hlas=hlas_nacitani(oled))
            else:
                knihovna.obsluz(ctecka, fonty)

            # Nové knihy a složky se tím ukážou samy, bez restartu. Skenuje se
            # po PERIODA_SKENU, ne při každém průchodu: v menu se smyčka točí
            # sedmkrát za sekundu a tolik výpisů adresáře je zbytečné.
            # Ve spánku se neskenuje: sahat na SD kartu dvakrát za sekundu po
            # dobu padesáti minut je pravý opak úspory a nikdo se stejně nedívá.
            # Jen v menu: při rychlém listování je uživatel v knize a nové
            # soubory ho nezajímají.
            ted = time.monotonic()
            if v_menu and not spi and ted - posledni_sken >= PERIODA_SKENU:
                posledni_sken = ted
                ctecka.nastav_seznam_knih(knihovna.nacti_strom())

    except KeyboardInterrupt:
        pass
    finally:
        logging.info("Ukončuji čtečku, vypínám displej...")
        for ovladac in ovladace:
            ovladac.close()
        obrazovka.vypni()

    # Až po úklidu: poweroff sestřelí systém pod rukama, takže se GPIO a I2C
    # musí pustit dřív, ne až se to bude hodit.
    if vypnout:
        vypni_system()


if __name__ == "__main__":
    main()
