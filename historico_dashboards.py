"""Histórico local de dashboards gerados, por cliente — cada vez que
um dashboard é gerado, os números-chave ficam salvos aqui. A próxima
vez que alguém gerar um dashboard pro MESMO cliente (casado por CNPJ,
ou por nome se não tiver CNPJ), os períodos anteriores aparecem
sozinhos no gráfico de tendência, sem precisar digitar de novo.

`data/historico_dashboards.json` — local, gitignored (tem número
financeiro real de cliente).
"""

import datetime
import json
from pathlib import Path

PASTA_DADOS = Path(__file__).resolve().parent / "data"
ARQUIVO = PASTA_DADOS / "historico_dashboards.json"
MAXIMO_POR_CLIENTE = 24  # 2 anos de competências mensais — não cresce sem limite


def _chave_cliente(cliente_nome, cliente_cnpj):
    """CNPJ é o identificador mais confiável (nome pode ter variação de
    digitação entre uma geração e outra) — só cai pro nome se não tiver
    CNPJ informado."""
    cnpj_limpo = "".join(c for c in (cliente_cnpj or "") if c.isdigit())
    return cnpj_limpo or (cliente_nome or "").strip().lower()


def registrar(cliente_nome, cliente_cnpj, competencia, dre, balancete):
    """Salva os números-chave deste dashboard no histórico do cliente.
    Não salva o comentário do contador nem nenhum dado além do
    necessário pro gráfico de tendência (minimização, seção 5.5 do
    ecossistema)."""
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    todos = _carregar_tudo()
    chave = _chave_cliente(cliente_nome, cliente_cnpj)

    lista_cliente = todos.get(chave, [])
    lista_cliente.append({
        "competencia": competencia,
        "quando_gerado": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
        "receita_liquida": dre["receita_liquida"],
        "lucro_liquido": dre["lucro_liquido"],
        "margem_liquida": dre["margem_liquida"],
        "ativo_total": balancete["ativo_total"],
        "patrimonio_liquido": balancete["patrimonio_liquido"],
        "liquidez_corrente": balancete["liquidez_corrente"],
    })
    todos[chave] = lista_cliente[-MAXIMO_POR_CLIENTE:]
    ARQUIVO.write_text(json.dumps(todos, ensure_ascii=False, indent=2), encoding="utf-8")


def historico_do_cliente(cliente_nome, cliente_cnpj, excluir_ultimo=False):
    """Devolve a lista de períodos já registrados pra esse cliente,
    mais antigo primeiro (ordem de gráfico de tendência). `excluir_ultimo`
    remove o registro mais recente — usado logo depois de `registrar()`
    quando quem chama já tem os dados do período atual à mão e só quer
    o histórico ANTERIOR a ele, pra não duplicar no gráfico."""
    todos = _carregar_tudo()
    lista = list(todos.get(_chave_cliente(cliente_nome, cliente_cnpj), []))
    if excluir_ultimo and lista:
        lista = lista[:-1]
    return lista


def _carregar_tudo():
    try:
        return json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return {}
