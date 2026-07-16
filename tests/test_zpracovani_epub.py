"""Čtení EPUBu — pořadí kapitol, duplikace textu, lazy obrázky."""

import zipfile

import ebooklib
import pytest
from bs4 import BeautifulSoup
from ebooklib import epub
from PIL import Image

import vykresleni
import zpracovani_epub


@pytest.fixture
def obsah(kniha):
    return zpracovani_epub.nacti_epub_obsah(kniha)


class TestVystupniKontrakt:
    def test_typy_polozek(self, obsah):
        assert {p["typ"] for p in obsah} <= {"text", "obrazek"}

    def test_obrazky_jsou_metadata_ne_pil(self, obsah):
        obrazky = [p for p in obsah if p["typ"] == "obrazek"]
        assert obrazky
        assert all(isinstance(p["hodnota"], str) for p in obrazky)

    def test_zadna_pil_instance_ve_vystupu(self, obsah):
        assert not any(isinstance(p["hodnota"], Image.Image) for p in obsah)


class TestPoradiCteni:
    """Pořadí určuje spine, ne manifest."""

    def test_zacina_prvnim_dokumentem_spine(self, kniha, obsah):
        """Titulní strana Treasonu nese jen obrázek, žádný text."""
        k = epub.read_epub(kniha)
        prvni_doc = k.get_item_with_id(k.spine[0][0])
        soup = BeautifulSoup(prvni_doc.get_content(), "html.parser")

        prvni_img = soup.find("img")
        if prvni_img is None:
            pytest.skip("první dokument ve spine nemá obrázek")

        assert obsah[0]["typ"] == "obrazek"
        assert obsah[0]["hodnota"].endswith(prvni_img["src"].split("/")[-1])

    def test_spine_se_lisi_od_manifestu(self, kniha):
        """Když by se lišit nemohlo, test výše by nic nedokazoval."""
        k = epub.read_epub(kniha)
        manifest = [
            i.file_name
            for i in k.get_items()
            if i.get_type() == ebooklib.ITEM_DOCUMENT
        ]
        spine = [
            k.get_item_with_id(i).file_name
            for i, _ in k.spine
            if k.get_item_with_id(i)
        ]
        assert manifest[: len(spine)] != spine


class TestDuplikaceTextu:
    """<div><p>…</p></div> dřív vydal odstavec dvakrát."""

    def _slepence(self, polozky):
        texty = [p["hodnota"] for p in polozky if p["typ"] == "text"]
        return sum(
            1
            for i in range(len(texty) - 1)
            if len(texty[i]) > 40
            and len(texty[i + 1]) > 20
            and texty[i + 1] in texty[i]
        )

    def test_zadna_duplikace(self, obsah):
        assert self._slepence(obsah) == 0

    def test_zadna_duplikace_druha_kniha(self, kniha2):
        assert self._slepence(zpracovani_epub.nacti_epub_obsah(kniha2)) == 0

    def test_text_se_bere_jen_z_listovych_bloku(self):
        html = "<div><p>Prvni.</p><p>Druhy.</p></div>"
        soup = BeautifulSoup(html, "html.parser")
        obsah = []
        zpracovani_epub._projdi_dokument(soup, "OEBPS/a.xhtml", set(), obsah)
        assert [p["hodnota"] for p in obsah] == ["Prvni.", "Druhy."]

    def test_div_bez_vnorenych_bloku_text_vyda(self):
        soup = BeautifulSoup("<div>Holy text.</div>", "html.parser")
        obsah = []
        zpracovani_epub._projdi_dokument(soup, "OEBPS/a.xhtml", set(), obsah)
        assert [p["hodnota"] for p in obsah] == ["Holy text."]


class TestSlevaniSlov:
    """get_text(strip=True) slepoval slova přes hranice vnořených tagů."""

    def _text(self, html):
        soup = BeautifulSoup(html, "html.parser")
        obsah = []
        zpracovani_epub._projdi_dokument(soup, "OEBPS/a.xhtml", set(), obsah)
        return obsah[0]["hodnota"]

    def test_mezera_mezi_tagy_zustane(self):
        assert self._text('<p><em>"Admiral."</em> Krennic hlas</p>') == '"Admiral." Krennic hlas'

    def test_slovo_rozdelene_tagem_se_nerozsekne(self):
        # get_text(" ", strip=True) by tady udělal "Hello wor ld"
        assert self._text("<p>Hello <b>wor</b>ld</p>") == "Hello world"

    def test_nasobne_mezery_se_sliji(self):
        assert self._text("<p>a   b\n\nc</p>") == "a b c"

    def test_realna_kniha_nema_slepence(self, obsah):
        texty = [p["hodnota"] for p in obsah if p["typ"] == "text"]
        assert not [t for t in texty if '.”Krennic' in t or '.“Krennic' in t]


class TestLazyObrazky:
    @pytest.fixture
    def obrazky(self, obsah):
        o = [p for p in obsah if p["typ"] == "obrazek"]
        if not o:
            pytest.skip("kniha nemá obrázky")
        return o

    def test_cesty_existuji_v_archivu(self, kniha, obrazky):
        with zipfile.ZipFile(kniha) as z:
            v_archivu = set(z.namelist())
        assert all(p["hodnota"] in v_archivu for p in obrazky)

    def test_nacti_obrazek_vraci_eink_bitmapu(self, kniha, obrazky):
        img = zpracovani_epub.nacti_obrazek(
            kniha, obrazky[0]["hodnota"], vykresleni.TEXT_SIRKA, vykresleni.TEXT_VYSKA
        )
        assert isinstance(img, Image.Image)
        assert img.mode == "1"
        assert img.width <= vykresleni.TEXT_SIRKA
        assert img.height <= vykresleni.TEXT_VYSKA

    def test_pomer_stran_zustava(self, kniha, obrazky):
        with zipfile.ZipFile(kniha) as z:
            import io

            orig = Image.open(io.BytesIO(z.read(obrazky[0]["hodnota"])))
        img = zpracovani_epub.nacti_obrazek(
            kniha, obrazky[0]["hodnota"], vykresleni.TEXT_SIRKA, vykresleni.TEXT_VYSKA
        )
        assert abs(orig.width / orig.height - img.width / img.height) < 0.02

    def test_vystup_nedrzi_dekodovana_data(self, obrazky):
        assert all(len(p["hodnota"]) < 200 for p in obrazky)  # jen cesty


class TestOdolnostVstupu:
    def test_neexistujici_epub(self):
        assert zpracovani_epub.nacti_epub_obsah("/neexistuje.epub") == []

    def test_neexistujici_obrazek(self, kniha):
        assert zpracovani_epub.nacti_obrazek(kniha, "neni/tam.jpg", 100, 100) is None

    def test_obrazek_z_neexistujiciho_epubu(self):
        assert zpracovani_epub.nacti_obrazek("/neexistuje.epub", "a.jpg", 100, 100) is None


class TestKorenOpf:
    def test_najde_se_z_container_xml(self, kniha):
        with zipfile.ZipFile(kniha) as z:
            koren = zpracovani_epub._koren_opf(z)
            assert f"{koren}/" in "".join(z.namelist()) or koren == ""

    def test_cesty_v_archivu_maji_koren(self, obsah):
        obrazky = [p for p in obsah if p["typ"] == "obrazek"]
        if obrazky:
            assert "/" in obrazky[0]["hodnota"]
