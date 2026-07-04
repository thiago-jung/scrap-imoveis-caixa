import requests
import json

def test_api():
    # Let's try some common paths for property search APIs
    urls_to_try = [
        "https://prd-api.sodresantoro.com.br/imoveis",
        "https://prd-api.sodresantoro.com.br/lotes?categoria=imoveis",
        "https://prd-api.sodresantoro.com.br/pesquisa?q=imoveis",
        "https://prd-api.sodresantoro.com.br/leiloes/imoveis"
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }
    
    for url in urls_to_try:
        try:
            print(f"Trying {url}...")
            r = requests.get(url, headers=headers, timeout=5)
            print(f"  Status: {r.status_code}")
            if r.status_code == 200:
                try:
                    data = r.json()
                    print(f"  Data keys: {data.keys()}")
                except:
                    print(f"  Response (text): {r.text[:100]}")
        except Exception as e:
            print(f"  Error: {e}")

if __name__ == "__main__":
    test_api()
