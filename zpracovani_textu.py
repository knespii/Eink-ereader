def zformatuj_a_rozdel(obsah, font, max_sirka_px, max_vyska_px, rozestup_radku=5):
    stranky = []
    aktualni_stranka_radky = []
    aktualni_vyska = 0
    
    ascent, descent = font.getmetrics()
    vyska_radku = ascent + descent + rozestup_radku

    # --- VYSOKOVÝKONNOSTNÍ CACHE PRO PI ZERO W ---
    word_cache = {}
    space_width = font.getlength(" ")

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
                # Rozdělíme na slova a vyčistíme případné vícenásobné mezery
                slova = [s for s in odstavec.split(" ") if s]
                if not slova:
                    continue
                
                aktualni_radky_slova = []
                aktualni_sirka = 0
                
                for slovo in slova:
                    # Pokud slovo ještě neznáme, změříme ho (volá se jen jednou za celou knihu)
                    if slovo not in word_cache:
                        word_cache[slovo] = font.getlength(slovo)
                    sirka_slova = word_cache[slovo]
                    
                    # Vypočítáme potřebnou šířku (pokud už na řádku slovo je, přičteme mezeru)
                    potrebna_mezera = space_width if aktualni_radky_slova else 0
                    
                    if aktualni_sirka + potrebna_mezera + sirka_slova <= max_sirka_px:
                        # Slovo se vejde, přidáme ho na aktuální řádek
                        aktualni_radky_slova.append(slovo)
                        aktualni_sirka += potrebna_mezera + sirka_slova
                    else:
                        # Slovo se nevejde, zabalíme dosavadní řádek do textu
                        if aktualni_radky_slova:
                            radek_text = " ".join(aktualni_radky_slova)
                            if aktualni_vyska + vyska_radku > max_vyska_px:
                                stranky.append({"typ": "text", "obsah": aktualni_stranka_radky})
                                aktualni_stranka_radky = [radek_text]
                                aktualni_vyska = vyska_radku
                            else:
                                aktualni_stranka_radky.append(radek_text)
                                aktualni_vyska += vyska_radku
                        
                        # Nový řádek začíná aktuálním slovem
                        aktualni_radky_slova = [slovo]
                        aktualni_sirka = sirka_slova

                # Dojetí úplně posledního řádku v odstavci
                if aktualni_radky_slova:
                    radek_text = " ".join(aktualni_radky_slova)
                    if aktualni_vyska + vyska_radku > max_vyska_px:
                        stranky.append({"typ": "text", "obsah": aktualni_stranka_radky})
                        aktualni_stranka_radky = [radek_text]
                        aktualni_vyska = vyska_radku
                    else:
                        aktualni_stranka_radky.append(radek_text)
                        aktualni_vyska += vyska_radku
            
            # Konec bloku odstavců - přidáme prázdný řádek pro lepší čitelnost
            if aktualni_vyska + vyska_radku <= max_vyska_px:
                 aktualni_stranka_radky.append("")
                 aktualni_vyska += vyska_radku

    if aktualni_stranka_radky:
        stranky.append({"typ": "text", "obsah": aktualni_stranka_radky})

    return stranky