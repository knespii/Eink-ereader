"""Rozhraní displeje a jeho implementace."""

import sys

import pytest
from PIL import Image

import displej


@pytest.fixture
def bitmapy():
    return Image.new("1", (528, 880), 255), Image.new("1", (528, 880), 255)


class TestImportNeshodiProgram:
    """Dřív byl import waveshare_epd na úrovni modulu a sys.exit(1) shodil i testy."""

    def test_import_modulu_nesahne_po_ovladaci(self):
        assert "waveshare_epd" not in sys.modules

    def test_waveshare_na_desktopu_hodi_importerror(self):
        with pytest.raises(ImportError):
            displej.WaveshareDriver()

    def test_vytvor_displej_sahne_po_dummy(self):
        assert isinstance(displej.vytvor_displej(), displej.DummyDriver)


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
