import logging
from scrapers.mega_leiloes import MegaLeiloesScraper
import json

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def test_mega_leiloes_scraper():
    print("Iniciando scraper do Mega Leilões...")
    # Filtro apenas para São Paulo para testar
    scraper = MegaLeiloesScraper(cidades_alvo=["SÃO PAULO", "CATANDUVA", "OLÍMPIA"])
    
    # Vamos rodar apenas para pegar os resultados da página 1.
    # O método raspar() tem paginação, então pra teste rápido vou 
    # apenas verificar o retorno. No test, ele vai rodar todas, mas como não temos muitas cidades, tá OK.
    # Para evitar demorar muito no teste, vou injetar uma URL com filtro da cidade
    
    # O Mega Leilões tem URL própria para cidades, mas o scraper base raspa a geral e filtra.
    imoveis = scraper.raspar()
    
    print(f"\nTotal de imóveis filtrados encontrados: {len(imoveis)}")
    for imovel in imoveis[:5]:
        print(json.dumps(imovel, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    test_mega_leiloes_scraper()
