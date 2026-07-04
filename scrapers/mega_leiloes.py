import requests
from bs4 import BeautifulSoup
import re
import logging
from typing import List, Optional
from scrapers.base import BaseScraper, ImovelPadronizado, normalizar

log = logging.getLogger(__name__)

class MegaLeiloesScraper(BaseScraper):
    def __init__(self, cidades_alvo: list[str]):
        super().__init__(cidades_alvo)
        self.base_url = "https://www.megaleiloes.com.br/imoveis"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        
    def _parse_valor_brl(self, texto: str) -> float:
        if not texto: return 0.0
        # "R$ 49.395,34" -> 49395.34
        limpo = re.sub(r'[^\d,]', '', texto)
        limpo = limpo.replace(',', '.')
        try:
            return float(limpo)
        except ValueError:
            return 0.0
            
    def _parse_desconto(self, texto: str) -> float:
        if not texto: return 0.0
        # "40%" -> 40.0
        limpo = re.sub(r'[^\d]', '', texto)
        try:
            return float(limpo)
        except ValueError:
            return 0.0

    def raspar(self) -> List[ImovelPadronizado]:
        imoveis = []
        pagina = 1
        
        while True:
            url = f"{self.base_url}?pagina={pagina}"
            log.info(f"Mega Leilões: Baixando página {pagina} - {url}")
            try:
                resp = requests.get(url, headers=self.headers, timeout=30)
                resp.raise_for_status()
            except Exception as e:
                log.error(f"Erro ao acessar {url}: {e}")
                break
                
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.find_all("div", class_="card")
            
            if not cards:
                log.info(f"Fim das páginas no Mega Leilões na página {pagina}")
                break
                
            for card in cards:
                try:
                    imovel = self._parse_card(card)
                    if imovel:
                        cidade_imovel = normalizar(imovel['cidade'])
                        cidades_alvo_norm = [normalizar(c) for c in self.cidades_alvo]
                        # Se houver filtro de cidades, checa.
                        if not self.cidades_alvo or any(c in cidade_imovel for c in cidades_alvo_norm):
                            imoveis.append(imovel)
                except Exception as e:
                    log.warning(f"Erro ao fazer o parse de um card no Mega Leilões: {e}")
            
            # Checar se existe botão/link de próxima página
            # Geralmente é um `li class="next"` ou `a[data-page]` 
            next_page = soup.find("li", class_="next")
            if not next_page or "disabled" in next_page.get("class", []):
                log.info(f"Fim da paginação (última página: {pagina})")
                break
                
            pagina += 1
            
        return imoveis

    def _parse_card(self, card) -> Optional[ImovelPadronizado]:
        link_el = card.find("a", href=True)
        if not link_el:
            return None
        link = link_el["href"]
        
        title_el = card.find(class_="card-title")
        descricao = title_el.text.strip() if title_el else ""
        
        id_el = card.find(class_=re.compile("card-number"))
        id_str = id_el.text.strip() if id_el else ""
        
        locality_el = card.find(class_="card-locality")
        cidade = ""
        estado = ""
        if locality_el:
            partes = locality_el.text.split(",")
            cidade = partes[0].strip()
            if len(partes) > 1:
                estado = partes[1].strip()
                
        price_el = card.find(class_="card-price")
        preco = self._parse_valor_brl(price_el.text) if price_el else 0.0
        
        # Avaliacao = 1ª Praça value (geralmente)
        avaliacao = 0.0
        first_instance = card.find(class_=re.compile("instance.*first"))
        if first_instance:
            val_el = first_instance.find(class_="card-instance-value")
            if val_el:
                avaliacao = self._parse_valor_brl(val_el.text)
                
        if avaliacao == 0.0:
            avaliacao = preco # fallback se não achar
            
        desconto_el = card.find(class_="value")
        desconto = self._parse_desconto(desconto_el.text) if desconto_el else 0.0
        
        if desconto == 0.0 and avaliacao > 0 and preco > 0 and avaliacao > preco:
            desconto = 100 * (1 - (preco / avaliacao))
            
        modalidade_el = card.find(class_="card-instance-title")
        modalidade = modalidade_el.text.strip().replace('\\n', ' ') if modalidade_el else "Leilão"
        
        # Endereço não é explícito no card, geralmente é a descrição
        endereco = descricao

        return ImovelPadronizado(
            id=id_str,
            origem="Mega Leilões",
            cidade=cidade,
            bairro="", # Bairro não vem no card diretamente
            endereco=endereco,
            preco=preco,
            avaliacao=avaliacao,
            desconto=desconto,
            link=link,
            modalidade=modalidade,
            descricao=descricao
        )
