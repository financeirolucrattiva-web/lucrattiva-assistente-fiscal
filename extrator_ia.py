"""Extração de DRE/Balancete por IA — substitui a busca de texto por
rótulo (`leitor_arquivos.sugerir_campos()`, que errou contra os
arquivos reais do BRLOIO AGROPECUARIA: pegou a coluna "Crédito" em vez
de "Saldo Atual" no balancete, e não achou IRPJ/CSLL porque, nesse
arquivo, eles aparecem DENTRO de "Deduções da Receita", não como linha
própria — achado real, 05/10/2026).

Manda o(s) PDF(s) direto pro Claude como documento (não como texto já
extraído) — o modelo lê a tabela com a estrutura visual, não um texto
corrido que embaralhou coluna. Arquivo Excel continua usando a
extração local (`leitor_arquivos.py`) e entra como texto na mesma
mensagem, porque a Claude API não aceita .xlsx como bloco de documento
(só PDF e texto).

Sempre devolve os valores como SUGESTÃO pra conferência — mesmo IA
entendendo o documento, nunca é usado sem revisão humana (mesmo
princípio do resto do projeto).
"""

import base64
import json
from pathlib import Path

import anthropic

MODELO = "claude-opus-5-5"  # tarefa exige entender tabela/layout de verdade, não é classificação simples

_CAMPOS = [
    "receita_bruta", "deducoes", "cmv", "despesas_operacionais",
    "resultado_financeiro", "irpj_csll", "ativo_circulante",
    "ativo_nao_circulante", "passivo_circulante", "passivo_nao_circulante",
    "patrimonio_liquido",
]

_SISTEMA = """Você lê documentos contábeis brasileiros (DRE — Demonstração do \
Resultado do Exercício, e Balancete de Verificação) e extrai valores pra um \
formulário fixo. A estrutura varia de empresa pra empresa — raciocine sobre \
o que cada conta REPRESENTA, não espere um rótulo exato.

Regras de extração:

- "receita_bruta": total de receita bruta de vendas/serviços, ANTES de \
qualquer dedução.
- "deducoes": some TODAS as deduções da receita bruta (impostos sobre venda, \
devoluções, descontos incondicionais, SENAR/FETHAB e contribuições do tipo, \
e também IRPJ/CSLL SE estiverem classificados como dedução da receita nesse \
arquivo específico — alguns planos de contas rurais fazem isso). Não conte \
a mesma conta duas vezes.
- "cmv": custo das mercadorias/produtos/serviços vendidos.
- "despesas_operacionais": use o total da linha "DESPESAS OPERACIONAIS" em \
si (o valor que aparece logo junto desse rótulo, geralmente ANTES de \
qualquer subcategoria como "Despesas Administrativas" ser detalhada) — \
NUNCA o subtotal de uma subcategoria aninhada mais abaixo (ex.: o total só \
de "Despesas Administrativas", que é menor que o total geral porque não \
inclui "Despesas Gerais" e outras). Se não existir uma linha "DESPESAS \
OPERACIONAIS" pronta, aí sim some as subcategorias (administrativas + \
comerciais + gerais).
- "resultado_financeiro": receitas financeiras MENOS despesas financeiras \
(pode ser negativo). Se o documento já traz um "Resultado Financeiro" \
pronto, use ele; se traz "Receitas Financeiras" e "Despesas Financeiras" \
separadas, subtraia.
- "irpj_csll": só preencha aqui se IRPJ/CSLL aparecer como linha PRÓPRIA, \
separada, geralmente perto do resultado final (não a mesma conta já somada \
em "deducoes" — nunca conte a mesma linha duas vezes em campos diferentes).
- No Balancete, cada conta de totalização (Ativo, Ativo Circulante, Ativo \
Não Circulante, Passivo Circulante, Passivo Não Circulante, Patrimônio \
Líquido) tem várias colunas de valor (ex.: Saldo Anterior, Débito, Crédito, \
Saldo Atual) — use SEMPRE a coluna de saldo FINAL/ATUAL do período (a \
última coluna de valor da linha, geralmente chamada "Saldo Atual" ou \
"Saldo Final"), nunca Débito/Crédito/Saldo Anterior.
- Use o valor da linha de TOTAL da categoria (ex.: "1.1 ATIVO CIRCULANTE"), \
nunca some as subcontas você mesmo se já existe uma linha de total pronta.
- "cliente_nome_sugerido": razão social da empresa (campo "Empresa" no \
cabeçalho). "competencia_sugerida": período do documento, em formato curto \
tipo "Junho/2026" ou "Jan-Jun/2026" se for período composto.
- Campo que não aparece no documento: use `null`, nunca invente ou estime.
- "notas": 1-3 frases curtas em português explicando qualquer soma ou \
cálculo que você fez (ex.: "Deduções = SENAR + IRPJ + CSLL + FETHAB, \
listados juntos no documento") — League pra quem for conferir saber o que \
checar primeiro. Vazio ("") se não houve nenhum cálculo, só leitura direta.

Todo valor numérico é POSITIVO (magnitude) — despesas/deduções não vêm \
negativas, EXCETO "resultado_financeiro", que pode ser negativo de verdade \
(despesa financeira líquida)."""

_FORMATO = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            **{campo: {"type": ["number", "null"]} for campo in _CAMPOS},
            "cliente_nome_sugerido": {"type": ["string", "null"]},
            "competencia_sugerida": {"type": ["string", "null"]},
            "notas": {"type": "string"},
        },
        "required": _CAMPOS + ["cliente_nome_sugerido", "competencia_sugerida", "notas"],
        "additionalProperties": False,
    },
}


def extrair_campos_com_ia(caminhos, chave_api, textos_excel=None):
    """`caminhos`: lista de `Path` de PDF já salvos em disco.
    `textos_excel`: lista opcional de (nome_arquivo, texto_extraido) pra
    arquivo Excel — já extraído por `leitor_arquivos.py`, entra como
    texto na mensagem porque a API não aceita .xlsx como documento.

    Devolve `(sugestoes_dict_ou_None, erro_ou_None)`. `sugestoes_dict`
    tem os campos de `_CAMPOS` + `cliente_nome_sugerido` +
    `competencia_sugerida` + `notas` — qualquer campo não encontrado
    vem como `None`, nunca inventado.
    """
    blocos_conteudo = []
    for caminho in caminhos:
        caminho = Path(caminho)
        try:
            dados_b64 = base64.standard_b64encode(caminho.read_bytes()).decode("utf-8")
        except OSError as erro:
            return None, f"Não consegui ler {caminho.name}: {erro!r}"
        blocos_conteudo.append({
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": dados_b64},
            "title": caminho.name,
        })

    for nome_arquivo, texto in (textos_excel or []):
        blocos_conteudo.append({
            "type": "text",
            "text": f"Conteúdo extraído da planilha '{nome_arquivo}':\n\n{texto[:20000]}",
        })

    if not blocos_conteudo:
        return None, "Nenhum arquivo legível pra mandar pra IA."

    blocos_conteudo.append({
        "type": "text",
        "text": "Extraia os campos do formulário a partir do(s) documento(s) acima.",
    })

    try:
        cliente = anthropic.Anthropic(api_key=chave_api)
        resposta = cliente.messages.create(
            model=MODELO,
            # 1024 era baixo demais — achado real, 05/10/2026: com 2
            # documentos maiores (balancete de imobiliária, mais
            # contas), bateu no teto antes de terminar o JSON (Opus
            # sempre "pensa" antes de responder, isso consome parte do
            # limite junto com a resposta em si).
            max_tokens=8192,
            system=_SISTEMA,
            messages=[{"role": "user", "content": blocos_conteudo}],
            output_config={"format": _FORMATO},
        )
    except anthropic.AuthenticationError:
        return None, "Chave da API inválida."
    except anthropic.RateLimitError:
        return None, "Limite de uso da API atingido — tente de novo em instantes."
    except anthropic.APIError as erro:
        return None, f"Erro da API da Anthropic: {erro}"

    if resposta.stop_reason != "end_turn":
        return None, f"Resposta incompleta da IA ({resposta.stop_reason})."

    texto_resposta = next((b.text for b in resposta.content if b.type == "text"), "")
    try:
        return json.loads(texto_resposta), None
    except json.JSONDecodeError as erro:
        return None, f"IA respondeu num formato inesperado: {erro!r}"
