"""Obnova posledního stavu po zapnutí — bez bliknutí, naváže kde skončil.

E-ink drží obraz i bez napájení, takže po zapnutí čtečka obnoví poslední
zobrazený stav a displej nepřekresluje; teprve první stisk kreslí.
"""

import knihovna
from conftest import STRANKY_ATRAPA
from stav import Ctecka, Stav


class TestPrekresleniNaStartu:
    def test_vychozi_startuje_s_prekreslenim(self):
        """Beze změny — první spuštění (nic uloženého) kreslí menu."""
        c = Ctecka(["a.epub"])
        assert c.spotrebuj_prekresleni() is True

    def test_obnova_nevyzaduje_prekresleni(self):
        c = Ctecka(["a.epub"], prekreslit_na_startu=False)
        assert c.spotrebuj_prekresleni() is False


class TestObnovaCteni:
    def test_vrati_do_knihy_bez_prekresleni(self):
        c = Ctecka(["a.epub"], prekreslit_na_startu=False)
        assert c.obnov_cteni("a.epub", STRANKY_ATRAPA, 2) is True

        s = c.snimek()
        assert s.stav is Stav.CTENI
        assert s.cislo_stranky == 3
        assert c.spotrebuj_prekresleni() is False  # panel drží obraz, neblikáme

    def test_prazdne_stranky_neobnovi(self):
        c = Ctecka(["a.epub"], prekreslit_na_startu=False)
        assert c.obnov_cteni("a.epub", [], 0) is False
        assert c.snimek().stav is Stav.MENU

    def test_pozice_se_orizne(self):
        c = Ctecka(["a.epub"], prekreslit_na_startu=False)
        c.obnov_cteni("a.epub", STRANKY_ATRAPA, 999)
        assert c.snimek().cislo_stranky == len(STRANKY_ATRAPA)

    def test_prvni_stisk_po_obnove_uz_kresli(self):
        c = Ctecka(["a.epub"], prekreslit_na_startu=False)
        c.obnov_cteni("a.epub", STRANKY_ATRAPA, 2)
        c.dalsi()  # první stisk
        assert c.spotrebuj_prekresleni() is True
        assert c.snimek().cislo_stranky == 4


class TestObnovaMenu:
    def test_vrati_kurzor_bez_prekresleni(self):
        c = Ctecka(["a.epub", "b.epub", "c.epub"], prekreslit_na_startu=False)
        c.obnov_menu(2)
        assert c.snimek().vyber == 2
        assert c.spotrebuj_prekresleni() is False

    def test_orizne_na_rozsah(self):
        c = Ctecka(["a.epub"], prekreslit_na_startu=False)
        c.obnov_menu(99)
        assert c.snimek().vyber == 0


class TestVyzadejPrekresleni:
    def test_vynuti_prekresleni(self):
        c = Ctecka(["a.epub"], prekreslit_na_startu=False)
        assert c.spotrebuj_prekresleni() is False
        c.vyzadej_prekresleni()
        assert c.spotrebuj_prekresleni() is True


class TestPersistence:
    def test_ulozeni_a_nacteni_cteni(self):
        c = Ctecka(["a.epub"])
        c.akce()
        c.vyzvedni_pozadavek()
        c.dodej_stranky("a.epub", STRANKY_ATRAPA, 2)

        knihovna.uloz_posledni_stav(c.snimek())
        stav = knihovna.nacti_posledni_stav()
        assert stav == {"typ": "cteni", "kniha": "a.epub", "stranka": 2}

    def test_ulozeni_a_nacteni_menu(self):
        c = Ctecka(["a.epub", "b.epub"])
        c.dalsi()
        knihovna.uloz_posledni_stav(c.snimek())
        assert knihovna.nacti_posledni_stav() == {
            "typ": "menu",
            "vyber": 1,
            "adresar": "",
        }

    def test_ulozeni_menu_uvnitr_slozky(self):
        """Adresář se musí uložit, jinak se čtečka po zapnutí probere v kořeni."""
        c = Ctecka(
            {
                "": [{"typ": "slozka", "nazev": "scifi", "cesta": "scifi"}],
                "scifi": [{"typ": "kniha", "nazev": "duna.epub", "cesta": "scifi/duna.epub"}],
            }
        )
        c.akce()  # vstup do složky, kurzor zůstane na ".."
        c.dalsi()  # na duna.epub
        knihovna.uloz_posledni_stav(c.snimek())
        assert knihovna.nacti_posledni_stav() == {
            "typ": "menu",
            "vyber": 1,
            "adresar": "scifi",
        }

    def test_obnovi_menu_ve_slozce(self):
        c = Ctecka(
            {
                "": [{"typ": "slozka", "nazev": "scifi", "cesta": "scifi"}],
                "scifi": [{"typ": "kniha", "nazev": "duna.epub", "cesta": "scifi/duna.epub"}],
            }
        )
        knihovna.uloz_posledni_stav(_snimek_menu(1, "scifi"))
        assert knihovna.obnov_posledni_stav(c, None) is True
        snimek = c.snimek()
        assert snimek.adresar == "scifi"
        assert snimek.polozky[snimek.vyber].cesta == "scifi/duna.epub"

    def test_chybejici_soubor_vraci_none(self):
        assert knihovna.nacti_posledni_stav() is None

    def test_rozbity_soubor_vraci_none(self):
        with open(knihovna.SOUBOR_STAVU, "w") as f:
            f.write("{neni json")
        assert knihovna.nacti_posledni_stav() is None

    def test_zapis_je_atomicky(self):
        c = Ctecka(["a.epub"])
        knihovna.uloz_posledni_stav(c.snimek())
        import os

        assert not os.path.exists(f"{knihovna.SOUBOR_STAVU}.tmp")


class TestObnovPosledniStav:
    def test_bez_ulozeneho_stavu_vraci_false(self, fonty):
        c = Ctecka(knihovna.nacti_seznam_knih(), prekreslit_na_startu=False)
        assert knihovna.obnov_posledni_stav(c, fonty) is False

    def test_obnovi_rozectenou_knihu(self, kniha, fonty):
        # ulož stav "čtu Treason na straně 60"
        knihovna.uloz_posledni_stav(
            _snimek_cteni("Treason.epub", 60)
        )
        c = Ctecka(knihovna.nacti_seznam_knih(), prekreslit_na_startu=False)

        assert knihovna.obnov_posledni_stav(c, fonty) is True
        s = c.snimek()
        assert s.stav is Stav.CTENI
        assert s.kniha == "Treason.epub"
        assert s.cislo_stranky == 61
        assert c.spotrebuj_prekresleni() is False  # žádné bliknutí

    def test_smazana_kniha_vraci_false(self, fonty):
        knihovna.uloz_posledni_stav(_snimek_cteni("neexistuje.epub", 5))
        c = Ctecka(knihovna.nacti_seznam_knih(), prekreslit_na_startu=False)

        # panel drží stránku smazané knihy -> obnova selže, volající překreslí
        assert knihovna.obnov_posledni_stav(c, fonty) is False
        assert c.snimek().stav is Stav.MENU

    def test_obnovi_menu(self, fonty):
        knihy = knihovna.nacti_seznam_knih()
        if len(knihy) < 2:
            import pytest

            pytest.skip("potřebuje aspoň dvě knihy")
        knihovna.uloz_posledni_stav(_snimek_menu(1))
        c = Ctecka(knihy, prekreslit_na_startu=False)
        assert knihovna.obnov_posledni_stav(c, fonty) is True
        assert c.snimek().vyber == 1


# --- pomůcky: malé atrapy snímku pro uložení bez plné Ctecka ---


class _FakeSnimek:
    def __init__(self, stav, kniha, cislo_stranky, vyber, adresar=""):
        self.stav = stav
        self.kniha = kniha
        self.cislo_stranky = cislo_stranky
        self.vyber = vyber
        self.adresar = adresar


def _snimek_cteni(kniha, stranka):
    return _FakeSnimek(Stav.CTENI, kniha, stranka + 1, 0)


def _snimek_menu(vyber, adresar=""):
    return _FakeSnimek(Stav.MENU, None, 0, vyber, adresar)
