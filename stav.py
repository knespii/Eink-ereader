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
    # Listování stránkami jen po OLEDu: e-ink se nedotkne, dokud uživatel
    # výběr nepotvrdí. Bez toho by každé cvrnknutí kodéru stálo ~29 s.
    RYCHLE_LISTOVANI = "RYCHLE_LISTOVANI"


class Typ(StrEnum):
    """Druh položky v menu. ZPET je syntetická položka "..", na disku není."""

    SLOZKA = "slozka"
    KNIHA = "kniha"
    ZPET = "zpet"


@dataclass(frozen=True)
class Polozka:
    """Jeden řádek menu. `cesta` je relativní ke složce knih, u ZPET prázdná."""

    typ: Typ
    nazev: str
    cesta: str = ""


# Položka pro návrat z adresáře o úroveň výš. Je vždy první v pořadí, takže
# otočení kodéru doleva z první knihy vede rovnou na ni.
POLOZKA_ZPET = Polozka(typ=Typ.ZPET, nazev="..")


@dataclass(frozen=True)
class Snimek:
    """Konzistentní kopie stavu pro jedno vykreslení.

    Vzniká pod zámkem, takže se nemůže stát, že by vykreslování četlo stav
    rozpůlený stiskem tlačítka (např. stav CTENI, ale už prázdné stránky).
    """

    stav: Stav
    seznam_knih: tuple[str, ...]  # jen názvy, pro zpětnou kompatibilitu vykreslení
    polozky: tuple[Polozka, ...]  # obsah aktuálního adresáře včetně ".."
    adresar: str  # relativní cesta otevřené složky, "" = kořen
    vyber: int
    kniha: str | None  # relativní cesta otevřené knihy
    kniha_nazev: str | None  # jen jméno souboru, k zobrazení
    stranka: Any | None  # data aktuální stránky, pro tuto třídu neprůhledná
    cislo_stranky: int
    pocet_stranek: int
    nacita_se: bool
    chyba: str | None
    # Číslo stránky (1..N), na které se stálo při vstupu do RYCHLE_LISTOVANI.
    # Mimo tento stav je rovné cislo_stranky a nikdo se na něj nedívá.
    puvodni_cislo_stranky: int = 0


class Ctecka:
    """Stav čtečky a přechody mezi MENU a CTENI.

    Metody dalsi(), predchozi(), akce() a ukonci() jsou určené pro obsluhu
    tlačítek a smí se volat z cizích vláken. Ostatní metody patří hlavní smyčce.
    """

    def __init__(self, seznam_knih=None, prekreslit_na_startu=True):
        self._zamek = threading.Condition()

        self._stav = Stav.MENU
        # Celá knihovna: {"": [položky kořene], "slozka": [položky složky]}.
        # Ctecka nesmí sahat na disk, takže strom dodává hlavní smyčka a
        # navigace ve složkách se pak obejde bez I/O.
        self._strom: dict[str, tuple[Polozka, ...]] = {"": ()}
        self._adresar = ""  # "" = kořen
        self._vyber = 0

        self._kniha: str | None = None
        self._stranky: list[Any] = []
        self._stranka = 0
        # Kam se vrátit, když uživatel rychlé listování zruší.
        self._puvodni_stranka = 0

        self._pozadavek: str | None = None  # čeká na vyzvednutí
        self._nacitana: str | None = None  # vyzvednuto, právě se parsuje
        self._chyba: str | None = None

        self._pozice_k_ulozeni: tuple[str, int] | None = None
        self._prekreslit = True
        self._konec = False

        if seznam_knih is not None:
            self.nastav_seznam_knih(seznam_knih)

        # Nastavuje se až nakonec: nastav_seznam_knih() výše si vyžádá
        # překreslení, ale při obnově po startu ho nechceme — e-ink drží obraz
        # z minula, takže se nemá co překreslovat, dokud uživatel nezmáčkne.
        self._prekreslit = prekreslit_na_startu

    # --- STAV PRO VYKRESLENÍ ---

    def snimek(self):
        with self._zamek:
            stranka = None
            if self._stav is not Stav.MENU and 0 <= self._stranka < len(self._stranky):
                stranka = self._stranky[self._stranka]

            polozky = self._pohled()
            return Snimek(
                stav=self._stav,
                seznam_knih=tuple(p.nazev for p in polozky),
                polozky=polozky,
                adresar=self._adresar,
                vyber=self._vyber,
                kniha=self._kniha,
                kniha_nazev=self._kniha.rpartition("/")[2] if self._kniha else None,
                stranka=stranka,
                cislo_stranky=self._stranka + 1,
                pocet_stranek=len(self._stranky),
                nacita_se=self._nacita_se(),
                chyba=self._chyba,
                puvodni_cislo_stranky=self._puvodni_stranka + 1,
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

    def nastav_seznam_knih(self, strom):
        """Nahradí knihovnu tím, co našla hlavní smyčka na disku.

        `strom` je buď {adresar: [položky]} z knihovna.nacti_strom(), nebo
        plochý seznam knih — ten se bere jako obsah kořene, aby staré volání
        a testy bez složek fungovaly dál.

        Výběr se drží na téže položce, i když se seznam kolem ní změnil.
        Vrací True, pokud se knihovna skutečně změnila — když ne, nepřekresluje
        se, protože refresh e-inku trvá sekundy a nemá smysl na tentýž obsah.
        """
        novy = self._normalizuj_strom(strom)
        with self._zamek:
            if novy == self._strom:
                return False

            drzena = self._pohled()
            drzena = drzena[self._vyber].cesta if 0 <= self._vyber < len(drzena) else None

            self._strom = novy
            # Otevřená složka mohla zmizet — pak se vracíme do kořene, jinak by
            # menu ukazovalo prázdno bez cesty ven.
            if self._adresar not in self._strom:
                self._adresar = ""

            polozky = self._pohled()
            cesty = [p.cesta for p in polozky]
            if drzena and drzena in cesty:
                self._vyber = cesty.index(drzena)
            else:
                self._vyber = min(self._vyber, max(0, len(polozky) - 1))

            self._zadej_prekresleni()
            return True

    @staticmethod
    def _normalizuj_strom(strom):
        """Sjednotí vstup na {adresar: tuple[Polozka]} se stabilním pořadím.

        Přijímá Polozka i prosté dicty z knihovny — ta o téhle třídě nemá vědět,
        takže si položky předávají jako data, ne jako typy.
        """
        if not isinstance(strom, dict):
            strom = {"": strom}

        vysledek = {}
        for adresar, polozky in strom.items():
            prevedene = []
            for p in polozky:
                if isinstance(p, Polozka):
                    prevedene.append(p)
                elif isinstance(p, dict):
                    prevedene.append(
                        Polozka(
                            typ=Typ(p["typ"]),
                            nazev=p["nazev"],
                            cesta=p.get("cesta", p["nazev"]),
                        )
                    )
                else:  # holý řetězec = kniha v kořeni (staré volání)
                    prevedene.append(Polozka(typ=Typ.KNIHA, nazev=p, cesta=p))
            # Složky napřed, pak knihy — na jednořádkovém OLEDu se jinak
            # uživatel k podsložkám doroluje až někde uprostřed abecedy.
            prevedene.sort(key=lambda p: (p.typ is not Typ.SLOZKA, p.nazev))
            vysledek[adresar] = tuple(prevedene)

        vysledek.setdefault("", ())
        return vysledek

    def _pohled(self):
        """Obsah aktuálního adresáře včetně ".." — volat jen se zámkem."""
        polozky = self._strom.get(self._adresar, ())
        if self._adresar:
            return (POLOZKA_ZPET,) + polozky
        return polozky

    # --- OBNOVENÍ POSLEDNÍHO STAVU PO STARTU ---
    # Obnova záměrně nevyžaduje překreslení: panel drží obraz z minula, takže
    # displej už tu správnou věc ukazuje. První stisk tlačítka pak překreslí.

    def obnov_cteni(self, nazev, stranky, stranka):
        """Vrátí čtečku do knihy na danou stránku, bez vyžádání překreslení."""
        if not stranky:
            return False
        with self._zamek:
            self._kniha = nazev
            self._stranky = stranky
            self._stranka = max(0, min(stranka, len(stranky) - 1))
            self._puvodni_stranka = self._stranka
            self._stav = Stav.CTENI
            return True

    def obnov_menu(self, vyber, adresar=""):
        """Vrátí kurzor v menu na danou položku, bez vyžádání překreslení.

        Neznámý adresář se tiše ignoruje (složka mezitím zmizela) — zůstane se
        v kořeni, protože prázdné menu bez cesty ven je horší než špatný výběr.
        """
        with self._zamek:
            if adresar in self._strom:
                self._adresar = adresar
            polozky = self._pohled()
            if polozky:
                self._vyber = max(0, min(vyber, len(polozky) - 1))

    def vyzadej_prekresleni(self):
        """Vynutí překreslení. Používá se, když obnova po startu neseděla a
        panel drží obraz, který už neodpovídá stavu."""
        with self._zamek:
            self._zadej_prekresleni()

    # --- OBSLUHA TLAČÍTEK (volá se z cizích vláken) ---

    def dalsi(self):
        """Další kniha v menu / další stránka v knize."""
        self._posun(1)

    def predchozi(self):
        """Předchozí kniha v menu / předchozí stránka v knize."""
        self._posun(-1)

    def akce(self):
        """Krátký stisk tlačítka v kodéru — jediné potvrzovací tlačítko čtečky.

        V menu podle druhu položky: vstoupí do složky, vrátí se přes "..", nebo
        otevře knihu. Při čtení otevře menu nad rozečtenou knihou, aby se dalo
        dlouhým stiskem uteču zpátky, aniž by se cokoli stránkovalo znovu.

        Vstup do složky i návrat jsou čistě práce s pamětí, takže je bezpečné
        je vyřídit rovnou tady, v cizím vlákně. Načtení knihy zůstává jako
        požadavek pro hlavní smyčku — parsování trvá na Pi Zero W ~16 s.
        """
        with self._zamek:
            if self._konec or self._nacita_se():
                return

            if self._stav is Stav.RYCHLE_LISTOVANI:
                # Uprostřed listování je krátký stisk potvrzení výběru, ne
                # cesta do menu — tam se dostane až dalším stiskem při čtení.
                self._potvrd_rychle_listovani()
                return

            if self._stav is not Stav.MENU:
                # Ne _zpet_do_menu(): ta stránky zahazuje, takže by se dlouhý
                # stisk neměl kam vrátit. Zůstává jako veřejná metoda pro
                # případ, kdy je opravdu potřeba knihu zavřít.
                self._otevri_menu()
                return

            polozky = self._pohled()
            if not (0 <= self._vyber < len(polozky)):
                return
            polozka = polozky[self._vyber]

            if polozka.typ is Typ.ZPET:
                # Kurzor se v kořeni postaví na složku, ze které jsme vyšli —
                # bez toho by uživatel po opuštění složky skončil na začátku
                # seznamu a hledal, kde vlastně byl.
                opustena = self._adresar
                self._adresar = ""
                self._vyber = self._index_cesty(opustena)
                self._zadej_prekresleni()
            elif polozka.typ is Typ.SLOZKA:
                self._adresar = polozka.cesta
                self._vyber = 0
                self._zadej_prekresleni()
            else:
                self._pozadavek = polozka.cesta
                self._chyba = None
                self._zadej_prekresleni()

    def _index_cesty(self, cesta):
        """Pozice položky s danou cestou v aktuálním pohledu, jinak 0."""
        for i, p in enumerate(self._pohled()):
            if p.cesta == cesta:
                return i
        return 0

    def zpet_do_menu(self):
        with self._zamek:
            self._zpet_do_menu()

    def otevri_menu(self):
        """Menu nad rozečtenou knihou (to, co dělá akce() při čtení).

        Na rozdíl od zpet_do_menu() se stránky ani pozice nezahazují. Kniha
        zůstane v paměti, takže dlouhý stisk (zpet_do_cteni) se k ní vrátí
        okamžitě a hlavně bez sáhnutí na e-ink — text na panelu je pořád ten
        správný a jeho překreslení stojí ~29 s.

        Cenou je držená kniha v RAM po dobu procházení menu: naměřeno 2,8 MB
        u knihy o 1500 stranách, tedy 0,5 % paměti Pi Zero W. Obrázky se v
        stránkách nedrží, jen cesty do ZIPu.
        """
        with self._zamek:
            return self._otevri_menu()

    def zpet_do_cteni(self):
        """Dlouhý stisk kodéru: útěk z menu zpátky do knihy, ať jsi kdekoliv.

        Vrací True, jen když je kam utéct. Bez rozečtené knihy (čerstvý start
        do menu, nebo kniha zavřená přes zpet_do_menu()) se nestane nic —
        vlajka překreslení se ani nenastaví, aby smyčka nesahala na e-ink.
        """
        with self._zamek:
            return self._zpet_do_cteni()

    def dlouhy_stisk(self):
        """Dlouhé držení tlačítka v kodéru — protějšek akce().

        Význam se liší podle stavu, ale pořád je to totéž gesto „pryč odsud":

            CTENI            → rychlé listování (skok knihou bez buzení e-inku)
            RYCHLE_LISTOVANI → zrušení, zpátky na výchozí stránku
            MENU             → útěk do rozečtené knihy

        Větvení je schválně tady, ne v obsluze tlačítka: jinak by ho simulátor
        musel opsat a rozešel by se s železem — přesně to se stalo, když
        rychlé listování přibylo jen v hlavni_ctecka.py.
        """
        with self._zamek:
            if self._stav is Stav.CTENI:
                return self._zacni_rychle_listovani()
            if self._stav is Stav.RYCHLE_LISTOVANI:
                return self._zrus_rychle_listovani()
            return self._zpet_do_cteni()

    def zacni_rychle_listovani(self):
        """Dlouhý stisk při čtení: listování po OLEDu, e-ink se nedotkne.

        Zapamatuje si stránku, na které uživatel stál, aby se dalo zrušit.
        Vrací True, jen když se stav opravdu přepnul.
        """
        with self._zamek:
            return self._zacni_rychle_listovani()

    def potvrd_rychle_listovani(self):
        """Krátký stisk: vybraná stránka platí, ať ji e-ink vykreslí.

        Pozice se zapisuje až tady, ne při každém cvaknutí kodéru — jinak by
        se do progress.json ukládaly i stránky, kterými se jen prolétlo.
        """
        with self._zamek:
            return self._potvrd_rychle_listovani()

    def zrus_rychle_listovani(self):
        """Dlouhý stisk během listování: zpátky na stránku, odkud se vyšlo.

        Překreslení se vyžádá, i když se stránka nezměnila: e-ink pak nesáhne
        na panel (drží tentýž text), ale OLED se musí vrátit do čtecího režimu.
        """
        with self._zamek:
            return self._zrus_rychle_listovani()

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
            self._puvodni_stranka = self._stranka
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
                if 0 <= novy < len(self._pohled()):
                    self._vyber = novy
                    self._zadej_prekresleni()
            else:
                novy = self._stranka + smer
                if 0 <= novy < len(self._stranky):
                    self._stranka = novy
                    # Při rychlém listování se pozice nezapisuje: uživatel se
                    # může vrátit zpět a průletové stránky nemají co na SD kartě
                    # dělat. Uloží je až potvrd_rychle_listovani().
                    if self._stav is Stav.CTENI:
                        self._pozice_k_ulozeni = (self._kniha, novy)
                    self._zadej_prekresleni()

    def _zpet_do_cteni(self):
        if self._konec or not self._stranky:
            return False
        # Rozpracované načítání jiné knihy se ruší: jinak by za chvíli
        # přebilo tu, ke které se uživatel právě vrátil.
        self._pozadavek = None
        self._nacitana = None
        self._stav = Stav.CTENI
        self._chyba = None
        self._zadej_prekresleni()
        return True

    def _zacni_rychle_listovani(self):
        if self._konec or self._stav is not Stav.CTENI or not self._stranky:
            return False
        self._puvodni_stranka = self._stranka
        self._stav = Stav.RYCHLE_LISTOVANI
        self._zadej_prekresleni()
        return True

    def _zrus_rychle_listovani(self):
        if self._konec or self._stav is not Stav.RYCHLE_LISTOVANI:
            return False
        self._stranka = self._puvodni_stranka
        self._stav = Stav.CTENI
        self._zadej_prekresleni()
        return True

    def _potvrd_rychle_listovani(self):
        if self._konec or self._stav is not Stav.RYCHLE_LISTOVANI:
            return False
        self._stav = Stav.CTENI
        if self._stranka != self._puvodni_stranka:
            self._pozice_k_ulozeni = (self._kniha, self._stranka)
        self._puvodni_stranka = self._stranka
        self._zadej_prekresleni()
        return True

    def _otevri_menu(self):
        if self._konec or self._stav is Stav.MENU:
            return False
        self._stav = Stav.MENU
        self._zadej_prekresleni()
        return True

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
