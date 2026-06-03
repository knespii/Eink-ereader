def zformatuj_pro_displej(text, font, max_sirka_px):
    odstavce = text.split("\n")
    zformatovane_radky = []

    for odstavec in odstavce:
        if not odstavec.strip():
            zformatovane_radky.append("")
            continue

        slova = odstavec.split(" ")
        aktualni_radek = ""

        for slovo in slova:
            test_radek = aktualni_radek + slovo + " "
            sirka_px = font.getlength(test_radek)

            if sirka_px <= max_sirka_px:
                aktualni_radek = test_radek
            else:
                zformatovane_radky.append(aktualni_radek.strip())
                aktualni_radek = slovo + " "

        if aktualni_radek:
            zformatovane_radky.append(aktualni_radek.strip())
        zformatovane_radky.append("")

    return zformatovane_radky


def rozdel_na_stranky(radky, font, max_vyska_px, rozestup_radku=5):
    ascent, descent = font.getmetrics()
    vyska_radku = ascent + descent + rozestup_radku

    stranky = []
    aktualni_stranka = []
    aktualni_vyska = 0

    for radek in radky:
        if aktualni_vyska + vyska_radku > max_vyska_px:
            stranky.append(aktualni_stranka)
            aktualni_stranka = [radek]
            aktualni_vyska = vyska_radku
        else:
            aktualni_stranka.append(radek)
            aktualni_vyska += vyska_radku

    if aktualni_stranka:
        stranky.append(aktualni_stranka)

    return stranky
