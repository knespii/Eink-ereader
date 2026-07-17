# [PROJECT_OVERVIEW]

DIY hardwarová **e-ink čtečka EPUB knih** běžící na **Raspberry Pi Zero W** s displejem **Waveshare 7.5" HD (epd7in5b_HD, dvoubarevný černá/červená, 880×528 px)**, ovládaná 3 fyzickými GPIO tlačítky. Repozitář obsahuje produkční běhový modul, jeho vývojovou variantu a webový **Flask simulátor** pro vývoj bez hardwaru.

---

# [TECH_STACK]

- **Jazyk:** Python 3.13 (venv v `.venv/`, interpreter `python3.13`)
- **Runtime target:** Raspberry Pi Zero W (ARM), Linux
- **Rendering / grafika:** `Pillow` 12.2.0 (`PIL.Image`, `ImageDraw`, `ImageFont`)
- **Parsing EPUB:** `ebooklib` 0.20 (`epub.read_epub`, `ITEM_DOCUMENT`, `ITEM_IMAGE`)
- **Parsing HTML:** `beautifulsoup4` (`bs4`), `soupsieve` 2.8.4, backend `lxml` 6.1.1
- **GPIO (produkce):** `RPi.GPIO` — modul `hlavni_ctecka.py`
- **GPIO (dev varianta):** `gpiozero` — modul `test_tlacitek_hl_ctecka.py`
- **Web simulátor:** `Flask` 3.1.3 (+ tranzitivní `Jinja2` 3.1.6, `Werkzeug`, `itsdangerous` 2.2.0, `blinker` 1.9.0, `MarkupSafe`)
- **Font:** DejaVu Sans TTF (`/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` na Pi; `DejaVuSans.ttf` v CWD u simulátoru)
- **Externí závislost (NENÍ v repu):** ovladač `waveshare_epd.epd7in5b_HD` — očekáván v `./waveshare_epd/`, jinak `sys.exit(1)`
- **Deklarace závislostí:** `resources.txt` (`pillow`, `ebooklib`, `beautifulsoup4`, `gpiozero`, `Flask`) — bez verzí, **není** `requirements.txt`

---

# [ARCHITECTURE]

- **Konečný automat (Finite State Machine):** globální `aktualni_stav` s hodnotami `"MENU"` a `"CTENI"`; veškerá logika tlačítek i vykreslování větví na tomto stavu.
- **Event-driven + polling smyčka:** GPIO tlačítka registrují **callbacky na hraně FALLING**, které pouze mutují globální stav a nastaví `prekreslit_displej = True`; nekonečná `while` smyčka v `main()` na základě této vlajky provede vykreslení. Vykreslování NEbíhá v callbacku (e-ink refresh je pomalý).
- **Separation of concerns (3 vrstvy):**
  1. `zpracovani_epub.py` — extrakce obsahu (I/O + parsing).
  2. `zpracovani_textu.py` — layout engine (word-wrap + stránkování), čistá funkce bez I/O.
  3. `hlavni_ctecka.py` / `simulator.py` — orchestrace, stav, render na cílové zařízení.
- **Sdílený stavový model:** `hlavni_ctecka.py` a `simulator.py` **duplikují** identické globální proměnné a pomocné funkce (`nacti_seznam_knih`, `nacti_pozici`, `uloz_pozici`, `otevri_knihu`) — simulátor je HW-agnostická zrcadlová implementace stejné logiky.
- **Debounce dvouúrovňový:** HW debounce (`bouncetime=300` ms / `bounce_time=0.2` s) + SW throttle (`time.time() - posledni_stisk_cas < 2.0`) + guard `probiha_vykreslovani`.
- **Cache-aside vzor:** naparsovaná kniha se serializuje `pickle` do `cache/<nazev>.epub.pkl`; při dalším otevření se čte z cache (obchází pomalý parsing na Pi Zero).
- **Lazy import:** těžké moduly (`zpracovani_epub`, `zpracovani_textu`) se importují až uvnitř `otevri_knihu()` při cache-miss → rychlejší start.
- **Micro-optimalizace paměti:** rotace obrazu `Image.ROTATE_90` (displej fyzicky na výšku) + předání dat do `epd.display()` jako `bytearray` (produkce) vs. `list` (dev varianta).

---

# [FILE_STRUCTURE]

```
ctecka/
├── hlavni_ctecka.py              # PRODUKČNÍ vstupní bod; FSM + render loop + RPi.GPIO callbacky + cache
├── test_tlacitek_hl_ctecka.py    # Vývojová varianta hlavní čtečky používající gpiozero (+ dlouhý stisk = exit)
├── simulator.py                  # Flask web simulátor displeje (HTTP tlačítka, render do PNG) pro vývoj bez HW
├── zpracovani_epub.py            # Parsing EPUB → lineární seznam bloků {"typ":"text"|"obrazek", "hodnota":...}
├── zpracovani_textu.py           # Layout engine: word-wrap + stránkování bloků na render-ready stránky
├── resources.txt                 # Seznam pip závislostí (bez verzí)
├── progress.json                 # Perzistence pozice čtení: {"epuby/<kniha>.epub": <index_stranky>}
├── dokumentace.md                # ZASTARALÝ kontext pro LLM (Gemini); popisuje staré API a špatné piny — viz DATA_FLOW pozn.
├── .gitignore                    # Ignoruje .venv, __pycache__, /epuby/, *.epub, progress.json
├── epuby/                        # Vstupní složka EPUB knih (git-ignored); zdroj pro seznam_knih
│   ├── Treason.epub
│   └── Alliances.epub
├── cache/                        # (runtime, vytváří se) pickle cache naparsovaných knih *.pkl
├── __pycache__/                  # Bytecode cache
└── .venv/                        # Python 3.13 virtuální prostředí
```

**Poznámka:** Adresář `waveshare_epd/` (ovladač displeje) je vyžadován za běhu na Pi, ale v repozitáři chybí.

---

# [CORE_COMPONENTS]

## `hlavni_ctecka.py` (produkční runtime)
- **Vstupní bod** aplikace na Pi (`if __name__ == "__main__": main()`).
- **GPIO piny (BCM):** `PIN_DALSI = 21`, `PIN_PREDCHOZI = 26`, `PIN_AKCE = 19`; režim `GPIO.IN` s `pull_up_down=GPIO.PUD_UP`, detekce `GPIO.FALLING`, `bouncetime=300`.
- **Callbacky:** `stisk_dalsi(channel)`, `stisk_predchozi(channel)`, `stisk_akce(channel)` — mutují stav, řízeny hodnotou `aktualni_stav`.
- **Render loop v `main()`:** vytváří dvě 1-bit bitmapy `528×880` (`image_black`, `image_red`), kreslí menu/text/obrázek, rotuje o 90°, posílá přes `epd.init()` → `epd.display(bytearray, bytearray)` → `epd.sleep()`.
- **Komunikace:** volá `zpracovani_epub.nacti_epub_obsah()` a `zpracovani_textu.zformatuj_a_rozdel()` (lazy import), čte/zapisuje `progress.json` a `cache/`.

## `test_tlacitek_hl_ctecka.py` (dev varianta produkce)
- Funkčně shodná s `hlavni_ctecka.py`, ale ovládání přes **`gpiozero.Button`** (`bounce_time=0.2`, `when_pressed`).
- **Navíc:** `btn_akce` má `hold_time=2.0` + `when_held = stisk_akce_dlouhy` → **dlouhý stisk ukončí program** (`konec_programu = True`).
- Data do `epd.display()` posílá jako `list(...)` (neoptimalizováno oproti `bytearray`).
- Verbose `print()` logování stavů debounce.

## `simulator.py` (Flask simulátor)
- HW-nezávislá replika FSM pro vývoj v prohlížeči; renderuje do **RGB PNG** místo e-ink.
- **Routy:**
  - `GET /` → HTML stránka s `<img>` displejem a 3 tlačítky (JS `fetch` POST).
  - `GET /screen` → generuje aktuální snímek stavu jako PNG (`send_file`, mimetype `image/png`).
  - `POST /api/stisk/<tlacitko>` → `tlacitko ∈ {predchozi, akce, dalsi}`; ekvivalent HW callbacků.
- Spouští `app.run(debug=True, host="0.0.0.0", port=5000)`.
- **Odlišnost:** v menu zobrazuje název souboru **včetně** přípony (`kniha`), zatímco produkce ořezává `.epub` (`kniha[:-5]`).

## `zpracovani_epub.py` (EPUB parser)
- Funkce **`nacti_epub_obsah(cesta_k_souboru, max_sirka=880, max_vyska=488)`**.
- Prochází `ITEM_DOCUMENT` položky, `BeautifulSoup(..., 'html.parser')`, iteruje `['p','div','img']` v pořadí výskytu.
- Text → `{"typ": "text", "hodnota": str}`; obrázek → dohledá binární `ITEM_IMAGE` podle názvu souboru, `Image.thumbnail((max_sirka,max_vyska))`, `convert('1')` (1-bit), `{"typ": "obrazek", "hodnota": PIL.Image}`.
- Volající předávají `max_sirka=488, max_vyska=820` (pozor: default v signatuře je opačný).
- Chyba → vrací `[]`.

## `zpracovani_textu.py` (layout engine)
- Funkce **`zformatuj_a_rozdel(obsah, font, max_sirka_px, max_vyska_px, rozestup_radku=5)`** → `list[dict]` stránek.
- Čistá funkce (žádné I/O). Word-wrap podle `font.getlength()`; **`word_cache`** memoizuje šířky slov (výkon na Pi Zero).
- Výška řádku = `ascent + descent + rozestup_radku`; obrázek dostává **vlastní samostatnou stránku**; mezi bloky vkládá prázdný řádek.
- Výstupní stránka: `{"typ": "text", "obsah": list[str]}` nebo `{"typ": "obrazek", "obsah": PIL.Image}`.

---

# [DATA_FLOW]

## Proces 1: Start aplikace (`main()`)
1. Načtou se 3 fonty z `FONT_PATH` (fallback `ImageFont.load_default()` při `IOError`).
2. `nacti_seznam_knih()` → naplní `seznam_knih` `.epub` soubory ze `slozka_knih = "epuby"` (řazeno, `sort()`).
3. Inicializace displeje `epd = epd7in5b_HD.EPD()` a GPIO tlačítek s callbacky.
4. Vstup do `while not konec_programu` smyčky; `prekreslit_displej = True` → první render menu.

## Proces 2: Stisk tlačítka → překreslení
1. HW hrana FALLING → callback (`stisk_dalsi` / `stisk_predchozi` / `stisk_akce`).
2. **Guard:** pokud `probiha_vykreslovani` NEBO `< 2.0 s` od `posledni_stisk_cas` → `return` (ignorováno).
3. Podle `aktualni_stav`:
   - `MENU` + DALŠÍ/PŘEDCHOZÍ → posun `vybrana_kniha_index` v mezích.
   - `MENU` + AKCE → `otevri_knihu(seznam_knih[vybrana_kniha_index])`.
   - `CTENI` + DALŠÍ/PŘEDCHOZÍ → posun `aktualni_stranka` + **`uloz_pozici()`**.
   - `CTENI` + AKCE → `nacti_seznam_knih()`, `aktualni_stav = "MENU"`.
4. `prekreslit_displej = True`.
5. Smyčka detekuje vlajku → `probiha_vykreslovani = True` → render → rotace 90° → `epd.init()`/`display()`/`sleep()` → `probiha_vykreslovani = False`.

## Proces 3: Otevření knihy (`otevri_knihu`)
1. Sestaví `cache_soubor = cache/<nazev>.epub.pkl`.
2. **Cache-hit:** `pickle.load()` → `kniha_stranky`.
3. **Cache-miss:** lazy import → `nacti_epub_obsah()` → `zformatuj_a_rozdel(obsah, font_text, 488, 820)` → `pickle.dump()` do cache.
4. `aktualni_stranka = nacti_pozici(aktualni_kniha)`; clamp na `len(kniha_stranky)-1`.
5. `aktualni_stav = "CTENI"`, `prekreslit_displej = True`.

## Proces 4: Simulátor (bez HW)
1. `POST /api/stisk/<tlacitko>` mutuje stav (stejná FSM logika jako HW).
2. JS front-end po odpovědi znovu načte `GET /screen?t=<timestamp>` (cache-busting).
3. `/screen` renderuje aktuální stav do PNG a vrací `send_file`.

**Pozn. o `dokumentace.md`:** popisuje **zastaralé** API (`nacti_epub_text` bez obrázků, piny 16/20/21, jen 3 moduly, adresát „Gemini") a **neodpovídá** aktuálnímu kódu — nepoužívat jako zdroj pravdy. Aktuální piny jsou 21/26/19, EPUB parser zpracovává i obrázky.

---

# [STATE_AND_STORAGE]

## In-memory stav (globální proměnné)
| Proměnná | Význam |
|---|---|
| `aktualni_stav` | FSM: `"MENU"` \| `"CTENI"` |
| `seznam_knih` | `list[str]` názvů `.epub` ve složce `epuby` |
| `vybrana_kniha_index` | index kurzoru v menu |
| `aktualni_kniha` | cesta k otevřené knize (klíč do `progress.json`) |
| `aktualni_stranka` | index aktuální stránky v `kniha_stranky` |
| `kniha_stranky` | `list[dict]` render-ready stránek (text/obrázek) |
| `prekreslit_displej` | vlajka: vyžádat překreslení v render loopu |
| `probiha_vykreslovani` | zámek proti stisku během e-ink refreshe |
| `posledni_stisk_cas` | timestamp posledního přijatého stisku (SW debounce 2.0 s) |
| `konec_programu` | ukončovací vlajka (dlouhý stisk v dev variantě) |

## Perzistentní úložiště
- **`progress.json`** (JSON, UTF-8, `indent=4`): mapa `{"<cesta_ke_knize>": <index_stranky>}`, např. `{"epuby/Alliances.epub": 280, "epuby/Treason.epub": 113}`. Zapisuje se při každém obrátění stránky (`uloz_pozici`), čte při otevření (`nacti_pozici`). Git-ignored (per-device).
- **`cache/<nazev>.epub.pkl`** (Python `pickle`, binární): serializovaný `kniha_stranky`. Runtime-generovaný, obsahuje i PIL `Image` objekty obrázkových stránek. Cache-aside, bez invalidace/expirace (smazat ručně při změně layoutu/fontu).

## Zdrojová data
- **`epuby/*.epub`**: read-only vstup, git-ignored, indexováno `os.listdir` + filtr `.endswith(".epub")`.

## Rozlišení & render buffery
- Logická plocha: `528×880 px` (na výšku); text area layout: `488×820 px`.
- Produkce: dvě **1-bit** bitmapy (`image_black`, `image_red`) → rotace `ROTATE_90` → `bytearray` do dvoubarevného e-ink.
- Simulátor: jedna **RGB** bitmapa `528×880` → PNG (červená lišta `(220,0,0)`).
- **Žádná** relační DB ani externí cache (Redis apod.) — vše lokální souborový systém.
