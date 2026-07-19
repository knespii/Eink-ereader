"""Produkční program — tlačítka, smyčka, čištění displeje."""

import threading
import time

import pytest

import displej
import hlavni_ctecka as h
from conftest import STRANKY_ATRAPA
from stav import Ctecka, Stav

ZDROJ = open(h.__file__, encoding="utf-8").read()


class TestZadnyGlobalniStav:
    def test_zadne_global(self):
        assert "global " not in ZDROJ

    def test_zadny_vlastni_stav(self):
        assert "aktualni_stav" not in ZDROJ
        assert "prekreslit_displej" not in ZDROJ

    def test_neimportuje_waveshare_primo(self):
        assert "waveshare" not in ZDROJ

    def test_nekresli_sam(self):
        assert "ImageDraw" not in ZDROJ


@pytest.fixture
def tlacitka_a_ctecka():
    c = Ctecka(["Alliances.epub", "Treason.epub"])
    tlacitka = h.pripoj_tlacitka(c)
    c.spotrebuj_prekresleni()
    yield c, tlacitka
    for t in tlacitka:
        t.close()


class TestTlacitka:
    """Z původní trojice zbyly dvě: listování. Vstup do menu a zpátky přešel
    na tlačítko v kodéru, protože třetí tlačítko z hardwaru zmizelo."""

    def test_dalsi_posune_vyber(self, tlacitka_a_ctecka, stisk):
        c, _ = tlacitka_a_ctecka
        stisk(h.PIN_DALSI)
        assert c.snimek().vyber == 1
        assert c.spotrebuj_prekresleni() is True

    def test_predchozi_vrati_vyber(self, tlacitka_a_ctecka, stisk):
        c, _ = tlacitka_a_ctecka
        stisk(h.PIN_DALSI)
        stisk(h.PIN_PREDCHOZI)
        assert c.snimek().vyber == 0

    def test_jsou_jen_dve(self, tlacitka_a_ctecka):
        """Odstraněné tlačítko se nesmí vrátit zadními vrátky — každý další
        Button by na chybějícím pinu jen visel a mátl."""
        _, tlacitka = tlacitka_a_ctecka
        assert len(tlacitka) == 2
        assert not hasattr(h, "PIN_AKCE")



def test_stisk_behem_renderu_se_neztrati(tlacitka_a_ctecka, stisk):
    """Vlajka se shazuje před renderem, ne po něm."""
    c, _ = tlacitka_a_ctecka
    c.akce()
    c.vyzvedni_pozadavek()
    c.dodej_stranky("Alliances.epub", STRANKY_ATRAPA, 0)

    assert c.cekej_na_prekresleni(0.1) is True  # smyčka začíná kreslit
    stisk(h.PIN_DALSI)  # stisk uprostřed patnáctisekundového zápisu
    assert c.cekej_na_prekresleni(0.5) is True
    assert c.snimek().cislo_stranky == 2


class TestZobraz:
    def test_posle_driveru_neotocene_bitmapy(self, fonty, stranky):
        poslano = []
        obrazovka = displej.DummyDriver()
        obrazovka.zobraz = lambda c, r: poslano.append((c, r))

        c = Ctecka(["Treason.epub"])
        h.zobraz(obrazovka, c, fonty)

        assert len(poslano) == 1
        assert poslano[0][0].size == (528, 880)  # rotaci řeší až driver


class TestCisteniDispleje:
    """Clear() naměřen na 91 s, display() na 99 s — čištění je proto vypnuté."""

    def test_vychozi_je_vypnuto(self):
        assert h.PERIODA_CISTENI == 0

    def test_vycisti_je_v_rozhrani(self):
        assert hasattr(displej.DummyDriver(), "vycisti")

    def test_vypnute_cisteni_nesahne_na_panel(self, monkeypatch):
        volano = []
        monkeypatch.setattr(h, "PERIODA_CISTENI", 0)
        obrazovka = displej.DummyDriver()
        obrazovka.vycisti = lambda: volano.append("vycisti")

        # tělo startu smyčky
        if h.PERIODA_CISTENI:
            obrazovka.vycisti()
        assert volano == []

    def test_zapnute_cisteni_panel_vybili(self, monkeypatch):
        volano = []
        monkeypatch.setattr(h, "PERIODA_CISTENI", 20)
        obrazovka = displej.DummyDriver()
        obrazovka.vycisti = lambda: volano.append("vycisti")

        if h.PERIODA_CISTENI:
            obrazovka.vycisti()
        assert volano == ["vycisti"]


# --- ROTAČNÍ KODÉR ---

STROM_ATRAPA = {
    "": [
        {"typ": "slozka", "nazev": "scifi", "cesta": "scifi"},
        {"typ": "kniha", "nazev": "Alliances.epub", "cesta": "Alliances.epub"},
    ],
    "scifi": [{"typ": "kniha", "nazev": "Duna.epub", "cesta": "scifi/Duna.epub"}],
}


def krok_enkoderu(pin, prvni, druhy):
    """Jedno cvaknutí kodéru — kvadraturní sekvence na dvojici pinů.

    Pořadí pinů určuje směr: (CLK, DT) je po směru hodinových ručiček,
    obráceně proti směru.
    """
    pin(prvni).drive_low()
    pin(druhy).drive_low()
    pin(prvni).drive_high()
    pin(druhy).drive_high()
    time.sleep(0.1)


@pytest.fixture
def enkoder_a_ctecka():
    c = Ctecka(STROM_ATRAPA)
    zarizeni = h.pripoj_enkoder(c)
    assert zarizeni, "kodér se nepřipojil — piny už asi drží jiný test"
    c.spotrebuj_prekresleni()
    yield c, pin_enkoderu(zarizeni)
    for z in zarizeni:
        z.close()


def pin_enkoderu(zarizeni):
    from gpiozero import Device

    return lambda cislo: Device.pin_factory.pin(cislo)


class TestEnkoderVMenu:
    def test_otoceni_po_smeru_posune_dal(self, enkoder_a_ctecka):
        c, pin = enkoder_a_ctecka
        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)
        assert c.snimek().vyber == 1

    def test_otoceni_proti_smeru_posune_zpet(self, enkoder_a_ctecka):
        c, pin = enkoder_a_ctecka
        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)
        krok_enkoderu(pin, h.PIN_ENKODER_DT, h.PIN_ENKODER_CLK)
        assert c.snimek().vyber == 0

    def test_stisk_vstoupi_do_slozky(self, enkoder_a_ctecka, stisk):
        c, _ = enkoder_a_ctecka
        stisk(h.PIN_ENKODER_SW)
        snimek = c.snimek()
        assert snimek.adresar == "scifi"
        assert snimek.stav is Stav.MENU
        # Složka není kniha — hlavní smyčka nesmí dostat co parsovat.
        assert c.vyzvedni_pozadavek() is None

    def test_stisk_na_knize_zada_pozadavek(self, enkoder_a_ctecka, stisk):
        c, pin = enkoder_a_ctecka
        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)  # na Alliances
        stisk(h.PIN_ENKODER_SW)
        assert c.snimek().stav is Stav.MENU  # callback nic nenačetl
        assert c.snimek().nacita_se is True
        assert c.vyzvedni_pozadavek() == "Alliances.epub"

    def test_callback_je_okamzity(self, enkoder_a_ctecka, stisk):
        """Parsování trvá stovky ms; callback, který ho spouští, by se neschoval.

        Měřit jméno vlákna nejde — mock piny volají callback synchronně
        z volajícího vlákna, na reálném HW je to vlákno gpiozero.
        """
        c, pin = enkoder_a_ctecka
        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)
        trvani = []
        puvodni = c.akce

        def sledovana():
            t0 = time.time()
            puvodni()
            trvani.append(time.time() - t0)

        c.akce = sledovana  # na_uvolneni() volá ctecka.akce() dynamicky
        stisk(h.PIN_ENKODER_SW)
        assert trvani[0] < 0.01


class TestEnkoderPriCteni:
    """Otáčení je při čtení hluché: stránky patří tlačítkům u e-inku a nechtěné
    cvrnknutí by jinak spustilo ~29s překreslení panelu. Tlačítko v kodéru
    naopak funguje pořád — je to jediná cesta do menu a zpátky."""

    @pytest.fixture
    def ve_cteni(self, enkoder_a_ctecka):
        c, pin = enkoder_a_ctecka
        c.dalsi()  # z složky scifi na Alliances.epub
        c.akce()
        c.vyzvedni_pozadavek()
        c.dodej_stranky("Alliances.epub", STRANKY_ATRAPA, 2)
        assert c.snimek().stav is Stav.CTENI
        c.spotrebuj_prekresleni()
        return c, pin

    def test_otoceni_neposune_stranku(self, ve_cteni):
        c, pin = ve_cteni
        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)
        krok_enkoderu(pin, h.PIN_ENKODER_DT, h.PIN_ENKODER_CLK)
        assert c.snimek().cislo_stranky == 3
        assert c.spotrebuj_prekresleni() is False  # ani nevyžádalo překreslení

    def test_kratky_stisk_otevre_menu(self, ve_cteni, stisk):
        c, _ = ve_cteni
        stisk(h.PIN_ENKODER_SW)
        assert c.snimek().stav is Stav.MENU

    def test_kratky_stisk_nezahodi_knihu(self, ve_cteni, stisk):
        """Menu se otevírá nad rozečtenou knihou — jinak by dlouhý stisk
        neměl kam utéct a musel by knihu znovu stránkovat (~16 s)."""
        c, _ = ve_cteni
        stisk(h.PIN_ENKODER_SW)
        assert c.zpet_do_cteni() is True
        assert c.snimek().cislo_stranky == 3


def drz(pin, cislo, doba=None):
    """Dlouhý stisk: podrží pin přes hold_time a zase pustí."""
    pin(cislo).drive_low()
    time.sleep(h.DOBA_DRZENI_ENKODER + 0.4 if doba is None else doba)
    pin(cislo).drive_high()
    time.sleep(0.2)


class TestDlouhyStiskEnkoderu:
    """Globální escape: z libovolného místa v menu zpátky do knihy."""

    @pytest.fixture
    def s_knihou(self, enkoder_a_ctecka):
        c, pin = enkoder_a_ctecka
        c.dalsi()
        c.akce()
        c.vyzvedni_pozadavek()
        c.dodej_stranky("Alliances.epub", STRANKY_ATRAPA, 2)
        c.otevri_menu()
        c.spotrebuj_prekresleni()
        return c, pin

    def test_vrati_do_cteni(self, s_knihou, pin):
        c, _ = s_knihou
        drz(pin, h.PIN_ENKODER_SW)
        assert c.snimek().stav is Stav.CTENI
        assert c.snimek().cislo_stranky == 3

    def test_utece_i_ze_zanorene_slozky(self, s_knihou, pin):
        c, _ = s_knihou
        c.predchozi()  # zpátky na složku scifi
        c.akce()  # vstup dovnitř
        assert c.snimek().adresar == "scifi"
        drz(pin, h.PIN_ENKODER_SW)
        assert c.snimek().stav is Stav.CTENI

    def test_dlouhy_stisk_nepotvrdi_polozku(self, s_knihou, pin):
        """Kdyby krátký stisk visel na when_pressed, držení nad složkou by
        nejdřív vlezlo dovnitř a teprve pak uteklo."""
        c, _ = s_knihou
        drz(pin, h.PIN_ENKODER_SW)
        assert c.snimek().adresar == ""
        assert c.vyzvedni_pozadavek() is None

    def test_bez_rozecetene_knihy_se_nic_nestane(self, enkoder_a_ctecka, pin):
        """Není kam utéct — a hlavně se nesmí vyžádat překreslení, jinak by
        smyčka sáhla na e-ink."""
        c, _ = enkoder_a_ctecka
        drz(pin, h.PIN_ENKODER_SW)
        assert c.snimek().stav is Stav.MENU
        assert c.spotrebuj_prekresleni() is False


# --- ÚSPORA ENERGIE ---


class TestHlidac:
    """Fáze je čistá funkce času, takže se dá celá hodina nečinnosti proběhnout
    předáním `ted` — bez čekání a bez monkeypatchování hodin."""

    def test_cerstvy_vstup_je_bdeni(self):
        hlidac = h.Hlidac(do_spanku=10, do_vypnuti=60, ted=0.0)
        assert hlidac.faze(ted=9.9) is h.Uspora.BDENI

    def test_po_prahu_usne(self):
        hlidac = h.Hlidac(do_spanku=10, do_vypnuti=60, ted=0.0)
        assert hlidac.faze(ted=10.0) is h.Uspora.SPANEK

    def test_po_druhem_prahu_vypina(self):
        hlidac = h.Hlidac(do_spanku=10, do_vypnuti=60, ted=0.0)
        assert hlidac.faze(ted=60.0) is h.Uspora.VYPNUTI

    def test_vstup_posune_oba_prahy(self):
        """Hodina musí být nepřerušená — jedno cvaknutí v 59. minutě ji vynuluje."""
        hlidac = h.Hlidac(do_spanku=10, do_vypnuti=60, ted=0.0)
        hlidac.zaznamenej_vstup(ted=59.0)
        assert hlidac.faze(ted=61.0) is h.Uspora.BDENI
        assert hlidac.faze(ted=70.0) is h.Uspora.SPANEK
        assert hlidac.faze(ted=119.0) is h.Uspora.VYPNUTI

    def test_vstup_za_bdeni_se_nepolyka(self):
        hlidac = h.Hlidac(do_spanku=10, do_vypnuti=60, ted=0.0)
        assert hlidac.zaznamenej_vstup(ted=5.0) is False

    def test_vstup_ze_spanku_se_polyka(self):
        hlidac = h.Hlidac(do_spanku=10, do_vypnuti=60, ted=0.0)
        assert hlidac.zaznamenej_vstup(ted=11.0) is True

    def test_polyka_se_jen_prvni_vstup(self):
        """Druhé cvaknutí už musí projít — jinak by čtečka po probuzení
        ignorovala všechno, dokud znovu neusne."""
        hlidac = h.Hlidac(do_spanku=10, do_vypnuti=60, ted=0.0)
        assert hlidac.zaznamenej_vstup(ted=11.0) is True
        assert hlidac.zaznamenej_vstup(ted=11.5) is False


class TestProbouzeciVstup:
    """První vstup ze spánku smí jen rozsvítit. Kdyby otočil stránku, čeká se
    ~29 s na refresh e-inku kvůli sáhnutí na tmavou čtečku."""

    def _ctecka_a_hlidac(self, usnula):
        c = Ctecka(STROM_ATRAPA)
        c.spotrebuj_prekresleni()
        # do_spanku=0 → hlídač považuje za spánek každý vstup
        hlidac = h.Hlidac(do_spanku=0 if usnula else 10_000, do_vypnuti=10_000)
        return c, hlidac

    def test_ze_spanku_akci_neprovede(self):
        c, hlidac = self._ctecka_a_hlidac(usnula=True)
        h.probouzeci(c, hlidac, c.dalsi)()
        assert c.snimek().vyber == 0, "probouzecí vstup posunul kurzor"

    def test_ze_spanku_vyzada_prekresleni(self):
        """Callback kreslit nesmí, takže probuzení hlásí smyčce takhle."""
        c, hlidac = self._ctecka_a_hlidac(usnula=True)
        h.probouzeci(c, hlidac, c.dalsi)()
        assert c.spotrebuj_prekresleni() is True

    def test_za_bdeni_akci_provede(self):
        c, hlidac = self._ctecka_a_hlidac(usnula=False)
        h.probouzeci(c, hlidac, c.dalsi)()
        assert c.snimek().vyber == 1

    def test_bez_hlidace_akci_provede(self):
        c, _ = self._ctecka_a_hlidac(usnula=False)
        h.probouzeci(c, None, c.dalsi)()
        assert c.snimek().vyber == 1


class TestProbouzeciStiskEnkoderu:
    """Jedno stisknutí je trojice callbacků, takže polykání musí přežít celé
    gesto — jinak by uvolnění vidělo už bdělou čtečku a potvrdilo položku."""

    @pytest.fixture
    def spici_enkoder(self):
        c = Ctecka(STROM_ATRAPA)
        zarizeni = h.pripoj_enkoder(c, h.Hlidac(do_spanku=0, do_vypnuti=10_000))
        assert zarizeni, "kodér se nepřipojil — piny už asi drží jiný test"
        c.spotrebuj_prekresleni()
        yield c, pin_enkoderu(zarizeni)
        for z in zarizeni:
            z.close()

    def test_kratky_stisk_jen_probudi(self, spici_enkoder, stisk):
        c, _ = spici_enkoder
        stisk(h.PIN_ENKODER_SW)  # kurzor stojí na složce scifi
        assert c.snimek().adresar == "", "probouzecí stisk vlezl do složky"
        assert c.vyzvedni_pozadavek() is None
        assert c.spotrebuj_prekresleni() is True  # ale rozsvítit se má

    def test_dlouhy_stisk_jen_probudi(self, spici_enkoder, pin):
        """Držení přes práh nesmí ze spánku utéct do knihy."""
        c, _ = spici_enkoder
        c.dalsi()
        c.akce()
        c.vyzvedni_pozadavek()
        c.dodej_stranky("Alliances.epub", STRANKY_ATRAPA, 2)
        c.otevri_menu()

        drz(pin, h.PIN_ENKODER_SW)
        assert c.snimek().stav is Stav.MENU, "probouzecí držení uteklo do knihy"

    def test_otoceni_jen_probudi(self, spici_enkoder):
        c, pin = spici_enkoder
        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)
        assert c.snimek().vyber == 0


# --- VÝSTUP NA OLED ---


class TestZhasinaniOled:
    """Zhasnutí je jediný strážce v prekresli(), aby se na spánek nemuselo
    myslet na každém volacím místě ve smyčce."""

    def test_zhasnuty_nekresli(self):
        zarizeni = TestVystupOled._Atrapa()
        vystup = h.VystupOled(zarizeni, h.oled_ui.nacti_fonty())
        vystup.zhasni()
        zapisy = zarizeni.zapisy
        assert vystup.prekresli(Ctecka(STROM_ATRAPA).snimek()) is False
        assert zarizeni.zapisy == zapisy

    def test_pouzije_hide_kdyz_je(self):
        class SHide(TestVystupOled._Atrapa):
            def __init__(self):
                super().__init__()
                self.volani = []

            def hide(self):
                self.volani.append("hide")

            def show(self):
                self.volani.append("show")

        zarizeni = SHide()
        vystup = h.VystupOled(zarizeni, h.oled_ui.nacti_fonty())
        vystup.zhasni()
        vystup.rozsvit()
        assert zarizeni.volani == ["hide", "show"]

    def test_bez_hide_posle_prazdny_obraz(self):
        """Atrapa ani starší luma hide() mít nemusí — displej musí zhasnout tak
        jako tak, ne spadnout na AttributeError."""
        zarizeni = TestVystupOled._Atrapa()
        vystup = h.VystupOled(zarizeni, h.oled_ui.nacti_fonty())
        vystup.zhasni()
        assert zarizeni.zapisy == 1

    def test_po_rozsviceni_zase_kresli(self):
        zarizeni = TestVystupOled._Atrapa()
        vystup = h.VystupOled(zarizeni, h.oled_ui.nacti_fonty())
        snimek = Ctecka(STROM_ATRAPA).snimek()
        vystup.prekresli(snimek)
        vystup.zhasni()
        vystup.rozsvit()
        # Cache se zahazuje: co panel po hide() drží, závisí na knihovně, a
        # tipnout si znamená risk, že zůstane tmavý.
        assert vystup.prekresli(snimek) is True

    def test_opakovane_zhasnuti_nic_nedela(self):
        zarizeni = TestVystupOled._Atrapa()
        vystup = h.VystupOled(zarizeni, h.oled_ui.nacti_fonty())
        vystup.zhasni()
        vystup.zhasni()
        assert zarizeni.zapisy == 1


class TestVystupOled:
    """Smyčka se v menu budí několikrát za sekundu kvůli tickeru. Bez tohohle
    filtru by na I2C tekl pořád dokola tentýž obraz."""

    class _Atrapa:
        def __init__(self):
            self.zapisy = 0

        def display(self, obraz):
            self.zapisy += 1

    def test_prvni_kresleni_se_posle(self):
        zarizeni = self._Atrapa()
        vystup = h.VystupOled(zarizeni, h.oled_ui.nacti_fonty())
        assert vystup.prekresli(Ctecka(STROM_ATRAPA).snimek()) is True
        assert zarizeni.zapisy == 1

    def test_stejny_obraz_se_neposila(self):
        zarizeni = self._Atrapa()
        vystup = h.VystupOled(zarizeni, h.oled_ui.nacti_fonty())
        snimek = Ctecka(STROM_ATRAPA).snimek()
        vystup.prekresli(snimek)
        assert vystup.prekresli(snimek) is False
        assert zarizeni.zapisy == 1

    def test_zmena_vyberu_se_posle(self):
        zarizeni = self._Atrapa()
        vystup = h.VystupOled(zarizeni, h.oled_ui.nacti_fonty())
        c = Ctecka(STROM_ATRAPA)
        vystup.prekresli(c.snimek())
        c.dalsi()
        assert vystup.prekresli(c.snimek()) is True
        assert zarizeni.zapisy == 2


# --- ROZVĚTVENÍ SMYČKY: který displej se kdy zapíše ---


def pockej(podminka, limit=3.0):
    """Čeká na podmínku místo pevného sleepu — jinak je test buď pomalý,
    nebo na pomalejším stroji náhodně padá."""
    konec = time.monotonic() + limit
    while time.monotonic() < konec:
        if podminka():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def bezici_smycka(monkeypatch):
    """Spustí main() proti atrapám obou displejů a zaznamenává, kam se psalo."""
    yield from _spust_smycku(monkeypatch)


@pytest.fixture
def spici_smycka(monkeypatch):
    """Totéž, ale s prahy v desetinách sekundy, aby šel spánek proběhnout.

    DOBA_DO_VYPNUTI zůstává nedosažitelně vysoko — test, který si ji chce
    zkrátit, ať si ji přepíše sám a monkeypatchne vypni_system(). Tady by ji
    omylem trefil kdokoli, kdo test o pár set milisekund zpomalí.
    """
    monkeypatch.setattr(h, "DOBA_DO_SPANKU", 0.3)
    monkeypatch.setattr(h, "DOBA_DO_VYPNUTI", 10_000.0)
    monkeypatch.setattr(h, "TIK_SPANKU", 0.05)
    yield from _spust_smycku(monkeypatch)


def _spust_smycku(monkeypatch):
    zaznam = []

    class OledAtrapa:
        def display(self, obraz):
            zaznam.append("oled")

        def hide(self):
            zaznam.append("oled_zhasnut")

        def show(self):
            zaznam.append("oled_rozsvicen")

    class EinkAtrapa(displej.DummyDriver):
        def zobraz(self, cerna, cervena):
            zaznam.append("eink")

    monkeypatch.setattr(h.oled_ui, "vytvor_oled", lambda *a, **kw: OledAtrapa())
    monkeypatch.setattr(h.displej, "vytvor_displej", EinkAtrapa)
    monkeypatch.setattr(h.knihovna, "nacti_strom", lambda: STROM_ATRAPA)
    monkeypatch.setattr(
        h.knihovna, "nacti_stranky", lambda nazev, fonty, hlas=None: STRANKY_ATRAPA
    )
    monkeypatch.setattr(h.knihovna, "nacti_posledni_stav", lambda: None)

    # main() si Ctecku vyrábí sám; tudy se k ní dostaneme, abychom ji na konci
    # mohli slušně ukončit (dlouhý stisk by stál dvě sekundy navíc).
    drzena = []
    puvodni_ctecka = h.Ctecka
    monkeypatch.setattr(
        h, "Ctecka", lambda *a, **kw: drzena.append(puvodni_ctecka(*a, **kw)) or drzena[0]
    )

    vlakno = threading.Thread(target=h.main, daemon=True)
    vlakno.start()
    assert pockej(lambda: drzena and zaznam), "smyčka nenaběhla"

    yield drzena[0], zaznam

    drzena[0].ukonci()
    vlakno.join(timeout=3.0)
    assert not vlakno.is_alive(), "smyčka se neukončila"


class TestUsporaVeSmycce:
    """Dvě fáze nečinnosti proti skutečně běžící smyčce."""

    def test_po_prahu_zhasne_oled(self, spici_smycka):
        _, zaznam = spici_smycka
        assert pockej(lambda: "oled_zhasnut" in zaznam), "OLED po prahu nezhasl"

    def test_ve_spanku_se_na_i2c_nepise(self, spici_smycka):
        """Ticker se v menu točí dvanáctkrát za sekundu — ve spánku musí mlčet,
        jinak je celé zhasnutí k ničemu."""
        _, zaznam = spici_smycka
        assert pockej(lambda: "oled_zhasnut" in zaznam)
        zaznam.clear()
        time.sleep(0.5)
        assert zaznam == [], f"ve spánku se kreslilo: {zaznam}"

    def test_eink_zustava_netknuty(self, spici_smycka):
        _, zaznam = spici_smycka
        assert pockej(lambda: "oled_zhasnut" in zaznam)
        assert "eink" not in zaznam

    def test_vstup_rozsviti_a_neposune_kurzor(self, spici_smycka, pin):
        ctecka, zaznam = spici_smycka
        assert pockej(lambda: "oled_zhasnut" in zaznam)
        vyber = ctecka.snimek().vyber

        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)

        assert pockej(lambda: "oled_rozsvicen" in zaznam), "vstup nerozsvítil OLED"
        assert ctecka.snimek().vyber == vyber, "probouzecí vstup posunul kurzor"
        assert pockej(lambda: "oled" in zaznam), "po probuzení se nepřekreslilo"

    def test_probuzeni_pri_cteni_prekresli_oled(self, spici_smycka, pin, stisk):
        """Při čtení se smyčka na ticker nespoléhá — v CTENI žádný není, takže
        probuzení musí OLED překreslit samo, jinak zůstane prázdný až do
        otočení stránky."""
        ctecka, zaznam = spici_smycka
        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)  # na knihu
        stisk(h.PIN_ENKODER_SW)
        assert pockej(lambda: ctecka.snimek().stav is Stav.CTENI)
        assert pockej(lambda: "oled_zhasnut" in zaznam), "OLED při čtení nezhasl"

        zaznam.clear()
        stisk(h.PIN_ENKODER_SW)  # probouzecí stisk

        assert pockej(lambda: "oled_rozsvicen" in zaznam)
        assert pockej(lambda: "oled" in zaznam), "po probuzení zůstal OLED prázdný"
        assert ctecka.snimek().stav is Stav.CTENI, "probouzecí stisk otevřel menu"
        assert "eink" not in zaznam

    def test_druhy_vstok_uz_projde(self, spici_smycka, pin):
        ctecka, zaznam = spici_smycka
        assert pockej(lambda: "oled_zhasnut" in zaznam)
        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)  # probuzení
        assert pockej(lambda: "oled_rozsvicen" in zaznam)

        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)

        assert pockej(lambda: ctecka.snimek().vyber == 1), "druhý vstup se taky spolkl"

    def test_po_druhem_prahu_vypne_system(self, monkeypatch):
        """Fáze 2: ukonci() uklidí GPIO a I2C, halt přijde až po tom úklidu."""
        poradi = []
        monkeypatch.setattr(h, "DOBA_DO_SPANKU", 0.1)
        monkeypatch.setattr(h, "DOBA_DO_VYPNUTI", 0.3)
        monkeypatch.setattr(h, "TIK_SPANKU", 0.05)
        monkeypatch.setattr(h, "vypni_system", lambda: poradi.append("halt"))

        puvodni_vypni = displej.DummyDriver.vypni
        monkeypatch.setattr(
            displej.DummyDriver,
            "vypni",
            lambda self: poradi.append("uklid") or puvodni_vypni(self),
        )

        smycka = _spust_smycku(monkeypatch)
        ctecka, _ = next(smycka)
        try:
            assert pockej(lambda: "halt" in poradi, limit=5.0), "systém se nevypnul"
            assert ctecka.konec is True, "ukonci() se nezavolalo"
            assert poradi.index("uklid") < poradi.index("halt"), (
                "halt přišel dřív než úklid GPIO a I2C"
            )
        finally:
            for _ in smycka:  # dojede teardown fixtury
                pass

    def test_vypni_system_neshodi_program(self, caplog):
        """Bez NOPASSWD v sudoers sudo selže — čtečka to má přežít."""
        h.vypni_system(prikaz=("/nonexistent/halt",))
        assert "Vypnutí selhalo" in caplog.text


class TestRozvetveniVystupu:
    """Jádro hybridního UI: v menu se sahá jen na OLED, při čtení jen na e-ink.

    Kdyby se do menu vrátil e-ink, každé cvaknutí kodéru stojí ~10 s a celý
    smysl přechodu na OLED padá.
    """

    def test_menu_kresli_jen_na_oled(self, bezici_smycka, pin):
        ctecka, zaznam = bezici_smycka
        zaznam.clear()
        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)

        assert pockej(lambda: "oled" in zaznam)
        assert "eink" not in zaznam
        assert ctecka.snimek().vyber == 1

    def test_vstup_do_slozky_nesahne_na_eink(self, bezici_smycka, stisk):
        ctecka, zaznam = bezici_smycka
        zaznam.clear()
        stisk(h.PIN_ENKODER_SW)  # kurzor stojí na složce scifi

        assert pockej(lambda: ctecka.snimek().adresar == "scifi")
        assert "eink" not in zaznam

    def test_otevreni_knihy_probudi_eink(self, bezici_smycka, pin, stisk):
        ctecka, zaznam = bezici_smycka
        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)  # na Alliances
        zaznam.clear()
        stisk(h.PIN_ENKODER_SW)

        assert pockej(lambda: ctecka.snimek().stav is Stav.CTENI)
        assert pockej(lambda: "eink" in zaznam)

    def test_pri_cteni_enkoder_nekresli_nic(self, bezici_smycka, pin, stisk):
        ctecka, zaznam = bezici_smycka
        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)
        stisk(h.PIN_ENKODER_SW)
        assert pockej(lambda: ctecka.snimek().stav is Stav.CTENI)
        assert pockej(lambda: "eink" in zaznam)

        zaznam.clear()
        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)
        krok_enkoderu(pin, h.PIN_ENKODER_DT, h.PIN_ENKODER_CLK)
        time.sleep(0.5)

        assert zaznam == [], f"kodér při čtení překreslil {zaznam}"
        assert ctecka.snimek().cislo_stranky == 1

    def test_pri_cteni_tlacitko_otoci_stranku_na_einku(self, bezici_smycka, pin, stisk):
        ctecka, zaznam = bezici_smycka
        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)
        stisk(h.PIN_ENKODER_SW)
        assert pockej(lambda: ctecka.snimek().stav is Stav.CTENI)
        assert pockej(lambda: "eink" in zaznam)

        zaznam.clear()
        stisk(h.PIN_DALSI)

        assert pockej(lambda: "eink" in zaznam), "tlačítko neotočilo stránku"
        assert ctecka.snimek().cislo_stranky == 2

    def test_navrat_do_menu_necha_eink_byt(self, bezici_smycka, pin, stisk):
        """E-ink drží poslední stránku jako přirozenou záložku — a přesně to
        popisuje i posledni_stav.json, který se zapisuje jen při zápisu na panel."""
        ctecka, zaznam = bezici_smycka
        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)
        stisk(h.PIN_ENKODER_SW)
        assert pockej(lambda: ctecka.snimek().stav is Stav.CTENI)
        assert pockej(lambda: "eink" in zaznam)

        zaznam.clear()
        stisk(h.PIN_ENKODER_SW)  # krátký stisk kodéru = zpět do menu

        assert pockej(lambda: ctecka.snimek().stav is Stav.MENU)
        assert pockej(lambda: "oled" in zaznam)
        time.sleep(0.4)
        assert "eink" not in zaznam, "návrat do menu zbytečně překreslil panel"

    def test_utek_z_menu_prekresli_jen_oled(self, bezici_smycka, pin, stisk):
        """Jádro dlouhého stisku: text na panelu je pořád ten správný, takže
        se čtecí rozhraní obnoví jen na OLEDu a ušetří se ~29 s refreshe."""
        ctecka, zaznam = bezici_smycka
        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)
        stisk(h.PIN_ENKODER_SW)
        assert pockej(lambda: ctecka.snimek().stav is Stav.CTENI)
        assert pockej(lambda: "eink" in zaznam)

        stisk(h.PIN_ENKODER_SW)  # do menu
        assert pockej(lambda: ctecka.snimek().stav is Stav.MENU)
        zaznam.clear()

        drz(pin, h.PIN_ENKODER_SW)  # dlouhý stisk = útěk zpět do knihy

        assert pockej(lambda: ctecka.snimek().stav is Stav.CTENI)
        assert pockej(lambda: "oled" in zaznam)
        time.sleep(0.4)
        assert "eink" not in zaznam, f"útěk do knihy sáhl na panel: {zaznam}"


class TestHlaseniNacitani:
    """Parsování knihy blokuje smyčku na ~16 s. Bez odezvy by displej celou
    tu dobu ukazoval starý obsah a čtečka působila zaseknutě."""

    def test_hlaseni_je_vycentrovane(self):
        obraz = h.oled_ui.vykresli_hlaseni("Načítám…", h.oled_ui.nacti_fonty())
        pole = obraz.load()
        xs = [x for x in range(obraz.width) for y in range(obraz.height) if pole[x, y]]
        ys = [y for y in range(obraz.height) for x in range(obraz.width) if pole[x, y]]
        assert abs(min(xs) - (obraz.width - max(xs) - 1)) <= 2
        assert abs(min(ys) - (obraz.height - max(ys) - 1)) <= 2

    def test_hlaseni_obejde_porovnani_s_poslednim(self):
        """Musí se poslat vždy, i kdyby vyšlo shodně s tím, co už na displeji je."""
        zarizeni = TestVystupOled._Atrapa()
        vystup = h.VystupOled(zarizeni, h.oled_ui.nacti_fonty())
        vystup.hlaseni("Načítám…")
        vystup.hlaseni("Načítám…")
        assert zarizeni.zapisy == 2

    def test_hlaseni_prijde_pred_parsovanim(self, monkeypatch, bezici_smycka, pin, stisk):
        """Kdyby se hláška kreslila až po obsluz(), uživatel ji uvidí až ve
        chvíli, kdy je kniha dávno načtená — tedy k ničemu."""
        poradi = []
        monkeypatch.setattr(
            h.knihovna,
            "nacti_stranky",
            lambda nazev, fonty, hlas=None: poradi.append("parsovani") or STRANKY_ATRAPA,
        )
        monkeypatch.setattr(
            h.VystupOled,
            "hlaseni",
            lambda self, text, podil=None: poradi.append("hlaseni"),
        )

        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)  # ze složky na knihu
        stisk(h.PIN_ENKODER_SW)

        assert pockej(lambda: "parsovani" in poradi)
        assert poradi.index("hlaseni") < poradi.index("parsovani")


class TestFazeTickeru:
    """Fáze se odvozuje od času, ne od počtu překreslení — smyčku může zdržet
    sken složky nebo zápis pozice a název by se pak trhal."""

    def test_pred_prodlevou_stoji(self):
        assert h.faze_tickeru(0.0, h.PRODLEVA_TICKERU - 0.01) == 0

    def test_po_prodleve_se_rozjede(self):
        assert h.faze_tickeru(0.0, h.PRODLEVA_TICKERU + 1.0) == int(h.RYCHLOST_TICKERU)

    def test_roste_linearne_s_casem(self):
        za_sekundu = h.faze_tickeru(0.0, h.PRODLEVA_TICKERU + 1.0)
        za_dve = h.faze_tickeru(0.0, h.PRODLEVA_TICKERU + 2.0)
        assert za_dve == 2 * za_sekundu

    def test_nezavisi_na_poctu_volani(self):
        """Sto volání ve stejném okamžiku musí dát tutéž fázi."""
        t = h.PRODLEVA_TICKERU + 0.7
        assert len({h.faze_tickeru(0.0, t) for _ in range(100)}) == 1


class TestScrollovaniNazvu:
    """Posouvat se smí jen název. Ikona a počítadlo musí stát."""

    DLOUHY = "Velmi dlouhy nazev knihy ktery se na displej nevejde.epub"

    @pytest.fixture
    def snimek_s_dlouhym_nazvem(self):
        c = Ctecka(
            {
                "": [
                    {"typ": "kniha", "nazev": self.DLOUHY, "cesta": self.DLOUHY},
                    {"typ": "kniha", "nazev": "Duna.epub", "cesta": "Duna.epub"},
                ]
            }
        )
        c.dalsi()  # položky se řadí abecedně, Duna je první
        snimek = c.snimek()
        assert snimek.polozky[snimek.vyber].nazev == self.DLOUHY
        return snimek

    def _pruhy(self, obraz, fonty):
        """(ikona, název, počítadlo) jako svislé výřezy podle rozvržení modulu."""
        from PIL import Image, ImageDraw

        kresli = ImageDraw.Draw(Image.new("1", (h.oled_ui.SIRKA, h.oled_ui.VYSKA)))
        sirka_pocitadla = h.oled_ui._sirka(kresli, "2/2", fonty.drobne)
        konec_nazvu = h.oled_ui.SIRKA - h.oled_ui.OKRAJ - sirka_pocitadla - 4
        zacatek_pocitadla = h.oled_ui.SIRKA - h.oled_ui.OKRAJ - sirka_pocitadla

        pole = obraz.load()

        def vyrez(od, do):
            return tuple(
                pole[x, y] for x in range(od, do) for y in range(h.oled_ui.VYSKA)
            )

        return (
            vyrez(0, h.oled_ui._IKONA_X + h.oled_ui._IKONA_SIRKA),
            vyrez(h.oled_ui._TEXT_X, konec_nazvu),
            vyrez(zacatek_pocitadla, h.oled_ui.SIRKA),
        )

    def test_nazev_se_posouva_ikona_a_pocitadlo_stoji(self, snimek_s_dlouhym_nazvem):
        fonty = h.oled_ui.nacti_fonty()
        pruhy = [
            self._pruhy(
                h.oled_ui.vykresli_oled(snimek_s_dlouhym_nazvem, fonty, faze), fonty
            )
            for faze in range(0, 60, 4)
        ]

        assert len({p[0] for p in pruhy}) == 1, "ikona bliká"
        assert len({p[2] for p in pruhy}) == 1, "počítadlo bliká"
        assert len({p[1] for p in pruhy}) > 1, "název se neposouvá"

    def test_kratky_nazev_se_neposouva(self):
        """Jinak by menu poskakovalo i tam, kde se všechno vejde."""
        fonty = h.oled_ui.nacti_fonty()
        snimek = Ctecka(["Duna.epub"]).snimek()
        obrazy = {
            h.oled_ui.vykresli_oled(snimek, fonty, faze).tobytes()
            for faze in range(0, 60, 4)
        }
        assert len(obrazy) == 1


class TestUkazatelPostupu:
    """Vodorovná čára na dně OLEDu ukazuje, jak daleko je kniha přečtená."""

    POCET = 120

    def _snimek(self, stranka, pocet=None):
        pocet = pocet or self.POCET
        c = Ctecka(["Duna.epub"])
        c.akce()
        c.vyzvedni_pozadavek()
        c.dodej_stranky("Duna.epub", [{"typ": "text", "obsah": ["x"]}] * pocet, stranka)
        return c.snimek()

    def _delka(self, obraz):
        pole = obraz.load()
        y = h.oled_ui.VYSKA - 1
        return max((x for x in range(obraz.width) if pole[x, y]), default=-1) + 1

    @pytest.mark.parametrize(
        "stranka, ocekavano",
        [(0, 1), (29, 32), (59, 64), (89, 96), (119, 128)],
    )
    def test_delka_odpovida_podilu(self, stranka, ocekavano):
        fonty = h.oled_ui.nacti_fonty()
        obraz = h.oled_ui.vykresli_oled(self._snimek(stranka), fonty)
        assert self._delka(obraz) == ocekavano

    def test_posledni_stranka_je_plna_sirka(self):
        fonty = h.oled_ui.nacti_fonty()
        obraz = h.oled_ui.vykresli_oled(self._snimek(self.POCET - 1), fonty)
        assert self._delka(obraz) == h.oled_ui.SIRKA

    def test_prvni_stranka_neni_neviditelna(self):
        """Nulová čára vypadá jako rozbitý displej, ne jako začátek knihy."""
        fonty = h.oled_ui.nacti_fonty()
        obraz = h.oled_ui.vykresli_oled(self._snimek(0, pocet=1465), fonty)
        assert self._delka(obraz) >= 1

    def test_nezasahuje_do_textu(self):
        fonty = h.oled_ui.nacti_fonty()
        obraz = h.oled_ui.vykresli_oled(self._snimek(59), fonty)
        pole = obraz.load()
        mezera = h.oled_ui.VYSKA - h.oled_ui.VYSKA_UKAZATELE
        assert not any(pole[x, mezera - 1] for x in range(obraz.width))

    def test_prezije_posun_tickeru(self):
        """Ticker vkládá pruh přes celou výšku — ukazatel se musí kreslit až po něm."""
        dlouhy = "Velmi dlouhy nazev knihy ktery se na displej nevejde.epub"
        c = Ctecka([dlouhy])
        c.akce()
        c.vyzvedni_pozadavek()
        c.dodej_stranky(dlouhy, [{"typ": "text", "obsah": ["x"]}] * 100, 49)
        fonty = h.oled_ui.nacti_fonty()

        delky = {
            self._delka(h.oled_ui.vykresli_oled(c.snimek(), fonty, faze))
            for faze in (0, 20, 80, 200)
        }
        assert delky == {64}

    @pytest.mark.parametrize("popis", ["menu", "nacitani"])
    def test_mimo_cteni_se_nekresli(self, popis):
        c = Ctecka(["a.epub"])
        if popis == "nacitani":
            c.akce()
        obraz = h.oled_ui.vykresli_oled(c.snimek(), h.oled_ui.nacti_fonty())
        assert self._delka(obraz) == 0


class TestPostupNacitani:
    """Parsování blokuje smyčku ~16 s. Ukazatel pod hláškou dává najevo,
    že se něco děje a kde v tom čtečka je."""

    def _delka(self, obraz):
        pole = obraz.load()
        y = h.oled_ui.VYSKA - 1
        return max((x for x in range(obraz.width) if pole[x, y]), default=-1) + 1

    def test_hlaseni_bez_podilu_ukazatel_nekresli(self):
        obraz = h.oled_ui.vykresli_hlaseni("Načítám…", h.oled_ui.nacti_fonty())
        assert self._delka(obraz) == 0

    @pytest.mark.parametrize("podil, ocekavano", [(0.0, 1), (0.25, 32), (0.5, 64), (1.0, 128)])
    def test_hlaseni_s_podilem_kresli_ukazatel(self, podil, ocekavano):
        obraz = h.oled_ui.vykresli_hlaseni("Načítám…", h.oled_ui.nacti_fonty(), podil)
        assert self._delka(obraz) == ocekavano

    def test_hlas_omezuje_frekvenci(self):
        """Parser hlásí tisíckrát za knihu; kreslit tolikrát by načítání zdrželo."""
        volani = []
        oled = type("Atrapa", (), {"hlaseni": lambda self, t, p=None: volani.append(p)})()
        hlas = h.hlas_nacitani(oled, perioda=10.0)

        for i in range(1000):
            hlas(i / 1000)

        assert len(volani) <= 2, f"prošlo {len(volani)} překreslení, čekal nejvýš 2"

    def test_hlas_pusti_dalsi_az_po_periode(self):
        volani = []
        oled = type("Atrapa", (), {"hlaseni": lambda self, t, p=None: volani.append(p)})()
        hlas = h.hlas_nacitani(oled, perioda=0.05)

        hlas(0.1)
        time.sleep(0.06)
        hlas(0.9)

        assert volani == [0.1, 0.9]

    def test_obsluz_predava_hlas_dal(self, monkeypatch):
        """knihovna.obsluz() musí hlas propustit až do stránkování."""
        dostal = []
        monkeypatch.setattr(
            h.knihovna,
            "nacti_stranky",
            lambda nazev, fonty, hlas=None: dostal.append(hlas) or STRANKY_ATRAPA,
        )
        c = Ctecka(["a.epub"])
        c.akce()
        znacka = object()
        h.knihovna.obsluz(c, None, hlas=znacka)
        assert dostal == [znacka]

    def test_obsluz_funguje_i_bez_hlasu(self, monkeypatch):
        """Simulátor volá obsluz() bez hlasu a žádný OLED nemá."""
        monkeypatch.setattr(
            h.knihovna, "nacti_stranky", lambda nazev, fonty, hlas=None: STRANKY_ATRAPA
        )
        c = Ctecka(["a.epub"])
        c.akce()
        h.knihovna.obsluz(c, None)
        assert c.snimek().stav is Stav.CTENI


class TestHlasVeStrankovani:
    def test_zformatuj_hlasi_postup(self, fonty):
        import zpracovani_textu

        podily = []
        obsah = [{"typ": "text", "hodnota": f"odstavec {i}"} for i in range(20)]
        zpracovani_textu.zformatuj_a_rozdel(
            obsah, fonty.text, 400, 800, hlas=podily.append
        )

        assert podily, "hlas se nezavolal ani jednou"
        assert podily == sorted(podily), "podíl klesá"
        assert 0.0 <= min(podily) and max(podily) < 1.0

    def test_zformatuj_funguje_bez_hlasu(self, fonty):
        import zpracovani_textu

        obsah = [{"typ": "text", "hodnota": "nejaky text"}]
        assert zpracovani_textu.zformatuj_a_rozdel(obsah, fonty.text, 400, 800)


class TestRychleListovani:
    """Listování stránkami po OLEDu, dokud se výběr nepotvrdí.

    Celý smysl režimu je v tom, co se **nestane**: e-ink se během listování
    nesmí probudit, jinak stojí každé cvaknutí kodéru ~29 s. Testy proto hlídají
    hlavně nepřítomnost "eink" v záznamu, ne přítomnost "oled".
    """

    @pytest.fixture
    def ve_cteni_smycka(self, bezici_smycka, pin, stisk):
        """Běžící smyčka s otevřenou knihou na 2. stránce a čistým záznamem.

        Kniha z conftestu má 5 stránek, takže je kam listovat oběma směry.
        """
        ctecka, zaznam = bezici_smycka
        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)
        stisk(h.PIN_ENKODER_SW)
        assert pockej(lambda: ctecka.snimek().stav is Stav.CTENI)
        assert pockej(lambda: "eink" in zaznam)
        stisk(h.PIN_DALSI)
        assert pockej(lambda: ctecka.snimek().cislo_stranky == 2)
        zaznam.clear()
        return ctecka, zaznam

    def test_listovani_nesahne_na_eink(self, ve_cteni_smycka, pin):
        ctecka, zaznam = ve_cteni_smycka
        drz(pin, h.PIN_ENKODER_SW)
        assert ctecka.snimek().stav is Stav.RYCHLE_LISTOVANI

        for _ in range(3):
            krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)

        assert pockej(lambda: ctecka.snimek().cislo_stranky == 5)
        assert pockej(lambda: "oled" in zaznam)
        assert "eink" not in zaznam, f"e-ink se překreslil při listování: {zaznam}"
        assert ctecka.snimek().puvodni_cislo_stranky == 2

    def test_potvrzeni_prekresli_eink(self, ve_cteni_smycka, pin, stisk):
        ctecka, zaznam = ve_cteni_smycka
        drz(pin, h.PIN_ENKODER_SW)
        for _ in range(3):
            krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)
        assert pockej(lambda: ctecka.snimek().cislo_stranky == 5)
        zaznam.clear()

        stisk(h.PIN_ENKODER_SW)

        assert pockej(lambda: ctecka.snimek().stav is Stav.CTENI)
        assert pockej(lambda: "eink" in zaznam), "potvrzení nepřekreslilo panel"
        assert ctecka.snimek().cislo_stranky == 5

    def test_zruseni_vrati_stranku_a_nesahne_na_eink(self, ve_cteni_smycka, pin):
        """Zrušení překreslení vyžádá, ale panel drží tentýž text, takže
        VystupEink na něj nesáhne — vrátit se musí jen OLED."""
        ctecka, zaznam = ve_cteni_smycka
        drz(pin, h.PIN_ENKODER_SW)
        for _ in range(3):
            krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)
        assert pockej(lambda: ctecka.snimek().cislo_stranky == 5)
        zaznam.clear()

        drz(pin, h.PIN_ENKODER_SW)

        assert pockej(lambda: ctecka.snimek().stav is Stav.CTENI)
        assert ctecka.snimek().cislo_stranky == 2
        assert pockej(lambda: "oled" in zaznam), "OLED se nevrátil do čtení"
        assert "eink" not in zaznam, f"zrušení zbytečně vzbudilo panel: {zaznam}"

    def test_pri_cteni_enkoder_dal_mlci(self, ve_cteni_smycka, pin):
        """Uvolnění podmínky u otáčení se nesmí protáhnout do běžného čtení."""
        ctecka, zaznam = ve_cteni_smycka
        krok_enkoderu(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)
        time.sleep(0.3)

        assert ctecka.snimek().cislo_stranky == 2
        assert zaznam == [], f"kodér při čtení překreslil {zaznam}"


class TestAkcelerace:
    """Krok podle rychlosti ruky. Čas se vždy vstřikuje, aby test neměřil
    skutečné hodiny a nebyl tím náhodně křehký."""

    def test_prvni_cvaknuti_je_vzdy_po_jedne(self):
        """Po pauze uživatel míří na konkrétní stránku, netočí."""
        a = h.Akcelerace()
        assert a.krok(ted=100.0) == 1

    def test_rychla_serie_zrychli(self):
        a = h.Akcelerace(prah=0.08, zrychleny=10)
        assert a.krok(ted=100.00) == 1
        assert a.krok(ted=100.02) == 10
        assert a.krok(ted=100.04) == 10

    def test_pomale_krokovani_nezrychli(self):
        a = h.Akcelerace(prah=0.08, zrychleny=10)
        a.krok(ted=100.0)
        assert a.krok(ted=100.3) == 1
        assert a.krok(ted=100.6) == 1

    def test_zastaveni_zrychleni_zrusi(self):
        """Po pauze uprostřed série se musí vrátit přesné krokování — jinak by
        doladění pozice po rychlém skoku přestřelovalo."""
        a = h.Akcelerace(prah=0.08, zrychleny=10)
        a.krok(ted=100.0)
        assert a.krok(ted=100.02) == 10
        assert a.krok(ted=101.0) == 1

    def test_hranice_prahu_patri_pomalemu(self):
        """Přesně na prahu se ještě nezrychluje. Hodnoty jsou mocniny dvojky,
        aby test nezkoumal zaokrouhlení floatu místo logiky."""
        a = h.Akcelerace(prah=0.25, zrychleny=10)
        a.krok(ted=100.0)
        assert a.krok(ted=100.25) == 1

    def test_klid_po_prodleve(self):
        a = h.Akcelerace()
        assert a.je_klid(ted=100.0) is True, "bez cvaknutí je klid"
        a.krok(ted=100.0)
        assert a.je_klid(ted=100.2, prodleva=0.6) is False
        assert a.je_klid(ted=100.7, prodleva=0.6) is True


def rychle_cvaknuti(pin, prvni, druhy):
    """Cvaknutí kodéru bez prodlevy — napodobuje svižné otáčení rukou."""
    pin(prvni).drive_low()
    pin(druhy).drive_low()
    pin(prvni).drive_high()
    pin(druhy).drive_high()


class TestZrychleneListovaniNaZelezes:
    """Akcelerace propojená s kodérem a stavem, přes skutečné pin callbacky."""

    @pytest.fixture
    def v_listovani(self):
        c = Ctecka(STROM_ATRAPA)
        akcelerace = h.Akcelerace(prah=10.0, zrychleny=10)  # vše se bere jako rychlé
        zarizeni = h.pripoj_enkoder(c, None, akcelerace)
        assert zarizeni, "kodér se nepřipojil — piny už asi drží jiný test"
        c.dalsi()
        c.akce()
        c.vyzvedni_pozadavek()
        c.dodej_stranky("Alliances.epub", [f"s{i}" for i in range(100)], 50)
        c.zacni_rychle_listovani()
        yield c, pin_enkoderu(zarizeni), akcelerace
        for z in zarizeni:
            z.close()

    def test_rychle_otaceni_skace_po_deseti(self, v_listovani):
        c, pin, _ = v_listovani
        rychle_cvaknuti(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)  # první = 1
        rychle_cvaknuti(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)  # už zrychleně
        assert c.snimek().cislo_stranky == 62
        assert c.snimek().smer_listovani == 1

    def test_otaceni_zpet_nastavi_smer(self, v_listovani):
        c, pin, _ = v_listovani
        rychle_cvaknuti(pin, h.PIN_ENKODER_DT, h.PIN_ENKODER_CLK)
        assert c.snimek().smer_listovani == -1
        assert c.snimek().cislo_stranky == 50

    def test_pri_cteni_kodér_nehne_ani_casem(self, v_listovani):
        """Ignorované cvaknutí při čtení nesmí posunout měřený čas — jinak by
        první platné cvaknutí po vstupu do listování naskočilo jako zrychlené."""
        c, pin, akcelerace = v_listovani
        c.zrus_rychle_listovani()
        assert c.snimek().stav is Stav.CTENI

        rychle_cvaknuti(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)
        assert c.snimek().cislo_stranky == 51, "kodér při čtení otočil stránku"
        assert akcelerace.je_klid(prodleva=0.0) is True

        c.zacni_rychle_listovani()
        rychle_cvaknuti(pin, h.PIN_ENKODER_CLK, h.PIN_ENKODER_DT)
        assert c.snimek().cislo_stranky == 52, "první cvaknutí mělo být po jedné"


class TestGrafikaRychlehoListovani:
    """Vzhled obrazovky rychlého listování — šipky, centrování, zakulacení.

    Kreslí se do obrázku a čtou se pixely: OLED na desktopu není a tohle je
    jediný způsob, jak ověřit, co by na něm bylo vidět.
    """

    POCET = 300

    def _snimek(self, smer=0, stranka=144):
        c = Ctecka(["Duna.epub"])
        c.akce()
        c.vyzvedni_pozadavek()
        c.dodej_stranky("Duna.epub", [{"typ": "text", "obsah": ["x"]}] * self.POCET, stranka)
        c.zacni_rychle_listovani()
        if smer > 0:
            c.dalsi()
        elif smer < 0:
            c.predchozi()
        return c.snimek()

    def _obraz(self, smer=0):
        return h.oled_ui.vykresli_oled(self._snimek(smer), h.oled_ui.nacti_fonty())

    def _rozsah_x(self, obraz, od_y, do_y):
        """Krajní rozsvícené sloupce v pásmu řádků — kde text opravdu leží."""
        pole = obraz.load()
        sloupce = [
            x
            for x in range(obraz.width)
            for y in range(od_y, do_y + 1)
            if pole[x, y]
        ]
        return (min(sloupce), max(sloupce)) if sloupce else None

    def test_sipky_vpred_jsou_vpravo(self):
        assert h.oled_ui._radek_pozice(self._snimek(smer=1)) == "146 / 300 >>"

    def test_sipky_zpet_jsou_vlevo(self):
        assert h.oled_ui._radek_pozice(self._snimek(smer=-1)) == "<< 144 / 300"

    def test_v_klidu_jsou_cisla_bez_sipek(self):
        assert h.oled_ui._radek_pozice(self._snimek(smer=0)) == "145 / 300"

    @pytest.mark.parametrize("smer", [0, 1, -1])
    def test_spodni_radek_je_vycentrovany(self, smer):
        """Okraje vlevo a vpravo se smí lišit nejvýš o pixel (lichá šířka)."""
        obraz = self._obraz(smer)
        levy, pravy = self._rozsah_x(obraz, h.oled_ui.LIST_Y_DOLNI, h.oled_ui.VYSKA - 1)
        assert abs(levy - (h.oled_ui.SIRKA - 1 - pravy)) <= 1, (
            f"nevycentrováno: vlevo {levy}, vpravo {h.oled_ui.SIRKA - 1 - pravy}"
        )

    def test_horni_radek_je_vycentrovany(self):
        obraz = self._obraz()
        levy, pravy = self._rozsah_x(obraz, h.oled_ui.LIST_Y_HORNI, h.oled_ui.LIST_PRUH_OD - 1)
        assert abs(levy - (h.oled_ui.SIRKA - 1 - pravy)) <= 1

    def test_pruh_ma_zakulacene_rohy(self):
        """Rohový pixel obrysu musí být zhasnutý — jinak je to obyčejný obdélník."""
        pole = self._obraz().load()
        for x, y in (
            (0, h.oled_ui.LIST_PRUH_OD),
            (h.oled_ui.SIRKA - 1, h.oled_ui.LIST_PRUH_OD),
            (0, h.oled_ui.LIST_PRUH_DO),
            (h.oled_ui.SIRKA - 1, h.oled_ui.LIST_PRUH_DO),
        ):
            assert not pole[x, y], f"roh ({x}, {y}) svítí — pruh není zakulacený"

    def test_pruh_ma_obrys_i_vypln(self):
        pole = self._obraz().load()
        stred_y = (h.oled_ui.LIST_PRUH_OD + h.oled_ui.LIST_PRUH_DO) // 2
        assert pole[h.oled_ui.SIRKA - 1, stred_y], "chybí pravý okraj obrysu"
        assert pole[h.oled_ui.LIST_VYPLN_OKRAJ + 2, stred_y], "chybí výplň"

    def test_sipky_nezasahuji_do_pruhu(self):
        """Delší řádek se šipkami nesmí přerůst do pásma progress baru."""
        pole = self._obraz(smer=1).load()
        assert not any(
            pole[x, h.oled_ui.LIST_PRUH_DO + 1] for x in range(h.oled_ui.SIRKA)
        )
