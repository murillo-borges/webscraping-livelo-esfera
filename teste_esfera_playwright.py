"""
Teste isolado: verifica se dá pra extrair dados dos parceiros da Esfera
rodando via Playwright dentro do GitHub Actions.

Preocupação sendo testada: o IP de datacenter do GitHub Actions pode ser
bloqueado pelo Akamai Bot Manager do site da Esfera, mesmo com um navegador
de verdade (Chromium via Playwright) - isso não tem a ver com o código,
tem a ver com a reputação do IP de origem.

Testa só 2 parceiros conhecidos (Adidas e Agaxtur Viagens e Turismo) pra
manter o teste rápido e fácil de conferir. Não grava em planilha nenhuma -
só imprime o resultado no log da execução.
"""
import re
from playwright.sync_api import sync_playwright

URL_ESFERA = "https://www.esfera.com.vc/junte-pontos/junte-pontos/esf02163"
PARCEIROS_TESTE = ["Adidas", "Agaxtur Viagens e Turismo"]


def extrair_parceiros_esfera(pagina):
    links = pagina.eval_on_selector_all(
        'a[href*="/p/"]',
        """els => els
            .filter(a => a.textContent.includes('Ganhe'))
            .map(a => ({ href: a.href, texto: a.textContent.trim() }))
        """,
    )

    resultado = []
    for item in links:
        texto = item["texto"]
        m = re.match(r"^(.*?)\s*Ganhe\s+(.*)$", texto)
        if not m:
            continue
        nome = m.group(1).strip()
        if nome not in PARCEIROS_TESTE:
            continue
        resultado.append({"nome": nome, "frase_pontos": m.group(2).strip(), "link": item["href"]})
    return resultado


def main():
    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)
        pagina = navegador.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        )

        print(f"Acessando {URL_ESFERA} ...")
        pagina.goto(URL_ESFERA, timeout=30000, wait_until="domcontentloaded")
        pagina.wait_for_timeout(5000)  # dá tempo do JS carregar os parceiros

        print(f"Título da página carregada: {pagina.title()}")

        parceiros = extrair_parceiros_esfera(pagina)

        navegador.close()

    print()
    if not parceiros:
        print(
            "❌ NENHUM parceiro de teste encontrado — provavelmente bloqueado "
            "(Akamai) ou a página não carregou os dados a tempo."
        )
    else:
        print(f"✅ {len(parceiros)}/{len(PARCEIROS_TESTE)} parceiro(s) de teste encontrado(s):\n")
        for p in parceiros:
            print(f"Parceiro: {p['nome']}")
            print("Programa de Fidelidade: 🔴 Esfera")
            print(f"Pontuação (bruta): {p['frase_pontos']}")
            print(f"Link parceiro: {p['link']}")
            print()


if __name__ == "__main__":
    main()
