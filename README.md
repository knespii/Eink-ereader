# E-ink čtečka EPUB

Čtečka knih na Raspberry Pi Zero W s displejem Waveshare 7.5" HD (tříbarevný,
`epd7in5b_HD`). Ovládá se rotačním kodérem a dvojicí tlačítek na listování.
Python 3.13.

Panel je fyzicky na šířku (880×528), ale čte se na výšku — kreslí se tedy do
528×880 a otočení řeší až ovladač displeje.

## Architektura

Jádrem je pravidlo, že **stav, kreslení a hardware o sobě navzájem nevědí**.
Díky tomu jede simulátor na tomtéž kódu jako čtečka a jde všechno testovat na
desktopu bez Pi.

| Modul | Odpovědnost | Nesmí znát |
|---|---|---|
| `stav.py` | konečný automat (`MENU` / `CTENI`), třída `Ctecka` | PIL, GPIO, Flask, soubory |
| `vykresleni.py` | `vykresli(snimek, fonty)` → dvě bitmapy 528×880 | hardware, rotaci, EPUB |
| `displej.py` | rozhraní `Displej` + `WaveshareDriver` / `DummyDriver` | stav, obsah knih |
| `knihovna.py` | jediné místo s I/O: knihy, pozice, cache, obrázky | stav, kreslení |
| `zpracovani_epub.py` | EPUB → text a odkazy na obrázky | rozvržení, displej |
| `zpracovani_textu.py` | rozvržení do stránek + JSON cache | displej, GPIO |
| `hlavni_ctecka.py` | GPIO + hlavní smyčka | — |
| `simulator.py` | Flask + skládání vrstev do RGB | — |

### Jediný zdroj pravdy

`Ctecka` drží veškerý stav a je thread-safe. Produkční čtečka i simulátor
na ni sahají úplně stejně — liší se jen vstup (GPIO vs. HTTP) a výstup
(e-ink vs. PNG). Vykreslují touž funkcí `vykresli()`, takže **co je vidět
v prohlížeči, sedí na pixel s tím, co jde na displej** (ověřeno testem).

Pro vykreslení si `Ctecka` vydá `snimek()` — zmrazenou kopii stavu. Bez toho
by stisk tlačítka mohl stav změnit uprostřed kreslení.

### Drahá práce mimo callbacky

Rozstránkovat knihu trvá na Pi Zero W kolem 16 sekund. Callbacky gpiozero běží
ve vlastních vláknech, takže **smějí jen sáhnout na stav** — jinak by na dvacet
sekund umrtvily tlačítka.

Řeší to požadavek: `akce()` jen zaeviduje, co se má načíst, hlavní smyčka si to
vyzvedne přes `vyzvedni_pozadavek()`, odparsuje a vrátí přes `dodej_stranky()`.
Mezitím svítí `nacita_se` a na displeji je „Načítám…".

### Ochrana proti ztracenému překreslení

Zápis na e-ink trvá 15–20 s. Kdyby se vlajka překreslení shazovala *po* renderu,
stisk během něj by se ztratil a displej by zamrzl na staré stránce.
`cekej_na_prekresleni()` ji proto shazuje **před** renderem, atomicky pod zámkem.

### Cache stránkování

Výsledek jde do `~/.cache/ctecka/<hash>.json` — čistý JSON, žádný pickle
(ten by vázal cache na verzi Pillow a jeho načtení umí spustit cizí kód).

Klíč je hash z: knihy (jméno + velikost + mtime), fontu a jeho velikosti,
rozlišení, rozestupu řádků a `VERZE_ALGORITMU`. Změna čehokoli z toho cache
zneplatní sama. **Při zásahu do extrakce textu nebo rozvržení zvyš
`VERZE_ALGORITMU`** v `zpracovani_textu.py`, jinak si čtečka podrží staré
stránky.

## Ovládání

| Pin (BCM) | Tlačítko | V menu | Při čtení |
|---|---|---|---|
| 21 | Další | o knihu níž | další stránka |
| 26 | Předchozí | o knihu výš | předchozí stránka |
| 19 | Akce | otevřít knihu | zpět do menu |

Krátký stisk se vyhodnocuje **až při uvolnění**. Držení pinu 19 přes 2 sekundy
čtečku ukončí — a knihu už neotevře, takže vypínání nespustí stránkování.
Zákmity ošetřuje gpiozero (`bounce_time=0.1`).

Menu roluje po stránkách po 13 knihách. Pozice se ukládá do `progress.json`
atomicky (dočasný soubor + `os.replace` + `fsync`), protože čtečka se vypíná
odpojením napájení.

## Instalace

```bash
git clone https://github.com/knespii/E-inkk-ctecka.git
cd E-inkk-ctecka
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Ovladač displeje není na PyPI, nainstaluj ho zvlášť:

```bash
git clone https://github.com/waveshareteam/e-Paper.git /tmp/e-Paper
cp -r /tmp/e-Paper/RaspberryPi_JetsonNano/python/lib/waveshare_epd .
```

Bez něj čtečka nespadne — `vytvor_displej()` sáhne po `DummyDriveru` a poběží
naprázdno. Na Pi je ještě potřeba backend pro piny (`sudo apt install python3-lgpio`)
a povolené SPI (`sudo raspi-config` → Interface Options → SPI).

Ovladač musí používat **hardwarové SPI** (`epdconfig` přes `spidev`) a mít
`spi_writebyte2` — to má aktuální oficiální verze. Starší varianty se software
SPI (soubory `sysfs_software_spi.so`) `spi_writebyte2` nemají; `WaveshareDriver`
se pak vrátí k původnímu bajtovému `display()`, který na Pi Zero W trvá ~90 s.
Ověř to takto:

```bash
.venv/bin/python -c "from waveshare_epd import epdconfig; print(hasattr(epdconfig, 'spi_writebyte2'))"
```

`True` → hotovo. `False` → přeinstaluj ovladač z příkazu výše.

Knihy nakopíruj do `epuby/` (složka je v `.gitignore`).

## Spuštění

```bash
.venv/bin/python hlavni_ctecka.py     # na Pi
.venv/bin/python simulator.py         # simulátor na http://127.0.0.1:5000
```

## Automatické spuštění po zapnutí

Aby čtečka naskočila sama po každém připojení Pi k napájení, nainstaluj
systemd službu:

```bash
./install-sluzba.sh
```

Skript doplní do [`ctecka.service`](ctecka.service) aktuálního uživatele a cestu,
zaregistruje jednotku a rovnou ji spustí. Od té chvíle běží čtečka na pozadí:

```bash
sudo systemctl status ctecka      # běží?
journalctl -u ctecka -f           # živý log
sudo systemctl disable --now ctecka   # zrušit autostart
```

Čtečka nemá tlačítko na vypnutí — služba běží pořád a vypíná se odpojením
napájení. E-ink drží obraz i bez proudu, takže se tím nic neztratí; jediné, oč
přijdeš, je uspání panelu přes `epd.sleep()`. Po pádu (nenulový návrat) služba
startuje znovu.

### Navázání tam, kde jsi skončil

E-ink drží obraz i bez napájení, čehož čtečka využívá. Poslední zobrazený stav
(kniha a stránka, nebo pozice v menu) se ukládá do `posledni_stav.json` a po
zapnutí se obnoví **bez překreslení** — na displeji je pořád tvoje poslední
stránka, nic nebliká a čtečka pokračuje až po stisku tlačítka.

Funguje to, když čtečku vypínáš odpojením napájení na nějaké stránce (typický
scénář). Kdyby se panel mezitím smazal nebo byla otevřená kniha smazaná,
displej se při startu jednou překreslí, aby odpovídal skutečnosti.

Služba běží pod tvým uživatelem, ne pod rootem — potřebuje tedy přístup k GPIO
a SPI. Když v logu uvidíš chybu oprávnění, přidej se do skupin a restartuj:

```bash
sudo usermod -aG gpio,spi "$USER"
```

## Testy

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Testy nepotřebují hardware — gpiozero jede na mock pinech, takže se dá
otestovat i vteřinové držení tlačítka v kodéru. Skutečný `progress.json` ani cache
se přitom nedotknou (hlídají to autouse fixtury v `tests/conftest.py`).
Testy nad reálnou knihou se bez `epuby/` přeskočí.

## Známá omezení

- **Obálky se nezobrazují.** Titulní strany bývají `<svg><image xlink:href>`,
  a parser bere jen `<img>`.
- **Cache se neuklízí.** Soubory pro staré fonty a verze algoritmu zůstávají
  ležet (~0,75 MB na knihu a konfiguraci).
- **Dlouhá slova se nedělí.** Slovo širší než řádek (např. URL) přeteče.
- **Otočení stránky trvá ~10 s** a s tím se nedá nic dělat — tolik zabere
  budicí křivka tříbarevného panelu. Částečné překreslení (jako u čteček
  Kindle) tenhle panel neumí, protože pohyb červeného pigmentu vyžaduje plnou
  křivku přes celý panel.
- **Čištění panelu je vypnuté** (`PERIODA_CISTENI = 0`). Panel jede při každém
  `display()` plnou křivkou, takže obraz přepíše celý a duchy skoro nenechává.
  Kdyby se přesto objevili, nastav v `hlavni_ctecka.py` třeba 20.
