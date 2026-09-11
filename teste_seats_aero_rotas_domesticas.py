"""
Teste isolado: busca as passagens premiadas mais baratas entre TODAS as
rotas domésticas do Brasil (Gol/Smiles, Azul, LATAM), nos próximos 60
dias, sem repetir rota - cada trecho aparece só uma vez, com o menor
preço em pontos encontrado em qualquer data da janela.

Baseado na busca manual:
https://seats.aero/search?min_seats=1&op_carriers=G3,AD,LA&applicable_cabin=any&direct_only=true&max_fees=40000&disable_live_filtering=false&origins=BRL&destinations=BRL&start_date=...&end_date=...

"origins=BRL&destinations=BRL" busca TODAS as rotas dentro do Brasil de
uma vez (não é um aeroporto, é o país inteiro). Buscar por intervalo de
datas (start_date/end_date) exige conta Pro ("Searching by date range
requires a Pro subscription") - confirmado por teste manual - por isso
aqui a busca é feita dia a dia (uma data por vez), igual ao teste
FOR/CDG, e sem login (funciona no plano gratuito).

Regra de desempate pedida: entre duas datas com o MESMO preço mais
baixo para a mesma rota, fica a data mais distante (mais no futuro).

Não grava em planilha nenhuma e não manda nada pro WhatsApp - só imprime
o resultado no log da execução.
"""
import json
from datetime import datetime
from playwright.sync_api import sync_playwright

URL_SEATS_AERO = "https://seats.aero/search"
COMPANHIAS = "G3,AD,LA"  # Gol/Smiles, Azul, LATAM
DIAS_JANELA = 60  # limite do plano gratuito (~2 meses)
MAX_TAXAS_CENTAVOS = 40000  # mesmo limite usado na busca manual (max_fees)

# JS executado de dentro da página já carregada: varre as datas uma a uma
# e, pra cada rota (origem-destino) encontrada, guarda só a melhor oferta
# vista até agora (menor pontos; em empate, data mais distante). Faz a
# agregação já em JS pra não precisar trafegar todo o bruto (são ~900
# rotas por dia x 61 dias) de volta pro Python.
SCRIPT_JS = """
async ({ carriers, hoje, dias, maxTaxas }) => {
    const CLASSES = [
        ["Econômica", "ym", "ys"],
        ["Premium", "wm", "ws"],
        ["Executiva", "jm", "js"],
        ["Primeira", "fm", "fs"],
    ];
    const melhores = new Map();  // chave "OA-DA" -> melhor oferta vista
    const erros = [];
    const base = new Date(hoje + "T00:00:00");

    async function buscarComRetry(params, tentativas = 2) {
        for (let t = 1; t <= tentativas; t++) {
            const resp = await fetch("https://seats.aero/_api/search_partial?" + params.toString(), { credentials: "omit" });
            const texto = await resp.text();
            try {
                return { ok: true, data: JSON.parse(texto) };
            } catch (e) {
                if (t === tentativas) {
                    return { ok: false, erro: `resposta não-JSON após ${tentativas} tentativas: ${String(e)}` };
                }
                await new Promise(r => setTimeout(r, 2000));
            }
        }
    }

    for (let i = 0; i <= dias; i++) {
        const d = new Date(base);
        d.setDate(d.getDate() + i);
        const dataStr = d.toISOString().slice(0, 10);
        const params = new URLSearchParams({
            min_seats: "1",
            op_carriers: carriers,
            applicable_cabin: "any",
            direct_only: "true",
            max_fees: String(maxTaxas),
            disable_live_filtering: "false",
            origins: "BRL",
            destinations: "BRL",
            date: dataStr,
            client_date: hoje,
        });

        try {
            const resultado = await buscarComRetry(params);
            if (!resultado.ok) {
                erros.push({ data: dataStr, erro: resultado.erro });
            } else if (resultado.data.error) {
                erros.push({ data: dataStr, erro: resultado.data.errorMessage || "erro desconhecido" });
            } else if (resultado.data.metadata) {
                for (const m of resultado.data.metadata) {
                    const rota = m.oa + "-" + m.da;

                    // Acha a cabine mais barata DISPONÍVEL nesse registro
                    // (min_seats=1 já garante que tem assento, mas cada
                    // registro pode trazer mais de uma cabine).
                    let melhorCabine = null;
                    for (const [nome, campoM, campoS] of CLASSES) {
                        const pontos = m[campoM] || 0;
                        const assentos = m[campoS] || 0;
                        if (pontos > 0 && assentos > 0) {
                            if (!melhorCabine || pontos < melhorCabine.pontos) {
                                melhorCabine = { classe: nome, pontos, assentos };
                            }
                        }
                    }
                    if (!melhorCabine) continue;

                    const candidato = {
                        oa: m.oa, da: m.da, data: m.date, fonte: m.source,
                        classe: melhorCabine.classe, pontos: melhorCabine.pontos,
                        assentos: melhorCabine.assentos,
                    };

                    const atual = melhores.get(rota);
                    const melhorQue = !atual
                        || candidato.pontos < atual.pontos
                        || (candidato.pontos === atual.pontos && candidato.data > atual.data);
                    if (melhorQue) {
                        melhores.set(rota, candidato);
                    }
                }
            }
        } catch (e) {
            erros.push({ data: dataStr, erro: String(e) });
        }
        await new Promise(r => setTimeout(r, 500));
    }

    return { melhores: Array.from(melhores.values()), erros };
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
        pagina.wait_for_timeout(5000)

        print(f"Título da página carregada: {pagina.title()}")
        print(
            f"Buscando todas as rotas domésticas do Brasil ({COMPANHIAS}) de "
            f"{hoje} até +{DIAS_JANELA} dias - isso demora uns 40-60s..."
        )

        resultado = pagina.evaluate(
            SCRIPT_JS,
            {"carriers": COMPANHIAS, "hoje": hoje, "dias": DIAS_JANELA, "maxTaxas": MAX_TAXAS_CENTAVOS},
        )

        navegador.close()

    melhores = resultado["melhores"]
    erros = resultado["erros"]

    print(f"\nRotas únicas encontradas: {len(melhores)}")
    print(f"Dias com erro: {len(erros)}")
    if erros:
        print("Exemplos de erro:", json.dumps(erros[:3], ensure_ascii=False))

    print()
    if not melhores:
        print("❌ Nenhuma rota encontrada - algo bloqueou a busca ou não há disponibilidade.")
        return

    melhores.sort(key=lambda x: x["pontos"])
    print(f"✅ {len(melhores)} rota(s) domésticas (a mais barata de cada, sem repetir):\n")
    for r in melhores:
        print(
            f"{r['oa']}-{r['da']} | Classe: {r['classe']} | Pontos: {r['pontos']:,} | "
            f"Assentos: {r['assentos']} | Data: {r['data']} | Fonte: {r['fonte']}"
        )


if __name__ == "__main__":
    main()
