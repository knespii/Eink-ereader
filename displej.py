"""Rozhraní displeje a jeho implementace.

Tohle je jediné místo, které ví o hardwaru. Ovladač waveshare_epd se importuje
až v konstruktoru WaveshareDriver — díky tomu jde celý zbytek čtečky spustit
a testovat na desktopu, kde knihovna není. Dřív import na úrovni modulu shodil
program hned při startu (sys.exit(1)) a nešlo si sáhnout ani na testy.

Otočení plátna do hardwarových rozměrů řeší driver, ne vykreslování: že je
panel fyzicky na šířku, je vlastnost tohohle kusu železa, ne vlastnost knihy.
"""

import abc
import logging
import os
import sys

# Ovladač od Waveshare uvnitř sebe importuje sourozence nerelativně
# (`import epdconfig`, ne `from . import epdconfig`). Aby to prošlo, musí být
# na sys.path i adresář waveshare_epd/ sám — jinak import balíčku sice projde,
# ale spadne na "No module named 'epdconfig'". Bez tohohle řádku běží čtečka
# na DummyDriveru i s připojeným displejem.
_KOREN = os.path.dirname(os.path.realpath(__file__))
_ADRESAR_OVLADACE = os.path.join(_KOREN, "waveshare_epd")
if os.path.isdir(_ADRESAR_OVLADACE) and _ADRESAR_OVLADACE not in sys.path:
    sys.path.append(_ADRESAR_OVLADACE)


class Displej(abc.ABC):
    """Co čtečka od displeje potřebuje.

    zobraz() si sám displej probudí a zase uspí, takže volající neřeší nic
    kolem napájení panelu.
    """

    @abc.abstractmethod
    def zobraz(self, cerna, cervena):
        """Pošle na displej dvě bitmapy 528×880 (na výšku, neotočené)."""

    @abc.abstractmethod
    def vycisti(self):
        """Vybílí panel a spálí tím zbytky předchozího obrazu (ghosting).

        Trvá zhruba stejně dlouho jako zobraz(), takže se to nedělá pořád.
        """

    @abc.abstractmethod
    def vypni(self):
        """Uvolní hardware. Volá se jednou při ukončení programu."""


# --- Rychlý zápis dat na panel epd7in5b_HD ---
#
# Ovladač od Waveshare posílá obraz po jednom bajtu: display() zavolá 116 160×
# send_data() a každé volání třikrát cvakne GPIO (dc, cs dolů, cs nahoru). Na
# Pi Zero W je to ~460 tisíc pomalých gpiozero operací, tedy kolem 90 sekund —
# a to i s hardwarovým SPI, protože brzdí ta obsluha pinů, ne přenos. Přitom
# 116 KB na 4 MHz proteče za ~0,23 s.
#
# Reprodukujeme proto tutéž příkazovou sekvenci, ale oba buffery pošleme jedním
# hromadným writebytes2 s CS drženým dole po celý blok. Do panelu jdou úplně
# stejné bajty, jen se u každého zvlášť necvaká pin. Sekvence odpovídá display()
# a Clear() aktuálního epd7in5b_HD.py; kdyby ji Waveshare změnili, drží se
# pojistka na epd.display() (viz _zvladne_hromadne).
_CMD_NASTAV = 0x4F
_CMD_CERNA = 0x24
_CMD_CERVENA = 0x26
_CMD_NACTI_LUT = 0x22
_CMD_OBNOV = 0x20


def _posli_blok(epd, cfg, prikaz, data):
    """Příkaz a k němu celý datový blok jediným hromadným SPI přenosem."""
    epd.send_command(prikaz)
    cfg.digital_write(epd.dc_pin, 1)
    cfg.digital_write(epd.cs_pin, 0)
    cfg.spi_writebyte2(list(data))
    cfg.digital_write(epd.cs_pin, 1)


def _obnov_a_cekej(epd, cfg):
    epd.send_command(_CMD_NACTI_LUT)
    epd.send_data(0xC7)
    epd.send_command(_CMD_OBNOV)
    cfg.delay_ms(200)
    epd.ReadBusy()


def rychle_zobraz(epd, cfg, cerna_buf, cervena_buf):
    """Bajtově shodné s epd.display(), ale hromadným přenosem."""
    epd.send_command(_CMD_NASTAV)
    epd.send_data(0xAF)
    _posli_blok(epd, cfg, _CMD_CERNA, cerna_buf)
    # Červená vrstva se do panelu posílá invertovaná (viz display(): ~imagered).
    _posli_blok(epd, cfg, _CMD_CERVENA, [~b & 0xFF for b in cervena_buf])
    _obnov_a_cekej(epd, cfg)


def rychle_vycisti(epd, cfg):
    """Bajtově shodné s epd.Clear(), ale hromadným přenosem."""
    bajtu = int(epd.width * epd.height / 8)
    epd.send_command(_CMD_NASTAV)
    epd.send_data(0xAF)
    _posli_blok(epd, cfg, _CMD_CERNA, [0xFF] * bajtu)
    _posli_blok(epd, cfg, _CMD_CERVENA, [0x00] * bajtu)
    _obnov_a_cekej(epd, cfg)


class WaveshareDriver(Displej):
    """Waveshare 7.5" HD tříbarevný panel (epd7in5b_HD), fyzicky 880×528."""

    def __init__(self):
        # Lazy import: na desktopu tenhle konstruktor vyhodí ImportError,
        # což vytvor_displej() odchytí a sáhne po DummyDriveru.
        from waveshare_epd import epd7in5b_HD

        self._modul = epd7in5b_HD
        self._epd = epd7in5b_HD.EPD()

    def _zvladne_hromadne(self):
        """Má epdconfig hromadný přenos a driver očekávané vnitřnosti?

        Starší epdconfig (např. verze se software SPI přes .so) spi_writebyte2
        nemá — tam se spadne zpět na pomalý, ale funkční epd.display().
        """
        return hasattr(self._modul.epdconfig, "spi_writebyte2") and all(
            hasattr(self._epd, a) for a in ("dc_pin", "cs_pin", "send_command", "ReadBusy")
        )

    def zobraz(self, cerna, cervena):
        cerna_buf = self._epd.getbuffer(cerna.rotate(90, expand=True))
        cervena_buf = self._epd.getbuffer(cervena.rotate(90, expand=True))

        self._epd.init()
        if self._zvladne_hromadne():
            rychle_zobraz(self._epd, self._modul.epdconfig, cerna_buf, cervena_buf)
        else:
            logging.warning("Hromadný SPI přenos není k dispozici, kreslím pomalu.")
            self._epd.display(cerna_buf, cervena_buf)
        self._epd.sleep()

    def vycisti(self):
        self._epd.init()
        if self._zvladne_hromadne():
            rychle_vycisti(self._epd, self._modul.epdconfig)
        else:
            self._epd.Clear()
        self._epd.sleep()

    def vypni(self):
        self._modul.epdconfig.module_exit()


class DummyDriver(Displej):
    """Náhrada pro vývoj bez hardwaru. Jen loguje, co by se poslalo."""

    def zobraz(self, cerna, cervena):
        logging.info("DummyDriver: zobrazuji %s (černá) + %s (červená)", cerna.size, cervena.size)

    def vycisti(self):
        logging.info("DummyDriver: čistím panel")

    def vypni(self):
        logging.info("DummyDriver: vypínám")


def vytvor_displej():
    """Vrátí WaveshareDriver, a když ovladač není, DummyDriver."""
    try:
        return WaveshareDriver()
    except ImportError as e:
        logging.warning("Ovladač Waveshare není k dispozici (%s), běžím naprázdno.", e)
        return DummyDriver()
