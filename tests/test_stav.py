"""Konečný automat — čistá logika, žádný hardware."""

import sys
import threading
import time

import pytest

from conftest import STRANKY_ATRAPA
from stav import Ctecka, Stav


def test_neimportuje_hardware_ani_kresleni():
    """Hledat jména v textu nejde — docstring modulu je sám zmiňuje."""
    import ast

    import stav

    strom = ast.parse(open(stav.__file__, encoding="utf-8").read())
    importy = set()
    for uzel in ast.walk(strom):
        if isinstance(uzel, ast.Import):
            importy.update(a.name.split(".")[0] for a in uzel.names)
        elif isinstance(uzel, ast.ImportFrom) and uzel.module:
            importy.add(uzel.module.split(".")[0])

    assert importy == {"threading", "dataclasses", "enum", "typing"}


def test_startuje_v_menu():
    c = Ctecka(["b.epub", "a.epub"])
    assert c.snimek().stav is Stav.MENU


def test_seznam_se_radi():
    c = Ctecka(["b.epub", "a.epub"])
    assert c.snimek().seznam_knih == ("a.epub", "b.epub")


def test_prvni_vykresleni_je_vyzadano():
    c = Ctecka(["a.epub"])
    assert c.spotrebuj_prekresleni() is True
    assert c.spotrebuj_prekresleni() is False


class TestPohybVMenu:
    def test_na_zacatku_nejde_vys(self):
        c = Ctecka(["a.epub", "b.epub"])
        c.spotrebuj_prekresleni()
        c.predchozi()
        assert c.snimek().vyber == 0

    def test_marny_pohyb_neprekresluje(self):
        c = Ctecka(["a.epub", "b.epub"])
        c.spotrebuj_prekresleni()
        c.predchozi()
        assert c.spotrebuj_prekresleni() is False

    def test_posun_dolu(self):
        c = Ctecka(["a.epub", "b.epub"])
        c.spotrebuj_prekresleni()
        c.dalsi()
        assert c.snimek().vyber == 1
        assert c.spotrebuj_prekresleni() is True

    def test_na_konci_nejde_niz(self):
        c = Ctecka(["a.epub", "b.epub"])
        c.dalsi()
        c.dalsi()
        assert c.snimek().vyber == 1


class TestOtevreniPresPozadavek:
    """Parsování je drahé, takže akce() smí jen podat požadavek."""

    def test_akce_nemeni_stav_rovnou(self):
        c = Ctecka(["a.epub"])
        c.akce()
        assert c.snimek().stav is Stav.MENU
        assert c.snimek().nacita_se is True

    def test_pozadavek_nese_vybranou_knihu(self):
        c = Ctecka(["a.epub", "b.epub"])
        c.dalsi()
        c.akce()
        assert c.vyzvedni_pozadavek() == "b.epub"
        assert c.vyzvedni_pozadavek() is None

    def test_behem_parsovani_nacita_se_drzi(self):
        c = Ctecka(["a.epub"])
        c.akce()
        c.vyzvedni_pozadavek()
        assert c.snimek().nacita_se is True

    def test_vstup_se_behem_nacitani_ignoruje(self):
        c = Ctecka(["a.epub", "b.epub"])
        c.akce()
        c.vyzvedni_pozadavek()
        c.dalsi()
        c.akce()
        assert c.snimek().vyber == 0
        assert c.vyzvedni_pozadavek() is None


class TestDodaniStranek:
    def test_prepne_do_cteni(self):
        c = Ctecka(["a.epub"])
        c.akce()
        c.vyzvedni_pozadavek()
        assert c.dodej_stranky("a.epub", STRANKY_ATRAPA, 2) is True

        s = c.snimek()
        assert s.stav is Stav.CTENI
        assert s.nacita_se is False
        assert s.cislo_stranky == 3
        assert s.pocet_stranek == 5
        assert s.stranka == STRANKY_ATRAPA[2]

    def test_pozice_se_orizne_na_rozsah(self):
        c = Ctecka(["a.epub"])
        c.akce()
        c.vyzvedni_pozadavek()
        c.dodej_stranky("a.epub", STRANKY_ATRAPA, 999)
        assert c.snimek().cislo_stranky == 5

    def test_prazdna_dodavka_je_selhani(self):
        c = Ctecka(["rozbita.epub"])
        c.akce()
        c.vyzvedni_pozadavek()
        assert c.dodej_stranky("rozbita.epub", []) is False

        s = c.snimek()
        assert s.stav is Stav.MENU
        assert "rozbita.epub" in s.chyba
        assert s.nacita_se is False  # nezasekne se

    def test_zastarala_dodavka_se_zahodi(self):
        c = Ctecka(["a.epub", "b.epub"])
        c.akce()
        c.vyzvedni_pozadavek()
        c.zpet_do_menu()  # uživatel si to rozmyslel
        assert c.dodej_stranky("a.epub", STRANKY_ATRAPA) is False
        assert c.snimek().stav is Stav.MENU


class TestOtaceniStranek:
    @pytest.fixture
    def ctecka(self):
        c = Ctecka(["a.epub"])
        c.akce()
        c.vyzvedni_pozadavek()
        c.dodej_stranky("a.epub", STRANKY_ATRAPA, 2)
        return c

    def test_posun_vpred(self, ctecka):
        ctecka.dalsi()
        assert ctecka.snimek().cislo_stranky == 4

    def test_posledni_strana_nepreteka(self, ctecka):
        for _ in range(10):
            ctecka.dalsi()
        assert ctecka.snimek().cislo_stranky == 5

    def test_zapisy_se_sliji_do_jednoho(self, ctecka):
        assert ctecka.vyzvedni_pozici_k_ulozeni() is None
        ctecka.dalsi()
        ctecka.dalsi()
        assert ctecka.vyzvedni_pozici_k_ulozeni() == ("a.epub", 4)
        assert ctecka.vyzvedni_pozici_k_ulozeni() is None

    def test_marne_otoceni_nic_neuklada(self, ctecka):
        for _ in range(10):
            ctecka.dalsi()
        ctecka.vyzvedni_pozici_k_ulozeni()
        ctecka.dalsi()
        assert ctecka.vyzvedni_pozici_k_ulozeni() is None

    def test_navrat_do_menu_uvolni_pamet(self, ctecka):
        ctecka.akce()
        s = ctecka.snimek()
        assert s.stav is Stav.MENU
        assert s.pocet_stranek == 0
        assert s.kniha is None


def test_stisk_behem_renderu_se_neztrati():
    """Vlajka se shazuje před renderem, ne po něm."""
    c = Ctecka(["a.epub"])
    c.akce()
    c.vyzvedni_pozadavek()
    c.dodej_stranky("a.epub", STRANKY_ATRAPA, 0)

    assert c.spotrebuj_prekresleni() is True  # smyčka začíná kreslit
    c.dalsi()  # stisk PRÁVĚ TEĎ, uprostřed patnáctisekundového zápisu
    assert c.spotrebuj_prekresleni() is True  # a musí si vynutit další render
    assert c.snimek().cislo_stranky == 2


class TestSeznamKnih:
    def test_vyber_drzi_tutez_knihu(self):
        c = Ctecka(["a.epub", "b.epub", "c.epub"])
        c.dalsi()
        c.dalsi()
        c.nastav_seznam_knih(["a.epub", "b.epub", "c.epub", "nova.epub"])
        s = c.snimek()
        assert s.seznam_knih[s.vyber] == "c.epub"

    def test_po_smazani_se_vyber_zaradi_zpet(self):
        c = Ctecka(["a.epub", "b.epub", "c.epub"])
        c.dalsi()
        c.dalsi()
        c.nastav_seznam_knih(["a.epub"])
        assert c.snimek().vyber == 0

    def test_stejny_seznam_neprekresluje(self):
        c = Ctecka(["a.epub"])
        assert c.nastav_seznam_knih(["a.epub"]) is False


class TestPrazdnaKnihovna:
    def test_nic_nepada(self):
        c = Ctecka([])
        c.akce()
        c.dalsi()
        c.predchozi()
        assert c.vyzvedni_pozadavek() is None
        assert c.snimek().stav is Stav.MENU


def test_ukonceni_probudi_cekajici_smycku():
    c = Ctecka(["a.epub"])
    c.spotrebuj_prekresleni()

    t0 = time.time()
    threading.Timer(0.1, c.ukonci).start()
    c.cekej_na_prekresleni(timeout=5.0)

    assert time.time() - t0 < 1.0  # ne celý timeout
    assert c.konec is True


def test_soubeh_vlaken_neztrati_stisky():
    c = Ctecka(["a.epub"])
    c.akce()
    c.vyzvedni_pozadavek()
    c.dodej_stranky("a.epub", [{"typ": "text", "obsah": []} for _ in range(1000)], 0)

    def macka():
        for _ in range(200):
            c.dalsi()

    vlakna = [threading.Thread(target=macka) for _ in range(4)]
    for v in vlakna:
        v.start()
    for v in vlakna:
        v.join()

    assert c.snimek().cislo_stranky == 801  # 4×200, žádný ztracený inkrement
