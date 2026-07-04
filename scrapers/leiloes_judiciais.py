import re
import logging
import requests
from bs4 import BeautifulSoup
from typing import List, Optional

from scrapers.base import BaseScraper, ImovelPadronizado, normalizar

log = logging.getLogger(__name__)

class LeiloesJudiciaisScraper(BaseScraper):
    def __init__(self, cidades_alvo: list[str]):
        super().__init__(cidades_alvo)
        self.base_url = "https://www.leiloesjudiciais.com.br"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        })

    def raspar(self) -> List[ImovelPadronizado]:
        cidades_alvo_norm = [normalizar(c) for c in self.cidades_alvo]
        imoveis_filtrados = []
        pagina = 1
        
        while True:
            url = f"{self.base_url}/imoveis?pagina={pagina}"
            log.info(f"Leilões Judiciais: Baixando página {pagina} - {url}")
            
            try:
                resp = self.session.get(url, timeout=15)
                resp.raise_for_status()
            except Exception as e:
                log.error(f"Leilões Judiciais: Erro ao baixar página {pagina}: {e}")
                break
                
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.find_all('div', class_='base-card')
            
            if not cards:
                log.info(f"Fim da paginação (nenhum card na página {pagina})")
                break
                
            for card in cards:
                imovel = self._parse_card(card)
                if not imovel:
                    continue
                    
                # Filtro de cidade
                cidade_imovel = normalizar(imovel["cidade"])
                if not self.cidades_alvo or any(c in cidade_imovel for c in cidades_alvo_norm):
                    imoveis_filtrados.append(imovel)
            
            # Verifica se há próxima página
            pagination = soup.find('ul', class_=re.compile("pagination"))
            tem_proxima = False
            if pagination:
                links = pagination.find_all('a', href=True)
                for link in links:
                    if f"pagina={pagina+1}" in link['href']:
                        tem_proxima = True
                        break
                        
            if not tem_proxima:
                log.info(f"Fim da paginação (última página: {pagina})")
                break
                
            pagina += 1
            
        log.info(f"Total de imóveis filtrados encontrados no Leilões Judiciais: {len(imoveis_filtrados)}")
        return imoveis_filtrados

    def _parse_card(self, card) -> Optional[ImovelPadronizado]:
        try:
            link_el = card.find('a', href=True)
            link = link_el['href'] if link_el else ""
            if link and not link.startswith('http'):
                link = self.base_url + link
                
            text_parts = [t.strip() for t in card.stripped_strings if t.strip()]
            if not text_parts:
                return None
                
            # Exemplo de text_parts:
            # ['#95911', 'Aberto para Lance', '4608', '0', 'Fazenda São Bento...', 'Alto Parnaíba/MA', 'Avaliação', 'R$ 160.000.000,00', 'Lance mínimo', 'R$ 160.000.000,00']
            
            id_str = text_parts[0]
            
            # Procurar endereço e cidade (geralmente partes 4 e 5)
            # Mas vamos ser mais resilientes buscando por padrões ou pegando o texto longo antes de 'Avaliação'
            
            avaliacao = 0.0
            preco = 0.0
            endereco = ""
            cidade = ""
            
            for i, part in enumerate(text_parts):
                if 'Avalia' in part:
                    if i + 1 < len(text_parts):
                        avaliacao = self._parse_valor_brl(text_parts[i+1])
                elif 'Lance' in part and 'Atual' not in part and part != 'Aberto para Lance':
                    # Lance mínimo ou 1º Leilão
                    if i + 1 < len(text_parts) and preco == 0.0:
                        preco = self._parse_valor_brl(text_parts[i+1])
            
            # Se não achou preço no Lance, tenta Lance Atual
            if preco == 0.0:
                for i, part in enumerate(text_parts):
                    if 'Lance Atual' in part:
                        if i + 1 < len(text_parts):
                            preco = self._parse_valor_brl(text_parts[i+1])
                            
            # Avaliação fallback
            if avaliacao == 0.0:
                avaliacao = preco
                
            desconto = 0.0
            if avaliacao > 0 and preco > 0 and avaliacao > preco:
                desconto = 100 * (1 - (preco / avaliacao))
                
            # Endereço e Cidade
            # A cidade costuma ter uma barra (ex: São Paulo/SP)
            for part in text_parts:
                if len(part) > 3 and '/' in part[-4:]:
                    cidade_str = part.split('/')[0].strip()
                    # Pode vir algo como "Terreno no Jardim Krahe, em Viamão"
                    # Vamos pegar o último trecho depois de vírgula ou hífen
                    if ',' in cidade_str:
                        cidade_str = cidade_str.split(',')[-1].strip()
                    elif '-' in cidade_str:
                        cidade_str = cidade_str.split('-')[-1].strip()
                    
                    if cidade_str.lower().startswith('em '):
                        cidade_str = cidade_str[3:].strip()
                    elif cidade_str.lower().startswith('no '):
                        cidade_str = cidade_str[3:].strip()
                    elif cidade_str.lower().startswith('na '):
                        cidade_str = cidade_str[3:].strip()
                        
                    cidade = cidade_str
                    break
                    
            # A descrição costuma ser a string mais longa
            long_strings = [p for p in text_parts if len(p) > 20 and not p.startswith('R$')]
            if long_strings:
                endereco = long_strings[0]
                
            return {
                "id": id_str,
                "origem": "Leilões Judiciais",
                "cidade": cidade,
                "bairro": "", # Bairro não é explícito no card
                "endereco": endereco,
                "preco": preco,
                "avaliacao": avaliacao,
                "desconto": desconto,
                "link": link,
                "modalidade": "Judicial",
                "descricao": endereco
            }
        except Exception as e:
            log.debug(f"Erro ao parsear card Leilões Judiciais: {e}")
            return None

    def _parse_valor_brl(self, texto: str) -> float:
        import re
        match = re.search(r'R\$\s*([\d\.,]+)', texto)
        if not match:
            return 0.0
        val_str = match.group(1).replace('.', '').replace(',', '.')
        try:
            return float(val_str)
        except ValueError:
            return 0.0
