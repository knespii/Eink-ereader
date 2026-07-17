"""Společné fixtury.

Dvě z nich jsou autouse a chrání skutečná data: bez nich by testy přepsaly
progress.json s rozečtenými knihami a zaneřádily ~/.cache/ctecka.

Testy potřebují knihy v epuby/, které v repozitáři nejsou (jsou v .gitignore
kvůli autorským právům). Bez nich se testy nad reálnou knihou přeskočí.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# gpiozero musí dostat mock piny dřív, než kdokoliv sáhne na Button.
from gpiozero import Device  # noqa: E402
from gpiozero.pins.mock import MockFactory  # noqa: E402

Device.pin_factory = MockFactory()

import knihovna  # noqa: E402
import vykresleni  # noqa: E402

KNIHA = os.path.join(knihovna.SLOZKA_KNIH, "Treason.epub")
KNIHA2 = os.path.join(knihovna.SLOZKA_KNIH, "Alliances.epub")


@pytest.fixture(autouse=True)
def docasna_cache(tmp_path, monkeypatch):
    """Cache stránkování mimo ~/.cache, ať testy nesahají na uživatelovu."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


@pytest.fixture(autouse=True)
def docasne_pozice(tmp_path, monkeypatch):
    """progress.json a posledni_stav.json mimo repozitář — jinak by testy
    přepsaly rozečtené knihy a poslední stav uživatele."""
    monkeypatch.setattr(knihovna, "SOUBOR_POZIC", str(tmp_path / "progress.json"))
    monkeypatch.setattr(knihovna, "SOUBOR_STAVU", str(tmp_path / "posledni_stav.json"))


@pytest.fixture(scope="session")
def fonty():
    return vykresleni.nacti_fonty()


@pytest.fixture
def kniha():
    if not os.path.exists(KNIHA):
        pytest.skip(f"chybí testovací kniha {KNIHA}")
    return KNIHA


@pytest.fixture
def kniha2():
    if not os.path.exists(KNIHA2):
        pytest.skip(f"chybí testovací kniha {KNIHA2}")
    return KNIHA2


@pytest.fixture
def stranky(kniha, fonty):
    """Rozstránkovaná reálná kniha."""
    import zpracovani_epub
    import zpracovani_textu

    obsah = zpracovani_epub.nacti_epub_obsah(kniha)
    return zpracovani_textu.zformatuj_a_rozdel(
        obsah, fonty.text, vykresleni.TEXT_SIRKA, vykresleni.TEXT_VYSKA
    )


@pytest.fixture
def pin():
    """Přístup k mock pinům."""

    def _pin(cislo):
        return Device.pin_factory.pin(cislo)

    return _pin


@pytest.fixture
def stisk(pin):
    """Stiskne a pustí tlačítko na mock pinu (Button je pull-up: stisk = zem)."""
    import time

    def _stisk(cislo, doba=0.05):
        pin(cislo).drive_low()
        time.sleep(doba)
        pin(cislo).drive_high()
        time.sleep(0.15)  # bounce_time + doběh callbacku

    return _stisk


STRANKY_ATRAPA = [{"typ": "text", "obsah": [f"radek {i}"]} for i in range(5)]
