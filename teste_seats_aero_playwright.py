"""
Teste isolado: verifica se dá pra extrair disponibilidade de passagens
premiadas do seats.aero rodando via Playwright dentro do GitHub Actions,
sem precisar de API key nem login.

Preocupação sendo testada: o site usa Cloudflare, que bloqueia requests
HTTP simples (testado: HTTP 403 direto com requests/curl). A ideia é
carregar o site uma vez com um navegador de verdade (Chromium via
Playwright) - o que passa pelo Cloudflare normalmente - e, de DENTRO da
página já carregada, disparar as buscas via fetch() no próprio contexto
JS do navegador (mesma origem, mesmas credenciais de rede que o
Cloudflare já liberou).

Busca de teste: FOR -> CDG operado pela Air France (AF), via Smiles,
varrendo os próximos 60 dias (limite do plano gratuito do seats.aero -
confirmado manualmente que não precisa de login pra isso). Não grava em
planilha nenhuma e não manda nada pro WhatsApp - só imprime o resultado
no log da execução.
"""
import json
from datetime import datetime
from playwright.sync_api import sync_playwright

URL_SEATS_AERO = "https://seats.aero/search"
ORIGEM = "FOR"
DESTINO = "CDG"
COMPANHIA = "AF"  # Air France
DIAS_JANELA = 60  # limite do plano gratuito (~2 meses)

# Nome de cada classe + os campos correspondentes na resposta da API
# (y=economica, w=premium, j=executiva, f=primeira; sufixo c=companhias,
# m=pontos, s=assentos).
CLASSES = [
    ("Econômica", "yc", "ym", "ys"),
    ("Premium", "wc", "wm", "ws"),
    ("Executiva", "jc", "jm", "js"),
    ("Primeira", "fc", "fm", "fs"),
]

# JS executado de dentro da página já carregada: varre as datas e chama
# a API de busca pontual (_api/search_partial) uma vez por dia, com uma
# pequena pausa entre cada chamada pra não parecer abuso.
SCRIPT_JS = """
async ({ origem, destino, hoje, dias }) => {
    const resultados = [];
    const erros = [];
    const base = new Date(hoje + "T00:00:00");
    for (let i = 0; i <= dias; i++) {
        const d = new Date(base);
        d.setDate(d.getDate() + i);
        const dataStr = d.toISOString().slice(0, 10);
        const params = new URLSearchParams({
            min_seats: "1",
            applicable_cabin: "any",
            max_fees: "40000",
            disable_live_filtering: "false",
            date: dataStr,
            origins: origem,
            destinations: destino,
            client_date: hoje,
        });
        try {
            const resp = await fetch("https://seats.aero/_api/search_partial?" + params.toString(), { credentials: "omit" });
            const data = await resp.json();
            if (!data.error && data.metadata) {
                resultados.push({ data: dataStr, metadata: data.metadata });
            } else if (data.error) {
                erros.push({ data: dataStr, erro: data.errorMessage || "erro desconhecido" });
            }
        } catch (e) {
            erros.push({ data: dataStr, erro: String(e) });
        }
        await new Promise(r => setTimeout(r, 500));
    }
    return { resultados, erros };
}
"""


def main():
    hoje = datetime.now().strftime("%Y-%m-%d")

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)
        pagina = navegador.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ))

        print(f"Acessando {URL_SEATS_AERO} ...")
        pagina.goto(URL_SEATS_AERO, timeout=45000, wait_until="networkidle")
        pagina.wait_for_timeout(3000)

        print(f"Título da página carregada: {pagina.title()}")
        print(f"Buscando {ORIGEM} -> {DESTINO} de {hoje} até +{DIAS_JANELA} dias (isso demora ~30-40s)...")

        resultado = pagina.evaluate(
            SCRIPT_JS,
            {"origem": ORIGEM, "destino": DESTINO, "hoje": hoje, "dias": DIAS_JANELA},
        )

        navegador.close()

    print(f"\nDias com resposta válida: {len(resultado['resultados'])}")
    print(f"Dias com erro: {len(resultado['erros'])}")
    if resultado["erros"]:
        print("Exemplos de erro:", json.dumps(resultado["erros"][:3], ensure_ascii=False))

    encontrados = []
    for item in resultado["resultados"]:
        for m in item["metadata"]:
            if m.get("source") != "smiles":
                continue
            for classe, campo_carrier, campo_pontos, campo_assentos in CLASSES:
                carriers = [c.strip() for c in (m.get(campo_carrier) or "").split(",") if c.strip()]
                if COMPANHIA not in carriers:
                    continue
                pontos = m.get(campo_pontos) or 0
                assentos = m.get(campo_assentos) or 0
                if pontos and assentos:
                    encontrados.append({
                        "data": m["date"],
                        "classe": classe,
                        "pontos": pontos,
                        "assentos": assentos,
                    })

    print()
    if not encontrados:
        print(
            f"❌ NENHUMA vaga com {COMPANHIA} na Smiles encontrada em {ORIGEM}->{DESTINO} "
            "nos próximos 60 dias - pode ser falta de disponibilidade real, ou algo bloqueou a busca."
        )
    else:
        print(f"✅ {len(encontrados)} vaga(s) encontrada(s) com {COMPANHIA} via Smiles:\n")
        for e in sorted(encontrados, key=lambda x: x["data"]):
            print(f"Data: {e['data']} | Classe: {e['classe']} | Pontos: {e['pontos']:,} | Assentos: {e['assentos']}")


if __name__ == "__main__":
    main()
