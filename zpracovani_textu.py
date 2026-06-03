def zformatuj_a_rozdel(obsah, font, max_sirka_px, max_vyska_px, rozestup_radku=5):
    stranky = []
    aktualni_stranka_radky = []
    aktualni_vyska = 0
    
    ascent, descent = font.getmetrics()
    vyska_radku = ascent + descent + rozestup_radku

    for polozka in obsah:
        if polozka["typ"] == "obrazek":
            # Pokud už máme rozepsaný text na aktuální stránce, uložíme ho
            if aktualni_stranka_radky:
                stranky.append({"typ": "text", "obsah": aktualni_stranka_radky})
                aktualni_stranka_radky = []
                aktualni_vyska = 0
                
            # Obrázek dostane vlastní samostatnou stránku
            stranky.append({"typ": "obrazek", "obsah": polozka["hodnota"]})
        
        elif polozka["typ"] == "text":
            odstavce = polozka["hodnota"].split("\n")
            for odstavec in odstavce:
                slova = odstavec.split(" ")
                aktualni_radek = ""
                
                for slovo in slova:
                    test_radek = aktualni_radek + slovo + " "
                    sirka_px = font.getlength(test_radek)

                    if sirka_px <= max_sirka_px:
                        aktualni_radek = test_radek
                    else:
                        if aktualni_vyska + vyska_radku > max_vyska_px:
                            stranky.append({"typ": "text", "obsah": aktualni_stranka_radky})
                            aktualni_stranka_radky = [aktualni_radek.strip()]
                            aktualni_vyska = vyska_radku
                        else:
                            aktualni_stranka_radky.append(aktualni_radek.strip())
                            aktualni_vyska += vyska_radku
                        aktualni_radek = slovo + " "

                if aktualni_radek:
                    if aktualni_vyska + vyska_radku > max_vyska_px:
                        stranky.append({"typ": "text", "obsah": aktualni_stranka_radky})
                        aktualni_stranka_radky = [aktualni_radek.strip()]
                        aktualni_vyska = vyska_radku
                    else:
                        aktualni_stranka_radky.append(aktualni_radek.strip())
                        aktualni_vyska += vyska_radku
            
            # Konec odstavce - přidáme prázdný řádek pro lepší čitelnost
            if aktualni_vyska + vyska_radku <= max_vyska_px:
                 aktualni_stranka_radky.append("")
                 aktualni_vyska += vyska_radku

    if aktualni_stranka_radky:
        stranky.append({"typ": "text", "obsah": aktualni_stranka_radky})

    return stranky