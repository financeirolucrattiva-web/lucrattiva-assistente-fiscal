"""Cálculo dos indicadores do dashboard DRE + Balancete — lógica pura,
sem nada de Flask/HTML aqui (mais fácil de testar e de trocar a fonte
dos dados depois, quando tiver parser de arquivo real).

v1: os valores vêm de um formulário preenchido à mão (ver
`templates/dashboard_form.html`) — ainda não lê PDF/Excel do Domínio
Contabilidade. Pedir um arquivo real de DRE/Balancete antes de propor
um parser automático é o próximo passo (mesmo princípio de sempre:
nunca adivinhar formato de arquivo sem ver um de verdade).
"""


def _dividir_seguro(numerador, denominador):
    """Evita ZeroDivisionError quando o denominador é 0 (empresa sem
    receita no período, por exemplo) — devolve None em vez de
    quebrar; quem exibe decide como mostrar "—"."""
    if not denominador:
        return None
    return numerador / denominador


def calcular_dre(receita_bruta, deducoes, cmv, despesas_operacionais, resultado_financeiro, irpj_csll):
    receita_liquida = receita_bruta - deducoes
    lucro_bruto = receita_liquida - cmv
    resultado_operacional = lucro_bruto - despesas_operacionais
    resultado_antes_ir = resultado_operacional + resultado_financeiro
    lucro_liquido = resultado_antes_ir - irpj_csll

    return {
        "receita_bruta": receita_bruta,
        "deducoes": deducoes,
        "receita_liquida": receita_liquida,
        "cmv": cmv,
        "lucro_bruto": lucro_bruto,
        "despesas_operacionais": despesas_operacionais,
        "resultado_operacional": resultado_operacional,
        "resultado_financeiro": resultado_financeiro,
        "resultado_antes_ir": resultado_antes_ir,
        "irpj_csll": irpj_csll,
        "lucro_liquido": lucro_liquido,
        "margem_bruta": _dividir_seguro(lucro_bruto, receita_liquida),
        "margem_liquida": _dividir_seguro(lucro_liquido, receita_liquida),
    }


def calcular_balancete(ativo_circulante, ativo_nao_circulante, passivo_circulante, passivo_nao_circulante, patrimonio_liquido):
    ativo_total = ativo_circulante + ativo_nao_circulante
    passivo_mais_pl = passivo_circulante + passivo_nao_circulante + patrimonio_liquido
    # Diferença entre Ativo e Passivo+PL deveria ser 0 (balancete
    # fechado) — se não fechar, é sinal de erro de digitação (os
    # valores vieram de um formulário à mão, não de uma exportação
    # validada), então isso é mostrado como alerta, não escondido.
    diferenca_fechamento = ativo_total - passivo_mais_pl

    return {
        "ativo_circulante": ativo_circulante,
        "ativo_nao_circulante": ativo_nao_circulante,
        "ativo_total": ativo_total,
        "passivo_circulante": passivo_circulante,
        "passivo_nao_circulante": passivo_nao_circulante,
        "patrimonio_liquido": patrimonio_liquido,
        "passivo_mais_pl": passivo_mais_pl,
        "diferenca_fechamento": diferenca_fechamento,
        "balancete_fechado": abs(diferenca_fechamento) < 0.01,
        "liquidez_corrente": _dividir_seguro(ativo_circulante, passivo_circulante),
        "endividamento": _dividir_seguro(passivo_circulante + passivo_nao_circulante, ativo_total),
    }


def composicao_receita(dre):
    """Quebra a receita líquida em fatias (CMV, despesas operacionais,
    resultado financeiro negativo, impostos sobre lucro, lucro líquido)
    — "pra onde foi cada R$ 1,00 de receita". Devolve uma lista de
    `(rotulo, valor, fracao_0_a_1)`, só com fatias > 0 (uma despesa
    financeira líquida POSITIVA, por exemplo, não vira fatia negativa
    confusa no gráfico — fica de fora, já que o resultado financeiro só
    "consome" receita quando é negativo)."""
    base = dre["receita_liquida"]
    if base <= 0:
        return []

    # Cor fixa por conta (não por posição) — a lista final só mostra
    # fatias > 0, então a posição de cada item muda de empresa pra
    # empresa; a cor não pode.
    fatias_brutas = [
        ("Custos (CMV/CPV)", dre["cmv"], "#b9bec7"),
        ("Despesas operacionais", dre["despesas_operacionais"], "#8d97a3"),
        ("Despesas financeiras", max(0.0, -dre["resultado_financeiro"]), "var(--viz-critico)"),
        ("IRPJ/CSLL", dre["irpj_csll"], "var(--marca-dourado-claro)"),
        ("Lucro líquido", max(0.0, dre["lucro_liquido"]), "var(--marca-verde)"),
    ]
    fatias = [
        {"rotulo": rotulo, "valor": valor, "fracao": valor / base, "cor": cor}
        for rotulo, valor, cor in fatias_brutas if valor > 0
    ]
    return fatias


def construir_grafico_tendencia(pontos, largura=560, altura=200):
    """Monta as coordenadas SVG de um gráfico de linha (Receita Líquida
    e Lucro Líquido ao longo dos períodos) — devolve um dict pronto pro
    template desenhar, sem Jinja precisar fazer conta nenhuma.

    `pontos`: lista de dicts com `competencia`, `receita_liquida`,
    `lucro_liquido`, mais antigo primeiro. Com 0 ou 1 ponto, devolve
    `None` — gráfico de tendência não faz sentido com um ponto só (o
    template mostra uma mensagem simples nesse caso, não um gráfico
    vazio)."""
    if len(pontos) < 2:
        return None

    margem_esq, margem_dir, margem_cima, margem_baixo = 44, 16, 16, 28
    largura_util = largura - margem_esq - margem_dir
    altura_util = altura - margem_cima - margem_baixo

    todos_valores = [p["receita_liquida"] for p in pontos] + [p["lucro_liquido"] for p in pontos]
    maximo = max(todos_valores + [1])
    minimo = min(todos_valores + [0])
    # Nunca deixa o eixo começar acima de 0 — lucro pode ser a única
    # série negativa num mês ruim, e o gráfico precisa mostrar isso,
    # não cortar fora.
    minimo = min(minimo, 0)
    amplitude = (maximo - minimo) or 1

    def x_de(indice):
        if len(pontos) == 1:
            return margem_esq
        return margem_esq + (indice / (len(pontos) - 1)) * largura_util

    def y_de(valor):
        fracao = (valor - minimo) / amplitude
        return margem_cima + altura_util - (fracao * altura_util)

    pontos_receita = [(x_de(i), y_de(p["receita_liquida"])) for i, p in enumerate(pontos)]
    pontos_lucro = [(x_de(i), y_de(p["lucro_liquido"])) for i, p in enumerate(pontos)]

    caminho_receita = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pontos_receita)
    caminho_lucro = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pontos_lucro)

    y_linha_zero = y_de(0)

    return {
        "largura": largura,
        "altura": altura,
        "caminho_receita": caminho_receita,
        "caminho_lucro": caminho_lucro,
        "pontos_receita": pontos_receita,
        "pontos_lucro": pontos_lucro,
        "rotulos_x": [p["competencia"] for p in pontos],
        "y_linha_zero": y_linha_zero,
        "mostra_linha_zero": minimo < 0,
    }


def construir_gauge_liquidez(valor, maximo_escala=2.5, raio=76):
    """Monta um velocímetro semicircular (SVG) pra Liquidez Corrente —
    geometria calculada aqui em Python (trigonometria não tem em Jinja
    puro), o template só desenha os `path` prontos.

    Faixas de cor (prática contábil comum): abaixo de 1 é zona de
    alerta (não cobre o passivo circulante com o ativo circulante);
    entre 1 e 1,5 é uma zona de atenção; acima de 1,5 é confortável.
    `maximo_escala` é só o teto visual do mostrador (1 valor de
    liquidez de 5, por exemplo, não estoura o gauge pra fora da tela —
    fica cravado em 100% com uma nota).
    """
    import math

    cx, cy = 100, 90
    if valor is None:
        fracao = 0.0
        cor = "#b9bec7"
    else:
        fracao = max(0.0, min(valor / maximo_escala, 1.0))
        if valor < 1:
            cor = "var(--viz-critico)"
        elif valor < 1.5:
            cor = "var(--viz-aviso)"
        else:
            cor = "var(--viz-bom)"

    def ponto(angulo_graus):
        angulo = math.radians(angulo_graus)
        return cx + raio * math.cos(angulo), cy - raio * math.sin(angulo)

    x_esq, y_esq = ponto(180)
    x_dir, y_dir = ponto(0)
    angulo_valor = 180 - fracao * 180
    x_val, y_val = ponto(angulo_valor)

    caminho_fundo = f"M {x_esq:.1f},{y_esq:.1f} A {raio},{raio} 0 0 1 {x_dir:.1f},{y_dir:.1f}"
    caminho_valor = f"M {x_esq:.1f},{y_esq:.1f} A {raio},{raio} 0 0 1 {x_val:.1f},{y_val:.1f}"

    return {
        "cx": cx, "cy": cy, "raio": raio,
        "caminho_fundo": caminho_fundo,
        "caminho_valor": caminho_valor,
        "cor": cor,
        "estourou_escala": valor is not None and valor > maximo_escala,
    }


def calcular_variacao(valor_atual, valor_anterior):
    """Devolve a variação percentual entre dois períodos, ou `None` se
    não tiver período anterior informado ou se o anterior for zero."""
    if valor_anterior is None:
        return None
    return _dividir_seguro(valor_atual - valor_anterior, abs(valor_anterior))


_CAMPOS_COMPARATIVO = (
    "receita_liquida", "lucro_liquido", "margem_liquida",
    "ativo_total", "patrimonio_liquido", "liquidez_corrente",
)


def montar_tabela_comparativa(pontos):
    """Tabela período a período com os 6 indicadores do histórico (não só
    receita/lucro do gráfico de tendência) e a variação de cada um vs o
    período anterior — "dados comparativos históricos", pedido do
    usuário (06/10/2026). `pontos`: mesma lista usada no gráfico de
    tendência, mais antigo primeiro. Primeira linha não tem variação
    (não existe período anterior a ela)."""
    linhas = []
    anterior = None
    for p in pontos:
        linha = {"competencia": p.get("competencia")}
        for campo in _CAMPOS_COMPARATIVO:
            valor = p.get(campo)
            linha[campo] = valor
            linha[f"{campo}_variacao"] = (
                calcular_variacao(valor, anterior[campo])
                if anterior is not None and valor is not None else None
            )
        linhas.append(linha)
        anterior = linha
    return linhas


_ROTULOS_TENDENCIA = {
    "margem_liquida": "margem líquida",
    "liquidez_corrente": "liquidez corrente",
    "lucro_liquido": "lucro líquido",
}


def detectar_tendencias(linhas, minimo_sequencia=3):
    """Aponta indicador subindo ou caindo em sequência nos últimos N
    períodos — só padrão numérico determinístico (sem IA, sem inventar
    causa): um humano decide se é motivo de atenção ou acaso. Devolve
    lista de frases prontas pra exibir; vazia se não há sequência longa
    o bastante em nenhum indicador."""
    avisos = []
    for campo, rotulo in _ROTULOS_TENDENCIA.items():
        pontos_validos = [(l["competencia"], l[campo]) for l in linhas if l.get(campo) is not None]
        if len(pontos_validos) < minimo_sequencia:
            continue
        ultimos = pontos_validos[-minimo_sequencia:]
        valores = [v for _, v in ultimos]
        if all(valores[i] < valores[i - 1] for i in range(1, len(valores))):
            avisos.append(f"⚠️ {rotulo.capitalize()} caindo há {minimo_sequencia} períodos seguidos (desde {ultimos[0][0]})")
        elif all(valores[i] > valores[i - 1] for i in range(1, len(valores))):
            avisos.append(f"✓ {rotulo.capitalize()} subindo há {minimo_sequencia} períodos seguidos (desde {ultimos[0][0]})")
    return avisos
