"""Vykreslení — čisté PIL, bez hardwaru."""

import sys

import pytest
from PIL import Image

import vykresleni
import zpracovani_epub
import zpracovani_textu
from stav import Ctecka, Stav


def _inkoust(bitmapa):
    return sum(n for n, v in bitmapa.getcolors() if v == 0)


def _radku_na_strance(fonty):
    """Kolik řádků se vejde na plnou stránku — týž výpočet jako ve stránkování."""
    return vykresleni.TEXT_VYSKA // zpracovani_textu.vyska_radku(fonty.text)


def _zacatky_radku(bitmapa):
    """Horní hrana každého souvislého pásma inkoustu — tedy začátky řádků."""
    pole = bitmapa.load()
    ma_inkoust = [
        any(pole[x, y] == 0 for x in range(bitmapa.width))
        for y in range(bitmapa.height)
    ]
    return [
        y
        for y in range(bitmapa.height)
        if ma_inkoust[y] and not (y > 0 and ma_inkoust[y - 1])
    ]


def _svisly_rozsah(bitmapa):
    """(nejvyšší, nejnižší) řádek s inkoustem. Bez inkoustu vrací (0, 0)."""
    pole = bitmapa.load()
    radky = [
        y
        for y in range(bitmapa.height)
        for x in range(0, bitmapa.width, 4)
        if pole[x, y] == 0
    ]
    return (min(radky), max(radky)) if radky else (0, 0)


class TestCistota:
    def test_neimportuje_hardware(self):
        """Přes AST, ne přes sys.modules — ten může naplnit kdokoliv jiný."""
        import ast

        strom = ast.parse(open(vykresleni.__file__, encoding="utf-8").read())
        importy = set()
        for uzel in ast.walk(strom):
            if isinstance(uzel, ast.Import):
                importy.update(a.name.split(".")[0] for a in uzel.names)
            elif isinstance(uzel, ast.ImportFrom) and uzel.module:
                importy.add(uzel.module.split(".")[0])

        assert "waveshare_epd" not in importy
        assert "gpiozero" not in importy
        assert "flask" not in importy

    def test_zdroj_nezna_waveshare_ani_rotaci(self):
        zdroj = open(vykresleni.__file__, encoding="utf-8").read()
        assert "waveshare" not in zdroj
        assert "rotate" not in zdroj  # rotace patří driveru

    def test_dve_volani_nad_stejnym_snimkem_daji_totez(self, fonty):
        c = Ctecka(["a.epub"])
        a1, _ = vykresleni.vykresli(c.snimek(), fonty)
        a2, _ = vykresleni.vykresli(c.snimek(), fonty)
        assert a1.tobytes() == a2.tobytes()
        assert a1 is not a2  # nesdílí buffer


class TestRozmery:
    def test_odvozene_konstanty(self):
        assert (vykresleni.SIRKA, vykresleni.VYSKA) == (528, 880)
        assert vykresleni.TEXT_SIRKA == 488
        assert vykresleni.TEXT_VYSKA == 820
        assert vykresleni.LISTA_Y == 840

    def test_vraci_dve_bitmapy_na_vysku(self, fonty):
        c = Ctecka(["a.epub"])
        cerna, cervena = vykresleni.vykresli(c.snimek(), fonty)
        assert cerna.size == cervena.size == (528, 880)
        assert cerna.mode == cervena.mode == "1"


class TestMenu:
    def test_neco_se_nakresli(self, fonty):
        cerna, cervena = vykresleni.vykresli(Ctecka(["a.epub"]).snimek(), fonty)
        assert _inkoust(cerna) > 0
        assert _inkoust(cervena) < 5000  # červená má jen lištu

    def test_vyber_se_zvyrazni(self, fonty):
        c = Ctecka(["a.epub", "b.epub"])
        prvni, _ = vykresleni.vykresli(c.snimek(), fonty)
        c.dalsi()
        druhy, _ = vykresleni.vykresli(c.snimek(), fonty)
        assert prvni.tobytes() != druhy.tobytes()

    def test_prazdna_knihovna_nepada(self, fonty):
        cerna, _ = vykresleni.vykresli(Ctecka([]).snimek(), fonty)
        assert _inkoust(cerna) > 0

    def test_nacitani_se_ukaze_v_liste(self, fonty):
        c = Ctecka(["a.epub"])
        _, klid = vykresleni.vykresli(c.snimek(), fonty)
        c.akce()
        _, nacita = vykresleni.vykresli(c.snimek(), fonty)
        assert nacita.tobytes() != klid.tobytes()

    def test_chyba_se_ukaze(self, fonty):
        c = Ctecka(["a.epub"])
        c.akce()
        c.dodej_stranky(c.vyzvedni_pozadavek(), [])
        assert c.snimek().chyba is not None
        cerna, cervena = vykresleni.vykresli(c.snimek(), fonty)
        assert _inkoust(cervena) > 0


class TestNazevKnihy:
    def test_odreze_priponu(self):
        assert vykresleni._nazev_knihy("Treason.epub") == "Treason"

    def test_zkrati_dlouhy(self):
        assert vykresleni._nazev_knihy("A" * 40 + ".epub") == "A" * 22 + "..."

    def test_bez_pripony_necha_byt(self):
        assert vykresleni._nazev_knihy("Kniha") == "Kniha"


class TestRolovaniMenu:
    KNIHY = [f"Kniha {i:02d}.epub" for i in range(30)]

    def test_vejde_se_13(self):
        assert vykresleni.POLOZEK_NA_STRANKU == 13

    def test_vybrana_kniha_je_vzdy_videt(self):
        c = Ctecka(self.KNIHY)
        for _ in range(len(self.KNIHY)):
            s = c.snimek()
            prvni = vykresleni._prvni_v_okne(s)
            assert prvni <= s.vyber < prvni + vykresleni.POLOZEK_NA_STRANKU
            c.dalsi()

    def test_nic_nepreteka_pres_listu(self, fonty):
        c = Ctecka(self.KNIHY)
        for _ in range(len(self.KNIHY)):
            cerna, _ = vykresleni.vykresli(c.snimek(), fonty)
            pole = cerna.load()
            assert not any(
                pole[x, y] == 0
                for y in range(vykresleni.LISTA_Y + 3, vykresleni.VYSKA)
                for x in range(0, vykresleni.SIRKA, 4)
            )
            c.dalsi()

    def test_roluje_se_po_strankach(self):
        c = Ctecka(self.KNIHY)
        for _ in range(12):
            c.dalsi()
        assert vykresleni._prvni_v_okne(c.snimek()) == 0  # 13. položka je ještě doma
        c.dalsi()
        assert vykresleni._prvni_v_okne(c.snimek()) == 13  # až teď se přeskočí

    @pytest.mark.parametrize(
        "posun,ocekavano",
        [(0, "Knihy 1–13 z 30"), (12, "Knihy 1–13 z 30"),
         (13, "Knihy 14–26 z 30"), (29, "Knihy 27–30 z 30")],
    )
    def test_lista_hlasi_rozsah(self, posun, ocekavano):
        c = Ctecka(self.KNIHY)
        for _ in range(posun):
            c.dalsi()
        assert vykresleni._text_listy(c.snimek()) == ocekavano

    def test_bez_rolovani_zustava_pocet(self):
        c = Ctecka(["a.epub", "b.epub"])
        assert vykresleni._text_listy(c.snimek()) == "Počet knih: 2"


class TestCteni:
    @pytest.fixture
    def ctecka_v_knize(self, stranky):
        c = Ctecka(["Treason.epub"])
        c.akce()
        c.dodej_stranky(c.vyzvedni_pozadavek(), stranky, 60)
        return c

    def test_text_se_vykresli(self, ctecka_v_knize, fonty):
        cerna, _ = vykresleni.vykresli(ctecka_v_knize.snimek(), fonty)
        assert _inkoust(cerna) > 10000

    def test_cervena_vrstva_zustane_prazdna(self, ctecka_v_knize, fonty):
        """Na e-inku je při čtení jen text knihy — číslo stránky ukazuje OLED.

        Lišta se sem kreslila dřív; kdyby se vrátila, ubere místo textu a
        vynutí překreslení panelu i tehdy, když se změnilo jen pořadové číslo.
        """
        _, cervena = vykresleni.vykresli(ctecka_v_knize.snimek(), fonty)
        assert _inkoust(cervena) == 0

    def test_menu_listu_porad_kresli(self, fonty):
        """Kontrola, že se lišta zrušila jen pro čtení, ne pro menu."""
        _, cervena = vykresleni.vykresli(Ctecka(["a.epub"]).snimek(), fonty)
        assert _inkoust(cervena) > 0

    def test_text_sahá_az_dolu(self, ctecka_v_knize, fonty):
        """Se zadrátovanými 37 px končil kolem y=700.

        Prohledává se celá výška panelu, ne jen po LISTA_Y: po zrušení lišty
        text sahá i pod ni a užší výřez by neodhalil, že se text seká.
        """
        cerna, _ = vykresleni.vykresli(ctecka_v_knize.snimek(), fonty)
        nahore, dole = _svisly_rozsah(cerna)
        assert 780 < dole < vykresleni.VYSKA

    def test_text_je_svisle_na_stredu(self, ctecka_v_knize, fonty):
        """Volné místo po zrušené liště se rozdělí nahoru a dolů.

        Dřív text začínal na OKRAJ a celý zbytek zůstal dole.
        """
        cerna, _ = vykresleni.vykresli(ctecka_v_knize.snimek(), fonty)
        nahore, dole = _svisly_rozsah(cerna)
        okraj_dole = vykresleni.VYSKA - dole - 1
        assert abs(nahore - okraj_dole) < 15, f"okraje {nahore} vs {okraj_dole}"

    def test_kratka_stranka_neplave_uprostred(self, fonty):
        """Odsazení se počítá z plné stránky, ne z počtu řádků na té aktuální —
        jinak by text mezi stránkami poskakoval.

        Obě stránky mají shodný první řádek, aby se porovnávalo odsazení,
        ne náhodou vyšší glyf.
        """
        radek = "Ahoj svete"
        c = Ctecka(["a.epub"])
        c.akce()
        c.dodej_stranky(
            c.vyzvedni_pozadavek(),
            [
                {"typ": "text", "obsah": [radek]},
                {"typ": "text", "obsah": [radek] * _radku_na_strance(fonty)},
            ],
            0,
        )
        kratka, _ = vykresleni.vykresli(c.snimek(), fonty)
        c.dalsi()
        plna, _ = vykresleni.vykresli(c.snimek(), fonty)

        assert _svisly_rozsah(kratka)[0] == _svisly_rozsah(plna)[0]

    def test_pouziva_rozestup_z_layoutu(self, fonty):
        """Rozteč nakreslených řádků se musí rovnat té, se kterou počítalo
        stránkování. Měří se z bitmapy, ne proti zadrátovanému číslu — to by
        se muselo přepisovat při každé změně velikosti fontu a testovalo by
        konstantu místo vazby mezi layoutem a kreslením.
        """
        c = Ctecka(["a.epub"])
        c.akce()
        c.dodej_stranky(c.vyzvedni_pozadavek(), [{"typ": "text", "obsah": ["Ahoj"] * 3}], 0)
        cerna, _ = vykresleni.vykresli(c.snimek(), fonty)

        zacatky = _zacatky_radku(cerna)
        assert len(zacatky) == 3, f"nenašel jsem tři řádky, ale {len(zacatky)}"
        rozestup = zpracovani_textu.vyska_radku(fonty.text)
        assert zacatky[1] - zacatky[0] == rozestup
        assert zacatky[2] - zacatky[1] == rozestup


class TestObrazkovaStranka:
    @pytest.fixture
    def ctecka_na_obrazku(self, stranky):
        index = next(
            (i for i, s in enumerate(stranky) if s["typ"] == "obrazek"), None
        )
        if index is None:
            pytest.skip("kniha nemá obrázkovou stránku")
        c = Ctecka(["Treason.epub"])
        c.akce()
        c.dodej_stranky(c.vyzvedni_pozadavek(), stranky, index)
        return c

    def test_loader_dostane_cestu_v_archivu(self, ctecka_na_obrazku, fonty, kniha):
        volano = []

        def loader(cesta):
            volano.append(cesta)
            return zpracovani_epub.nacti_obrazek(
                kniha, cesta, vykresleni.TEXT_SIRKA, vykresleni.TEXT_VYSKA
            )

        cerna, _ = vykresleni.vykresli(ctecka_na_obrazku.snimek(), fonty, loader)
        assert volano == [ctecka_na_obrazku.snimek().stranka["obsah"]]
        assert _inkoust(cerna) > 1000

    def test_bez_loaderu_se_vykresli_zastupka(self, ctecka_na_obrazku, fonty):
        cerna, _ = vykresleni.vykresli(ctecka_na_obrazku.snimek(), fonty)
        assert _inkoust(cerna) > 100  # něco tam je, ale nespadlo to

    def test_loader_vracejici_none_nepada(self, ctecka_na_obrazku, fonty):
        cerna, _ = vykresleni.vykresli(
            ctecka_na_obrazku.snimek(), fonty, lambda c: None
        )
        assert isinstance(cerna, Image.Image)
