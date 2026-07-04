from scrapers.leiloes_judiciais import LeiloesJudiciaisScraper
import json

def test_judiciais():
    # Cidades alvo para o teste (vamos pegar umas maiores ou comuns para garantir que acha algo)
    cidades = ["São Paulo", "Ribeirão Preto", "Guarulhos", "Campinas"]
    
    scraper = LeiloesJudiciaisScraper(cidades)
    imoveis = scraper.raspar()
    
    for imovel in imoveis[:5]:
        print(json.dumps(imovel, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    test_judiciais()
