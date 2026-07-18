# [PROJECT_OVERVIEW]

DIY hardwarová **e-ink čtečka EPUB knih** na **Raspberry Pi Zero W** s displejem **Waveshare 7.5" HD (`epd7in5b_HD`, tříbarevný černá/bílá/červená, fyzicky 880×528 px)**, ovládaná 3 fyzickými GPIO tlačítky. Součástí repozitáře je i **Flask simulátor**, který běží na **stejném kódu** jako produkce (ne jako zrcadlová kopie) a slouží k vývoji bez hardwaru.

Kód i komentáře jsou česky, včetně názvů funkcí a proměnných.

---

# [TECH_STACK]

- **Jazyk:** Python (venv v `.venv/`; na Pi 3.11, na vývojovém desktopu 3.13)
- **Runtime target:** Raspberry Pi Zero W (ARM), Raspberry Pi OS
- **Rendering:** `Pillow` 12.2.0 (`PIL.Image`, `ImageDraw`, `ImageFont`)
- **Parsing EPUB:** `EbookLib` 0.20 (`epub.read_epub`, `spine`, `ITEM_DOCUMENT`)
- **Parsing HTML:** `beautifulsoup4` 4.14.3, `soupsieve` 2.8.4, `lxml` 6.1.1
- **GPIO:** `gpiozero` 2.0.1 (backend `lgpio`, na Pi balík `python3-lgpio`)
- **Web simulátor:** `Flask` 3.1.3
- **Testy:** `pytest` 9.1.1, GPIO přes `gpiozero.pins.mock.MockFactory` (bez HW)
- **Font:** DejaVu Sans TTF, `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` (jedna cesta pro produkci i simulátor; fallback `ImageFont.load_default()`)
- **Deklarace závislostí:** `requirements.txt` s **pevnými verzemi** + `requirements-dev.txt` (pytest)
- **Externí závislost (NENÍ v repu):** ovladač `waveshare_epd` — očekáván v `./waveshare_epd/`. Když chybí, program **nespadne**: `vytvor_displej()` sáhne po `DummyDriver` a běží naprázdno.

---

# [ARCHITECTURE]

Základní pravidlo: **stav, kreslení a hardware o sobě navzájem nevědí.** Díky tomu jede simulátor na produkčním kódu a všechno jde testovat bez Pi.

| Modul | Odpovědnost | Nesmí znát |
|---|---|---|
| `stav.py` | konečný automat `MENU`/`CTENI`, třída `Ctecka` | PIL, GPIO, Flask, soubory |
| `vykresleni.py` | `vykresli(snimek, fonty, nacti_obrazek)` → 2 bitmapy | hardware, rotaci, EPUB |
| `displej.py` | rozhraní `Displej` + `WaveshareDriver` / `DummyDriver` | stav, obsah knih |
| `knihovna.py` | jediné místo s I/O: knihy, pozice, cache, obrázky | stav, kreslení |
| `zpracovani_epub.py` | EPUB → text a **cesty** k obrázkům | rozvržení, displej |
| `zpracovani_textu.py` | rozvržení do stránek + JSON cache | displej, GPIO |
| `hlavni_ctecka.py` | GPIO + hlavní smyčka | — |
| `simulator.py` | Flask + skládání vrstev do RGB | — |

**Klíčové vzory:**

- **Jediný zdroj pravdy:** `Ctecka` drží veškerý stav a je **thread-safe** (`threading.Condition`). Produkce i simulátor na ni sahají identicky; liší se jen vstup (GPIO vs. HTTP) a výstup (e-ink vs. PNG). Ověřeno testem, že web ukazuje **bajtově totéž**, co jde na panel.
- **Snímek místo živého stavu:** `Ctecka.snimek()` vrací zmrazený `@dataclass(frozen=True) Snimek`. Vykreslování tak nemůže přečíst stav rozpůlený stiskem tlačítka.
- **Drahá práce mimo callbacky:** stránkování trvá na Pi Zero W ~16 s. Callbacky gpiozero smějí **jen sáhnout na stav** (měřeno: 0,02 ms). Otevření knihy jde přes **požadavek**: `akce()` ho zaeviduje → hlavní smyčka `vyzvedni_pozadavek()` → parsuje → `dodej_stranky()`. Mezitím svítí `nacita_se`.
- **Ochrana proti ztracenému překreslení:** `cekej_na_prekresleni()` shazuje vlajku **před** renderem, atomicky pod zámkem. Stisk během ~10s zápisu na e-ink se tak neztratí.
- **Koalescence zápisů:** rychlé listování se slije do **jednoho** zápisu `progress.json` (šetří SD kartu).
- **Rotace patří driveru:** `vykresleni.py` kreslí 528×880 na výšku; otočení o 90° do 880×528 dělá `WaveshareDriver`, protože to je vlastnost železa, ne knihy.
- **Lazy import ovladače:** `waveshare_epd` se importuje až v konstruktoru `WaveshareDriver` → zbytek jde spustit a testovat na desktopu.
- **Hromadný SPI přenos:** viz [PERFORMANCE].

---

# [FILE_STRUCTURE]

```
ctecka/
├── stav.py                  # FSM: třída Ctecka + Snimek + Stav (StrEnum). Bez PIL/GPIO/Flask.
├── vykresleni.py            # vykresli(snimek, fonty, nacti_obrazek) -> (cerna, cervena) 528×880
├── displej.py               # rozhraní Displej; WaveshareDriver (rotace + hromadné SPI) / DummyDriver
├── knihovna.py              # jediné I/O: seznam knih, progress.json, posledni_stav.json, cache, obrázky
├── zpracovani_epub.py       # EPUB -> [{"typ":"text","hodnota":str} | {"typ":"obrazek","hodnota":cesta_v_zipu}]
├── zpracovani_textu.py      # word-wrap + stránkování + JSON cache s invalidačním hashem
├── hlavni_ctecka.py         # produkční vstupní bod: gpiozero + hlavní smyčka
├── simulator.py             # Flask simulátor na produkčním kódu (localhost:5000)
├── ctecka.service           # systemd šablona (placeholdery __UZIVATEL__ / __ADRESAR__)
├── install-sluzba.sh        # doplní placeholdery a nainstaluje autostart
├── requirements.txt         # běhové závislosti s pevnými verzemi
├── requirements-dev.txt     # + pytest
├── pytest.ini               # testpaths = tests, pythonpath = . tests
├── README.md                # dokumentace pro člověka
├── AI_CONTEXT.md            # tento soubor
├── tests/                   # 192 testů (pytest), bez hardwaru
│   ├── conftest.py          # autouse fixtury chránící progress.json a cache uživatele
│   ├── test_stav.py, test_vykresleni.py, test_displej.py, test_knihovna.py
│   ├── test_zpracovani_epub.py, test_zpracovani_textu.py
│   ├── test_hlavni_ctecka.py, test_simulator.py
│   ├── test_rychly_prenos.py    # bajtová shoda hromadného SPI přenosu
│   └── test_obnoveni.py         # navázání po zapnutí bez bliknutí
├── epuby/                   # vstupní EPUB knihy (git-ignored)
├── waveshare_epd/           # ovladač displeje (NENÍ v repu, instaluje se zvlášť)
├── progress.json            # pozice v knihách (git-ignored)
├── posledni_stav.json       # poslední zobrazený stav (git-ignored)
└── .venv/
```

---

# [CORE_COMPONENTS]

## `stav.py` — konečný automat
- `Stav(StrEnum)`: `MENU` | `CTENI`. `Snimek` = frozen dataclass (stav, seznam_knih, vyber, kniha, stranka, cislo_stranky, pocet_stranek, nacita_se, chyba).
- `Ctecka(seznam_knih=None, prekreslit_na_startu=True)`.
- **Pro tlačítka (z cizích vláken):** `dalsi()`, `predchozi()`, `akce()`, `ukonci()`.
- **Pro hlavní smyčku:** `snimek()`, `cekej_na_prekresleni(timeout)`, `spotrebuj_prekresleni()`, `vyzvedni_pozadavek()`, `dodej_stranky(nazev, stranky, pocatecni_stranka)`, `vyzvedni_pozici_k_ulozeni()`, `nastav_seznam_knih(seznam)`, vlastnost `konec`.
- **Obnova po startu:** `obnov_cteni(nazev, stranky, stranka)`, `obnov_menu(vyber)` — nastaví stav **bez** vyžádání překreslení; `vyzadej_prekresleni()` když obnova neseděla.
- Návrat do menu **zahazuje stránky** (paměť na 512 MB) a **ruší** rozpracované načítání — jinak by kniha za chvíli stejně naskočila.

## `vykresleni.py` — kreslení
- `nacti_fonty(cesta)` → `Fonty(text=32, info=20, titulek=40)`.
- `vykresli(snimek, fonty, nacti_obrazek=None)` → `(cerna, cervena)`, obě `PIL.Image` mode `"1"`, 528×880, **neotočené**.
- Rozměry se **odvozují**: `TEXT_SIRKA = SIRKA - 2*OKRAJ = 488`, `TEXT_VYSKA = LISTA_Y - OKRAJ = 820`, `LISTA_Y = 840`.
- Řádkování bere z `zpracovani_textu.vyska_radku(fonty.text)` — **jeden zdroj pravdy** s layoutem (43 px pro DejaVu 32).
- Menu roluje **po stránkách** po `POLOZEK_NA_STRANKU = 13`; lišta hlásí `Knihy 14–26 z 30`.
- Obrázky nenačítá sám — dostane `nacti_obrazek(cesta_v_archivu)`. Bez něj kreslí zástupku.

## `displej.py` — hardware
- `Displej` (ABC): `zobraz(cerna, cervena)`, `vycisti()`, `vypni()`.
- `WaveshareDriver`: rotace o 90°, `init()` → data → `sleep()`. Import `waveshare_epd` až v `__init__`.
- `rychle_zobraz(epd, cfg, cerna_buf, cervena_buf)` / `rychle_vycisti(epd, cfg)` — hromadný SPI přenos (viz [PERFORMANCE]). Fallback na `epd.display()`, když `epdconfig` nemá `spi_writebyte2`.
- Na `sys.path` se přidává i adresář `waveshare_epd/` — starší ovladač uvnitř dělá `import epdconfig` nerelativně.
- `DummyDriver` jen loguje; `vytvor_displej()` vybírá podle dostupnosti ovladače.

## `knihovna.py` — všechno I/O
- `nacti_seznam_knih()`, `nacti_pozice()`, `uloz_pozici(kniha, stranka)`, `nacti_stranky(nazev, fonty)`, `nacti_obrazek_knihy(nazev)`.
- `obsluz(ctecka, fonty)` — vyřídí požadavek na načtení a zápis pozice. Volá ji hlavní smyčka i simulátor.
- `uloz_posledni_stav(snimek)` / `nacti_posledni_stav()` / `obnov_posledni_stav(ctecka, fonty)`.
- `_zapis_json_atomicky(cesta, data)` — tmp + `fsync` + `os.replace`.
- Cesty se odvozují od `__file__`, **ne** od CWD (jinak by čtečka ze systemd nenašla knihy).

## `zpracovani_epub.py` — parser
- `nacti_epub_obsah(cesta_k_souboru)` → seznam `{"typ": "text"|"obrazek", "hodnota": ...}` v **pořadí čtení**.
- Iteruje **`kniha.spine`**, ne `get_items()` (to vrací pořadí manifestu, které nemusí odpovídat kapitolám).
- Text bere **jen z listových bloků** (`p`, `div` bez vnořených bloků) — jinak by `<div><p>` vydal odstavec dvakrát.
- Text čistí přes `" ".join(el.get_text().split())` — zachová mezery mezi vnořenými tagy a nerozsekne slovo.
- Obrázky se **nedekódují**: `hodnota` je cesta v ZIPu (např. `OEBPS/Images/cover.jpeg`). Kořen se bere z `META-INF/container.xml`.
- `nacti_obrazek(cesta_k_epubu, cesta_v_archivu, max_sirka, max_vyska)` → `PIL.Image` mode `"1"`, volá se až před vykreslením.

## `zpracovani_textu.py` — layout + cache
- `vyska_radku(font, rozestup=5)` = `ascent + descent + rozestup`. **Volá i vykreslování.**
- `zformatuj_a_rozdel(obsah, font, max_sirka_px, max_vyska_px)` → stránky `{"typ":"text","obsah":list[str]}` | `{"typ":"obrazek","obsah":cesta}`.
- `klic_cache(...)`, `nacti_z_cache(klic)`, `uloz_do_cache(klic, stranky)`.
- `VERZE_ALGORITMU = 2` — **zvyš při každé změně, která mění výsledné stránky**, včetně zásahu do `zpracovani_epub`.

## `hlavni_ctecka.py` — produkce
- Piny (BCM): `PIN_DALSI = 21`, `PIN_PREDCHOZI = 26`, `PIN_AKCE = 19`; `bounce_time = 0.1`, `hold_time = 2.0`.
- Krátký stisk visí na **`when_released`** (s vlajkou `drzeno`) — jinak by dlouhý stisk nejdřív otevřel knihu.
- `PERIODA_CISTENI = 0` (čištění vypnuté, viz [PERFORMANCE]).
- Hlavní smyčka: `cekej_na_prekresleni(1.0)` → `zobraz()` → `knihovna.obsluz()` → v `MENU` obnova seznamu knih.

## `simulator.py` — Flask
- Routy: `GET /`, `GET /screen` (PNG), `POST /api/stisk/<dalsi|predchozi|akce>`.
- Drží tutéž `Ctecka` a kreslí toutéž `vykresli()`; navíc jen skládá 1-bit vrstvy do RGB (`ImageChops.invert` jako maska).
- Běží na `debug=False, host="127.0.0.1"` — dřívější `debug=True` + `0.0.0.0` byla otevřená Werkzeug konzole (RCE).

---

# [DATA_FLOW]

## Start
1. `nacti_fonty()`.
2. Když existuje `posledni_stav.json` → `Ctecka(..., prekreslit_na_startu=False)` + `obnov_posledni_stav()`. Panel drží obraz z minula, takže **nic nebliká**. Když obnova selže (smazaná kniha) → `vyzadej_prekresleni()`.
3. Bez uloženého stavu → normální start v `MENU` s překreslením.
4. `vytvor_displej()`, `pripoj_tlacitka()`, vstup do smyčky.

## Stisk → překreslení
1. Callback gpiozero (cizí vlákno) sáhne na `Ctecka` a probudí smyčku. **Nic nenačítá.**
2. `cekej_na_prekresleni()` vrátí `True` a **zároveň shodí vlajku** (stisk během renderu se tak neztratí).
3. `zobraz()` → `vykresli(snimek, ...)` → `obrazovka.zobraz()` → `uloz_posledni_stav(snimek)`.
4. `knihovna.obsluz()` vyřídí případný požadavek na knihu a zápis pozice.

## Otevření knihy
1. `akce()` v `MENU` zaeviduje **požadavek** (stav zůstává `MENU`, `nacita_se = True`).
2. Smyčka `vyzvedni_pozadavek()` → `nacti_stranky()` → cache hit (ihned) nebo parse + stránkování (~16 s).
3. `dodej_stranky(nazev, stranky, nacti_pozice().get(nazev, 0))` → `CTENI` + překreslení.

## Vypnutí a zapnutí
1. Dlouhý stisk → `ukonci()` → smyčka končí, `obrazovka.vypni()`. Návrat 0, takže systemd nerestartuje.
2. E-ink drží poslední obraz i bez napájení.
3. Po zapnutí systemd spustí program, ten obnoví stav z `posledni_stav.json` **bez překreslení** a čeká na stisk.

---

# [STATE_AND_STORAGE]

## Stav v paměti
Veškerý stav je **uvnitř instance `Ctecka`** pod zámkem — žádné globální proměnné. Ven jde jen přes `snimek()`.

## Perzistence
| Soubor | Obsah |
|---|---|
| `progress.json` | `{"<jméno souboru>.epub": <index stránky>}` — klíč je **jméno souboru**, ne cesta (nezávislé na CWD). Zápis atomický. |
| `posledni_stav.json` | `{"typ":"cteni","kniha":...,"stranka":N}` nebo `{"typ":"menu","vyber":N}` — poslední **zobrazený** stav. |
| `~/.cache/ctecka/<hash>.json` | Stránkování knihy. **Čistý JSON, ne pickle.** |

**Invalidační klíč cache** = SHA-256 (16 hex znaků) z: jména knihy + její velikosti + mtime, cesty k fontu, velikosti fontu, rozlišení, rozestupu řádků a `VERZE_ALGORITMU`. Změna čehokoli z toho cache zneplatní sama. Pickle se nepoužívá záměrně — vázal by cache na verzi Pillow a jeho načtení umí spustit cizí kód.

## Rozlišení
- Logická plocha (na výšku): **528×880**, textová oblast **488×820**, stavová lišta na `y = 840`.
- Fyzický panel (na šířku): **880×528** — rotaci dělá driver.
- Dvě 1-bitové vrstvy: černá + červená (červená se do panelu posílá **invertovaná**).

---

# [PERFORMANCE]

Naměřeno na Pi Zero W:

| Operace | Čas |
|---|---|
| Import modulů + vykreslení menu | 4,8 s |
| `display()` původním ovladačem | ~99 s |
| `display()` s hromadným přenosem | **~10 s** (budicí křivka panelu) |
| `Clear()` | ~91 s |
| Stránkování knihy (cache miss) | ~16 s |
| Stránkování z cache | ihned |

**Proč byl původní `display()` pomalý:** ovladač posílá obraz po jednom bajtu — 116 160 volání `send_data()`, každé třikrát cvakne GPIO (~460 tisíc gpiozero operací). Samotný přenos 116 KB na 4 MHz trvá 0,23 s; brzdila obsluha pinů, ne panel ani SPI.

**Řešení:** `WaveshareDriver` reprodukuje tutéž příkazovou sekvenci (`0x4F`/`0xAF`, `0x24` černá, `0x26` invertovaná červená, `0x22`/`0xC7`, `0x20`), ale oba buffery pošle **jedním `writebytes2`** s CS drženým dole. **9 SPI transakcí místo 116 167**, do panelu jdou bajtově shodná data (ověřeno testem proti skutečnému ovladači).

**Čištění panelu vypnuté** (`PERIODA_CISTENI = 0`): tříbarevný panel jede při každém `display()` plnou křivkou, obraz přepíše celý a duchy prakticky nenechává; `Clear()` by jen přidal 91 s.

**Částečné překreslení není možné** — červený pigment vyžaduje plnou budicí křivku přes celý panel. To je vlastnost hardwaru, ne kódu.

---

# [TESTING]

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest          # 192 passed, 2 skipped
```

- **Bez hardwaru:** gpiozero jede na `MockFactory`, takže jde otestovat i dvouvteřinové držení tlačítka.
- **Chrání data uživatele:** autouse fixtury v `conftest.py` odklánějí `progress.json`, `posledni_stav.json` i cache mimo repozitář.
- **Bez knih v `epuby/`** se testy nad reálnou knihou přeskočí.
- Klíčové vlastnosti pokryté testy: bajtová shoda simulátoru s panelem, bajtová shoda hromadného SPI přenosu, ztracené překreslení při souběhu, dlouhý stisk neotevře knihu, atomický zápis přežije výpadek napájení, obnova po startu nebliká.

---

# [DEPLOYMENT]

```bash
git clone https://github.com/knespii/Eink-ereader.git
cd Eink-ereader
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# ovladač displeje (není na PyPI):
git clone https://github.com/waveshareteam/e-Paper.git /tmp/e-Paper
cp -r /tmp/e-Paper/RaspberryPi_JetsonNano/python/lib/waveshare_epd .
sudo apt install -y python3-lgpio          # backend pro gpiozero
sudo raspi-config nointeractive do_spi 0   # povolit SPI
./install-sluzba.sh                        # autostart po zapnutí
```

Ovladač musí mít `epdconfig.spi_writebyte2` (hardwarové SPI). Starší verze se software SPI (soubory `sysfs_software_spi.so`) ho nemají a čtečka spadne zpět na pomalý režim. Kontrola:

```bash
.venv/bin/python -c "from waveshare_epd import epdconfig; print(hasattr(epdconfig, 'spi_writebyte2'))"
```

Správa služby: `sudo systemctl status ctecka`, `journalctl -u ctecka -f`, `sudo systemctl disable --now ctecka`.

---

# [KNOWN_LIMITATIONS]

- **Obálky knih se nezobrazují** — titulní strany bývají `<svg><image xlink:href>`, parser bere jen `<img>`.
- **Cache se neuklízí** — soubory pro staré fonty a verze algoritmu zůstávají ležet (~0,75 MB na knihu a konfiguraci).
- **Dlouhá slova se nedělí** — slovo širší než řádek (např. URL) přeteče.
- **Otočení stránky trvá ~10 s** — strop daný panelem, viz [PERFORMANCE].
- **Obnova po zapnutí předpokládá**, že panel drží poslední obraz. Kdyby se smazal, displej se srovná při prvním stisku.

---

# [HISTORY_NOTE]

Do commitu `4248dad` byl projekt postavený na **globálních proměnných** duplikovaných mezi `hlavni_ctecka.py` a `simulator.py`. Refaktor je rozdělil podle osy stav/kreslení/hardware a opravil mimo jiné: pořadí kapitol (manifest → spine), zdvojený text z `<div><p>`, slévání slov přes hranice tagů, rozestup řádků (zadrátovaných 37 px vs. 43 px z metrik fontu), ztracené překreslení při souběhu, parsování v GPIO callbacku, neatomický zápis pozic, klíče závislé na CWD a Werkzeug RCE v simulátoru.

**Dřívější verze tohoto souboru popisovala věci, které v kódu nikdy nebyly** — `pickle` cache v `cache/*.pkl`, dvouúrovňový debounce s `probiha_vykreslovani` a `posledni_stisk_cas`, `RPi.GPIO` v produkci a dev variantu `test_tlacitek_hl_ctecka.py`. Nic z toho neexistuje; při práci podle tohoto dokumentu si klíčová tvrzení ověř v kódu.
