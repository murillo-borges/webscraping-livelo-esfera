"""
Teste isolado: verifica se dá pra extrair disponibilidade de passagens
premiadas do seatspy.com rodando via requests puro (sem navegador, sem
Playwright) dentro do GitHub Actions.

Diferente do seats.aero (que bloqueia requests simples via Cloudflare e
precisa de Playwright), o seatspy.com aceita chamadas diretas de
requests/curl, sem login e sem bloqueio - confirmado manualmente antes
de escrever este teste.

Fluxo de 2 passos (assíncrono):
1. POST /api/request-year-data - pede a busca, devolve um token
2. POST /api/retrieve-year-data - busca o resultado pelo token (pode
   precisar tentar de novo se ainda não tiver terminado de processar)

Busca de teste: GRU -> MAD operado pela Iberia Airlines. Os IDs internos
(GRU=476, MAD=317, IB=Iberia) foram descobertos inspecionando a página
manualmente - ainda não sabemos o ID de outros aeroportos/companhias.

Não grava em planilha nenhuma e não manda nada pro WhatsApp - só imprime
o resultado no log da execução.
"""
import json
import time
import requests

BASE_URL = "https://www.seatspy.com"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}

# IDs internos do seatspy.com (descobertos manualmente na página)
COMPANHIA = "IB"  # Iberia Airlines
ORIGEM_ID = "476"  # GRU - Guarulhos
DESTINO_ID = "317"  # MAD - Madrid
ORIGEM_IATA = "GRU"
DESTINO_IATA = "MAD"

TENTATIVAS_RETRIEVE = 6
ESPERA_ENTRE_TENTATIVAS = 3  # segundos


def pedir_busca():
    """Passo 1: pede a busca do ano inteiro, devolve o token pra consultar
    o resultado depois."""
    payload = {
        "airline_short_codes": [COMPANHIA],
        "origin": ORIGEM_ID,
        "destination": DESTINO_ID,
        "num_passengers": "1",
        "direction": "outbound",
        "historic_collection_index": 1,
        "attempt": 1,
    }
    resp = requests.post(f"{BASE_URL}/api/request-year-data", headers=HEADERS, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data["tokens"][0]


def buscar_resultado(token):
    """Passo 2: consulta o resultado pelo token. Como é assíncrono, tenta
    de novo (com espera) enquanto o status não vier "Completed"."""
    payload = {"search_request_ids": [token]}
    for tentativa in range(1, TENTATIVAS_RETRIEVE + 1):
        resp = requests.post(f"{BASE_URL}/api/retrieve-year-data", headers=HEADERS, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")
        progresso = data.get("progress")
        print(f"Tentativa {tentativa}/{TENTATIVAS_RETRIEVE}: status={status} progresso={progresso}%")
        if status == "Completed":
            return data
        time.sleep(ESPERA_ENTRE_TENTATIVAS)
    raise TimeoutError(f"Busca não terminou de processar após {TENTATIVAS_RETRIEVE} tentativas.")


def main():
    print(f"Buscando {ORIGEM_IATA} -> {DESTINO_IATA} via {COMPANHIA} (seatspy.com)...")

    token = pedir_busca()
    print(f"Token da busca: {token}")

    resultado = buscar_resultado(token)
    datas = resultado.get("data", {}).get("dates", [])

    print(f"\nTotal de dias retornados: {len(datas)}")
    if datas:
        print(f"Primeira data: {datas[0]['startDate']}")
        print(f"Última data: {datas[-1]['startDate']}")

    encontrados = []
    for item in datas:
        for voo in item.get("flights", []):
            if not voo.get("hasAvailability"):
                continue
            for classe, campo_milhas, campo_assentos in [
                ("Econômica", "economyMiles", "economy"),
                ("Premium", "premiumMiles", "premium"),
                ("Executiva", "businessMiles", "business"),
                ("Primeira", "firstMiles", "first"),
            ]:
                milhas = voo.get(campo_milhas)
                assentos = voo.get(campo_assentos)
                if milhas and assentos:
                    encontrados.append({
                        "data_raw": voo.get("departureTime") or item.get("startDate"),
                        "classe": classe,
                        "milhas": milhas,
                        "assentos": assentos,
                    })

    print()
    if not encontrados:
        print(f"❌ Nenhuma vaga encontrada para {ORIGEM_IATA}->{DESTINO_IATA} via {COMPANHIA}.")
    else:
        print(f"✅ {len(encontrados)} vaga(s) encontrada(s):\n")
        for e in encontrados:
            print(f"Data: {e['data_raw']} | Classe: {e['classe']} | Milhas: {e['milhas']:,} | Assentos: {e['assentos']}")


if __name__ == "__main__":
    main()
