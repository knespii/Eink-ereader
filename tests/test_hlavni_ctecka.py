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

    def test_akce_jen_zada_pozadavek(self, tlacitka_a_ctecka, stisk):
        c, _ = tlacitka_a_ctecka
        stisk(h.PIN_AKCE)
        assert c.snimek().stav is Stav.MENU  # callback nic nenačetl
        assert c.snimek().nacita_se is True
        assert c.vyzvedni_pozadavek() == "Alliances.epub"

    def test_callback_je_okamzity(self, tlacitka_a_ctecka, stisk):
        """Parsování trvá stovky ms; callback, který ho spouští, by se neschoval.

        Měřit jméno vlákna nejde — mock piny volají callback synchronně
        z volajícího vlákna, na reálném HW je to vlákno gpiozero.
        """
        c, _ = tlacitka_a_ctecka
        trvani = []
        puvodni = c.akce

        def sledovana():
            t0 = time.time()
            puvodni()
            trvani.append(time.time() - t0)

        c.akce = sledovana  # na_uvolneni() volá ctecka.akce() dynamicky
        stisk(h.PIN_AKCE)
        assert trvani[0] < 0.01


class TestDlouhyStisk:
    """when_pressed přijde okamžitě, takže krátký stisk visí na uvolnění."""

    def test_dlouhy_stisk_ukonci(self, pin):
        c = Ctecka(["Alliances.epub"])
        tlacitka = h.pripoj_tlacitka(c)
        try:
            pin(h.PIN_AKCE).drive_low()
            time.sleep(2.4)  # přes hold_time=2.0
            pin(h.PIN_AKCE).drive_high()
            time.sleep(0.2)
            assert c.konec is True
        finally:
            for t in tlacitka:
                t.close()

    def test_dlouhy_stisk_neotevre_knihu(self, pin):
        """Jinak by vypnutí čtečky pokaždé spustilo stránkování."""
        c = Ctecka(["Alliances.epub"])
        tlacitka = h.pripoj_tlacitka(c)
        try:
            pin(h.PIN_AKCE).drive_low()
            time.sleep(2.4)
            pin(h.PIN_AKCE).drive_high()
            time.sleep(0.2)
            assert c.vyzvedni_pozadavek() is None
        finally:
            for t in tlacitka:
                t.close()

    def test_kratky_stisk_po_dlouhem_zase_funguje(self, pin, stisk):
        c = Ctecka(["Alliances.epub"])
        tlacitka = h.pripoj_tlacitka(c)
        try:
            pin(h.PIN_AKCE).drive_low()
            time.sleep(2.4)
            pin(h.PIN_AKCE).drive_high()
            time.sleep(0.2)
        finally:
            for t in tlacitka:
                t.close()

        c2 = Ctecka(["Alliances.epub"])
        tlacitka2 = h.pripoj_tlacitka(c2)
        try:
            stisk(h.PIN_AKCE)
            assert c2.vyzvedni_pozadavek() == "Alliances.epub"
        finally:
            for t in tlacitka2:
                t.close()


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
        assert c.vyzvedni_pozadavek() == "Alliances.epub"


class TestEnkoderPriCteni:
    """Při čtení je kodér hluchý: stránky patří tlačítkům u e-inku a nechtěné
    cvrnknutí by jinak spustilo desetisekundové překreslení panelu."""

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

    def test_stisk_nevrati_do_menu(self, ve_cteni, stisk):
        c, _ = ve_cteni
        stisk(h.PIN_ENKODER_SW)
        assert c.snimek().stav is Stav.CTENI


# --- VÝSTUP NA OLED ---


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
    zaznam = []

    class OledAtrapa:
        def display(self, obraz):
            zaznam.append("oled")

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
        stisk(h.PIN_AKCE)  # krátký stisk = zpět do menu

        assert pockej(lambda: ctecka.snimek().stav is Stav.MENU)
        time.sleep(0.4)
        assert "eink" not in zaznam, "návrat do menu zbytečně překreslil panel"


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
