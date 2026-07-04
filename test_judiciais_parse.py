from bs4 import BeautifulSoup
import re

def test_pagination():
    with open("leiloes_judiciais_sample.html", "r", encoding="utf-8") as f:
        html = f.read()
        
    soup = BeautifulSoup(html, "html.parser")
    pagination = soup.find('ul', class_=re.compile("pagination"))
    if pagination:
        links = pagination.find_all('a', href=True)
        for link in links:
            print(f"Page link: {link.text.strip()} -> {link['href']}")

if __name__ == "__main__":
    test_pagination()
