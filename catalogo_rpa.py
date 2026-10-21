"""Catálogo das rotinas de RPA do `dominio-automation-engine` (motor que
opera o Domínio Escrita Fiscal via OCR/clique sintético) — fonte única
de verdade pro que os 57 agentes fiscais sabem sobre "o que já dá pra
automatizar hoje". Mantido à mão aqui (não lido do outro repositório em
tempo de execução, de propósito: os dois projetos são separados por
risco — ver `CLAUDE.md`/`docs/HANDOFF.md` de lá — e um catálogo copiado
é mais robusto que uma dependência entre repositórios).

Pedido do usuário (06/10/2026): "ajuste os agentes para que eles
futuramente possam sugerir funções repetitivas da domínio que podemos
automatizar com meu RPA (...) queremos que ele aprenda a solicitar e
abrir por lá". Escopo de HOJE, por trava de segurança já combinada no
`dominio-automation-engine` (ver `projeto-dominio-automation-engine` na
memória — "chat só converte linguagem natural numa chamada estruturada
de uma rotina JÁ EXISTENTE E REVISADA, nunca decide ação livre"): os
agentes aprendem a SUGERIR em texto, nunca a executar nada sozinhos.
Acionar de verdade (o "solicitar e abrir por lá") é o próximo passo,
depois que a validação de conteúdo das rotinas já prontas e o piloto em
andamento (Registro de Saídas) fecharem — ver `STATUS_GERAL` abaixo.

**Atualize este arquivo manualmente sempre que o status de uma rotina
mudar no `dominio-automation-engine`** — é o único lugar que precisa
mudar pra todos os 57 agentes saberem da atualização."""

from __future__ import annotations

# Setas de confiança, da mais fraca pra mais forte — usadas tal e qual
# no texto que vai pro prompt, pra nunca inflar status de uma rotina.
NAO_INICIADA = "NÃO INICIADA — só existe planejamento, nenhum código rodou contra o Domínio"
NUNCA_RODOU_REAL = "NUNCA RODOU CONTRA O DOMÍNIO REAL — código existe (generalizado por analogia), zero execução real"
PARCIALMENTE_VALIDADA = "PARCIALMENTE VALIDADA — parte do caminho confirmada ao vivo, falta fechar o resto"
MECANISMO_VALIDADO = "MECANISMO VALIDADO — roda ponta a ponta sem travar contra o Domínio real; o CONTEÚDO do arquivo gerado ainda não foi comparado com o que seria entregue de verdade"

ROTINAS_RPA = [
    {
        "nome": "SPED Fiscal (EFD ICMS/IPI)",
        "status": MECANISMO_VALIDADO,
        "regimes_atendidos": ["LUCRO_PRESUMIDO", "LUCRO_REAL"],
        "observacao": "Dispensado em geral pro Simples Nacional — não é candidato de automação pra esse regime.",
        "como_rodar_hoje": "scripts/explorar.py (uma empresa) ou scripts/executar_lote.py (lote) no dominio-automation-engine, sempre com supervisão humana.",
    },
    {
        "nome": "EFD Contribuições (PIS/COFINS)",
        "status": MECANISMO_VALIDADO,
        "regimes_atendidos": ["LUCRO_PRESUMIDO", "LUCRO_REAL"],
        "observacao": "Só atende Lucro Presumido/Real — não serve Simples Nacional.",
        "como_rodar_hoje": "scripts/explorar_contribuicoes.py (uma empresa) ou scripts/executar_lote.py (lote).",
    },
    {
        "nome": "Registro de Saídas (Livro Fiscal)",
        "status": PARCIALMENTE_VALIDADA,
        "regimes_atendidos": ["SIMPLES_NACIONAL", "LUCRO_PRESUMIDO", "LUCRO_REAL"],
        "observacao": (
            "Independe de regime — é o que mais fecha a lacuna pras empresas do Simples (maioria da "
            "carteira), que não são atendidas por SPED Fiscal/EFD Contribuições. Confirmado ao vivo: "
            "navegação, marcar a caixa certa, preencher período, confirmar e abrir pré-visualização. "
            "Ainda NÃO confirmada: a exportação completa pra PDF de ponta a ponta."
        ),
        "como_rodar_hoje": "scripts/explorar_registro_saidas.py — só com supervisão, ainda em validação.",
    },
    {
        "nome": "Registro de Entradas (Livro Fiscal)",
        "status": NUNCA_RODOU_REAL,
        "regimes_atendidos": ["SIMPLES_NACIONAL", "LUCRO_PRESUMIDO", "LUCRO_REAL"],
        "observacao": "Código generalizado a partir do Registro de Saídas (mesma tela, outra caixa marcada) — nunca testado contra o Domínio de verdade.",
        "como_rodar_hoje": "scripts/explorar_registro_entradas.py — só com supervisão, nunca validado.",
    },
]

STATUS_GERAL = (
    "Nenhuma rotina deste catálogo tem o CONTEÚDO do arquivo gerado validado ainda "
    "(comparado com o que seria entregue de verdade pra uma competência já fechada) — "
    "só o mecanismo (roda sem travar) foi confirmado nas que dizem MECANISMO VALIDADO. "
    "Por isso nenhum agente deve dizer que um resultado gerado pelo RPA já pode ser "
    "entregue ao cliente sem conferência humana antes."
)


def bloco_prompt_rpa() -> str:
    """Texto pronto pra entrar no system prompt de qualquer um dos 57
    agentes — explica o que é o RPA, lista o catálogo com status real,
    e deixa explícita a única coisa que o agente pode fazer com essa
    informação hoje: sugerir em texto, nunca executar."""
    linhas = [
        "\n\n---\n",
        "## Automação RPA do Domínio Escrita Fiscal — o que você sabe sobre isso",
        "",
        "O escritório tem um motor de RPA (`dominio-automation-engine`) que opera o "
        "Domínio Escrita Fiscal via OCR/clique sintético (não é integração por API — "
        "o Domínio roda via GraphOn GO-Global, só dá pra automatizar simulando um "
        "usuário na tela). Rotinas disponíveis hoje, com status real (nunca infle isso):",
        "",
    ]
    for r in ROTINAS_RPA:
        linhas.append(f"- **{r['nome']}** — {r['status']}")
        linhas.append(f"  Regimes atendidos: {', '.join(r['regimes_atendidos'])}. {r['observacao']}")
    linhas += [
        "",
        STATUS_GERAL,
        "",
        "**O que você PODE fazer com essa informação:** se a pessoa descrever uma tarefa "
        "manual repetitiva no Domínio que bate com uma destas rotinas, avise que já existe "
        "(ou está em validação) uma automação pra isso, cite o status real tal como listado "
        "acima, e diga como rodar hoje (sempre com supervisão humana, nunca sozinho).",
        "",
        "**O que você NUNCA faz:** executar, abrir, clicar ou disparar qualquer ação no "
        "Domínio por conta própria — você não tem esse acesso, e mesmo quando essa ponte "
        "existir no futuro, a regra combinada é que a automação só roda uma rotina já "
        "existente e revisada, nunca uma ação livre decidida por IA. Se a pessoa pedir pra "
        "você 'rodar' ou 'abrir' algo agora, explique que ainda não existe esse botão — "
        "quem roda é um humano, pelo script do próprio motor.",
    ]
    return "\n".join(linhas)
