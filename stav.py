"""Konečný automat čtečky — čistá logika bez vazby na hardware.

Modul záměrně neimportuje PIL, gpiozero ani Flask. Veškeré I/O (parsování
EPUBu, čtení a zápis pozice, kreslení) obstarává volající; třída Ctecka drží
jen stav a odkaz na již načtená data, do kterých nenahlíží.

Parsování knihy je na Pi Zero W drahé (desítky sekund), a proto se nesmí dít
ve vlákně tlačítka. Řeší se to požadavkem: stisk požadavek pouze zaeviduje,
hlavní smyčka si jej vyzvedne, provede parsování a výsledek vrátí zpět.

Očekávaná hlavní smyčka:

    while not ctecka.konec:
        if ctecka.cekej_na_prekresleni(timeout=1.0):
            vykresli(ctecka.snimek())

        nazev = ctecka.vyzvedni_pozadavek()
        if nazev:
            stranky = zpracovani_epub.nacti(...)
            ctecka.dodej_stranky(nazev, stranky, nacti_pozici(nazev))

        pozice = ctecka.vyzvedni_pozici_k_ulozeni()
        if pozice:
            uloz_pozici(*pozice)

Pořadí je podstatné: požadavek se vyzvedává až po vykreslení, aby se stihla
zobrazit hláška "Načítám…" dřív, než smyčku na desítky sekund zablokuje parser.
"""

import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Stav(StrEnum):
    MENU = "MENU"
    CTENI = "CTENI"


@dataclass(frozen=True)
class Snimek:
    """Konzistentní kopie stavu pro jedno vykreslení.

    Vzniká pod zámkem, takže se nemůže stát, že by vykreslování četlo stav
    rozpůlený stiskem tlačítka (např. stav CTENI, ale už prázdné stránky).
    """

    stav: Stav
    seznam_knih: tuple[str, ...]
    vyber: int
    kniha: str | None
    stranka: Any | None  # data aktuální stránky, pro tuto třídu neprůhledná
    cislo_stranky: int
    pocet_stranek: int
    nacita_se: bool
    chyba: str | None


class Ctecka:
    """Stav čtečky a přechody mezi MENU a CTENI.

    Metody dalsi(), predchozi(), akce() a ukonci() jsou určené pro obsluhu
    tlačítek a smí se volat z cizích vláken. Ostatní metody patří hlavní smyčce.
    """

    def __init__(self, seznam_knih=None):
        self._zamek = threading.Condition()

        self._stav = Stav.MENU
        self._seznam_knih: list[str] = []
        self._vyber = 0

        self._kniha: str | None = None
        self._stranky: list[Any] = []
        self._stranka = 0

        self._pozadavek: str | None = None  # čeká na vyzvednutí
        self._nacitana: str | None = None  # vyzvednuto, právě se parsuje
        self._chyba: str | None = None

        self._pozice_k_ulozeni: tuple[str, int] | None = None
        self._prekreslit = True
        self._konec = False

        if seznam_knih is not None:
            self.nastav_seznam_knih(seznam_knih)

    # --- STAV PRO VYKRESLENÍ ---

    def snimek(self):
        with self._zamek:
            stranka = None
            if self._stav is Stav.CTENI and 0 <= self._stranka < len(self._stranky):
                stranka = self._stranky[self._stranka]

            return Snimek(
                stav=self._stav,
                seznam_knih=tuple(self._seznam_knih),
                vyber=self._vyber,
                kniha=self._kniha,
                stranka=stranka,
                cislo_stranky=self._stranka + 1,
                pocet_stranek=len(self._stranky),
                nacita_se=self._nacita_se(),
                chyba=self._chyba,
            )

    @property
    def konec(self):
        with self._zamek:
            return self._konec

    def spotrebuj_prekresleni(self):
        """Neblokující: vrátí True a shodí vlajku, je-li potřeba překreslit."""
        with self._zamek:
            if self._prekreslit:
                self._prekreslit = False
                return True
            return False

    def cekej_na_prekresleni(self, timeout=None):
        """Blokuje, dokud není potřeba překreslit, dokud nepřijde požadavek na
        ukončení, nebo dokud nevyprší timeout. Vlajku shodí atomicky.

        Vlajka se shazuje před vykreslením, ne po něm: stisk tlačítka, který
        přijde během několikasekundového refreshe e-inku, tak nastaví vlajku
        znovu a smyčka rovnou překreslí ještě jednou.
        """
        with self._zamek:
            if not self._prekreslit and not self._konec:
                self._zamek.wait(timeout)
            if self._prekreslit:
                self._prekreslit = False
                return True
            return False

    # --- KNIHOVNA ---

    def nastav_seznam_knih(self, seznam):
        """Nahradí seznam knih tím, co našla hlavní smyčka ve složce.

        Výběr se drží na téže knize, i když se seznam kolem ní změnil.
        Vrací True, pokud se seznam skutečně změnil — když ne, nepřekresluje
        se, protože refresh e-inku trvá sekundy a nemá smysl na tentýž obsah.
        """
        novy = sorted(seznam)
        with self._zamek:
            if novy == self._seznam_knih:
                return False

            drzena = (
                self._seznam_knih[self._vyber]
                if 0 <= self._vyber < len(self._seznam_knih)
                else None
            )
            self._seznam_knih = novy
            if drzena in novy:
                self._vyber = novy.index(drzena)
            else:
                self._vyber = min(self._vyber, max(0, len(novy) - 1))

            self._zadej_prekresleni()
            return True

    # --- OBSLUHA TLAČÍTEK (volá se z cizích vláken) ---

    def dalsi(self):
        """Další kniha v menu / další stránka v knize."""
        self._posun(1)

    def predchozi(self):
        """Předchozí kniha v menu / předchozí stránka v knize."""
        self._posun(-1)

    def akce(self):
        """Krátký stisk: v menu otevře knihu, při čtení se vrátí do menu."""
        with self._zamek:
            if self._konec or self._nacita_se():
                return

            if self._stav is Stav.MENU:
                if not self._seznam_knih:
                    return
                self._pozadavek = self._seznam_knih[self._vyber]
                self._chyba = None
                self._zadej_prekresleni()
            else:
                self._zpet_do_menu()

    def zpet_do_menu(self):
        with self._zamek:
            self._zpet_do_menu()

    def ukonci(self):
        """Dlouhý stisk: požadavek na ukončení programu."""
        with self._zamek:
            self._konec = True
            self._zamek.notify_all()

    # --- PŘEDÁVÁNÍ DRAHÝCH DAT (volá hlavní smyčka) ---

    def vyzvedni_pozadavek(self):
        """Atomicky vyjme název knihy, kterou má hlavní smyčka načíst.

        Dokud nepřijde dodej_stranky(), zůstává nacita_se == True, takže se
        dá zobrazit hláška a další stisky se ignorují.
        """
        with self._zamek:
            pozadavek = self._pozadavek
            if pozadavek is not None:
                self._pozadavek = None
                self._nacitana = pozadavek
            return pozadavek

    def dodej_stranky(self, nazev, stranky, pocatecni_stranka=0):
        """Předá načtená data a přepne do stavu CTENI.

        `stranky` je libovolný indexovatelný seznam — třída se do něj nedívá.
        Prázdný seznam znamená neúspěch parsování: zůstane se v menu a nastaví
        se chyba. Vrací True, pokud byla dodávka přijata.
        """
        with self._zamek:
            if nazev != self._nacitana:
                return False  # zastaralá dodávka, o tuhle knihu už nikdo nestojí
            self._nacitana = None

            if not stranky:
                self._chyba = f"Knihu {nazev} se nepodařilo načíst."
                self._zadej_prekresleni()
                return False

            self._kniha = nazev
            self._stranky = stranky
            self._stranka = max(0, min(pocatecni_stranka, len(stranky) - 1))
            self._stav = Stav.CTENI
            self._chyba = None
            self._zadej_prekresleni()
            return True

    def vyzvedni_pozici_k_ulozeni(self):
        """Vrátí (kniha, stranka) k zápisu na disk, nebo None.

        Volá se po vykreslení. Několik otočení stránek během jednoho refreshe
        se tím sloučí do jediného zápisu na SD kartu.
        """
        with self._zamek:
            pozice = self._pozice_k_ulozeni
            self._pozice_k_ulozeni = None
            return pozice

    # --- VNITŘNÍ (volat jen se zámkem) ---

    def _posun(self, smer):
        with self._zamek:
            if self._konec or self._nacita_se():
                return

            if self._stav is Stav.MENU:
                novy = self._vyber + smer
                if 0 <= novy < len(self._seznam_knih):
                    self._vyber = novy
                    self._zadej_prekresleni()
            else:
                novy = self._stranka + smer
                if 0 <= novy < len(self._stranky):
                    self._stranka = novy
                    self._pozice_k_ulozeni = (self._kniha, novy)
                    self._zadej_prekresleni()

    def _zpet_do_menu(self):
        # Rozpracované načítání se ruší: parser v hlavní smyčce sice doběhne,
        # ale dodej_stranky() jeho výsledek odmítne jako zastaralý. Bez toho by
        # návrat do menu během parsování knihu za chvíli stejně otevřel.
        zrusene_nacitani = self._nacita_se()
        self._pozadavek = None
        self._nacitana = None

        if self._stav is Stav.MENU and not zrusene_nacitani:
            return

        self._stav = Stav.MENU
        # Stránky se zahazují kvůli paměti: obrázky celé knihy se na 512 MB
        # Pi Zero W nevyplatí držet, dokud si uživatel prohlíží menu. Cenou je
        # nové parsování při opětovném otevření téže knihy.
        self._stranky = []
        self._kniha = None
        self._stranka = 0
        self._zadej_prekresleni()

    def _nacita_se(self):
        return self._pozadavek is not None or self._nacitana is not None

    def _zadej_prekresleni(self):
        self._prekreslit = True
        self._zamek.notify_all()
