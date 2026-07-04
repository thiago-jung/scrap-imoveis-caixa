from typing import TypedDict, Optional
from datetime import datetime
import abc
import unicodedata

def normalizar(texto: str) -> str:
    if not texto: return ""
    nfkd = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return sem_acento.upper()

class ImovelPadronizado(TypedDict):
    id: str
    origem: str  # e.g., "Caixa", "Mega Leilões"
    cidade: str
    bairro: str
    endereco: str
    preco: float
    avaliacao: float
    desconto: float
    link: str
    modalidade: str  # e.g., "Venda Direta", "1ª Praça", "2ª Praça"
    descricao: str
    
class BaseScraper(abc.ABC):
    def __init__(self, cidades_alvo: list[str]):
        """
        cidades_alvo: Lista de cidades para filtrar (tudo em maiúsculo, sem acento, ex: ['PORTO ALEGRE', 'CANOAS'])
        Se for vazio, pode raspar tudo (ou pelo menos o que a plataforma permitir).
        """
        self.cidades_alvo = cidades_alvo

    @abc.abstractmethod
    def raspar(self) -> list[ImovelPadronizado]:
        """
        Executa a extração no site alvo e retorna a lista de imóveis.
        Deve lidar com paginação e eventuais proteções antibot da plataforma.
        """
        pass
