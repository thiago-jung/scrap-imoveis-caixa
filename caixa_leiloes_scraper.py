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
import webbrowser
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
    """Baixa via requests simples (rápido, mas costuma ser bloqueado pelo Radware Bot Manager)."""
    url = BASE_URL.format(uf=uf.upper())
    log.info("Baixando lista de %s: %s", uf, url)
    resp = requests.get(url, headers=HEADERS, timeout=60)
    log.info(
        "Resposta: status=%s content-type=%s content-length=%s bytes-recebidos=%d",
        resp.status_code,
        resp.headers.get("Content-Type"),
        resp.headers.get("Content-Length"),
        len(resp.content),
    )
    resp.raise_for_status()
    return resp.content


def parece_desafio_radware(conteudo: bytes) -> bool:
    amostra = conteudo[:2000].lower()
    return b"radware" in amostra or b"bot manager" in amostra or b"captcha" in amostra


def baixar_csv_via_navegador(uf: str, headless: bool = True, tentativas: int = 3) -> bytes:
    """Baixa o CSV usando um Chrome de verdade (via Playwright).

    Necessário porque o site usa Radware Bot Manager, que bloqueia requisições
    HTTP "cruas" (sem JS, sem fingerprint de navegador). Um Chrome de verdade
    resolve o desafio automaticamente ao carregar a página.

    O arquivo CSV é servido com cabeçalho de download (Content-Disposition),
    então o Chrome trata a navegação como um download em vez de renderizar a
    página -- por isso primeiro "aquecemos" a sessão numa página normal do
    site (pra passar o desafio do Radware e ganhar os cookies), e só depois
    disparamos o download do CSV em si, capturando o evento de download.

    Requer: pip install playwright && playwright install chromium
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            "Playwright não está instalado. Rode:\n"
            "  pip install playwright\n"
            "  playwright install chromium"
        ) from e

    url_csv = BASE_URL.format(uf=uf.upper())
    url_aquecimento = "https://venda-imoveis.caixa.gov.br/sistema/busca-imovel.asp"
    log.info("Baixando lista de %s via navegador: %s", uf, url_csv)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        contexto = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="pt-BR",
            accept_downloads=True,
        )
        pagina = contexto.new_page()

        # 1) Aquece a sessão numa página normal (resolve o desafio do Radware, ganha cookies)
        log.info("Aquecendo sessão em %s ...", url_aquecimento)
        pagina.goto(url_aquecimento, wait_until="networkidle", timeout=30000)
        pagina.wait_for_timeout(3000)

        conteudo = b""
        for tentativa in range(1, tentativas + 1):
            try:
                # 2) Dispara o download do CSV em si (o goto vai "falhar" com
                #    "Download is starting" -- isso é esperado, o download
                #    real é capturado pelo expect_download)
                with pagina.expect_download(timeout=30000) as download_info:
                    try:
                        pagina.goto(url_csv, timeout=15000)
                    except Exception:
                        pass  # esperado: goto interrompe por causa do download
                download = download_info.value
                caminho_tmp = download.path()
                conteudo = Path(caminho_tmp).read_bytes()
            except Exception as e:
                log.warning("Tentativa %d: não veio como download (%s), tentando ler como página...", tentativa, e)
                resposta = pagina.goto(url_csv, wait_until="networkidle", timeout=30000)
                conteudo = resposta.body() if resposta else b""

            if conteudo and not parece_desafio_radware(conteudo):
                log.info("Desafio passado na tentativa %d (bytes: %d)", tentativa, len(conteudo))
                break
            log.warning("Tentativa %d: ainda recebendo o desafio do Radware, aguardando e tentando de novo...", tentativa)
            pagina.wait_for_timeout(4000)
        else:
            log.warning("Não consegui passar do desafio do Radware após %d tentativas.", tentativas)

        browser.close()

    return conteudo


def parsear_csv(conteudo: bytes) -> list[dict]:
    """Faz o parsing do CSV da Caixa.

    O arquivo real vem assim (confirmado em 2026-07):
        Linha 1: "Lista de Imóveis da Caixa;;Data de geração:;DD/MM/AAAA;;;;;;;"  <- lixo, ignorar
        Linha 2: " Nº do imóvel;UF;Cidade;Bairro;Endereço;Preço;..."              <- cabeçalho real
        Linha 3: em branco
        Linha 4+: dados, separados por ';', campos com espaços sobrando

    Por isso não dá pra usar csv.Sniffer nem assumir que a primeira linha é o
    cabeçalho -- é preciso achar a linha que contém "Cidade" e "UF".
    """
    texto = conteudo.decode("latin-1", errors="replace")
    linhas_texto = texto.splitlines()

    idx_header = None
    for i, linha in enumerate(linhas_texto):
        if "Cidade" in linha and "UF" in linha:
            idx_header = i
            break

    if idx_header is None:
        log.warning("Não encontrei a linha de cabeçalho esperada (com 'Cidade' e 'UF'). "
                     "O formato do arquivo pode ter mudado. Tentando a partir da linha 0.")
        log.warning("Amostra do conteúdo bruto recebido (primeiros 1000 chars): %r", texto[:1000])
        idx_header = 0

    texto_util = "\n".join(l for l in linhas_texto[idx_header:] if l.strip())
    leitor = csv.DictReader(io.StringIO(texto_util), delimiter=";")

    linhas = []
    for row in leitor:
        # limpa espaços em branco de chaves e valores (o CSV da Caixa vem cheio deles)
        row_limpo = {(k or "").strip(): (v or "").strip() for k, v in row.items() if k}
        if any(row_limpo.values()):
            linhas.append(row_limpo)

    log.info("Parseadas %d linhas", len(linhas))
    return linhas


def filtrar_por_cidade(linhas: list[dict], cidades: list[str]) -> list[dict]:
    """Mantém só as linhas cuja cidade bate com alguma da lista.

    Usa a coluna 'Cidade' quando existe (caso normal do CSV da Caixa). Se por
    algum motivo essa coluna não existir, cai pro modo antigo (procura a
    cidade em qualquer campo da linha).
    """
    cidades_norm = [normalizar(c) for c in cidades]
    tem_coluna_cidade = linhas and "Cidade" in linhas[0]

    filtradas = []
    for row in linhas:
        if tem_coluna_cidade:
            alvo = normalizar(row.get("Cidade", ""))
            bate = any(alvo == cidade or cidade in alvo for cidade in cidades_norm)
        else:
            texto_linha = normalizar(" | ".join(str(v) for v in row.values() if v))
            bate = any(cidade in texto_linha for cidade in cidades_norm)
        if bate:
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


def _parar_valor_brl(texto: str) -> float:
    """Converte '147.398,67' (formato BR: ponto=milhar, vírgula=decimal) em float."""
    if not texto:
        return 0.0
    limpo = texto.strip().replace(".", "").replace(",", ".")
    try:
        return float(limpo)
    except ValueError:
        return 0.0


def _parar_desconto(texto: str) -> float:
    """Desconto já vem como '48.10' (ponto decimal padrão)."""
    try:
        return float((texto or "0").strip())
    except ValueError:
        return 0.0


def _montar_registro_js(row: dict, ids_novos: set[str], id_col: str) -> dict:
    preco = _parar_valor_brl(row.get("Preço", ""))
    avaliacao = _parar_valor_brl(row.get("Valor de avaliação", ""))
    desconto = _parar_desconto(row.get("Desconto", ""))
    return {
        "id": row.get(id_col, ""),
        "cidade": row.get("Cidade", ""),
        "bairro": row.get("Bairro", "").title(),
        "endereco": row.get("Endereço", ""),
        "preco": preco,
        "avaliacao": avaliacao,
        "desconto": desconto,
        "financiamento": row.get("Financiamento", ""),
        "modalidade": row.get("Modalidade de venda", ""),
        "descricao": row.get("Descrição", ""),
        "link": row.get("Link de acesso", ""),
        "novo": row.get(id_col, "") in ids_novos,
    }


def gerar_html(
    uf: str,
    data_atual: str,
    novos: list[dict],
    removidos: list[dict],
    todas: list[dict],
    cidades: list[str] | None,
    caminho_saida: Path,
):
    import json

    id_col = achar_coluna_id(todas) if todas else ""
    ids_novos = {row.get(id_col) for row in novos} if todas else set()
    registros = [_montar_registro_js(row, ids_novos, id_col) for row in todas]
    registros.sort(key=lambda r: r["desconto"], reverse=True)

    bairros = sorted({r["bairro"] for r in registros if r["bairro"]})
    modalidades = sorted({r["modalidade"] for r in registros if r["modalidade"]})
    cidades_disp = sorted({r["cidade"] for r in registros if r["cidade"]})

    desconto_medio = sum(r["desconto"] for r in registros) / len(registros) if registros else 0
    melhor = max(registros, key=lambda r: r["desconto"]) if registros else None

    dados_json = json.dumps(registros, ensure_ascii=False).replace("</script>", "<\\/script>")
    filtro_txt = ", ".join(cidades) if cidades else "sem filtro (todas as cidades)"

    opcoes_bairro = "".join(f'<option value="{b}">{b}</option>' for b in bairros)
    opcoes_modalidade = "".join(f'<option value="{m}">{m}</option>' for m in modalidades)
    opcoes_cidade = "".join(f'<option value="{c}">{c}</option>' for c in cidades_disp)

    removidos_html = ""
    if removidos:
        itens = "".join(
            f"<li>{r.get('Bairro','').title()} — {r.get('Endereço','')}</li>" for r in removidos
        )
        removidos_html = f"""
        <details class="removidos">
          <summary>{len(removidos)} imóvel(is) saíram da lista desde ontem</summary>
          <ul>{itens}</ul>
        </details>"""

    resumo_melhor = ""
    if melhor:
        resumo_melhor = (
            f'{melhor["desconto"]:.0f}% em {melhor["bairro"] or melhor["cidade"]}'
        )

    html = f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Leilões Caixa · {uf} · {data_atual}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #0a0b0d;
    --panel: #131519;
    --panel-2: #191c21;
    --border: #262a31;
    --text: #eceef1;
    --muted: #8790a0;
    --gold: #d4a35a;
    --gold-dim: #8a713f;
    --good: #4ea87a;
    --mid: #c9a227;
    --low: #6b7280;
    --novo-bg: #1a2a20;
    --novo-border: #2f6b45;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: 'Inter', -apple-system, sans-serif;
    -webkit-font-smoothing: antialiased;
  }}
  .num {{ font-family: 'IBM Plex Mono', monospace; }}
  .container {{ max-width: 1320px; margin: 0 auto; padding: 28px 20px 60px; }}

  header.top {{ display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 16px; margin-bottom: 22px; }}
  h1 {{
    font-family: 'Barlow Condensed', sans-serif; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.04em; font-size: 34px; margin: 0; color: var(--text);
  }}
  h1 span {{ color: var(--gold); }}
  .subtitulo {{ color: var(--muted); font-size: 13px; margin-top: 4px; }}

  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 22px; }}
  .stat {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; }}
  .stat .valor {{ font-family: 'Barlow Condensed', sans-serif; font-size: 26px; font-weight: 600; line-height: 1; }}
  .stat .valor.gold {{ color: var(--gold); }}
  .stat .rotulo {{ color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 5px; }}

  .toolbar {{
    display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
    background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
    padding: 12px; margin-bottom: 16px; position: sticky; top: 12px; z-index: 5;
  }}
  .toolbar input[type="text"], .toolbar select {{
    background: var(--panel-2); border: 1px solid var(--border); color: var(--text);
    border-radius: 6px; padding: 8px 10px; font-size: 13px; font-family: inherit;
  }}
  .toolbar input[type="text"] {{ flex: 1 1 220px; min-width: 160px; }}
  .toolbar select {{ min-width: 130px; }}
  .toolbar label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; display: flex; flex-direction: column; gap: 4px; }}
  .toolbar .desconto-min {{ display: flex; align-items: center; gap: 8px; }}
  .toolbar input[type="range"] {{ accent-color: var(--gold); width: 110px; }}
  .contagem {{ margin-left: auto; color: var(--muted); font-size: 12px; }}
  .contagem b {{ color: var(--text); }}

  .tabela-wrap {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 8px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; min-width: 900px; }}
  th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }}
  th {{
    background: var(--panel-2); color: var(--muted); font-weight: 600; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.04em; position: sticky; top: 0; cursor: pointer;
    user-select: none;
  }}
  th:hover {{ color: var(--gold); }}
  th.ativo {{ color: var(--gold); }}
  tbody tr {{ background: var(--panel); }}
  tbody tr:hover {{ background: var(--panel-2); }}
  tbody tr.novo {{ background: var(--novo-bg); }}
  tbody tr.novo:hover {{ background: #223829; }}
  td.endereco {{ white-space: normal; max-width: 260px; }}
  td.endereco .bairro {{ font-weight: 600; }}
  td.endereco .rua {{ color: var(--muted); font-size: 12px; display: block; }}
  .badge-novo {{
    background: var(--good); color: #06170e; font-size: 10px; font-weight: 700;
    padding: 2px 6px; border-radius: 4px; text-transform: uppercase; letter-spacing: 0.03em; margin-left: 6px;
  }}
  .desconto-cel {{ display: flex; flex-direction: column; gap: 4px; min-width: 90px; }}
  .desconto-num {{ font-weight: 600; }}
  .barra {{ height: 4px; border-radius: 2px; background: var(--border); overflow: hidden; }}
  .barra > i {{ display: block; height: 100%; border-radius: 2px; }}
  .modalidade-tag {{
    font-size: 11px; padding: 3px 8px; border-radius: 100px; border: 1px solid var(--border);
    color: var(--muted); white-space: nowrap;
  }}
  a.ver-btn {{
    display: inline-block; color: var(--bg); background: var(--gold); font-weight: 600;
    font-size: 12px; padding: 5px 10px; border-radius: 6px; text-decoration: none; white-space: nowrap;
  }}
  a.ver-btn:hover {{ background: #e3b671; }}

  .vazio {{ color: var(--muted); font-style: italic; padding: 24px; text-align: center; }}

  .removidos {{ margin-top: 20px; color: var(--muted); font-size: 13px; }}
  .removidos summary {{ cursor: pointer; color: var(--muted); }}
  .removidos ul {{ margin: 8px 0 0; padding-left: 18px; }}

  footer {{ margin-top: 30px; color: var(--muted); font-size: 11px; text-align: center; }}

  @media (max-width: 640px) {{
    h1 {{ font-size: 26px; }}
    .toolbar {{ position: static; }}
  }}
</style>
</head>
<body>
<div class="container">
  <header class="top">
    <div>
      <h1>Leilões <span>Caixa</span> — {uf}</h1>
      <div class="subtitulo">Atualizado em {data_atual} · Região: {filtro_txt}</div>
    </div>
  </header>

  <div class="stats">
    <div class="stat"><div class="valor">{len(todas)}</div><div class="rotulo">Ativos hoje</div></div>
    <div class="stat"><div class="valor gold">{len(novos)}</div><div class="rotulo">Novos hoje</div></div>
    <div class="stat"><div class="valor">{desconto_medio:.0f}%</div><div class="rotulo">Desconto médio</div></div>
    <div class="stat"><div class="valor gold">{resumo_melhor or '—'}</div><div class="rotulo">Maior desconto</div></div>
  </div>

  <div class="toolbar">
    <input type="text" id="busca" placeholder="Buscar por endereço, bairro...">
    <label>Cidade
      <select id="filtro-cidade"><option value="">Todas</option>{opcoes_cidade}</select>
    </label>
    <label>Bairro
      <select id="filtro-bairro"><option value="">Todos</option>{opcoes_bairro}</select>
    </label>
    <label>Modalidade
      <select id="filtro-modalidade"><option value="">Todas</option>{opcoes_modalidade}</select>
    </label>
    <label>Só novos hoje
      <select id="filtro-novos"><option value="">Todos</option><option value="1">Sim</option></select>
    </label>
    <div class="desconto-min">
      <label>Desconto mín. <span id="desconto-min-valor">0%</span>
        <input type="range" id="desconto-min" min="0" max="90" value="0" step="5">
      </label>
    </div>
    <span class="contagem"><b id="contagem-num">{len(todas)}</b> imóveis</span>
  </div>

  <div class="tabela-wrap">
    <table id="tabela">
      <thead>
        <tr>
          <th data-col="bairro">Local</th>
          <th data-col="preco" class="num">Preço</th>
          <th data-col="avaliacao" class="num">Avaliação</th>
          <th data-col="desconto" class="ativo">Desconto</th>
          <th data-col="modalidade">Modalidade</th>
          <th></th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
    <div id="vazio" class="vazio" style="display:none">Nenhum imóvel bate com esse filtro.</div>
  </div>

  {removidos_html}

  <footer>Fonte: venda-imoveis.caixa.gov.br · dados públicos da Caixa Econômica Federal</footer>
</div>

<script>
const DADOS = {dados_json};

const fmtBRL = (v) => v.toLocaleString('pt-BR', {{style:'currency', currency:'BRL', maximumFractionDigits:0}});

function corDesconto(d) {{
  if (d >= 50) return 'var(--good)';
  if (d >= 30) return 'var(--mid)';
  return 'var(--low)';
}}

let ordenarPor = 'desconto';
let ordemAsc = false;

function aplicarFiltros() {{
  const busca = document.getElementById('busca').value.trim().toLowerCase();
  const cidade = document.getElementById('filtro-cidade').value;
  const bairro = document.getElementById('filtro-bairro').value;
  const modalidade = document.getElementById('filtro-modalidade').value;
  const soNovos = document.getElementById('filtro-novos').value;
  const descMin = parseInt(document.getElementById('desconto-min').value, 10);

  let filtrados = DADOS.filter(r => {{
    if (busca && !(r.endereco.toLowerCase().includes(busca) || r.bairro.toLowerCase().includes(busca))) return false;
    if (cidade && r.cidade !== cidade) return false;
    if (bairro && r.bairro !== bairro) return false;
    if (modalidade && r.modalidade !== modalidade) return false;
    if (soNovos === '1' && !r.novo) return false;
    if (r.desconto < descMin) return false;
    return true;
  }});

  filtrados.sort((a, b) => {{
    let va = a[ordenarPor], vb = b[ordenarPor];
    if (typeof va === 'string') {{ va = va.toLowerCase(); vb = vb.toLowerCase(); }}
    if (va < vb) return ordemAsc ? -1 : 1;
    if (va > vb) return ordemAsc ? 1 : -1;
    return 0;
  }});

  renderizar(filtrados);
}}

function renderizar(lista) {{
  const tbody = document.getElementById('tbody');
  const vazio = document.getElementById('vazio');
  document.getElementById('contagem-num').textContent = lista.length;

  if (lista.length === 0) {{
    tbody.innerHTML = '';
    vazio.style.display = 'block';
    return;
  }}
  vazio.style.display = 'none';

  tbody.innerHTML = lista.map(r => `
    <tr class="${{r.novo ? 'novo' : ''}}">
      <td class="endereco">
        <span class="bairro">${{r.bairro || r.cidade}}${{r.novo ? '<span class="badge-novo">novo</span>' : ''}}</span>
        <span class="rua">${{r.endereco}}</span>
      </td>
      <td class="num">${{fmtBRL(r.preco)}}</td>
      <td class="num">${{fmtBRL(r.avaliacao)}}</td>
      <td>
        <div class="desconto-cel">
          <span class="desconto-num num" style="color:${{corDesconto(r.desconto)}}">${{r.desconto.toFixed(0)}}%</span>
          <div class="barra"><i style="width:${{Math.min(r.desconto,100)}}%; background:${{corDesconto(r.desconto)}}"></i></div>
        </div>
      </td>
      <td><span class="modalidade-tag">${{r.modalidade}}</span></td>
      <td><a class="ver-btn" href="${{r.link}}" target="_blank" rel="noopener">Ver no site →</a></td>
    </tr>
  `).join('');
}}

document.querySelectorAll('th[data-col]').forEach(th => {{
  th.addEventListener('click', () => {{
    const col = th.dataset.col;
    if (ordenarPor === col) {{ ordemAsc = !ordemAsc; }}
    else {{ ordenarPor = col; ordemAsc = false; }}
    document.querySelectorAll('th[data-col]').forEach(t => t.classList.remove('ativo'));
    th.classList.add('ativo');
    aplicarFiltros();
  }});
}});

document.getElementById('desconto-min').addEventListener('input', (e) => {{
  document.getElementById('desconto-min-valor').textContent = e.target.value + '%';
  aplicarFiltros();
}});
['busca','filtro-cidade','filtro-bairro','filtro-modalidade','filtro-novos'].forEach(id => {{
  document.getElementById(id).addEventListener('input', aplicarFiltros);
}});

aplicarFiltros();
</script>
</body>
</html>"""
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    caminho_saida.write_text(html, encoding="utf-8")
    log.info("Relatório HTML salvo em %s", caminho_saida)


def processar_uf(

    uf: str,
    outdir: Path,
    cidades: list[str] | None = None,
    html_out: Path | None = None,
    metodo: str = "navegador",
    headless: bool = True,
):
    if metodo == "navegador":
        conteudo = baixar_csv_via_navegador(uf, headless=headless)
    else:
        conteudo = baixar_csv(uf)

    if parece_desafio_radware(conteudo):
        log.error(
            "%s: recebi a página de desafio do Radware em vez do CSV. "
            "O bloqueio não foi resolvido -- ver instruções de troubleshooting.",
            uf,
        )
        return

    linhas = parsear_csv(conteudo)
    if not linhas:
        log.warning("Nenhuma linha encontrada para %s (site pode ter mudado o formato).", uf)
        # ainda assim gera um HTML vazio, pra não quebrar o commit do workflow
        if html_out:
            gerar_html(uf, datetime.now().strftime("%Y-%m-%d"), [], [], [], cidades, html_out)
        return

    if cidades:
        linhas_filtradas = filtrar_por_cidade(linhas, cidades)
        if not linhas_filtradas:
            log.warning(
                "Filtro de cidade não retornou nada -- confira se os nomes em "
                "CIDADES_RMPA batem com o texto real do CSV (rode sem --cidades pra conferir)."
            )
        linhas = linhas_filtradas

    id_col = achar_coluna_id(linhas) if linhas else ""
    data_atual = datetime.now().strftime("%Y-%m-%d")
    anteriores = carregar_snapshot_anterior(uf, outdir, data_atual)
    salvar_snapshot(linhas, uf, outdir)

    novos, removidos = comparar(linhas, anteriores, id_col) if linhas else ([], [])
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
    parser.add_argument(
        "--open",
        action="store_true",
        help="Abre o relatório HTML automaticamente no navegador padrão ao terminar",
    )
    parser.add_argument(
        "--metodo",
        choices=["navegador", "requests"],
        default="navegador",
        help="'navegador' usa Playwright pra passar do bloqueio Radware (default, recomendado). "
        "'requests' é o método simples antigo, que costuma ser bloqueado.",
    )
    parser.add_argument(
        "--mostrar-navegador",
        action="store_true",
        help="Mostra a janela do Chrome durante o download (útil se o modo headless continuar bloqueado)",
    )
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)  # garante que a pasta existe mesmo se tudo falhar
    cidades = args.cidades if args.cidades else None
    html_out = Path(args.html_out) if args.html_out else None

    sucesso = 0
    for uf in args.ufs:
        try:
            processar_uf(
                uf,
                outdir,
                cidades=cidades,
                html_out=html_out,
                metodo=args.metodo,
                headless=not args.mostrar_navegador,
            )
            sucesso += 1
        except requests.RequestException as e:
            log.error("Erro ao baixar/processar %s: %s", uf, e)

    if sucesso == 0:
        log.error("Nenhuma UF processada com sucesso -- abortando com erro.")
        raise SystemExit(1)

    if args.open and html_out and html_out.exists():
        webbrowser.open(html_out.resolve().as_uri())


if __name__ == "__main__":
    main()
