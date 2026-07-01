"""
Scraper diário de imóveis em leilão/venda da Caixa Econômica Federal.

Fonte: https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_{UF}.csv
(mesmo arquivo gerado pelo botão "Baixe a lista completa de imóveis" do site oficial)

O script:
  1. Baixa o CSV de cada UF configurada
  2. Filtra por cidade (default: Região Metropolitana de Porto Alegre)
  3. Salva um snapshot datado em disco (histórico)
  4. Compara com o snapshot anterior (novos/removidos)
  5. Gera um relatório HTML estático (index.html) pra abrir no navegador

Uso:
    python caixa_leiloes_scraper.py --ufs RS SP --outdir ./data

Agendamento sugerido:
    - cron:            0 7 * * *  python /path/caixa_leiloes_scraper.py --ufs RS
    - GitHub Actions:  schedule com cron diário (ver exemplo no final do arquivo)
"""

import argparse
import csv
import io
import logging
import os
import unicodedata
from datetime import datetime
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_{uf}.csv"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# Região Metropolitana de Porto Alegre (principais cidades).
# Edite essa lista à vontade -- é só o filtro padrão.
CIDADES_RMPA = [
    "PORTO ALEGRE",
    "CANOAS",
    "ALVORADA",
    "VIAMAO",
    "CACHOEIRINHA",
    "GRAVATAI",
    "GUAIBA",
    "ESTEIO",
    "SAPUCAIA DO SUL",
    "NOVO HAMBURGO",
    "SAO LEOPOLDO",
    "ELDORADO DO SUL",
]


def normalizar(texto: str) -> str:
    """Remove acentos e deixa em maiúsculas, pra comparar cidade sem depender de encoding."""
    nfkd = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return sem_acento.upper()

# Coluna que identifica unicamente o imóvel dentro do CSV.
# O nome exato pode variar levemente (ex: "N° do imóvel" vs "Nº do imóvel");
# ajuste aqui se o parsing reclamar na primeira execução real.
ID_COLUMN_CANDIDATES = ["N° do imóvel", "Nº do imóvel", "N do imovel", "N° do Imóvel"]


def baixar_csv(uf: str) -> bytes:
    url = BASE_URL.format(uf=uf.upper())
    log.info("Baixando lista de %s: %s", uf, url)
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    return resp.content


def parsear_csv(conteudo: bytes) -> list[dict]:
    # Sites do governo BR costumam usar latin-1 e ';' como separador.
    texto = conteudo.decode("latin-1", errors="replace")
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(texto[:2000], delimiters=";,")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    leitor = csv.DictReader(io.StringIO(texto), dialect=dialect)
    linhas = [row for row in leitor if any(v.strip() for v in row.values() if v)]
    log.info("Parseadas %d linhas", len(linhas))
    return linhas


def filtrar_por_cidade(linhas: list[dict], cidades: list[str]) -> list[dict]:
    """Mantém só as linhas cujo texto (endereço/cidade/etc.) contém alguma das cidades.

    Não depende de saber o nome exato da coluna de cidade: concatena a linha
    inteira e procura a substring, o que é robusto a variações de cabeçalho.
    """
    cidades_norm = [normalizar(c) for c in cidades]
    filtradas = []
    for row in linhas:
        texto_linha = normalizar(" | ".join(str(v) for v in row.values() if v))
        if any(cidade in texto_linha for cidade in cidades_norm):
            filtradas.append(row)
    log.info("Filtro de cidade: %d de %d linhas mantidas", len(filtradas), len(linhas))
    return filtradas


def achar_coluna_id(linhas: list[dict]) -> str:
    if not linhas:
        return ""
    colunas = linhas[0].keys()
    for candidata in ID_COLUMN_CANDIDATES:
        if candidata in colunas:
            return candidata
    # fallback: primeira coluna
    primeira = next(iter(colunas))
    log.warning("Coluna de ID não encontrada nos candidatos, usando fallback: %r", primeira)
    return primeira


def salvar_snapshot(linhas: list[dict], uf: str, outdir: Path) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    data_str = datetime.now().strftime("%Y-%m-%d")
    caminho = outdir / f"{uf.upper()}_{data_str}.csv"
    if linhas:
        with caminho.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
            writer.writeheader()
            writer.writerows(linhas)
    log.info("Snapshot salvo em %s", caminho)
    return caminho


def carregar_snapshot_anterior(uf: str, outdir: Path, data_atual: str) -> list[dict] | None:
    arquivos = sorted(outdir.glob(f"{uf.upper()}_*.csv"))
    anteriores = [a for a in arquivos if a.stem != f"{uf.upper()}_{data_atual}"]
    if not anteriores:
        return None
    ultimo = anteriores[-1]
    log.info("Comparando com snapshot anterior: %s", ultimo)
    with ultimo.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def comparar(atuais: list[dict], anteriores: list[dict] | None, id_col: str):
    if anteriores is None:
        return atuais, []  # tudo é "novo" na primeira execução
    ids_atuais = {row.get(id_col) for row in atuais}
    ids_anteriores = {row.get(id_col) for row in anteriores}
    novos_ids = ids_atuais - ids_anteriores
    removidos_ids = ids_anteriores - ids_atuais
    novos = [row for row in atuais if row.get(id_col) in novos_ids]
    removidos = [row for row in anteriores if row.get(id_col) in removidos_ids]
    return novos, removidos


def _celula_html(valor: str) -> str:
    """Formata uma célula: se parecer uma URL, vira link clicável."""
    texto = (valor or "").strip()
    if texto.startswith("http://") or texto.startswith("https://"):
        return f'<a href="{texto}" target="_blank" rel="noopener">abrir</a>'
    return texto


def _tabela_html(linhas: list[dict], destacar: bool = False) -> str:
    if not linhas:
        return "<p class='vazio'>Nenhum imóvel.</p>"
    colunas = list(linhas[0].keys())
    thead = "".join(f"<th>{c}</th>" for c in colunas)
    linhas_html = []
    for row in linhas:
        tds = "".join(f"<td>{_celula_html(row.get(c, ''))}</td>" for c in colunas)
        classe = ' class="novo"' if destacar else ""
        linhas_html.append(f"<tr{classe}>{tds}</tr>")
    return f"""
    <div class="tabela-wrap">
    <table>
      <thead><tr>{thead}</tr></thead>
      <tbody>{''.join(linhas_html)}</tbody>
    </table>
    </div>
    """


def gerar_html(
    uf: str,
    data_atual: str,
    novos: list[dict],
    removidos: list[dict],
    todas: list[dict],
    cidades: list[str] | None,
    caminho_saida: Path,
):
    filtro_txt = ", ".join(cidades) if cidades else "sem filtro (todas as cidades)"
    html = f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Leilões Caixa - {uf} - {data_atual}</title>
<style>
  :root {{
    --bg: #0f1115; --panel: #171a21; --border: #262a35;
    --text: #e6e8ec; --muted: #9099a8; --accent: #4f8cff; --novo: #1f3a2a; --novo-border: #2f6b45;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 32px 24px; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .subtitulo {{ color: var(--muted); font-size: 14px; margin-bottom: 24px; }}
  .stats {{ display: flex; gap: 12px; margin-bottom: 28px; flex-wrap: wrap; }}
  .stat {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 14px 18px; min-width: 140px;
  }}
  .stat .num {{ font-size: 24px; font-weight: 600; }}
  .stat .label {{ font-size: 12px; color: var(--muted); margin-top: 2px; }}
  section {{ margin-bottom: 36px; }}
  h2 {{ font-size: 16px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }}
  .tabela-wrap {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ padding: 8px 10px; text-align: left; white-space: nowrap; border-bottom: 1px solid var(--border); }}
  th {{ background: var(--panel); position: sticky; top: 0; color: var(--muted); font-weight: 600; }}
  tr:hover td {{ background: #1c2029; }}
  tr.novo td {{ background: var(--novo); }}
  tr.novo:hover td {{ background: var(--novo-border); }}
  a {{ color: var(--accent); }}
  .vazio {{ color: var(--muted); font-style: italic; }}
  details summary {{ cursor: pointer; color: var(--accent); margin-bottom: 12px; }}
</style>
</head>
<body>
<div class="container">
  <h1>Leilões Caixa — {uf}</h1>
  <div class="subtitulo">Atualizado em {data_atual} · Filtro de cidade: {filtro_txt}</div>

  <div class="stats">
    <div class="stat"><div class="num">{len(todas)}</div><div class="label">Total ativos hoje</div></div>
    <div class="stat"><div class="num">{len(novos)}</div><div class="label">Novos hoje</div></div>
    <div class="stat"><div class="num">{len(removidos)}</div><div class="label">Saíram da lista</div></div>
  </div>

  <section>
    <h2>Novos hoje ({len(novos)})</h2>
    {_tabela_html(novos, destacar=True)}
  </section>

  <section>
    <h2>Saíram da lista desde ontem ({len(removidos)})</h2>
    {_tabela_html(removidos)}
  </section>

  <section>
    <details>
      <summary>Ver todos os {len(todas)} imóveis ativos filtrados</summary>
      {_tabela_html(todas)}
    </details>
  </section>
</div>
</body>
</html>"""
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    caminho_saida.write_text(html, encoding="utf-8")
    log.info("Relatório HTML salvo em %s", caminho_saida)


def processar_uf(uf: str, outdir: Path, cidades: list[str] | None = None, html_out: Path | None = None):
    conteudo = baixar_csv(uf)
    linhas = parsear_csv(conteudo)
    if not linhas:
        log.warning("Nenhuma linha encontrada para %s (site pode ter mudado o formato).", uf)
        return

    if cidades:
        linhas = filtrar_por_cidade(linhas, cidades)
        if not linhas:
            log.warning(
                "Filtro de cidade não retornou nada -- confira se os nomes em "
                "CIDADES_RMPA batem com o texto real do CSV (rode sem --cidades pra conferir)."
            )
            return

    id_col = achar_coluna_id(linhas)
    data_atual = datetime.now().strftime("%Y-%m-%d")
    anteriores = carregar_snapshot_anterior(uf, outdir, data_atual)
    salvar_snapshot(linhas, uf, outdir)

    novos, removidos = comparar(linhas, anteriores, id_col)
    log.info("%s: %d novos, %d removidos (total atual: %d)", uf, len(novos), len(removidos), len(linhas))

    if html_out:
        gerar_html(uf, data_atual, novos, removidos, linhas, cidades, html_out)


def main():
    parser = argparse.ArgumentParser(description="Scraper diário de leilões Caixa")
    parser.add_argument("--ufs", nargs="+", default=["RS"], help="Ex: RS SP RJ (default: RS)")
    parser.add_argument("--outdir", default="./data", help="Diretório de snapshots")
    parser.add_argument(
        "--cidades",
        nargs="*",
        default=CIDADES_RMPA,
        help="Cidades para filtrar (default: Região Metropolitana de Porto Alegre). "
        "Passe --cidades sem valores pra desativar o filtro.",
    )
    parser.add_argument(
        "--html-out",
        default="index.html",
        help="Caminho do relatório HTML gerado (default: index.html na raiz)",
    )
    args = parser.parse_args()

    outdir = Path(args.outdir)
    cidades = args.cidades if args.cidades else None
    html_out = Path(args.html_out) if args.html_out else None
    for uf in args.ufs:
        try:
            processar_uf(uf, outdir, cidades=cidades, html_out=html_out)
        except requests.RequestException as e:
            log.error("Erro ao processar %s: %s", uf, e)


if __name__ == "__main__":
    main()
