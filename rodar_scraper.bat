@echo off
echo Iniciando Scraper da Caixa...

:: Vai para a pasta do projeto
cd /d "C:\Projects\scrap-imoveis-caixa"

:: Roda o scraper
python caixa_leiloes_scraper.py --outdir data --html-out index.html >> log.txt 2>&1

echo. >> log.txt
echo ========================================= >> log.txt
echo Processo do Python concluido. >> log.txt

:: Garante as credenciais do bot
git config user.name "Scraper Automatico"
git config user.email "bot@seu-pc.local"

:: Adiciona os arquivos
git add data/ index.html

:: Tenta commitar. O operador || (OR) faz pular pro final se não houver mudanças reais.
git commit -m "Atualizacao automatica: %date%" >> log.txt 2>&1 || goto :sem_mudancas

echo Alteracoes detectadas. Enviando para o GitHub... >> log.txt
git push origin main >> log.txt 2>&1
goto :fim

:sem_mudancas
echo Nenhuma alteracao no HTML ou CSV detectada. Commit ignorado. >> log.txt

:fim
echo Processo concluido com sucesso! >> log.txt