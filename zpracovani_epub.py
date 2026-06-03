import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from PIL import Image
import io
import warnings

warnings.filterwarnings('ignore')

def nacti_epub_obsah(cesta_k_souboru, max_sirka=880, max_vyska=488):
    try:
        kniha = epub.read_epub(cesta_k_souboru)
        obsah = []

        for polozka in kniha.get_items():
            if polozka.get_type() == ebooklib.ITEM_DOCUMENT:
                soup = BeautifulSoup(polozka.get_content(), 'html.parser')
                
                # Procházíme odstavce a obrázky v pořadí, v jakém jsou v knize
                for element in soup.find_all(['p', 'div', 'img']):
                    if element.name in ['p', 'div']:
                        text = element.get_text(strip=True)
                        if text:
                            obsah.append({"typ": "text", "hodnota": text})
                            
                    elif element.name == 'img':
                        src = element.get('src')
                        if src:
                            # Najdeme binární data obrázku uvnitř EPUBu podle jména souboru
                            img_item = None
                            nazev_souboru = src.split('/')[-1]
                            for item in kniha.get_items():
                                if item.get_type() == ebooklib.ITEM_IMAGE and item.file_name.endswith(nazev_souboru):
                                    img_item = item
                                    break
                            
                            if img_item:
                                # Převedeme obrázek na černo-bílý e-ink formát
                                img = Image.open(io.BytesIO(img_item.get_content()))
                                img.thumbnail((max_sirka, max_vyska))
                                img_eink = img.convert('1')
                                obsah.append({"typ": "obrazek", "hodnota": img_eink})
                                
        return obsah
    except Exception as e:
        print(f"Chyba při čtení EPUBu: {e}")
        return []