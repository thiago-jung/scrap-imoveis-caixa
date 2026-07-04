import re
import json

def extract_properties():
    with open("sodre_sample.html", "r", encoding="utf-8") as f:
        html = f.read()
        
    # Let's find anything that looks like a property description or price
    # e.g. "lance atual", "valor de avaliacao", etc.
    
    # Alternatively, let's just use regex to find all json objects in the nuxt script
    # This is a bit hacky but might reveal keys like 'preco', 'lance', 'cidade', 'bairro'
    
    matches = re.findall(r'"cidade":"([^"]+)"', html, re.IGNORECASE)
    print(f"Cities found: {set(matches)}")
    
    matches2 = re.findall(r'"lance_atual":(\d+)', html, re.IGNORECASE)
    print(f"Lances found: {matches2}")
    
    matches3 = re.findall(r'"lote":"([^"]+)"', html, re.IGNORECASE)
    print(f"Lotes found: {matches3}")
    
    matches4 = re.findall(r'"categoria":"([^"]+)"', html, re.IGNORECASE)
    print(f"Categorias found: {set(matches4)}")
    
if __name__ == "__main__":
    extract_properties()
