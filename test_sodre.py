from playwright.sync_api import sync_playwright
import traceback

def test_sodre_playwright():
    url = "https://www.sodresantoro.com.br/imoveis/"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            print("Navegando para", url)
            page.goto(url, wait_until="networkidle", timeout=30000)
            
            # Allow some time for Nuxt to render client side
            page.wait_for_timeout(3000)
            
            html = page.content()
            with open("sodre_sample_playwright.html", "w", encoding="utf-8") as f:
                f.write(html)
                
            print("HTML salvo via Playwright!")
            browser.close()
    except Exception as e:
        print("Error:")
        traceback.print_exc()

if __name__ == "__main__":
    test_sodre_playwright()
