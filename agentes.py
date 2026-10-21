"""Carrega os 57 agentes fiscais (arquivos Markdown com frontmatter)
de `~/.claude/agents` — os mesmos usados no Claude Code, reaproveitados
aqui como "personas" de chat: a descrição vira o resumo mostrado na
lista, o corpo do arquivo (depois do frontmatter) vira o prompt de
sistema mandado pra API da Anthropic, sem alteração nenhuma.

Não copia nem duplica os arquivos — lê direto de `~/.claude/agents`
toda vez que a lista é pedida, então uma correção feita lá (como as
que já foram feitas no projeto `dominio-automation-engine`) aparece
aqui automaticamente, sem precisar sincronizar nada.
"""

from pathlib import Path

PASTA_AGENTES = Path.home() / ".claude" / "agents"


def _parse_frontmatter(texto):
    """Frontmatter destes arquivos é sempre `chave: valor` de uma linha
    só (sem bloco YAML aninhado) — por isso um parser simples resolve,
    sem precisar de dependência de YAML. Devolve (dict_frontmatter, corpo)."""
    partes = texto.split("---", 2)
    if len(partes) < 3:
        return {}, texto

    bloco_frontmatter = partes[1]
    corpo = partes[2].strip()

    dados = {}
    for linha in bloco_frontmatter.splitlines():
        linha = linha.strip()
        if not linha or ":" not in linha:
            continue
        chave, _, valor = linha.partition(":")
        dados[chave.strip()] = valor.strip()

    return dados, corpo


def carregar_agentes():
    """Devolve uma lista de dicts, um por agente, ordenada por nome de
    arquivo (mesma ordem numerada do pacote original):
    `{"id": "cadastro-nf", "arquivo": "24-cadastro-nf", "nome": ..., "descricao": ..., "prompt_sistema": ...}`.

    Agentes sem `name:`/`description:` no frontmatter (ex.: arquivo
    corrompido) são ignorados silenciosamente — não derruba a lista
    inteira por causa de um arquivo com problema."""
    agentes = []
    if not PASTA_AGENTES.exists():
        return agentes

    for caminho in sorted(PASTA_AGENTES.glob("*.md")):
        try:
            texto = caminho.read_text(encoding="utf-8")
        except OSError:
            continue

        frontmatter, corpo = _parse_frontmatter(texto)
        nome = frontmatter.get("name")
        descricao = frontmatter.get("description")
        if not nome or not corpo:
            continue

        agentes.append({
            "id": nome,
            "arquivo": caminho.stem,
            "nome": nome,
            "descricao": descricao or "",
            "prompt_sistema": corpo,
        })

    return agentes


def buscar_agente(agente_id):
    """Acha um agente pelo `id` (campo `name:` do frontmatter). Devolve
    `None` se não achar — quem chama decide o que fazer (404, erro)."""
    for agente in carregar_agentes():
        if agente["id"] == agente_id:
            return agente
    return None
