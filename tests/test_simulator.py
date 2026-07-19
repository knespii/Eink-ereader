"""Simulátor — hlavně to, že ukazuje přesně totéž, co poletí na e-ink."""

import io

import pytest
from PIL import Image

import hlavni_ctecka
import knihovna
import simulator
import vykresleni
from stav import Ctecka, Stav

ZDROJ = open(simulator.__file__, encoding="utf-8").read()


@pytest.fixture
def klient():
    return simulator.app.test_client()


@pytest.fixture
def cerstva_ctecka(monkeypatch):
    """Simulátor drží singleton; testy si přepnou na vlastní instanci."""

    def _nova():
        c = Ctecka(knihovna.nacti_seznam_knih())
        monkeypatch.setattr(simulator, "ctecka", c)
        monkeypatch.setattr(simulator, "TLACITKA", simulator.naveste_tlacitka(c))
        return c

    return _nova


def png_z_webu(klient):
    r = klient.get("/screen")
    assert r.status_code == 200
    return Image.open(io.BytesIO(r.data)).convert("RGB")


def vrstvy_pro_displej(ctecka, fonty):
    """Přesně to, co dostane WaveshareDriver.zobraz()."""
    s = ctecka.snimek()
    return vykresleni.vykresli(s, fonty, knihovna.nacti_obrazek_knihy(s.kniha))


class TestZadnyLokalniStav:
    def test_zadne_global(self):
        assert "global " not in ZDROJ

    def test_zadne_duplicitni_funkce(self):
        assert "def otevri_knihu" not in ZDROJ
        assert "def uloz_pozici" not in ZDROJ
        assert "def nacti_seznam_knih" not in ZDROJ

    def test_nekresli_si_sam(self):
        assert "ImageDraw" not in ZDROJ

    def test_zadne_zadratovane_rozmery(self):
        assert "528" not in ZDROJ
        assert "880" not in ZDROJ

    def test_pouziva_sdilenou_architekturu(self):
        assert "Ctecka(" in ZDROJ
        assert "vykresleni.vykresli(" in ZDROJ

    def test_nerotuje(self):
        assert "rotate" not in ZDROJ  # rotace patří driveru


class TestBezpecnost:
    """Dřív tu bylo debug=True + host=0.0.0.0, tedy Werkzeug konzole na síti."""

    def test_debug_vypnuty_a_localhost(self):
        radek = next(l for l in ZDROJ.splitlines() if "app.run(" in l)
        assert "debug=False" in radek
        assert "0.0.0.0" not in radek


class TestWeb:
    def test_index(self, klient):
        assert klient.get("/").status_code == 200

    def test_screen_vraci_png(self, klient):
        assert png_z_webu(klient).size == (vykresleni.SIRKA, vykresleni.VYSKA)

    def test_neznamé_tlacitko(self, klient):
        assert klient.post("/api/stisk/nesmysl").status_code == 404


class TestRoutySahajiNaCtecku:
    def test_dalsi_a_predchozi(self, klient, cerstva_ctecka):
        c = cerstva_ctecka()
        klient.post("/api/stisk/dalsi")
        assert c.snimek().vyber == 1
        klient.post("/api/stisk/predchozi")
        assert c.snimek().vyber == 0

    def test_akce_otevre_knihu(self, klient, cerstva_ctecka, kniha):
        c = cerstva_ctecka()
        klient.post("/api/stisk/akce")
        assert c.snimek().stav is Stav.CTENI
        assert c.snimek().nacita_se is False  # obsluz() práci dodělala


class TestShodaSDisplejem:
    """Klíčové: web ukazuje přesně to, co poletí na e-ink."""

    def test_png_odpovida_vrstvam_pixel_po_pixelu(
        self, klient, cerstva_ctecka, fonty, kniha
    ):
        c = cerstva_ctecka()
        klient.post("/api/stisk/akce")

        png = png_z_webu(klient)
        cerna, cervena = vrstvy_pro_displej(c, fonty)
        assert png.size == cerna.size == cervena.size

        p, cb, cr = png.load(), cerna.load(), cervena.load()
        nesedi = 0
        for y in range(0, vykresleni.VYSKA, 2):
            for x in range(0, vykresleni.SIRKA, 2):
                if cr[x, y] == 0:
                    ocekavano = simulator.BARVA_CERVENE  # červená se skládá poslední
                elif cb[x, y] == 0:
                    ocekavano = simulator.BARVA_INKOUSTU
                else:
                    ocekavano = (255, 255, 255)
                if p[x, y] != ocekavano:
                    nesedi += 1
        assert nesedi == 0

        # a test není prázdný
        assert sum(1 for y in range(0, 880, 2) for x in range(0, 528, 2) if cb[x, y] == 0) > 500

    def test_stejna_sekvence_pres_http_a_gpio_da_stejnou_bitmapu(
        self, klient, cerstva_ctecka, fonty, kniha, stisk, tmp_path
    ):
        import os

        sekvence = ["dalsi", "akce", "dalsi", "dalsi", "predchozi"]
        # "akce" už nemá vlastní tlačítko — na hardwaru ji dělá krátký stisk
        # tlačítka v kodéru. Listování zůstalo na dvojici u e-inku.
        piny = {
            "dalsi": hlavni_ctecka.PIN_DALSI,
            "predchozi": hlavni_ctecka.PIN_PREDCHOZI,
            "akce": hlavni_ctecka.PIN_ENKODER_SW,
        }

        def vynuluj_pozice():
            """Obě cesty sdílejí progress.json — bez tohohle by druhá z nich
            knihu otevřela na pozici uložené tou první."""
            if os.path.exists(knihovna.SOUBOR_POZIC):
                os.remove(knihovna.SOUBOR_POZIC)

        # --- cesta A: web ---
        vynuluj_pozice()
        c_web = cerstva_ctecka()
        for krok in sekvence:
            klient.post(f"/api/stisk/{krok}")
        png_web = png_z_webu(klient)

        # --- cesta B: hardware ---
        vynuluj_pozice()
        c_hw = Ctecka(knihovna.nacti_seznam_knih())
        ovladace = hlavni_ctecka.pripoj_tlacitka(c_hw) + hlavni_ctecka.pripoj_enkoder(
            c_hw
        )
        try:
            for krok in sekvence:
                stisk(piny[krok])
                knihovna.obsluz(c_hw, fonty)  # to, co dělá hlavní smyčka
        finally:
            for o in ovladace:
                o.close()

        assert c_web.snimek() == c_hw.snimek()

        cerna_web, cervena_web = vrstvy_pro_displej(c_web, fonty)
        cerna_hw, cervena_hw = vrstvy_pro_displej(c_hw, fonty)
        assert cerna_web.tobytes() == cerna_hw.tobytes()
        assert cervena_web.tobytes() == cervena_hw.tobytes()

        p, cb, cr = png_web.load(), cerna_hw.load(), cervena_hw.load()
        nesedi = sum(
            1
            for y in range(0, vykresleni.VYSKA, 2)
            for x in range(0, vykresleni.SIRKA, 2)
            if p[x, y]
            != (
                simulator.BARVA_CERVENE
                if cr[x, y] == 0
                else simulator.BARVA_INKOUSTU
                if cb[x, y] == 0
                else (255, 255, 255)
            )
        )
        assert nesedi == 0


class TestJedineTlacitkoCtecky:
    """Web má na místě odstraněného PIN_AKCE prostřední tlačítko, které umí
    krátký i dlouhý stisk. Kdyby se rozešlo s kodérem, simulátor by přestal
    testovat produkci a začal testovat sám sebe — přesně to, co se už jednou
    stalo (viz docstring simulator.py)."""

    def test_kratky_stisk_pri_cteni_otevre_menu_a_nechá_knihu(
        self, klient, cerstva_ctecka, kniha
    ):
        c = cerstva_ctecka()
        klient.post("/api/stisk/akce")  # otevře knihu
        assert c.snimek().stav is Stav.CTENI

        klient.post("/api/stisk/akce")  # a zpátky do menu
        assert c.snimek().stav is Stav.MENU
        assert c.snimek().pocet_stranek > 0, "kniha se zahodila, escape nemá kam"

    def test_dlouhy_stisk_vrati_do_knihy(self, klient, cerstva_ctecka, kniha):
        c = cerstva_ctecka()
        klient.post("/api/stisk/akce")
        klient.post("/api/stisk/dalsi")  # na stránku 2
        stranka = c.snimek().cislo_stranky
        klient.post("/api/stisk/akce")  # do menu
        assert c.snimek().stav is Stav.MENU

        klient.post("/api/stisk/dlouhy_stisk")

        assert c.snimek().stav is Stav.CTENI
        assert c.snimek().cislo_stranky == stranka

    def test_dlouhy_stisk_bez_knihy_nic_neudela(self, klient, cerstva_ctecka, kniha):
        c = cerstva_ctecka()
        r = klient.post("/api/stisk/dlouhy_stisk")
        assert r.status_code == 200
        assert c.snimek().stav is Stav.MENU

    def test_stranka_zna_oba_stisky(self, klient):
        """Endpointy bez tlačítka v HTML by nikdo nenamačkal."""
        html = klient.get("/").get_data(as_text=True)
        assert "'akce'" in html
        assert "'dlouhy_stisk'" in html
        assert str(int(hlavni_ctecka.DOBA_DRZENI_ENKODER * 1000)) in html

    def test_neznama_udalost_je_404(self, klient):
        assert klient.post("/api/stisk/neexistuje").status_code == 404


class TestPozice:
    def test_uklada_pres_sdilenou_knihovnu(self, klient, cerstva_ctecka, kniha):
        cerstva_ctecka()
        klient.post("/api/stisk/akce")
        klient.post("/api/stisk/dalsi")

        ulozene = knihovna.nacti_pozice()
        assert ulozene
        assert not any("/" in k for k in ulozene)
