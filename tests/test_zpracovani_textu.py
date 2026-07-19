"""Rozvržení textu a cache stránkování."""

import json
import os

import pytest
from PIL import ImageFont

import vykresleni
import zpracovani_textu

FONT_CESTA = vykresleni.FONT_CESTA
SIRKA, VYSKA = vykresleni.TEXT_SIRKA, vykresleni.TEXT_VYSKA


class TestVyskaRadku:
    """Jediný zdroj pravdy pro layout i kreslení."""

    def test_odvozeno_z_metrik_fontu(self, fonty):
        ascent, descent = fonty.text.getmetrics()
        assert zpracovani_textu.vyska_radku(fonty.text) == ascent + descent + 5

    def test_jiny_font_jina_vyska(self, fonty):
        """Velikost se odvozuje z produkční, ne zadrátovaně: pevná konstanta
        se s ní jednou srazí (stalo se při zmenšení písma na 20) a test pak
        padá na shodu, kterou vůbec nezkoumá."""
        maly = ImageFont.truetype(FONT_CESTA, fonty.text.size // 2)
        assert zpracovani_textu.vyska_radku(maly) != zpracovani_textu.vyska_radku(fonty.text)

    def test_rozestup_lze_zmenit(self, fonty):
        ascent, descent = fonty.text.getmetrics()
        assert zpracovani_textu.vyska_radku(fonty.text, 0) == ascent + descent


class TestRozvrzeni:
    def test_pocet_radku_odpovida_vysce(self, fonty, stranky):
        vr = zpracovani_textu.vyska_radku(fonty.text)
        textove = [s for s in stranky if s["typ"] == "text"]
        assert max(len(s["obsah"]) for s in textove) == VYSKA // vr

    def test_text_vyplni_stranku_az_dolu(self, fonty, stranky):
        """Se zadrátovanými 37 px zůstávalo dole 146 px prázdných."""
        vr = zpracovani_textu.vyska_radku(fonty.text)
        radku = max(len(s["obsah"]) for s in stranky if s["typ"] == "text")
        _, descent = fonty.text.getmetrics()
        spodek = vykresleni.OKRAJ + (radku - 1) * vr + descent
        assert 780 < spodek < vykresleni.LISTA_Y

    def test_radky_se_vejdou_do_sirky(self, fonty, stranky):
        preteklo = [
            radek
            for s in stranky[:200]
            if s["typ"] == "text"
            for radek in s["obsah"]
            if radek
            and len([w for w in radek.split(" ") if w]) > 1
            and fonty.text.getlength(radek) > SIRKA
        ]
        assert preteklo == []

    def test_stranka_nezacina_prazdnym_radkem(self, stranky):
        """Odsazení odstavce nemá na začátku stránky co dělat."""
        textove = [s for s in stranky if s["typ"] == "text"]
        assert not [s for s in textove if s["obsah"] and s["obsah"][0] == ""]


class TestOkrajoveVstupy:
    def test_prazdny_obsah(self, fonty):
        assert zpracovani_textu.zformatuj_a_rozdel([], fonty.text, SIRKA, VYSKA) == []

    def test_jeden_odstavec(self, fonty):
        v = zpracovani_textu.zformatuj_a_rozdel(
            [{"typ": "text", "hodnota": "ahoj"}], fonty.text, SIRKA, VYSKA
        )
        assert len(v) == 1
        assert v[0]["obsah"][0] == "ahoj"

    def test_slovo_sirsi_nez_radek_nezacykli(self, fonty):
        dlouhe = "x" * 500
        v = zpracovani_textu.zformatuj_a_rozdel(
            [{"typ": "text", "hodnota": dlouhe}], fonty.text, SIRKA, VYSKA
        )
        assert any(dlouhe in r for s in v for r in s["obsah"])

    def test_obrazek_dostane_vlastni_stranku(self, fonty):
        v = zpracovani_textu.zformatuj_a_rozdel(
            [{"typ": "obrazek", "hodnota": "a/b.jpg"}], fonty.text, SIRKA, VYSKA
        )
        assert v == [{"typ": "obrazek", "obsah": "a/b.jpg"}]

    def test_obrazek_rozdeli_text(self, fonty):
        v = zpracovani_textu.zformatuj_a_rozdel(
            [
                {"typ": "text", "hodnota": "pred"},
                {"typ": "obrazek", "hodnota": "i.jpg"},
                {"typ": "text", "hodnota": "po"},
            ],
            fonty.text,
            SIRKA,
            VYSKA,
        )
        assert [s["typ"] for s in v] == ["text", "obrazek", "text"]

    def test_vyska_mensi_nez_radek_nedeli_nulou(self, fonty):
        v = zpracovani_textu.zformatuj_a_rozdel(
            [{"typ": "text", "hodnota": "a b c d e f"}], fonty.text, SIRKA, 1
        )
        assert max(len(s["obsah"]) for s in v if s["typ"] == "text") == 1


class TestKlicCache:
    """Klíč musí obsáhnout všechno, na čem stránkování závisí."""

    @pytest.fixture
    def zaklad(self, kniha, fonty):
        return zpracovani_textu.klic_cache(kniha, fonty.text, SIRKA, VYSKA)

    def test_je_to_hex_hash(self, zaklad):
        assert len(zaklad) == 16
        assert all(c in "0123456789abcdef" for c in zaklad)

    def test_stejne_parametry_stejny_klic(self, kniha, fonty, zaklad):
        assert zpracovani_textu.klic_cache(kniha, fonty.text, SIRKA, VYSKA) == zaklad

    def test_jina_velikost_fontu(self, kniha, zaklad):
        jiny = ImageFont.truetype(FONT_CESTA, 28)
        assert zpracovani_textu.klic_cache(jiny and kniha, jiny, SIRKA, VYSKA) != zaklad

    def test_jiny_font(self, kniha, zaklad):
        serif = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", 32
        )
        assert zpracovani_textu.klic_cache(kniha, serif, SIRKA, VYSKA) != zaklad

    def test_jina_sirka(self, kniha, fonty, zaklad):
        assert zpracovani_textu.klic_cache(kniha, fonty.text, 400, VYSKA) != zaklad

    def test_jina_vyska(self, kniha, fonty, zaklad):
        assert zpracovani_textu.klic_cache(kniha, fonty.text, SIRKA, 700) != zaklad

    def test_jiny_rozestup(self, kniha, fonty, zaklad):
        assert zpracovani_textu.klic_cache(kniha, fonty.text, SIRKA, VYSKA, 8) != zaklad

    def test_jina_kniha(self, kniha2, fonty, zaklad):
        assert zpracovani_textu.klic_cache(kniha2, fonty.text, SIRKA, VYSKA) != zaklad

    def test_jina_verze_algoritmu(self, kniha, fonty, zaklad, monkeypatch):
        monkeypatch.setattr(zpracovani_textu, "VERZE_ALGORITMU", 99)
        assert zpracovani_textu.klic_cache(kniha, fonty.text, SIRKA, VYSKA) != zaklad

    def test_vymena_souboru_pod_stejnym_jmenem(self, kniha, kniha2, fonty, tmp_path):
        """Bez velikosti a mtime by nová kniha dostala staré stránkování."""
        import shutil

        podvrh = tmp_path / "kniha.epub"
        shutil.copy(kniha, podvrh)
        k1 = zpracovani_textu.klic_cache(str(podvrh), fonty.text, SIRKA, VYSKA)
        shutil.copy(kniha2, podvrh)
        k2 = zpracovani_textu.klic_cache(str(podvrh), fonty.text, SIRKA, VYSKA)
        assert k1 != k2

    def test_neexistujici_kniha_nezhavaruje(self, fonty):
        assert isinstance(
            zpracovani_textu.klic_cache("/neni.epub", fonty.text, SIRKA, VYSKA), str
        )

    def test_load_default_nerozhazi_klic(self, kniha, fonty):
        """font.path je u load_default() BytesIO, jehož repr nese adresu."""
        d1 = ImageFont.load_default()
        d2 = ImageFont.load_default()
        assert zpracovani_textu.klic_cache(
            kniha, d1, SIRKA, VYSKA
        ) == zpracovani_textu.klic_cache(kniha, d2, SIRKA, VYSKA)


class TestCache:
    @pytest.fixture
    def klic(self, kniha, fonty):
        return zpracovani_textu.klic_cache(kniha, fonty.text, SIRKA, VYSKA)

    def test_kolobeh(self, klic, stranky):
        assert zpracovani_textu.nacti_z_cache(klic) is None  # studený start
        zpracovani_textu.uloz_do_cache(klic, stranky)
        assert zpracovani_textu.nacti_z_cache(klic) == stranky

    def test_je_to_cisty_json_ne_pickle(self, klic, stranky):
        zpracovani_textu.uloz_do_cache(klic, stranky)
        syrovy = open(zpracovani_textu._soubor_cache(klic), "rb").read()
        assert json.loads(syrovy.decode("utf-8"))
        assert not syrovy.startswith(b"\x80")  # pickle protokol

    def test_stara_verze_se_nenacte(self, klic, stranky, monkeypatch):
        zpracovani_textu.uloz_do_cache(klic, stranky)
        monkeypatch.setattr(zpracovani_textu, "VERZE_ALGORITMU", 99)
        assert zpracovani_textu.nacti_z_cache(klic) is None

    def test_rozbity_json_se_zahoji(self, klic, stranky):
        zpracovani_textu.uloz_do_cache(klic, stranky)
        open(zpracovani_textu._soubor_cache(klic), "w").write("{neni json")
        assert zpracovani_textu.nacti_z_cache(klic) is None
        zpracovani_textu.uloz_do_cache(klic, stranky)
        assert zpracovani_textu.nacti_z_cache(klic) == stranky

    def test_chybejici_klic_stranky(self, klic):
        soubor = zpracovani_textu._soubor_cache(klic)
        os.makedirs(os.path.dirname(soubor), exist_ok=True)
        open(soubor, "w").write('{"verze": 2}')
        assert zpracovani_textu.nacti_z_cache(klic) is None

    def test_chybejici_soubor(self, klic):
        assert zpracovani_textu.nacti_z_cache(klic) is None

    def test_zapis_je_atomicky(self, klic, stranky):
        zpracovani_textu.uloz_do_cache(klic, stranky)
        assert not os.path.exists(f"{zpracovani_textu._soubor_cache(klic)}.tmp")
