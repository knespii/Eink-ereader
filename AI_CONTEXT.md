# [PROJECT_OVERVIEW]

DIY hardwarová **e-ink čtečka EPUB knih** na **Raspberry Pi Zero W** s displejem **Waveshare 7.5" HD (`epd7in5b_HD`, tříbarevný černá/bílá/červená, fyzicky 880×528 px)**. Součástí repozitáře je i **Flask simulátor**, který běží na **stejném kódu** jako produkce (ne jako zrcadlová kopie) a slouží k vývoji bez hardwaru.

Ovládání je **hybridní**, protože otočení stránky na e-inku trvá ~29 s (viz [PERFORMANCE]) a listování knihovnou je tím nepoužitelné:

| Stav | Displej | Ovládání |
|---|---|---|
| `MENU` | OLED 128×32 přes I2C | rotační kodér |
| `CTENI` | e-ink přes SPI | 3 GPIO tlačítka |

Knihy se dají třídit do **složek — jen jedna úroveň**, zanořené podsložky se ignorují.

Kód i komentáře jsou česky, včetně názvů funkcí a proměnných.

---

# [TECH_STACK]

- **Jazyk:** Python (venv v `.venv/`; na Pi 3.11, na vývojovém desktopu 3.13)
- **Runtime target:** Raspberry Pi Zero W (ARM), Raspberry Pi OS
- **Rendering:** `Pillow` 12.2.0 (`PIL.Image`, `ImageDraw`, `ImageFont`)
- **Parsing EPUB:** `EbookLib` 0.20 (`epub.read_epub`, `spine`, `ITEM_DOCUMENT`)
- **Parsing HTML:** `beautifulsoup4` 4.14.3, `soupsieve` 2.8.4, `lxml` 6.1.1
- **GPIO:** `gpiozero` 2.0.1 (backend `lgpio`, na Pi balík `python3-lgpio`) — `Button` i `RotaryEncoder`
- **OLED:** `luma.oled` 3.15.0 (SSD1306, I2C). Vyžaduje povolené I2C.
- **Web simulátor:** `Flask` 3.1.3
- **Testy:** `pytest` 9.1.1, GPIO přes `gpiozero.pins.mock.MockFactory` (bez HW)
- **Fonty:** DejaVu Sans TTF, `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` (jedna cesta pro produkci i simulátor; fallback `ImageFont.load_default()`). Pro ikony na OLEDu **Font Awesome 4.7.0**, vendorovaný v `fonts/FontAwesome.ttf` (OFL-1.1, licence přiložena) — na Raspberry Pi OS není předinstalovaný.
- **Deklarace závislostí:** `requirements.txt` s **pevnými verzemi** + `requirements-dev.txt` (pytest)
- **Externí závislost (NENÍ v repu):** ovladač `waveshare_epd` — očekáván v `./waveshare_epd/`. Když chybí, program **nespadne**: `vytvor_displej()` sáhne po `DummyDriver` a běží naprázdno.

---

# [ARCHITECTURE]

Základní pravidlo: **stav, kreslení a hardware o sobě navzájem nevědí.** Díky tomu jede simulátor na produkčním kódu a všechno jde testovat bez Pi.

| Modul | Odpovědnost | Nesmí znát |
|---|---|---|
| `stav.py` | konečný automat `MENU`/`CTENI`, třída `Ctecka`, navigace ve složkách | PIL, GPIO, Flask, soubory |
| `vykresleni.py` | `vykresli(snimek, fonty, nacti_obrazek)` → 2 bitmapy pro e-ink | hardware, rotaci, EPUB |
| `oled_ui.py` | `vykresli_oled(snimek, fonty, faze)` → 1 bitmapa 128×32 | stav, soubory, EPUB |
| `displej.py` | rozhraní `Displej` + `WaveshareDriver` / `DummyDriver` | stav, obsah knih |
| `knihovna.py` | jediné místo s I/O: knihy, složky, pozice, cache, obrázky | stav, kreslení |
| `zpracovani_epub.py` | EPUB → text a **cesty** k obrázkům | rozvržení, displej |
| `zpracovani_textu.py` | rozvržení do stránek + JSON cache | displej, GPIO |
| `hlavni_ctecka.py` | GPIO + hlavní smyčka | — |
| `simulator.py` | Flask + skládání vrstev do RGB | — |

**Klíčové vzory:**

- **Jediný zdroj pravdy:** `Ctecka` drží veškerý stav a je **thread-safe** (`threading.Condition`). Produkce i simulátor na ni sahají identicky; liší se jen vstup (GPIO vs. HTTP) a výstup (e-ink vs. PNG). Ověřeno testem, že web ukazuje **bajtově totéž**, co jde na panel.
- **Snímek místo živého stavu:** `Ctecka.snimek()` vrací zmrazený `@dataclass(frozen=True) Snimek`. Vykreslování tak nemůže přečíst stav rozpůlený stiskem tlačítka.
- **Drahá práce mimo callbacky:** stránkování trvá na Pi Zero W ~16 s. Callbacky gpiozero smějí **jen sáhnout na stav** (měřeno: 0,02 ms). Otevření knihy jde přes **požadavek**: `akce()` ho zaeviduje → hlavní smyčka `vyzvedni_pozadavek()` → parsuje → `dodej_stranky()`. Mezitím svítí `nacita_se`.
- **Ochrana proti ztracenému překreslení:** `cekej_na_prekresleni()` shazuje vlajku **před** renderem, atomicky pod zámkem. Stisk během ~29s zápisu na e-ink se tak neztratí.
- **Koalescence zápisů:** rychlé listování se slije do **jednoho** zápisu `progress.json` (šetří SD kartu).
- **Rotace patří driveru:** `vykresleni.py` kreslí 528×880 na výšku; otočení o 90° do 880×528 dělá `WaveshareDriver`, protože to je vlastnost železa, ne knihy.
- **Dva displeje, jeden snímek:** `MENU` kreslí jen na OLED, `CTENI` jen na e-ink. Oba renderery čtou tentýž `Snimek`, takže se nemůžou rozejít. Návrat z knihy do menu **e-ink nepřekresluje** — panel drží poslední stránku a funguje jako přirozená záložka. `posledni_stav.json` se zapisuje jen při zápisu na panel, takže pořád popisuje to, co je na něm vidět.
- **Kodér mlčí při čtení:** callbacky kodéru jsou obalené kontrolou stavu. Cvrnknutí do kodéru během čtení by jinak spustilo půlminutový refresh panelu.
- **Lazy import ovladačů:** `waveshare_epd` se importuje až v konstruktoru `WaveshareDriver`, `luma.oled` až ve `vytvor_oled()` → zbytek jde spustit a testovat na desktopu. Chybějící železo se obejde atrapou, nesestřelí program.
- **Hromadný SPI přenos:** viz [PERFORMANCE].

---

# [FILE_STRUCTURE]

```
ctecka/
├── stav.py                  # FSM: Ctecka + Snimek + Stav/Typ (StrEnum) + Polozka. Bez PIL/GPIO/Flask.
├── vykresleni.py            # vykresli(snimek, fonty, nacti_obrazek) -> (cerna, cervena) 528×880
├── oled_ui.py               # vykresli_oled(snimek, fonty, faze) -> 128×32; vytvor_oled() (luma.oled)
├── displej.py               # rozhraní Displej; WaveshareDriver (rotace + hromadné SPI) / DummyDriver
├── knihovna.py              # jediné I/O: strom knih a složek, progress.json, posledni_stav.json, cache
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
├── fonts/                   # FontAwesome.ttf (4.7.0, OFL-1.1) + LICENSE-FontAwesome.txt
├── tests/                   # 267 testů (pytest), bez hardwaru
│   ├── conftest.py          # autouse fixtury chránící progress.json a cache uživatele
│   ├── test_stav.py, test_vykresleni.py, test_displej.py, test_knihovna.py
│   ├── test_zpracovani_epub.py, test_zpracovani_textu.py
│   ├── test_hlavni_ctecka.py    # tlačítka, kodér, rozvětvení výstupu OLED/e-ink
│   ├── test_simulator.py
│   ├── test_rychly_prenos.py    # bajtová shoda hromadného SPI přenosu
│   └── test_obnoveni.py         # navázání po zapnutí bez bliknutí
├── epuby/                   # vstupní EPUB knihy a složky s knihami (git-ignored)
├── waveshare_epd/           # ovladač displeje (NENÍ v repu, instaluje se zvlášť)
├── progress.json            # pozice v knihách (git-ignored)
├── posledni_stav.json       # poslední zobrazený stav (git-ignored)
└── .venv/
```

---

# [CORE_COMPONENTS]

## `stav.py` — konečný automat
- `Stav(StrEnum)`: `MENU` | `CTENI`. `Typ(StrEnum)`: `SLOZKA` | `KNIHA` | `ZPET`.
- `Polozka` = frozen dataclass (`typ`, `nazev`, `cesta`). `POLOZKA_ZPET` je syntetické `".."` — na disku neexistuje, do pohledu se přidává jen mimo kořen a je vždy první.
- `Snimek` = frozen dataclass: stav, **polozky** (obsah aktuálního adresáře včetně `..`), **adresar**, vyber, kniha (relativní cesta), **kniha_nazev** (jen jméno souboru, k zobrazení), stranka, cislo_stranky, pocet_stranek, nacita_se, chyba. Pole `seznam_knih` zůstalo jako n-tice názvů kvůli `vykresleni.py`.
- `Ctecka(seznam_knih=None, prekreslit_na_startu=True)`.
- **Pro tlačítka a kodér (z cizích vláken):** `dalsi()`, `predchozi()`, `akce()`, `zpet_do_menu()`, `ukonci()`.
- **Pro hlavní smyčku:** `snimek()`, `cekej_na_prekresleni(timeout)`, `spotrebuj_prekresleni()`, `vyzvedni_pozadavek()`, `dodej_stranky(nazev, stranky, pocatecni_stranka)`, `vyzvedni_pozici_k_ulozeni()`, `nastav_seznam_knih(strom)`, vlastnost `konec`.
- **Složky bez I/O:** `Ctecka` drží **celý strom** (`{"": [...], "slozka": [...]}`), který jí dodá hlavní smyčka. Vstup do složky je tak čistá práce s pamětí a jde vyřídit rovnou v obsluze kodéru. `nastav_seznam_knih()` bere i plochý seznam (kompatibilita) a drží výběr na téže položce podle `cesta`.
- `akce()` se v menu větví podle `Typ`: `ZPET` → kořen (kurzor se postaví na opuštěnou složku), `SLOZKA` → vstup, `KNIHA` → požadavek pro hlavní smyčku.
- **Obnova po startu:** `obnov_cteni(nazev, stranky, stranka)`, `obnov_menu(vyber, adresar="")` — nastaví stav **bez** vyžádání překreslení; `vyzadej_prekresleni()` když obnova neseděla.
- Návrat do menu **zahazuje stránky** (paměť na 512 MB) a **ruší** rozpracované načítání — jinak by kniha za chvíli stejně naskočila. **Adresář si drží**, aby uživatel po zavření knihy nespadl do kořene.
- Zmizelá složka shodí `_adresar` na kořen: prázdné menu bez cesty ven je horší než špatný výběr.

## `vykresleni.py` — kreslení
- `nacti_fonty(cesta)` → `Fonty(text=32, info=20, titulek=40)`.
- `vykresli(snimek, fonty, nacti_obrazek=None)` → `(cerna, cervena)`, obě `PIL.Image` mode `"1"`, 528×880, **neotočené**.
- Rozměry se **odvozují**: `TEXT_SIRKA = SIRKA - 2*OKRAJ = 488`, `TEXT_VYSKA = LISTA_Y - OKRAJ = 820`, `LISTA_Y = 840`.
- Řádkování bere z `zpracovani_textu.vyska_radku(fonty.text)` — **jeden zdroj pravdy** s layoutem (43 px pro DejaVu 32).
- Menu roluje **po stránkách** po `POLOZEK_NA_STRANKU = 13`; lišta hlásí `Knihy 14–26 z 30`.
- **Stavová lišta je jen v menu.** Při čtení jde na panel čistý text knihy a **červená vrstva zůstává prázdná** — číslo stránky ukazuje OLED. Hlídá to `test_cervena_vrstva_zustane_prazdna`.
- `TEXT_VYSKA` zůstalo 820 i po zrušení lišty. Uvolnilo se 20 px, ale při rozestupu 43 px se na 820 i 840 px vejde stejných **19 řádků** — rozšíření by tedy nepřidalo ani řádek a jen by si vyžádalo zvýšení `VERZE_ALGORITMU` a přestránkování všech knih.
- Místo toho se blok textu **svisle vycentruje** (`_horni_okraj_textu()`): odsazení shora vyjde 34 px, naměřené okraje 40 / 35 px. Počítá se z **plné** stránky, ne z počtu řádků na té aktuální — jinak by poloprázdná stránka kapitoly plavala uprostřed a text by mezi stránkami poskakoval. Stránkování se tím nemění, cache zůstává platná.
- Obrázek se centruje na střed **celého panelu** (`VYSKA`), ne textové oblasti — při čtení už dole žádná lišta není.
- Obrázky nenačítá sám — dostane `nacti_obrazek(cesta_v_archivu)`. Bez něj kreslí zástupku.

## `displej.py` — hardware
- `Displej` (ABC): `zobraz(cerna, cervena)`, `vycisti()`, `vypni()`.
- `WaveshareDriver`: rotace o 90°, `init()` → data → `sleep()`. Import `waveshare_epd` až v `__init__`.
- `rychle_zobraz(epd, cfg, cerna_buf, cervena_buf)` / `rychle_vycisti(epd, cfg)` — hromadný SPI přenos (viz [PERFORMANCE]). Fallback na `epd.display()`, když `epdconfig` nemá `spi_writebyte2`.
- Na `sys.path` se přidává i adresář `waveshare_epd/` — starší ovladač uvnitř dělá `import epdconfig` nerelativně.
- `DummyDriver` jen loguje; `vytvor_displej()` vybírá podle dostupnosti ovladače.

## `knihovna.py` — všechno I/O
- `nacti_strom()` → `{"": [položky kořene], "slozka": [položky složky]}`. Položka je `{"typ": "slozka"|"kniha", "nazev", "cesta"}`. Podadresáře se hlásí **jen z kořene**, takže složka ve složce se ignoruje.
- `nacti_seznam_knih()` → ploché **relativní cesty** všech knih; slouží už jen k ověření, že kniha z `posledni_stav.json` pořád existuje.
- `nacti_pozice()`, `uloz_pozici(kniha, stranka)`, `nacti_stranky(nazev, fonty)`, `nacti_obrazek_knihy(nazev)` — `nazev` je všude **relativní cesta** (`"kniha.epub"` i `"slozka/kniha.epub"`).
- `_bezpecna_cesta(relativni)` — ověří, že cesta nevede ven ze `SLOZKA_KNIH`. Cesty se ukládají do JSONu, takže ručně upravený soubor by přes `..` jinak otevřel cokoli na disku.
- `obsluz(ctecka, fonty, hlas=None)` — vyřídí požadavek na načtení a zápis pozice. Volá ji hlavní smyčka i simulátor.
- **Hlášení postupu:** `hlas` je volitelné `callable(podil)` s podílem 0→1, které `nacti_stranky()` propouští do obou fází — `zpracovani_epub.nacti_epub_obsah(hlas=)` dostane úsek 0–0,5 (hlásí po kapitolách), `zpracovani_textu.zformatuj_a_rozdel(hlas=)` úsek 0,5–1 (hlásí po blocích). Dělí se napůl schválně; poměr časů se kniha od knihy liší, ale ukazatel má dát najevo, že se něco děje, ne měřit čas. **Callback, ne kreslení uvnitř:** knihovna o displejích nesmí vědět, jinak by se rozešla se simulátorem, který žádný OLED nemá. Na reálné knize (1465 stran) se `hlas` zavolá ~3900×.
- `uloz_posledni_stav(snimek)` / `nacti_posledni_stav()` / `obnov_posledni_stav(ctecka, fonty)`.
- `_zapis_json_atomicky(cesta, data)` — tmp + `fsync` + `os.replace`.
- Cesty se odvozují od `__file__`, **ne** od CWD (jinak by čtečka ze systemd nenašla knihy).

## `oled_ui.py` — menu na OLEDu
- `vykresli_oled(snimek, fonty=None, faze=0)` → `PIL.Image` mode `"1"`, **128×32**, bílá (255) na černé. Nic nezobrazuje, jen vrací obraz.
- UI je **carousel**: na 32 px výšky se vejde jeden řádek, takže je vidět vždy jen vybraná položka — ikona vlevo, název, počítadlo vpravo. `..` se ukazuje jako `← .. scifi` a do počítadla se nezapočítává.
- `nacti_fonty()` → `FontyOled(text, ikony, drobne, ikony_jsou)`. DejaVu 12/9 px, FontAwesome 13 px.
- FontAwesome se hledá ve třech cestách, první existující vyhrává: `fonts/FontAwesome.ttf` (odvozeno od `__file__`), pak dvě systémové. Když chybí, `ikony_jsou=False` a kreslí se náhradní ASCII (`[]`, `*`, `<-`) — menu zůstane čitelné.
- Ikony jsou kódy z **privátní oblasti FontAwesome 4** (`` složka, `` kniha, `` zpět, `` načítání, `` chyba, `` prázdno), zapsané escapem schválně. **V FA 5 a novějších se liší** — proto je vendorovaná právě 4.7.0.
- **Ticker:** název delší než pruh se posouvá podle `faze`, vykreslený dvakrát za sebou, aby přetočení najelo plynule. Kreslí se do vlastního pruhu a vkládá zpět, jinak by přetekl přes počítadlo. Přípona `.epub` se odřezává — na 128 px se počítá každý pixel.
- **Ukazatel postupu** `_ukazatel_postupu(obraz, podil)` — vodorovná čára na spodních 3 px (`VYSKA_UKAZATELE`) dlouhá `podil × SIRKA`, minimálně 1 px (nulová čára vypadá jako rozbitý displej). Používá se dvakrát: při `CTENI` jako postup v knize (`cislo_stranky / pocet_stranek` — z čísla stránky 1..N, ne z indexu, jinak by poslední stránka nikdy nevyšla na plnou šířku) a pod hláškou „Načítám…" jako postup parsování. Rozlišení je hrubé, u knihy o 1465 stranách se čára hne jednou za ~11 stránek.
- `vykresli_hlaseni(text, fonty, podil=None)` — vycentrovaná hláška; s `podil` přikreslí pod ni ukazatel.
- **Pořadí kreslení je závazné:** ukazatel se kreslí **až po** `_radek()`. Ticker vkládá posouvaný pruh přes celou výšku obrázku, takže dřív nakreslená čára by se v jeho sloupcích smazala. Hlídá to `test_prezije_posun_tickeru`.
- `vytvor_oled(port=1, adresa=0x3C)` — lazy import `luma.oled`; když knihovna, I2C nebo panel chybí, vrátí `_DummyOled` a čtečka běží dál.

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
- Tlačítka u e-inku (BCM): `PIN_DALSI = 21`, `PIN_PREDCHOZI = 26`, `PIN_AKCE = 19`; `bounce_time = 0.1`, `hold_time = 2.0`.
- Kodér u OLEDu (BCM): `PIN_ENKODER_CLK = 5`, `PIN_ENKODER_DT = 6`, `PIN_ENKODER_SW = 13`. OLED na I2C: BCM 2 (SDA) a 3 (SCL).
- Krátký stisk visí na **`when_released`** (s vlajkou `drzeno`) — jinak by dlouhý stisk nejdřív otevřel knihu.
- `pripoj_enkoder()` obaluje všechny tři callbacky kontrolou `Stav.MENU`. Chybějící kodér se odchytí a jen zaloguje — menu pak jede na tlačítkách.
- `VystupOled` porovnává vykreslený obraz s posledním odeslaným a shodný na I2C neposílá. Bez toho by krátký název při 0,15s tiku znamenal 7 zápisů za sekundu pro nic. `hlaseni(text, podil)` tohle porovnání obchází — hláška se musí objevit vždy.
- `hlas_nacitani(oled)` vrací callback pro `knihovna.obsluz()`, který během parsování překresluje ukazatel, ale nejvýš jednou za `PERIODA_HLASENI = 0.1` s. Parser hlásí tisíckrát za knihu; kreslit tolikrát by načítání znatelně prodloužilo.
- Časování: `TIK_MENU = 0.08` (kvůli plynulému tickeru, ~12,5 snímku/s), `TIK_CTENI = 1.0`, `PERIODA_SKENU = 2.0`.
- **Ticker jede podle hodin, ne podle tiků.** `faze_tickeru(polozka_od)` počítá posun z `time.monotonic()`: `RYCHLOST_TICKERU = 40` px/s po prodlevě `PRODLEVA_TICKERU = 1.0` s. Kdyby se fáze zvyšovala o konstantu na každý průchod, zdržel by ji sken složky nebo zápis pozice a text by se viditelně trhal. `time.sleep()` se nepoužívá nikde — čeká se na `threading.Condition`, takže cvaknutí kodéru smyčku probudí okamžitě.
- Posouvá se **jen název**. Ikona a počítadlo leží mimo posouvaný pruh (`_text_ticker()` kreslí do vlastního obrázku a vkládá ho zpět), takže se nemůžou hnout ani probliknout. Hlídá to `TestScrollovaniNazvu`.
- `PERIODA_CISTENI = 0` (čištění vypnuté, viz [PERFORMANCE]).
- Hlavní smyčka: `cekej_na_prekresleni(tik podle stavu)` → v `MENU` jen `oled.prekresli()`, v `CTENI` `zobraz()` na e-ink + levný stavový řádek na OLED → `knihovna.obsluz()` → v `MENU` přeskenování stromu, ale nejvýš po `PERIODA_SKENU`.
- Skenování je throttlované schválně: s `TIK_MENU` 0,15 s by se jinak vypisoval adresář sedmkrát za sekundu.

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

## Stisk / cvaknutí kodéru → překreslení
1. Callback gpiozero (cizí vlákno) sáhne na `Ctecka` a probudí smyčku. **Nic nenačítá ani nekreslí.**
2. `cekej_na_prekresleni()` vrátí `True` a **zároveň shodí vlajku** (stisk během renderu se tak neztratí).
3. Podle stavu: `MENU` → `oled.prekresli(snimek)`, `CTENI` → `zobraz()` → `vykresli(snimek, ...)` → `obrazovka.zobraz()` → `uloz_posledni_stav(snimek)`.
4. `knihovna.obsluz()` vyřídí případný požadavek na knihu a zápis pozice.

## Pohyb v menu a složkách
1. Otočení kodéru → `dalsi()` / `predchozi()` nad pohledem aktuálního adresáře.
2. Stisk kodéru → `akce()`: vstup do složky nebo návrat přes `..` se vyřídí **rovnou v callbacku** (jen paměť), otevření knihy jde přes požadavek.
3. Smyčka překreslí OLED. **E-ink se nedotkne.**

## Otevření knihy
1. `akce()` na položce typu `KNIHA` zaeviduje **požadavek** s relativní cestou (stav zůstává `MENU`, `nacita_se = True`, OLED ukáže „Načítám…").
2. Smyčka `vyzvedni_pozadavek()` → `nacti_stranky()` → cache hit (ihned) nebo parse + stránkování (~16 s).
3. `dodej_stranky(cesta, stranky, nacti_pozice().get(cesta, 0))` → `CTENI` + překreslení e-inku.

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
| `progress.json` | `{"<relativní cesta>.epub": <index stránky>}` — klíč je cesta **relativní ke složce knih** (`"kniha.epub"` i `"scifi/kniha.epub"`), tedy pořád nezávislá na CWD. Zápis atomický. |
| `posledni_stav.json` | `{"typ":"cteni","kniha":...,"stranka":N}` nebo `{"typ":"menu","vyber":N,"adresar":"..."}` — poslední obraz **na e-inku**. |
| `~/.cache/ctecka/<hash>.json` | Stránkování knihy. **Čistý JSON, ne pickle.** |

Klíčem v `progress.json` bývalo jen jméno souboru; se složkami by se dvě stejně pojmenované knihy v různých složkách přepisovaly navzájem. **Knihy přesunuté do složek proto ztratí dřív uloženou pozici**, knihy v kořeni jsou nedotčené.

`posledni_stav.json` se zapisuje **jen ve větvi e-inku** (`zobraz()`), takže pořád popisuje to, co panel skutečně ukazuje. Menu na OLEDu do něj nezasahuje — OLED je po zapnutí stejně prázdný a překreslit ho nic nestojí. Důsledek: kdo vypne čtečku v menu, probudí se v knize, kterou e-ink drží.

**Invalidační klíč cache** = SHA-256 (16 hex znaků) z: jména knihy + její velikosti + mtime, cesty k fontu, velikosti fontu, rozlišení, rozestupu řádků a `VERZE_ALGORITMU`. Změna čehokoli z toho cache zneplatní sama. Pickle se nepoužívá záměrně — vázal by cache na verzi Pillow a jeho načtení umí spustit cizí kód.

## Rozlišení
- **E-ink** — logická plocha (na výšku): **528×880**, textová oblast **488×820**, stavová lišta na `y = 840` (**jen v menu**, při čtení je červená vrstva prázdná). Fyzický panel (na šířku): **880×528**, rotaci dělá driver. Dvě 1-bitové vrstvy: černá + červená (červená se do panelu posílá **invertovaná**).
- **OLED** — **128×32**, jedna 1-bitová vrstva, bílá (255) na černé. Žádná rotace.

---

# [PERFORMANCE]

Naměřeno na Pi Zero W:

| Operace | Čas |
|---|---|
| Import modulů + vykreslení menu | 4,8 s |
| `display()` původním ovladačem | ~99 s |
| `Clear()` | ~91 s |
| Stránkování knihy (cache miss) | ~16 s |
| Stránkování z cache | ihned |

**Rozpad otočení stránky** (změřeno 19. 7. 2026 na Pi Zero W, `zobraz()` krok po kroku):

| Fáze | Před | Po | Kde to je |
|---|---|---|---|
| `vykresli()` | 0,35 s | 0,35 s | `vykresleni.py` |
| `rotate(90)` + buffer | **4,00 s** | **~0,1 s** | `WaveshareDriver._buffer()` |
| inverze červené + `list(data)` | ~0,12 s | ~0,003 s | `rychle_zobraz()`, `_posli_blok()` |
| `epd.init()` | 1,26 s | 1,26 s | ovladač |
| přenos + budicí křivka panelu | 25,33 s | 25,33 s | hardware |
| `epd.sleep()` | 2,00 s | 2,00 s | ovladač |
| **celkem** | **~33 s** | **~29 s** | |

**Ty 4 s byly `epd.getbuffer()`** — prochází všech 464 640 pixelů v Pythonu, 1,72 s na vrstvu. `WaveshareDriver._buffer()` to obchází přes `PIL.tobytes()` (0,04 s): panel je široký 880 px = 110 celých bajtů, takže se řádky nikde nedoplňují a balení MSB-napřed vychází bajtově shodně. Zkratka platí **jen** pro obraz o rozměru panelu a mode `"1"`; cokoli jiného jde dál přes `getbuffer()`, protože ovladač si to sám otáčí. Hlídá to `TestRychleBaleniBufferu` proti doslovnému přepisu původní smyčky, na bílém, černém, pruhovaném a náhodném vzoru — **bílý obraz sám nic nedokazuje**, tam obě cesty vyjdou jako samé `0xFF` bez ohledu na polaritu.

**Dalších ~0,12 s** braly dvě pythonovské smyčky po bajtech: `[~b & 0xFF for b in cervena_buf]` (58 080 iterací) a `list(data)` u obou vrstev. Nahrazeno `bytes.translate(_INVERZE)` a předáváním `bytes` rovnou do `spi_writebyte2`.

**Zbytek je hardware.** Po těchhle dvou opravách je veškerý Python v cestě pod 0,5 s. Rozdělení 25,33 s na přenos a budicí křivku bylo ověřeno na Pi — dominuje křivka, přenos 116 KB je zlomek. Přesná čísla toho rozpadu tady zapsaná nejsou.

**Dřívější údaj „`display()` s hromadným přenosem ~10 s" neplatí** — naměřeno 25,33 s pro přenos i křivku dohromady. Odkud se vzalo těch 10 s, není jasné; ber tabulku výše jako platnou.

**Nezměřeno / neuděláno:** `epd.init()` + `epd.sleep()` stojí 3,26 s na každou stránku. Vynechat `sleep()` mezi stránkami (nebo uspávat až po chvíli nečinnosti) by je ušetřilo, ale panel by zůstal pod napětím, před čímž Waveshare varuje kvůli DC bias.

**Prefetching stránek nemá smysl.** `Ctecka._stranky` je běžný list s celou knihou v RAM; `dalsi()` + `snimek()` trvá 0,004 s. Předpočítávat bitmapy by ušetřilo 0,35 s z 29 s.

**Proč byl původní `display()` pomalý:** ovladač posílá obraz po jednom bajtu — 116 160 volání `send_data()`, každé třikrát cvakne GPIO (~460 tisíc gpiozero operací). Samotný přenos 116 KB na 4 MHz trvá 0,23 s; brzdila obsluha pinů, ne panel ani SPI.

**Řešení:** `WaveshareDriver` reprodukuje tutéž příkazovou sekvenci (`0x4F`/`0xAF`, `0x24` černá, `0x26` invertovaná červená, `0x22`/`0xC7`, `0x20`), ale oba buffery pošle **jedním `writebytes2`** s CS drženým dole. **9 SPI transakcí místo 116 167**, do panelu jdou bajtově shodná data (ověřeno testem proti skutečnému ovladači).

**Čištění panelu vypnuté** (`PERIODA_CISTENI = 0`): tříbarevný panel jede při každém `display()` plnou křivkou, obraz přepíše celý a duchy prakticky nenechává; `Clear()` by jen přidal 91 s.

**Částečné překreslení není možné** — červený pigment vyžaduje plnou budicí křivku přes celý panel. To je vlastnost hardwaru, ne kódu.

**Proto vzniklo hybridní UI:** menu na e-inku znamenalo ~29 s na každý posun kurzoru. OLED se překreslí v jednotkách milisekund, takže knihovnou jde listovat plynule a e-ink zůstal jen na stránku textu, kde se stejně čeká.

**OLED zatím nebyl změřen na Pi Zero W.** Vykreslení 128×32 je řádově milisekundy a I2C přenos ~512 bajtů taky, ale čísla v téhle tabulce jsou z reálného měření, kdežto tohle je odhad — neber ho jako naměřený fakt.

---

# [TESTING]

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest          # 267 passed, 2 skipped
```

- **Bez hardwaru:** gpiozero jede na `MockFactory`, takže jde otestovat i dvouvteřinové držení tlačítka nebo kvadraturní sekvenci kodéru.
- **Chrání data uživatele:** autouse fixtury v `conftest.py` odklánějí `progress.json`, `posledni_stav.json` i cache mimo repozitář.
- **Bez knih v `epuby/`** se testy nad reálnou knihou přeskočí.
- Klíčové vlastnosti pokryté testy: bajtová shoda simulátoru s panelem, bajtová shoda hromadného SPI přenosu, ztracené překreslení při souběhu, dlouhý stisk neotevře knihu, atomický zápis přežije výpadek napájení, obnova po startu nebliká, odmítnutí cesty ven ze složky knih, ignorování zanořených podsložek.
- **Rozvětvení výstupu** hlídá `TestRozvetveniVystupu` v `test_hlavni_ctecka.py`: pouští `main()` ve vlákně proti atrapám obou displejů a zaznamenává, kam se psalo. Ověřeno mutací — když se do menu vrátí e-ink, spadnou 3 testy; když kodér přestane mlčet při čtení, spadnou 2.

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
sudo raspi-config nointeractive do_spi 0   # povolit SPI (e-ink)
sudo raspi-config nointeractive do_i2c 0   # povolit I2C (OLED)
./install-sluzba.sh                        # autostart po zapnutí
```

Font pro ikony se táhne s repozitářem (`fonts/FontAwesome.ttf`), instalovat se nemusí. Kontrola OLEDu:

```bash
sudo i2cdetect -y 1                        # na adrese 3c má něco být
```

Když OLED chybí nebo je špatně zapojený, čtečka **nespadne** — `vytvor_oled()` sáhne po atrapě a do logu jde varování. Totéž platí pro kodér.

Ovladač musí mít `epdconfig.spi_writebyte2` (hardwarové SPI). Starší verze se software SPI (soubory `sysfs_software_spi.so`) ho nemají a čtečka spadne zpět na pomalý režim. Kontrola:

```bash
.venv/bin/python -c "from waveshare_epd import epdconfig; print(hasattr(epdconfig, 'spi_writebyte2'))"
```

Správa služby: `sudo systemctl status ctecka`, `journalctl -u ctecka -f`, `sudo systemctl disable --now ctecka`.

---

# [KNOWN_LIMITATIONS]

- **Hybridní UI nebylo ověřeno na skutečném hardwaru.** OLED, kodér i vendorovaný font jsou otestované jen softwarově — vykreslením do obrázku, mock piny a atrapami displejů. Na reálný SSD1306 a kodér to zatím nikdo nepustil.
- **Obálky knih se nezobrazují** — titulní strany bývají `<svg><image xlink:href>`, parser bere jen `<img>`.
- **Cache se neuklízí** — soubory pro staré fonty a verze algoritmu zůstávají ležet (~0,75 MB na knihu a konfiguraci).
- **Dlouhá slova se nedělí** — slovo širší než řádek (např. URL) přeteče.
- **Otočení stránky trvá ~29 s**, z toho ~25 s je přenos a budicí křivka panelu — strop daný hardwarem. Zbylé ~4 s jsou `epd.init()` a `epd.sleep()`. Viz [PERFORMANCE].
- **Obnova po zapnutí předpokládá**, že panel drží poslední obraz. Kdyby se smazal, displej se srovná při prvním stisku.
- **Vypnutí v menu probudí čtečku v knize** — `posledni_stav.json` popisuje e-ink, a ten drží poslední stránku. Návrat do menu je pak na tlačítku `PIN_AKCE`.
- **Jen jedna úroveň složek.** Podsložka ve složce se ignoruje, knihy v ní jsou z menu nedostupné.
- **Menu na e-inku už nikdo nekreslí**, ale `vykresleni.py` ho pořád umí a používá k tomu `Snimek.seznam_knih` (jen názvy, bez rozlišení složky). Používá ho simulátor.
- **Simulátor nemá OLED** — kreslí pořád e-inkovou cestou, takže menu v prohlížeči vypadá jinak než na čtečce.

---

# [HISTORY_NOTE]

Do commitu `4248dad` byl projekt postavený na **globálních proměnných** duplikovaných mezi `hlavni_ctecka.py` a `simulator.py`. Refaktor je rozdělil podle osy stav/kreslení/hardware a opravil mimo jiné: pořadí kapitol (manifest → spine), zdvojený text z `<div><p>`, slévání slov přes hranice tagů, rozestup řádků (zadrátovaných 37 px vs. 43 px z metrik fontu), ztracené překreslení při souběhu, parsování v GPIO callbacku, neatomický zápis pozic, klíče závislé na CWD a Werkzeug RCE v simulátoru.

Na větvi `feature/oled-ui` přibylo hybridní UI: podpora složek (`nacti_strom()`, `Typ`, `Polozka`, adresář ve stavu), modul `oled_ui.py`, rotační kodér a rozdělení výstupu mezi OLED a e-ink. Klíč v `progress.json` se přitom změnil ze jména souboru na relativní cestu.

**Dřívější verze tohoto souboru popisovala věci, které v kódu nikdy nebyly** — `pickle` cache v `cache/*.pkl`, dvouúrovňový debounce s `probiha_vykreslovani` a `posledni_stisk_cas`, `RPi.GPIO` v produkci a dev variantu `test_tlacitek_hl_ctecka.py`. Nic z toho neexistuje; při práci podle tohoto dokumentu si klíčová tvrzení ověř v kódu.
