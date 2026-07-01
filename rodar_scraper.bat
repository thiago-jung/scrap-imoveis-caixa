@echo off
REM Roda o scraper de leiloes da Caixa (RS, regiao metropolitana de Porto Alegre)
REM e abre o relatorio automaticamente no navegador.
REM
REM Ajuste o caminho abaixo para a pasta onde voce salvou os arquivos.

cd /d "C:\leiloes-caixa"

python caixa_leiloes_scraper.py --outdir data --html-out index.html --open

REM Se quiser ver a janela ficar aberta pra conferir erros, descomente a linha abaixo:
REM pause
