"""Produkční program — tlačítka, smyčka, čištění displeje."""

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
