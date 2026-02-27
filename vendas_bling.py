"""
Script para extração de pedidos de venda da API do Bling (v3).

Autentica via OAuth2 (Bearer Token), percorre todas as páginas de pedidos,
extrai os campos solicitados e salva em vendas_bling.csv.
"""

import os
import time
import requests
import pandas as pd

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

# Substitua pelo seu Access Token OAuth2 gerado em:
# https://developer.bling.com.br/referencia
# Você também pode definir a variável de ambiente BLING_ACCESS_TOKEN para
# evitar expor o token diretamente no código.
ACCESS_TOKEN = os.getenv("BLING_ACCESS_TOKEN", "https://developer.bling.com.br/referencia")

BASE_URL = "https://www.bling.com.br/Api/v3"

HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Accept": "application/json",
}

# Delay em segundos entre requisições para respeitar rate-limit da API
DELAY_ENTRE_PAGINAS = 0.5

# Colunas do CSV de saída
COLUNAS = [
    "numero_pedido",
    "data_pedido",
    "cliente",
    "cpf_cnpj",
    "faturamento",
    "produto",
    "unidade",
    "quantidade",
    "valor_unitario",
    "estado",
    "cidade",
    "vendedor",
    "nome_loja",
    "situacao",
]


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------

def buscar_pagina_pedidos(pagina: int) -> dict:
    """Faz a requisição de uma página de pedidos de venda.

    Args:
        pagina: Número da página (começa em 1).

    Returns:
        Dicionário com o JSON retornado pela API.

    Raises:
        Exception: Quando a API retorna status diferente de 200.
    """
    url = f"{BASE_URL}/pedidos/vendas"
    params = {"pagina": pagina, "limite": 100}

    resposta = requests.get(url, headers=HEADERS, params=params, timeout=30)

    if resposta.status_code != 200:
        raise Exception(
            f"Erro na requisição (página {pagina}): "
            f"HTTP {resposta.status_code} – {resposta.text}"
        )

    return resposta.json()


def buscar_detalhe_pedido(id_pedido: int) -> dict:
    """Busca os detalhes completos de um pedido pelo seu ID.

    Args:
        id_pedido: Identificador interno do pedido no Bling.

    Returns:
        Dicionário com o JSON do pedido detalhado.

    Raises:
        Exception: Quando a API retorna status diferente de 200.
    """
    url = f"{BASE_URL}/pedidos/vendas/{id_pedido}"

    resposta = requests.get(url, headers=HEADERS, timeout=30)

    if resposta.status_code != 200:
        raise Exception(
            f"Erro ao buscar detalhes do pedido {id_pedido}: "
            f"HTTP {resposta.status_code} – {resposta.text}"
        )

    return resposta.json()


def extrair_linhas_pedido(pedido: dict) -> list[dict]:
    """Extrai uma lista de linhas (uma por item) a partir de um pedido detalhado.

    Se o pedido tiver múltiplos produtos, retorna uma linha para cada item.

    Args:
        pedido: Dicionário com os dados completos do pedido.

    Returns:
        Lista de dicionários, cada um representando uma linha do CSV.
    """
    # Campos de nível de pedido
    numero_pedido = pedido.get("numero", "")
    data_pedido = pedido.get("data", "")
    # Valor total do pedido: prefere totalProdutos (valor bruto dos itens);
    # cai em "total" como fallback para pedidos que usam campo diferente.
    faturamento = pedido.get("totalProdutos") or pedido.get("total", "")

    # Situação do pedido
    situacao_obj = pedido.get("situacao") or {}
    situacao = situacao_obj.get("nome", "") if isinstance(situacao_obj, dict) else str(situacao_obj)

    # Dados do cliente / contato
    contato = pedido.get("contato") or {}
    cliente = contato.get("nome", "")
    # CPF/CNPJ: campo padrão é "cpfCnpj"; fallback para "numeroDocumento"
    # em versões mais antigas do payload.
    cpf_cnpj = contato.get("cpfCnpj") or contato.get("numeroDocumento", "")

    # Endereço de entrega (UF e cidade)
    endereco = pedido.get("transporte", {}).get("enderecoEntrega") or {}
    estado = endereco.get("uf", "")
    cidade = endereco.get("municipio", "")

    # Vendedor
    vendedor_obj = pedido.get("vendedor") or {}
    vendedor = vendedor_obj.get("nome", "") if isinstance(vendedor_obj, dict) else str(vendedor_obj)

    # Loja de origem
    loja_obj = pedido.get("loja") or {}
    nome_loja = loja_obj.get("descricao", loja_obj.get("nome", "")) if isinstance(loja_obj, dict) else str(loja_obj)

    # Itens do pedido
    itens = pedido.get("itens") or []

    if not itens:
        # Pedido sem itens: gera uma linha com campos de produto em branco
        return [
            {
                "numero_pedido": numero_pedido,
                "data_pedido": data_pedido,
                "cliente": cliente,
                "cpf_cnpj": cpf_cnpj,
                "faturamento": faturamento,
                "produto": "",
                "unidade": "",
                "quantidade": "",
                "valor_unitario": "",
                "estado": estado,
                "cidade": cidade,
                "vendedor": vendedor,
                "nome_loja": nome_loja,
                "situacao": situacao,
            }
        ]

    linhas = []
    for item in itens:
        produto_obj = item.get("produto") or {}
        nome_produto = produto_obj.get("nome", item.get("descricao", ""))
        unidade = item.get("unidade", produto_obj.get("unidade", ""))
        quantidade = item.get("quantidade", "")
        # Valor unitário: campo primário é "valor"; fallback para
        # "valorUnitario" conforme variação do payload da API.
        valor_unitario = item.get("valor") or item.get("valorUnitario", "")

        linhas.append(
            {
                "numero_pedido": numero_pedido,
                "data_pedido": data_pedido,
                "cliente": cliente,
                "cpf_cnpj": cpf_cnpj,
                "faturamento": faturamento,
                "produto": nome_produto,
                "unidade": unidade,
                "quantidade": quantidade,
                "valor_unitario": valor_unitario,
                "estado": estado,
                "cidade": cidade,
                "vendedor": vendedor,
                "nome_loja": nome_loja,
                "situacao": situacao,
            }
        )

    return linhas


# ---------------------------------------------------------------------------
# Fluxo principal
# ---------------------------------------------------------------------------

def main():
    """Extrai todos os pedidos de venda da API do Bling e salva em CSV."""
    print("Iniciando extração de pedidos de venda do Bling...")

    todas_linhas = []
    pagina_atual = 1
    total_pedidos_processados = 0

    while True:
        print(f"  Buscando página {pagina_atual}...")

        try:
            dados = buscar_pagina_pedidos(pagina_atual)
        except Exception as erro:
            print(f"[ERRO] {erro}")
            break

        pedidos = dados.get("data", [])

        # Quando a lista de pedidos estiver vazia, chegamos ao fim
        if not pedidos:
            print("  Nenhum pedido encontrado nesta página. Extração concluída.")
            break

        for pedido_resumido in pedidos:
            id_pedido = pedido_resumido.get("id")

            if id_pedido is None:
                continue

            try:
                detalhe = buscar_detalhe_pedido(id_pedido)
                pedido_completo = detalhe.get("data", detalhe)
                linhas = extrair_linhas_pedido(pedido_completo)
                todas_linhas.extend(linhas)
                total_pedidos_processados += 1
            except Exception as erro:
                print(f"  [AVISO] Pedido {id_pedido} ignorado por erro: {erro}")

            # Pequeno delay para evitar atingir o rate-limit da API
            time.sleep(DELAY_ENTRE_PAGINAS)

        # Verifica se há mais páginas usando os metadados retornados pela API
        meta = dados.get("meta") or {}
        paginacao = meta.get("paginacao") or {}
        total_paginas = paginacao.get("totalPages") if isinstance(paginacao, dict) else None

        if total_paginas is not None and pagina_atual >= total_paginas:
            print("  Última página atingida.")
            break

        # Se a API não informar o total de páginas, para quando a página
        # retornar menos registros do que o limite solicitado (100)
        if len(pedidos) < 100 and total_paginas is None:
            print("  Página com menos registros que o limite. Extração concluída.")
            break

        pagina_atual += 1
        # Delay entre páginas
        time.sleep(DELAY_ENTRE_PAGINAS)

    print(f"\nTotal de pedidos processados: {total_pedidos_processados}")
    print(f"Total de linhas geradas: {len(todas_linhas)}")

    if not todas_linhas:
        print(
            "Nenhum dado para salvar. Verifique se o ACCESS_TOKEN é válido, "
            "se existem pedidos de venda cadastrados e se nenhum filtro "
            "excluiu todos os registros."
        )
        return

    df = pd.DataFrame(todas_linhas, columns=COLUNAS)
    arquivo_saida = "vendas_bling.csv"
    df.to_csv(arquivo_saida, index=False, encoding="utf-8-sig")
    print(f"\nArquivo salvo com sucesso: {arquivo_saida}")


if __name__ == "__main__":
    main()
