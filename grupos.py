"""Agrupa os 57 agentes fiscais em no máximo 6 "assistentes" gerais —
pedido do usuário (2026-10-02): 57 opções é demais pra quem não é
técnico escolher. Cada grupo tem uma lista fechada de especialistas
(`agentes`); a escolha de QUAL especialista responde uma pergunta
específica é feita em tempo de chat (ver `app.py::escolher_especialista`),
não aqui — isto aqui só define a composição de cada grupo.

Agrupamento por área de trabalho real do escritório, não por
similaridade técnica abstrata — pensado pra bater com "quem no
escritório cuidaria disso", não com a estrutura interna dos agentes.
"""

GRUPOS = {
    "fiscal-apuracao": {
        "nome": "Fiscal — Apuração de Tributos",
        "descricao": (
            "DAS (Simples), ICMS/ISS, PIS/COFINS, IRPJ/CSLL, SPED Fiscal, "
            "EFD Contribuições, IPI, MEI, retenções, DCTFWeb, Reinf, "
            "conferência de guia, DIMOB, DMED, Reforma Tributária (CBS/IBS)."
        ),
        "agentes": [
            "apuracao-simples-nacional", "icms-iss", "pis-cofins", "irpj-csll",
            "sped-fiscal", "efd-contribuicoes", "calculo-ipi", "apuracao-mei",
            "retencoes-tributarias-tomador", "dctfweb", "efd-reinf",
            "conferencia-guia", "reforma-tributaria-cbs-ibs",
            "recuperacao-creditos-pis-cofins", "dimob", "dmed",
        ],
    },
    "departamento-pessoal": {
        "nome": "Departamento Pessoal — Folha e eSocial",
        "descricao": (
            "Folha de pagamento, holerite, férias, 13º salário, rescisão, "
            "admissão, INSS/FGTS, IRRF sobre folha, eventos eSocial."
        ),
        "agentes": [
            "folha-pagamento-mensal", "holerite", "ferias-13-salario",
            "rescisao-clt-calculo", "inss-fgts", "admissao", "esocial",
            "calculo-irrf-folha",
        ],
    },
    "contabilidade-fechamento": {
        "nome": "Contabilidade — Fechamento e Relatórios",
        "descricao": (
            "Conciliação bancária/cartões/clientes/fornecedores, fechamento "
            "mensal, balancete, DRE gerencial, relatório ao cliente, fluxo "
            "de caixa, ativo imobilizado, plano de contas, ECD/ECF, "
            "lançamentos contábeis padrão."
        ),
        "agentes": [
            "conciliacao-bancaria", "conciliacao-cartoes-credenciadora",
            "conciliacao-fornecedores", "conciliacao-clientes",
            "fechamento-mensal", "balancete-analise",
            "ativo-imobilizado-depreciacao", "plano-contas-cpc",
            "lancamentos-contabeis-padrao", "ecf-ecd", "dre-gerencial",
            "relatorio-mensal", "fluxo-caixa-projetado",
        ],
    },
    "societario": {
        "nome": "Societário — Abrir, Alterar e Encerrar Empresas",
        "descricao": (
            "Abertura de empresa (REDESIM), alteração contratual (sócios, "
            "capital, endereço), encerramento/baixa."
        ),
        "agentes": ["abertura-empresa-cnpj", "alteracao-contratual", "encerramento-empresa-baixa"],
    },
    "planejamento-defesa-fiscal": {
        "nome": "Planejamento Tributário e Defesa Fiscal",
        "descricao": (
            "Comparativo de regime (Simples × Presumido × Real), "
            "cruzamento de SPEDs, malha fina (PF/PJ), resposta a "
            "fiscalização/intimação, parcelamento de débitos, due "
            "diligence, valuation, IRPF completa."
        ),
        "agentes": [
            "analise-tributaria-regime", "revisao-fiscal-cruzamento-sped",
            "malha-fina-pf-diagnostico", "malha-fina-pj-diagnostico",
            "resposta-fiscalizacao-intimacao", "parcelamento-receita-federal",
            "due-diligence-contabil", "valuation-pme", "irpf-declaracao-completa",
        ],
    },
    "atendimento-gestao": {
        "nome": "Atendimento e Gestão do Escritório",
        "descricao": (
            "Triagem de WhatsApp, documentos pendentes do cliente, "
            "onboarding de cliente novo, follow-up, cadastro de notas "
            "fiscais, prazos/calendário fiscal, cobrança de honorários, "
            "backup do escritório."
        ),
        "agentes": [
            "triagem-whatsapp", "documentos-pendentes", "onboarding-cliente",
            "follow-up-cliente", "cadastro-nf", "lembrete-prazo",
            "backup-escritorio", "cobranca-honorarios",
        ],
    },
}


def listar_grupos():
    """Devolve a lista de grupos no formato pra `/api/agentes` — sem a
    lista interna de ids de agente (detalhe de implementação, não
    precisa ir pro front-end)."""
    return [
        {"id": grupo_id, "nome": g["nome"], "descricao": g["descricao"]}
        for grupo_id, g in GRUPOS.items()
    ]


def agentes_do_grupo(grupo_id):
    """Devolve a lista de ids de agente de um grupo, ou `[]` se o grupo
    não existir."""
    grupo = GRUPOS.get(grupo_id)
    return list(grupo["agentes"]) if grupo else []
