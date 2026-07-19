"""Rychlý zápis na panel: bajtově shodný s ovladačem, ale hromadně.

Ovladač epd7in5b_HD posílá obraz po jednom bajtu (116 160 volání send_data),
což na Pi Zero W trvá ~90 s. rychle_zobraz()/rychle_vycisti() pošlou totéž
jedním writebytes2. Tady se ověřuje, že do panelu jdou úplně stejné bajty —
byte-identita proti skutečnému ovladači je změřená mimo testy, tohle drží
kontrakt do budoucna.
"""

import displej

# Příkazová sekvence epd7in5b_HD (z jeho display()/Clear()).
NASTAV, CERNA, CERVENA, LUT, OBNOV = 0x4F, 0x24, 0x26, 0x22, 0x20


class FakeCfg:
    """Náhrada epdconfig — zaznamená každý bajt tak, jak ho panel dostane."""

    def __init__(self, hromadne=True):
        self.DC_PIN, self.CS_PIN = 1, 3
        self.tok = []
        self._dc = 0
        self.pocet_spi = 0
        # spi_writebyte2 se naváže jen když má config umět hromadný přenos,
        # aby hasattr() odpovídal skutečnosti (starý epdconfig ho nemá).
        if hromadne:
            self.spi_writebyte2 = self._zaznam

    def digital_write(self, pin, val):
        if pin == self.DC_PIN:
            self._dc = val

    def digital_read(self, pin):
        return 0

    def delay_ms(self, ms):
        pass

    def _zaznam(self, data):
        self.pocet_spi += 1
        tag = "cmd" if self._dc == 0 else "data"
        self.tok.extend((tag, b & 0xFF) for b in data)

    def spi_writebyte(self, data):
        self._zaznam(data)


class FakeEpd:
    """Minimální epd7in5b_HD: send_command/send_data přes cfg, jako skutečný."""

    width, height = 880, 528

    def __init__(self, cfg):
        self._cfg = cfg
        self.dc_pin, self.cs_pin = cfg.DC_PIN, cfg.CS_PIN

    def send_command(self, cmd):
        self._cfg.digital_write(self.dc_pin, 0)
        self._cfg.spi_writebyte([cmd])

    def send_data(self, data):
        self._cfg.digital_write(self.dc_pin, 1)
        self._cfg.spi_writebyte([data])

    def ReadBusy(self):
        pass

    def init(self):
        pass

    def sleep(self):
        pass

    def getbuffer(self, img):
        return [0xFF] * int(self.width * self.height / 8)

    # referenční "pomalá" verze přesně podle ovladače Waveshare
    def display(self, cerna, cervena):
        self.send_command(NASTAV)
        self.send_data(0xAF)
        self.send_command(CERNA)
        for b in cerna:
            self.send_data(b)
        self.send_command(CERVENA)
        for b in cervena:
            self.send_data(~b)
        self.send_command(LUT)
        self.send_data(0xC7)
        self.send_command(OBNOV)
        self.ReadBusy()

    def Clear(self):
        n = int(self.width * self.height / 8)
        self.send_command(NASTAV)
        self.send_data(0xAF)
        self.send_command(CERNA)
        for _ in range(n):
            self.send_data(0xFF)
        self.send_command(CERVENA)
        for _ in range(n):
            self.send_data(0x00)
        self.send_command(LUT)
        self.send_data(0xC7)
        self.send_command(OBNOV)
        self.ReadBusy()


def _tok(fn, cfg):
    cfg.tok = []
    cfg._dc = 0
    fn()
    return list(cfg.tok)


def _buffery():
    # dva různé vzory, ať inverze červené něco dělá
    cerna = [(i * 37) & 0xFF for i in range(880 * 528 // 8)]
    cervena = [(i * 91) & 0xFF for i in range(880 * 528 // 8)]
    return cerna, cervena


class TestBajtovaShoda:
    def test_zobrazeni_je_bajtove_shodne_s_ovladacem(self):
        cfg = FakeCfg()
        epd = FakeEpd(cfg)
        cerna, cervena = _buffery()

        pomaly = _tok(lambda: epd.display(cerna, cervena), cfg)
        rychly = _tok(lambda: displej.rychle_zobraz(epd, cfg, cerna, cervena), cfg)
        assert rychly == pomaly

    def test_cisteni_je_bajtove_shodne_s_ovladacem(self):
        cfg = FakeCfg()
        epd = FakeEpd(cfg)

        pomaly = _tok(lambda: epd.Clear(), cfg)
        rychly = _tok(lambda: displej.rychle_vycisti(epd, cfg), cfg)
        assert rychly == pomaly

    def test_cervena_vrstva_jde_invertovana(self):
        """Kdyby se zapomnělo invertovat, barvy by se prohodily."""
        cfg = FakeCfg()
        epd = FakeEpd(cfg)
        cervena = [0xFF] * (880 * 528 // 8)
        _tok(lambda: displej.rychle_zobraz(epd, cfg, [0x00] * len(cervena), cervena), cfg)
        # ~0xFF & 0xFF == 0x00 — invertovaná plná červená
        data_cervene = [b for tag, b in cfg.tok if tag == "data"]
        assert 0x00 in data_cervene


class TestHromadnyPrenos:
    def test_posila_v_par_transakcich_ne_po_bajtu(self):
        cfg = FakeCfg()
        epd = FakeEpd(cfg)
        cerna, cervena = _buffery()

        displej.rychle_zobraz(epd, cfg, cerna, cervena)
        assert cfg.pocet_spi < 20  # ne 116 000+

    def test_pomaly_driver_by_mel_statisice_transakci(self):
        """Kontrola, že test výše něco znamená."""
        cfg = FakeCfg()
        epd = FakeEpd(cfg)
        cerna, cervena = _buffery()

        epd.display(cerna, cervena)
        assert cfg.pocet_spi > 100_000


class TestPojistka:
    def test_stary_epdconfig_bez_hromadneho_spadne_zpet(self):
        """Bez spi_writebyte2 se má sáhnout po pomalém, ale funkčním display()."""
        cfg = FakeCfg(hromadne=False)
        epd = FakeEpd(cfg)

        driver = displej.WaveshareDriver.__new__(displej.WaveshareDriver)
        driver._epd = epd
        driver._modul = type("M", (), {"epdconfig": cfg})
        assert driver._zvladne_hromadne() is False

    def test_novy_epdconfig_hromadne_zvladne(self):
        cfg = FakeCfg()
        epd = FakeEpd(cfg)

        driver = displej.WaveshareDriver.__new__(displej.WaveshareDriver)
        driver._epd = epd
        driver._modul = type("M", (), {"epdconfig": cfg})
        assert driver._zvladne_hromadne() is True


# --- RYCHLÉ BALENÍ BUFFERU ---

SIRKA_PANELU, VYSKA_PANELU = 880, 528


def getbuffer_referencni(image):
    """Doslovný přepis větve "Horizontal" z epd7in5b_HD.getbuffer().

    Slouží jako etalon: WaveshareDriver._buffer() tuhle smyčku obchází přes
    PIL.tobytes(), protože v Pythonu stojí 1,7 s na vrstvu. Tady se drží
    kontrakt, že obě cesty dávají tytéž bajty.
    """
    buf = [0xFF] * (SIRKA_PANELU // 8 * VYSKA_PANELU)
    monochrom = image.convert("1")
    pixely = monochrom.load()
    for y in range(VYSKA_PANELU):
        for x in range(SIRKA_PANELU):
            if pixely[x, y] == 0:
                buf[(x + y * SIRKA_PANELU) // 8] &= ~(0x80 >> (x % 8))
    return bytes(b & 0xFF for b in buf)


class _FakeEpdRozmery:
    width, height = SIRKA_PANELU, VYSKA_PANELU

    def __init__(self):
        self.getbuffer_volan = 0

    def getbuffer(self, obraz):
        self.getbuffer_volan += 1
        # Referenční smyčka je jen pro větev "Horizontal"; jiné rozměry si
        # skutečný ovladač otáčí sám a tady stačí vědět, že se zavolal.
        if obraz.mode == "1" and obraz.size == (self.width, self.height):
            return getbuffer_referencni(obraz)
        return b""


def _driver_s_fake_epd():
    """WaveshareDriver bez __init__ — ten importuje waveshare_epd, který na
    desktopu není."""
    d = displej.WaveshareDriver.__new__(displej.WaveshareDriver)
    d._epd = _FakeEpdRozmery()
    return d


class TestRychleBaleniBufferu:
    def _vzorky(self):
        import random

        from PIL import Image

        bajtu = SIRKA_PANELU // 8 * VYSKA_PANELU
        random.seed(20260719)
        return [
            ("bílý", Image.new("1", (SIRKA_PANELU, VYSKA_PANELU), 255)),
            ("černý", Image.new("1", (SIRKA_PANELU, VYSKA_PANELU), 0)),
            (
                "svislé pruhy",
                Image.frombytes(
                    "1", (SIRKA_PANELU, VYSKA_PANELU), bytes([0b10101010]) * bajtu
                ),
            ),
            (
                "náhodný",
                Image.frombytes(
                    "1",
                    (SIRKA_PANELU, VYSKA_PANELU),
                    bytes(random.randrange(256) for _ in range(bajtu)),
                ),
            ),
        ]

    def test_bajtove_shodne_s_ovladacem(self):
        """Bílý obraz sám o sobě nic nedokazuje — obě cesty na něm vyjdou 0xFF."""
        driver = _driver_s_fake_epd()
        for popis, obraz in self._vzorky():
            assert driver._buffer(obraz) == getbuffer_referencni(obraz), popis

    def test_zkratka_getbuffer_nevola(self):
        driver = _driver_s_fake_epd()
        _, obraz = self._vzorky()[3]
        driver._buffer(obraz)
        assert driver._epd.getbuffer_volan == 0

    def test_jiny_rozmer_nechava_ovladaci(self):
        """Neotočený obraz si musí otočit ovladač sám — zkratka by ho rozbila."""
        from PIL import Image

        driver = _driver_s_fake_epd()
        driver._buffer(Image.new("1", (VYSKA_PANELU, SIRKA_PANELU), 255))
        assert driver._epd.getbuffer_volan == 1

    def test_jiny_mode_nechava_ovladaci(self):
        from PIL import Image

        driver = _driver_s_fake_epd()
        driver._buffer(Image.new("L", (SIRKA_PANELU, VYSKA_PANELU), 255))
        assert driver._epd.getbuffer_volan == 1
