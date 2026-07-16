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


class WaveshareDriver(Displej):
    """Waveshare 7.5" HD tříbarevný panel (epd7in5b_HD), fyzicky 880×528."""

    def __init__(self):
        # Lazy import: na desktopu tenhle konstruktor vyhodí ImportError,
        # což vytvor_displej() odchytí a sáhne po DummyDriveru.
        from waveshare_epd import epd7in5b_HD

        self._modul = epd7in5b_HD
        self._epd = epd7in5b_HD.EPD()

    def zobraz(self, cerna, cervena):
        otocena_cerna = cerna.rotate(90, expand=True)
        otocena_cervena = cervena.rotate(90, expand=True)

        self._epd.init()
        self._epd.display(
            self._epd.getbuffer(otocena_cerna),
            self._epd.getbuffer(otocena_cervena),
        )
        self._epd.sleep()

    def vycisti(self):
        self._epd.init()
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
