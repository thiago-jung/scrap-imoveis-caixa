import os
import sys

# Add current dir to path to import scrapers
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from bs4 import BeautifulSoup
from scrapers.mega_leiloes import MegaLeiloesScraper
import json

def debug_parse():
    with open("mega_sample.html", "r", encoding="utf-8") as f:
        html = f.read()
        
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all("div", class_="card")
    print(f"Cards found: {len(cards)}")
    
    scraper = MegaLeiloesScraper(cidades_alvo=[])
    
    for card in cards[:2]:
        try:
            imovel = scraper._parse_card(card)
            print(json.dumps(imovel, indent=2, ensure_ascii=False))
        except Exception as e:
            print("Error parsing card:", e)

if __name__ == "__main__":
    debug_parse()
