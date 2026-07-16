"""Rozhraní displeje a jeho implementace."""

import os
import subprocess
import sys
import textwrap

import pytest
from PIL import Image

import displej

MA_OVLADAC = os.path.isdir(displej._ADRESAR_OVLADACE)


@pytest.fixture
def bitmapy():
    return Image.new("1", (528, 880), 255), Image.new("1", (528, 880), 255)


def _postav_atrapu(koren):
    """Ovladač se stejnou pastí jako ten od Waveshare: nerelativní import."""
    balicek = koren / "waveshare_epd"
    balicek.mkdir()
    (balicek / "__init__.py").touch()
    (balicek / "epdconfig.py").write_text("def module_exit(): pass\n")
    (balicek / "epd7in5b_HD.py").write_text(
        textwrap.dedent("""
            import epdconfig            # nerelativní, přesně jako u Waveshare
            class EPD:
                def init(self): return 0
                def Clear(self): pass
                def display(self, a, b): pass
                def sleep(self): pass
                def getbuffer(self, img): return b''
        """)
    )
    return balicek


def _zkus_import(cwd, cesty):
    """Naimportuje ovladač v čistém podprocesu — kvůli izolaci sys.path."""
    kod = textwrap.dedent(f"""
        import sys
        for c in {cesty!r}:
            sys.path.insert(0, c)
        from waveshare_epd import epd7in5b_HD
        print(epd7in5b_HD.EPD().init())
    """)
    return subprocess.run(
        [sys.executable, "-c", kod], cwd=str(cwd), capture_output=True, text=True
    )


class TestCestaKOvladaci:
    """Ovladač Waveshare importuje sourozence nerelativně (`import epdconfig`).

    Bez adresáře waveshare_epd/ na sys.path projde import balíčku, ale spadne
    na "No module named 'epdconfig'" — a čtečka pak i s připojeným displejem
    tiše běží na DummyDriveru.
    """

    def test_bez_adresare_balicku_spadne_na_epdconfig(self, tmp_path):
        _postav_atrapu(tmp_path)
        vysledek = _zkus_import(tmp_path, [str(tmp_path)])
        assert vysledek.returncode != 0
        assert "No module named 'epdconfig'" in vysledek.stderr

    def test_s_adresarem_balicku_projde(self, tmp_path):
        balicek = _postav_atrapu(tmp_path)
        vysledek = _zkus_import(tmp_path, [str(tmp_path), str(balicek)])
        assert vysledek.returncode == 0, vysledek.stderr
        assert vysledek.stdout.strip() == "0"

    @pytest.mark.skipif(not MA_OVLADAC, reason="ovladač Waveshare tu není")
    def test_displej_si_adresar_prida(self):
        assert displej._ADRESAR_OVLADACE in sys.path


class TestImportNeshodiProgram:
    """Dřív byl import waveshare_epd na úrovni modulu a sys.exit(1) shodil i testy."""

    @pytest.mark.skipif(MA_OVLADAC, reason="ovladač tu je, takže se naimportuje")
    def test_waveshare_bez_ovladace_hodi_importerror(self):
        with pytest.raises(ImportError):
            displej.WaveshareDriver()

    @pytest.mark.skipif(MA_OVLADAC, reason="ovladač tu je, sáhne se po něm")
    def test_vytvor_displej_sahne_po_dummy(self):
        assert isinstance(displej.vytvor_displej(), displej.DummyDriver)

    def test_vytvor_displej_nikdy_nespadne(self):
        assert isinstance(displej.vytvor_displej(), displej.Displej)


class TestRozhrani:
    def test_nelze_instanciovat(self):
        with pytest.raises(TypeError):
            displej.Displej()

    def test_neuplna_implementace_neprojde(self):
        class Neuplny(displej.Displej):
            def zobraz(self, cerna, cervena):
                pass

        with pytest.raises(TypeError):
            Neuplny()

    def test_uplna_implementace_projde(self):
        class Uplny(displej.Displej):
            def zobraz(self, cerna, cervena):
                pass

            def vycisti(self):
                pass

            def vypni(self):
                pass

        assert isinstance(Uplny(), displej.Displej)


class TestDummyDriver:
    def test_je_displej(self):
        assert isinstance(displej.DummyDriver(), displej.Displej)

    def test_metody_nic_neshodi(self, bitmapy):
        d = displej.DummyDriver()
        assert d.zobraz(*bitmapy) is None
        assert d.vycisti() is None
        assert d.vypni() is None
