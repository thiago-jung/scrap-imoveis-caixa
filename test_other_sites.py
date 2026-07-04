from bs4 import BeautifulSoup

def dump_html_text():
    with open("leilao_imovel_pw.html", "r", encoding="utf-8") as f:
        html = f.read()
        
    soup = BeautifulSoup(html, "html.parser")
    print(soup.get_text(strip=True)[:2000])

if __name__ == "__main__":
    dump_html_text()
