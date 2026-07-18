"""Práce se soubory — pozice, cache stránkování, cesty."""

import os
import time

import pytest

import knihovna


class TestCestyNezaviseNaCwd:
    def test_slozka_knih_je_absolutni(self):
        assert os.path.isabs(knihovna.SLOZKA_KNIH)

    def test_soubor_pozic_je_absolutni(self):
        assert os.path.isabs(knihovna.SOUBOR_POZIC)

    def test_knihy_se_najdou_i_z_jineho_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert isinstance(knihovna.nacti_seznam_knih(), list)


class TestPozice:
    def test_kolobeh(self):
        knihovna.uloz_pozici("Treason.epub", 42)
        assert knihovna.nacti_pozice() == {"Treason.epub": 42}

    def test_druha_kniha_nesmaze_prvni(self):
        knihovna.uloz_pozici("Treason.epub", 42)
        knihovna.uloz_pozici("Alliances.epub", 7)
        assert knihovna.nacti_pozice() == {"Treason.epub": 42, "Alliances.epub": 7}

    def test_cizi_klice_zustanou(self):
        import json

        with open(knihovna.SOUBOR_POZIC, "w") as f:
            json.dump({"epuby/stara.epub": 280}, f)
        knihovna.uloz_pozici("nova.epub", 2)
        assert knihovna.nacti_pozice() == {"epuby/stara.epub": 280, "nova.epub": 2}

    def test_klice_nejsou_cesty(self):
        knihovna.uloz_pozici("Treason.epub", 1)
        assert not any("/" in k for k in knihovna.nacti_pozice())


class TestOdolnostPozic:
    def test_chybejici_soubor(self):
        assert knihovna.nacti_pozice() == {}

    def test_rozbity_json_se_zahoji(self):
        open(knihovna.SOUBOR_POZIC, "w").write("{neni json")
        assert knihovna.nacti_pozice() == {}
        knihovna.uloz_pozici("Treason.epub", 5)
        assert knihovna.nacti_pozice() == {"Treason.epub": 5}


class TestAtomickyZapis:
    """Čtečka se vypíná odpojením napájení uprostřed zápisu."""

    def test_po_zapisu_nezustal_tmp(self):
        knihovna.uloz_pozici("Treason.epub", 42)
        assert not os.path.exists(f"{knihovna.SOUBOR_POZIC}.tmp")

    def test_vypadek_pred_prejmenovanim_nechá_stary_soubor_cely(self):
        knihovna.uloz_pozici("Treason.epub", 100)
        puvodni = open(knihovna.SOUBOR_POZIC).read()

        def selze(a, b):
            raise OSError("simulovaný výpadek")

        # Ne přes monkeypatch: jeho undo() by zrušilo i autouse fixturu, která
        # odklání SOUBOR_POZIC, a test by pak sáhl na skutečné pozice uživatele.
        realny_replace = os.replace
        os.replace = selze
        try:
            knihovna.uloz_pozici("Treason.epub", 999)
        finally:
            os.replace = realny_replace

        assert open(knihovna.SOUBOR_POZIC).read() == puvodni
        assert knihovna.nacti_pozice() == {"Treason.epub": 100}


class TestNactiStranky:
    def test_pouziva_cache(self, kniha, fonty):
        t0 = time.time()
        prvni = knihovna.nacti_stranky("Treason.epub", fonty)
        studeny = time.time() - t0

        t0 = time.time()
        druhy = knihovna.nacti_stranky("Treason.epub", fonty)
        teply = time.time() - t0

        assert prvni == druhy
        assert len(prvni) > 100
        assert teply < studeny / 3


class TestObsluz:
    def test_vyridi_pozadavek_a_ulozi_pozici(self, kniha, fonty):
        from stav import Ctecka, Stav

        c = Ctecka(knihovna.nacti_seznam_knih())
        c.akce()
        knihovna.obsluz(c, fonty)

        assert c.snimek().stav is Stav.CTENI
        c.dalsi()
        knihovna.obsluz(c, fonty)
        assert knihovna.nacti_pozice()

    def test_pri_ukonceni_uz_nestrankuje(self, fonty):
        from stav import Ctecka, Stav

        c = Ctecka(knihovna.nacti_seznam_knih())
        c.akce()
        c.ukonci()
        knihovna.obsluz(c, fonty)
        assert c.snimek().stav is Stav.MENU  # knihu neotevřel


class TestNactiObrazekKnihy:
    def test_bez_knihy_vraci_none(self):
        assert knihovna.nacti_obrazek_knihy(None) is None

    def test_s_knihou_vraci_funkci(self, kniha):
        loader = knihovna.nacti_obrazek_knihy("Treason.epub")
        assert callable(loader)
        assert loader("neexistuje/v/archivu.jpg") is None


class TestStrom:
    """Skenování knihovny: jedna úroveň složek, nic hlouběji."""

    def _knihovna(self, tmp_path, monkeypatch):
        monkeypatch.setattr(knihovna, "SLOZKA_KNIH", str(tmp_path))
        return tmp_path

    def test_koren_i_slozka(self, tmp_path, monkeypatch):
        self._knihovna(tmp_path, monkeypatch)
        (tmp_path / "koren.epub").touch()
        (tmp_path / "scifi").mkdir()
        (tmp_path / "scifi" / "duna.epub").touch()

        strom = knihovna.nacti_strom()
        assert set(strom) == {"", "scifi"}
        assert {p["nazev"]: p["typ"] for p in strom[""]} == {
            "koren.epub": "kniha",
            "scifi": "slozka",
        }
        assert [p["cesta"] for p in strom["scifi"]] == ["scifi/duna.epub"]

    def test_zanorena_slozka_se_ignoruje(self, tmp_path, monkeypatch):
        """Zadání povoluje jen 1. úroveň — hlouběji se nekouká."""
        self._knihovna(tmp_path, monkeypatch)
        (tmp_path / "scifi" / "hlubs").mkdir(parents=True)
        (tmp_path / "scifi" / "hlubs" / "skryta.epub").touch()

        strom = knihovna.nacti_strom()
        assert "scifi/hlubs" not in strom
        assert strom["scifi"] == []  # samotná podsložka se nehlásí ani jako položka

    def test_neepub_soubory_se_ignoruji(self, tmp_path, monkeypatch):
        self._knihovna(tmp_path, monkeypatch)
        (tmp_path / "poznamky.txt").touch()
        (tmp_path / "kniha.epub").touch()
        assert [p["nazev"] for p in knihovna.nacti_strom()[""]] == ["kniha.epub"]

    def test_seznam_knih_vraci_relativni_cesty(self, tmp_path, monkeypatch):
        self._knihovna(tmp_path, monkeypatch)
        (tmp_path / "koren.epub").touch()
        (tmp_path / "scifi").mkdir()
        (tmp_path / "scifi" / "duna.epub").touch()
        assert sorted(knihovna.nacti_seznam_knih()) == ["koren.epub", "scifi/duna.epub"]

    def test_prazdna_knihovna(self, tmp_path, monkeypatch):
        self._knihovna(tmp_path, monkeypatch)
        assert knihovna.nacti_strom() == {"": []}


class TestBezpecnaCesta:
    """Cesty jdou do progress.json — ručně upravený soubor nesmí sáhnout ven."""

    def test_odmitne_uniku_ze_slozky(self):
        with pytest.raises(ValueError):
            knihovna._bezpecna_cesta("../../etc/passwd")

    def test_odmitne_unik_pres_podslozku(self):
        with pytest.raises(ValueError):
            knihovna._bezpecna_cesta("scifi/../../tajne.epub")

    def test_pusti_beznou_cestu(self):
        cesta = knihovna._bezpecna_cesta("scifi/duna.epub")
        assert cesta.startswith(knihovna.SLOZKA_KNIH)
