"""Assistente Fiscal Lucrattiva — chat web local, pra equipe do
escritório conversar com os 57 agentes fiscais sem precisar instalar
Claude Code.

A pessoa escolhe um de 6 "assistentes" gerais (`grupos.py`), não um
entre 57 — pedido do usuário (2026-10-02), 57 opções é demais pra
quem não é técnico escolher. Por trás de cada assistente geral, um
classificador barato (Claude Haiku, resposta em formato fechado — só
escolhe entre os especialistas daquele grupo, nunca inventa um novo)
decide qual dos especialistas do grupo responde melhor a pergunta
específica, e SÓ ENTÃO a resposta de verdade é gerada com o prompt
completo daquele especialista (Claude Opus). Dois motivos pra não
simplesmente juntar os prompts dos especialistas num só: (1) cada
prompt já é longo (7-14 mil caracteres) e tem sua própria persona
("Você é contador X, Y anos...") — somar vários confundiria o modelo;
(2) o mesmo princípio de segurança já usado no resto deste ecossistema
(`dominio-automation-engine/app/ia.py`): IA só escolhe entre opções
fechadas, nunca decide livremente.

**NUNCA RODOU EM USO REAL** — construído numa sessão só, testado
isoladamente (carregar agentes, login, uma chamada de API), nunca
testado com várias pessoas de verdade usando ao mesmo tempo.

Diferença importante em relação ao resto do ecossistema
(`dominio-automation-engine`): aquele projeto nunca expõe nada pra
rede (roda só nesta máquina). **Este aqui expõe uma porta pra rede
local** (outros computadores do escritório conseguem acessar) — é uma
mudança real de superfície de risco, decidida com o usuário, não
escondida. Detalhes de segurança no README.

Como rodar:

    python app.py

Depois, de outro computador na mesma rede: http://<IP desta máquina>:5000
"""

import functools
import json
import secrets
from pathlib import Path
from urllib.parse import quote

import anthropic
from flask import (
    Flask, Response, abort, jsonify, redirect, render_template, request, send_from_directory,
    session, stream_with_context, url_for,
)

from agentes import buscar_agente, carregar_agentes
from catalogo_rpa import bloco_prompt_rpa
from dashboard import (
    calcular_balancete, calcular_dre, calcular_variacao, composicao_receita,
    construir_gauge_liquidez, construir_grafico_tendencia, detectar_tendencias,
    montar_tabela_comparativa,
)
from historico_dashboards import historico_do_cliente, registrar as registrar_historico_dashboard
from grupos import GRUPOS, agentes_do_grupo, listar_grupos
from extrator_ia import extrair_campos_com_ia
from leitor_arquivos import PASTA_UPLOADS, TAMANHO_MAXIMO_BYTES, extrair_conteudo, salvar_upload

PASTA_DADOS = Path(__file__).resolve().parent / "data"
ARQUIVO_SENHA = PASTA_DADOS / "senha.txt"
ARQUIVO_CHAVE_API = PASTA_DADOS / "chave_api.txt"
ARQUIVO_SECRET_KEY = PASTA_DADOS / "secret_key.txt"

MODELO_RESPOSTA = "claude-opus-5-5"
# Haiku pro classificador — decisão barata e rápida (escolher 1 entre
# até 16 opções fechadas), não precisa do modelo caro; mesmo modelo já
# usado pro mesmo tipo de tarefa em dominio-automation-engine/app/ia.py.
MODELO_CLASSIFICADOR = "claude-haiku-4-5"
MAX_TOKENS_RESPOSTA = 4096
GRUPO_GERAL = "geral"  # opção de fallback quando nenhum especialista bate direito
# Teto de mensagens mandadas pra API por requisição — o front-end manda
# o histórico inteiro a cada pergunta (sem banco de dados, mais simples
# pra uma v1); isso evita uma conversa crescer sem limite e virar custo
# alto sem ninguém perceber.
MAXIMO_MENSAGENS_HISTORICO = 40


def _ler_ou_none(caminho):
    try:
        conteudo = caminho.read_text(encoding="utf-8").strip()
        return conteudo or None
    except FileNotFoundError:
        return None


def _senha_configurada():
    return _ler_ou_none(ARQUIVO_SENHA)


def _chave_api_configurada():
    return _ler_ou_none(ARQUIVO_CHAVE_API)


def _obter_secret_key():
    """Chave de sessão do Flask — gerada uma vez e guardada local, pra
    sessões de login sobreviverem a um reinício do servidor (senão todo
    mundo precisaria logar de novo toda vez que o processo reiniciasse)."""
    chave = _ler_ou_none(ARQUIVO_SECRET_KEY)
    if chave:
        return chave
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    chave = secrets.token_hex(32)
    ARQUIVO_SECRET_KEY.write_text(chave, encoding="utf-8")
    return chave


app = Flask(__name__)
app.secret_key = _obter_secret_key()
app.config["MAX_CONTENT_LENGTH"] = TAMANHO_MAXIMO_BYTES


def _numero_br(valor_absoluto, casas):
    """Núcleo compartilhado: número positivo -> texto no padrão
    brasileiro (ponto a cada milhar, vírgula decimal), sem depender de
    locale do sistema operacional (locale do Windows costuma ser
    instável entre máquinas)."""
    return f"{valor_absoluto:,.{casas}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def formatar_moeda(valor):
    if valor is None:
        return "—"
    texto = _numero_br(abs(valor), 2)
    return f"-R$ {texto}" if valor < 0 else f"R$ {texto}"


def formatar_percentual(valor):
    if valor is None:
        return "—"
    texto = _numero_br(abs(valor) * 100, 1)
    return f"-{texto}%" if valor < 0 else f"{texto}%"


def formatar_numero(valor, casas=2):
    """Número puro no padrão brasileiro, sem R$ nem % — pra caixa de
    liquidez corrente e pra pré-preencher campo de formulário (achado
    real, 05/10/2026: `round()` do Jinja e `'%.2f'|format()` sempre
    devolvem ponto decimal e nunca separador de milhar, então a
    liquidez corrente e os campos de upload com IA saíam do padrão
    brasileiro enquanto o resto da página já estava certo)."""
    if valor is None:
        return "—"
    texto = _numero_br(abs(valor), casas)
    return f"-{texto}" if valor < 0 else texto


app.jinja_env.filters["moeda"] = formatar_moeda
app.jinja_env.filters["percentual"] = formatar_percentual
app.jinja_env.filters["numero"] = formatar_numero


def _resumo_dashboard_texto(competencia, dre, balancete, comentario, tem_documento=False):
    """Texto-resumo compartilhado entre o link de e-mail e o de
    WhatsApp — mesmo conteúdo, cada canal só formata/escapa do seu
    jeito (`mailto:` tem assunto separado; WhatsApp é só corpo).

    `tem_documento`: nem `mailto:` nem `wa.me` sabem anexar arquivo (é
    limitação do próprio link, não dá pra contornar) — quando há
    documento original salvo, a mensagem pede pra anexar à mão em vez
    de fingir que já vai anexado. Pedido do usuário, 06/10/2026: "deveria
    anexar o documento junto no email" — isso é o que dá pra fazer sem
    montar um envio de e-mail de verdade pelo servidor (precisaria de
    credencial SMTP, fora do escopo decidido antes)."""
    linhas = [
        "Olá,", "",
        f"Segue o resumo do dashboard financeiro de {competencia}:", "",
        f"Receita líquida: {formatar_moeda(dre['receita_liquida'])}",
        f"Lucro líquido: {formatar_moeda(dre['lucro_liquido'])}",
        f"Margem líquida: {formatar_percentual(dre['margem_liquida'])}",
        f"Patrimônio líquido: {formatar_moeda(balancete['patrimonio_liquido'])}",
        f"Liquidez corrente: {formatar_numero(balancete['liquidez_corrente'], 2)}",
    ]
    if comentario:
        linhas += ["", "Comentário do contador:", comentario]
    if tem_documento:
        linhas += ["", "(Lembrete: anexar o documento original antes de enviar.)"]
    linhas += ["", "Atenciosamente,", "Lucrattiva Contabilidade"]
    return "\n".join(linhas)


def montar_link_mailto(cliente_email, cliente_nome, competencia, dre, balancete, comentario, tem_documento=False):
    """Link `mailto:` com assunto/corpo já preenchidos — abre o cliente
    de e-mail padrão do usuário (Outlook, Gmail configurado como app
    padrão, etc.). Escolhido em vez de enviar o e-mail pelo próprio
    servidor (precisaria de credencial SMTP guardada no projeto, mais
    uma coisa sensível pra proteger) — decisão com o usuário, 06/10/2026.
    Devolve `None` se não tiver e-mail (campo é opcional no formulário);
    o template só mostra o botão quando este link existe.

    `mailto:` não anexa arquivo (limitação do link, não do código) — se
    `tem_documento`, a mensagem pede pra anexar à mão; o botão de baixar
    o documento original fica ao lado, pra isso ser rápido."""
    if not cliente_email:
        return None
    assunto = f"Dashboard financeiro — {cliente_nome} — {competencia}"
    corpo = _resumo_dashboard_texto(competencia, dre, balancete, comentario, tem_documento)
    return f"mailto:{quote(cliente_email)}?subject={quote(assunto)}&body={quote(corpo)}"


def montar_link_whatsapp(cliente_whatsapp, competencia, dre, balancete, comentario, tem_documento=False):
    """Link `https://wa.me/<numero>?text=...` com a mensagem já
    preenchida — no Windows, o navegador abre o WhatsApp Desktop se
    estiver instalado e registrado como handler (senão cai no WhatsApp
    Web, que também funciona). Pedido do usuário, 06/10/2026: "coloco o
    número que eu quero que envie" — o número vem do campo do
    formulário a cada dashboard, não fica fixo no código.

    Só dígitos no número, sempre com código do país — se a pessoa
    digitar um número brasileiro sem o 55 na frente (o comum, só DDD +
    número), completa sozinho; se já veio com código de país (mais de
    11 dígitos), não mexe. Devolve `None` sem número informado.
    `wa.me` também não anexa arquivo — mesma observação do mailto."""
    digitos = "".join(c for c in (cliente_whatsapp or "") if c.isdigit())
    if not digitos:
        return None
    if len(digitos) <= 11:
        digitos = "55" + digitos
    texto = _resumo_dashboard_texto(competencia, dre, balancete, comentario, tem_documento)
    return f"https://wa.me/{digitos}?text={quote(texto)}"


def requer_login(funcao):
    @functools.wraps(funcao)
    def wrapper(*args, **kwargs):
        if not session.get("autenticado"):
            return redirect(url_for("login"))
        return funcao(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    senha_configurada = _senha_configurada()
    erro = None

    if request.method == "POST":
        if not senha_configurada:
            erro = "Nenhuma senha configurada ainda — veja o README (data/senha.txt)."
        elif request.form.get("senha", "") == senha_configurada:
            session["autenticado"] = True
            return redirect(url_for("index"))
        else:
            erro = "Senha incorreta."

    return render_template("login.html", erro=erro, senha_configurada=bool(senha_configurada))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@requer_login
def index():
    return render_template("chat.html")


def _float_form(campo, padrao=0.0):
    """Lê um campo numérico do formulário, aceitando vírgula OU ponto
    decimal (formulário em português) — devolve `padrao` se vazio ou
    inválido, nunca quebra por um campo em branco."""
    bruto = request.form.get(campo, "").strip().replace(".", "").replace(",", ".")
    # a troca acima assume formato brasileiro (1.234,56) — se o campo
    # já não tiver separador de milhar, o replace("." , "") não afeta
    # nada (não há ponto a remover antes da vírgula decimal)
    if not bruto:
        return padrao
    try:
        return float(bruto)
    except ValueError:
        return padrao


def _float_form_opcional(campo):
    """Como `_float_form()`, mas devolve `None` (não 0) quando o campo
    está vazio — usado nos campos do período anterior, que são
    opcionais de verdade (campo vazio != valor zero)."""
    bruto = request.form.get(campo, "").strip()
    if not bruto:
        return None
    return _float_form(campo)


@app.route("/dashboard", methods=["GET"])
@requer_login
def dashboard_form():
    return render_template("dashboard_form.html")


@app.route("/dashboard/upload", methods=["POST"])
@requer_login
def dashboard_upload():
    """Recebe um ou mais arquivos (PDF e/ou Excel — DRE e Balancete
    juntos, por exemplo), salva em `data/uploads/` (local, gitignored —
    tem dado financeiro real de cliente) e manda pra IA entender e
    extrair os campos do formulário.

    Troca a abordagem antiga (busca de texto por rótulo,
    `leitor_arquivos.sugerir_campos()`) pela extração por IA
    (`extrator_ia.py`) — achado real contra os primeiros arquivos
    reais enviados (05/10/2026): a busca de texto simples pegava a
    coluna errada num balancete com várias colunas de valor por linha,
    e não entendia quando IRPJ/CSLL aparecia dentro de "Deduções da
    Receita" em vez de linha própria. A IA lê o documento (PDF nativo,
    não texto já extraído) e entende a estrutura de verdade.

    **Continua sendo sugestão, não preenchimento confiado sem
    revisão** — mesmo a IA entendendo o documento, sempre destacado
    pra conferência antes de gerar o dashboard."""
    arquivos = [a for a in request.files.getlist("arquivos") if a and a.filename]
    if not arquivos:
        return render_template("dashboard_form.html", erro_upload="Nenhum arquivo selecionado.")

    chave_api = _chave_api_configurada()
    if not chave_api:
        return render_template("dashboard_form.html", erro_upload="Chave da API não configurada ainda — veja o README (data/chave_api.txt).")

    caminhos_pdf = []
    textos_excel = []
    nomes_recebidos = []
    # Só o NOME do arquivo salvo (já único, com timestamp — ver
    # `salvar_upload`), nunca o caminho completo: é o que vai pro campo
    # oculto do formulário e pra rota de download, então tem que ser só
    # isso que `dashboard_arquivo_original()` aceita como seguro (sem
    # separador de pasta, sem jeito de escapar de `data/uploads/`).
    arquivos_salvos = []
    for arquivo in arquivos:
        arquivo.stream.seek(0, 2)
        tamanho = arquivo.stream.tell()
        arquivo.stream.seek(0)
        if tamanho > TAMANHO_MAXIMO_BYTES:
            return render_template("dashboard_form.html", erro_upload=f"'{arquivo.filename}' é maior que 15 MB — confira se é o arquivo certo.")

        caminho_salvo = salvar_upload(arquivo)
        if caminho_salvo is None:
            return render_template("dashboard_form.html", erro_upload=f"Formato não aceito em '{arquivo.filename}' — envie PDF, .xlsx ou .xls.")

        nomes_recebidos.append(arquivo.filename)
        arquivos_salvos.append(caminho_salvo.name)
        if caminho_salvo.suffix.lower() == ".pdf":
            caminhos_pdf.append(caminho_salvo)
        else:
            texto, metodo, erro = extrair_conteudo(caminho_salvo)
            if texto:
                textos_excel.append((arquivo.filename, texto))

    resultado_ia, erro_ia = extrair_campos_com_ia(caminhos_pdf, chave_api, textos_excel=textos_excel)
    if erro_ia:
        return render_template("dashboard_form.html", nome_arquivo_enviado=", ".join(nomes_recebidos), erro_extracao=erro_ia)

    sugestoes = {
        campo: {"valor": resultado_ia[campo], "linha": "sugerido pela IA a partir do documento"}
        for campo in (
            "receita_bruta", "deducoes", "cmv", "despesas_operacionais", "resultado_financeiro",
            "irpj_csll", "ativo_circulante", "ativo_nao_circulante", "passivo_circulante",
            "passivo_nao_circulante", "patrimonio_liquido",
        )
        if resultado_ia.get(campo) is not None
    }

    return render_template(
        "dashboard_form.html",
        nome_arquivo_enviado=", ".join(nomes_recebidos),
        metodo_extracao="IA (Claude)",
        sugestoes=sugestoes,
        cliente_nome_sugerido=resultado_ia.get("cliente_nome_sugerido"),
        competencia_sugerida=resultado_ia.get("competencia_sugerida"),
        notas_ia=resultado_ia.get("notas"),
        arquivos_salvos=arquivos_salvos,
    )


@app.route("/dashboard", methods=["POST"])
@requer_login
def dashboard_resultado():
    cliente_nome = request.form.get("cliente_nome", "").strip() or "Cliente"
    cliente_cnpj = request.form.get("cliente_cnpj", "").strip()
    cliente_email = request.form.get("cliente_email", "").strip()
    cliente_whatsapp = request.form.get("cliente_whatsapp", "").strip()
    competencia = request.form.get("competencia", "").strip()
    comentario = request.form.get("comentario", "").strip()

    # Nome puro (sem separador de pasta) de cada arquivo que o upload já
    # salvou em `data/uploads/` — só existe de verdade ali se a pessoa usou
    # o upload por IA; preenchimento 100% manual não tem documento pra
    # anexar/baixar depois, e tudo bem, o botão só aparece quando existe.
    nomes_arquivos_originais = [
        Path(n).name for n in request.form.getlist("arquivo_salvo")
        if n and (PASTA_UPLOADS / Path(n).name).is_file()
    ]

    dre = calcular_dre(
        receita_bruta=_float_form("receita_bruta"),
        deducoes=_float_form("deducoes"),
        cmv=_float_form("cmv"),
        despesas_operacionais=_float_form("despesas_operacionais"),
        resultado_financeiro=_float_form("resultado_financeiro"),
        irpj_csll=_float_form("irpj_csll"),
    )
    balancete = calcular_balancete(
        ativo_circulante=_float_form("ativo_circulante"),
        ativo_nao_circulante=_float_form("ativo_nao_circulante"),
        passivo_circulante=_float_form("passivo_circulante"),
        passivo_nao_circulante=_float_form("passivo_nao_circulante"),
        patrimonio_liquido=_float_form("patrimonio_liquido"),
    )

    # Histórico ANTES de registrar o período atual — senão o gráfico de
    # tendência mostraria o período atual duplicado (uma vez do
    # histórico recém-gravado, outra vez como "ponto atual").
    historico_anterior = historico_do_cliente(cliente_nome, cliente_cnpj)
    registrar_historico_dashboard(cliente_nome, cliente_cnpj, competencia, dre, balancete)

    # Campos de período anterior: usa o que a pessoa digitou à mão; se
    # deixou em branco e já existe histórico desse cliente, usa o
    # último período registrado sozinho — "se adapta à empresa" sem
    # exigir digitar de novo o que já foi gerado antes.
    receita_liquida_anterior = _float_form_opcional("receita_liquida_anterior")
    lucro_liquido_anterior = _float_form_opcional("lucro_liquido_anterior")
    if receita_liquida_anterior is None and historico_anterior:
        receita_liquida_anterior = historico_anterior[-1]["receita_liquida"]
    if lucro_liquido_anterior is None and historico_anterior:
        lucro_liquido_anterior = historico_anterior[-1]["lucro_liquido"]

    variacao_receita = calcular_variacao(dre["receita_liquida"], receita_liquida_anterior)
    variacao_lucro = calcular_variacao(dre["lucro_liquido"], lucro_liquido_anterior)

    # Os 6 indicadores do período atual, não só receita/lucro — pra
    # tabela comparativa histórica entrar com a mesma riqueza de dado
    # que o histórico já salvo tem (achado real, 06/10/2026: antes só
    # gravava 2 campos aqui, a tabela comparativa ficaria incompleta no
    # período mais recente, justo o que mais importa comparar).
    pontos_tendencia = historico_anterior + [{
        "competencia": competencia,
        "receita_liquida": dre["receita_liquida"],
        "lucro_liquido": dre["lucro_liquido"],
        "margem_liquida": dre["margem_liquida"],
        "ativo_total": balancete["ativo_total"],
        "patrimonio_liquido": balancete["patrimonio_liquido"],
        "liquidez_corrente": balancete["liquidez_corrente"],
    }]
    grafico_tendencia = construir_grafico_tendencia(pontos_tendencia)
    tabela_comparativa = montar_tabela_comparativa(pontos_tendencia)
    avisos_tendencia = detectar_tendencias(tabela_comparativa)
    tem_documento = bool(nomes_arquivos_originais)
    link_mailto = montar_link_mailto(cliente_email, cliente_nome, competencia, dre, balancete, comentario, tem_documento)
    link_whatsapp = montar_link_whatsapp(cliente_whatsapp, competencia, dre, balancete, comentario, tem_documento)

    return render_template(
        "dashboard_resultado.html",
        cliente_nome=cliente_nome,
        cliente_cnpj=cliente_cnpj,
        cliente_email=cliente_email,
        cliente_whatsapp=cliente_whatsapp,
        competencia=competencia,
        comentario=comentario,
        dre=dre,
        balancete=balancete,
        variacao_receita=variacao_receita,
        variacao_lucro=variacao_lucro,
        composicao=composicao_receita(dre),
        grafico_tendencia=grafico_tendencia,
        gauge_liquidez=construir_gauge_liquidez(balancete["liquidez_corrente"]),
        tabela_comparativa=tabela_comparativa,
        avisos_tendencia=avisos_tendencia,
        link_mailto=link_mailto,
        link_whatsapp=link_whatsapp,
        arquivos_originais=nomes_arquivos_originais,
    )


@app.route("/dashboard/arquivo/<nome_arquivo>")
@requer_login
def dashboard_arquivo_original(nome_arquivo):
    """Baixa um documento original (PDF/Excel) que foi enviado pelo
    upload por IA — pra anexar manualmente num e-mail/WhatsApp depois,
    já que nenhum dos dois canais anexa arquivo sozinho por link. Exige
    login (`@requer_login`, igual ao resto do site: tem dado financeiro
    real de cliente). `send_from_directory` já impede sair de
    `data/uploads/` (barra invertida, `..`, etc.) — não é preciso
    validação extra de caminho aqui."""
    caminho = PASTA_UPLOADS / nome_arquivo
    if not caminho.is_file():
        abort(404)
    return send_from_directory(PASTA_UPLOADS, nome_arquivo, as_attachment=True)


@app.route("/api/dashboard/comentario", methods=["POST"])
@requer_login
def api_dashboard_comentario():
    """Sugestão de comentário do contador, gerada por IA a partir dos
    números já calculados — nunca entra no dashboard sozinha, só
    preenche o campo de comentário pra revisão (mesmo princípio do
    resto do sistema: IA nunca decide o que vai pro cliente sem humano
    conferir antes)."""
    dados = request.get_json(silent=True) or {}
    chave_api = _chave_api_configurada()
    if not chave_api:
        return jsonify({"erro": "Chave da API não configurada."}), 503

    try:
        dre = calcular_dre(
            receita_bruta=float(dados.get("receita_bruta") or 0),
            deducoes=float(dados.get("deducoes") or 0),
            cmv=float(dados.get("cmv") or 0),
            despesas_operacionais=float(dados.get("despesas_operacionais") or 0),
            resultado_financeiro=float(dados.get("resultado_financeiro") or 0),
            irpj_csll=float(dados.get("irpj_csll") or 0),
        )
        balancete = calcular_balancete(
            ativo_circulante=float(dados.get("ativo_circulante") or 0),
            ativo_nao_circulante=float(dados.get("ativo_nao_circulante") or 0),
            passivo_circulante=float(dados.get("passivo_circulante") or 0),
            passivo_nao_circulante=float(dados.get("passivo_nao_circulante") or 0),
            patrimonio_liquido=float(dados.get("patrimonio_liquido") or 0),
        )
    except (TypeError, ValueError):
        return jsonify({"erro": "Valores inválidos — preencha os campos numéricos antes de pedir sugestão."}), 400

    liquidez = balancete["liquidez_corrente"]
    linha_liquidez = f"Liquidez corrente: {liquidez:.2f}" if liquidez is not None else "Liquidez corrente: —"
    resumo = (
        f"Receita líquida: {formatar_moeda(dre['receita_liquida'])}\n"
        f"Lucro líquido: {formatar_moeda(dre['lucro_liquido'])}\n"
        f"Margem líquida: {formatar_percentual(dre['margem_liquida'])}\n"
        f"Margem bruta: {formatar_percentual(dre['margem_bruta'])}\n"
        f"Ativo total: {formatar_moeda(balancete['ativo_total'])}\n"
        f"Patrimônio líquido: {formatar_moeda(balancete['patrimonio_liquido'])}\n"
        f"{linha_liquidez}"
    )

    sistema = (
        "Você é um contador escrevendo um comentário curto (3 a 4 frases, "
        "português do Brasil) pra acompanhar o dashboard financeiro mensal "
        "entregue a um cliente de escritório de contabilidade. Tom "
        "profissional e direto, sem jargão técnico desnecessário. Comente "
        "o que os números SIGNIFICAM pro negócio (margem, liquidez, saúde "
        "financeira) — não repita os valores, o dashboard já mostra eles. "
        "Nunca invente dado que não foi informado. Nunca dê conselho "
        "tributário específico aqui, só leitura gerencial do resultado. "
        "Responda só com o texto corrido do comentário — sem título, sem "
        "markdown (nada de **negrito**, #, -, etc.), vai direto numa caixa "
        "de texto simples."
    )

    try:
        cliente = anthropic.Anthropic(api_key=chave_api)
        resposta = cliente.messages.create(
            model=MODELO_CLASSIFICADOR,  # Haiku — tarefa curta e bem definida, não precisa do modelo caro
            max_tokens=400,
            system=sistema,
            messages=[{"role": "user", "content": resumo}],
        )
        texto = "".join(b.text for b in resposta.content if b.type == "text")
    except anthropic.APIError as erro:
        return jsonify({"erro": f"Erro da API da Anthropic: {erro}"}), 503

    return jsonify({"comentario": texto.strip()})


@app.route("/api/agentes")
@requer_login
def api_agentes():
    # Nome mantido por compatibilidade com o front-end, mas agora
    # devolve os 6 GRUPOS, não os 57 agentes individuais.
    return jsonify(listar_grupos())


def _especialistas_do_grupo_com_descricao(grupo_id):
    """Cruza `grupos.agentes_do_grupo()` (lista de ids) com
    `agentes.carregar_agentes()` (dados completos) — devolve só os
    agentes do grupo pedido, cada um com descrição, pronto pra montar
    o classificador."""
    ids_do_grupo = set(agentes_do_grupo(grupo_id))
    if not ids_do_grupo:
        return []
    return [a for a in carregar_agentes() if a["id"] in ids_do_grupo]


def escolher_especialista(cliente, grupo_id, especialistas, mensagens):
    """Classificador fechado (seção de desenho deste app, mesmo
    princípio de `dominio-automation-engine/app/ia.py`): a partir da
    ÚLTIMA pergunta do usuário, escolhe qual especialista do grupo
    melhor atende — ou `GRUPO_GERAL` se nenhum bater bem (ex.:
    saudação, pergunta fora do escopo do grupo). Nunca inventa um
    especialista fora da lista — resposta forçada em JSON Schema com
    enum fechado.

    Devolve o `id` escolhido (string). Se a chamada falhar por
    qualquer motivo (rede, limite, chave), cai em `GRUPO_GERAL` em vez
    de quebrar o chat inteiro — a pergunta ainda é respondida, só que
    pelo prompt geral do grupo em vez de um especialista."""
    ultima_pergunta = next(
        (m["content"] for m in reversed(mensagens) if m["role"] == "user"), ""
    )

    opcoes = [e["id"] for e in especialistas] + [GRUPO_GERAL]
    lista_descricoes = "\n".join(f"- {e['id']}: {e['descricao']}" for e in especialistas)
    sistema = (
        f"Você escolhe qual especialista do grupo \"{grupo_id}\" melhor responde "
        "a pergunta de um funcionário de escritório de contabilidade. Escolha só "
        f"entre estas opções:\n\n{lista_descricoes}\n- {GRUPO_GERAL}: nenhum "
        "especialista específico bate bem (saudação, pergunta genérica, fora do "
        "escopo do grupo)."
    )
    formato = {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": {"especialista": {"type": "string", "enum": opcoes}},
            "required": ["especialista"],
            "additionalProperties": False,
        },
    }

    try:
        resposta = cliente.messages.create(
            model=MODELO_CLASSIFICADOR,
            max_tokens=256,
            system=sistema,
            messages=[{"role": "user", "content": ultima_pergunta}],
            output_config={"format": formato},
        )
        if resposta.stop_reason != "end_turn":
            return GRUPO_GERAL
        texto = next((b.text for b in resposta.content if b.type == "text"), "")
        escolhido = json.loads(texto).get("especialista")
        return escolhido if escolhido in opcoes else GRUPO_GERAL
    except (anthropic.APIError, json.JSONDecodeError, AttributeError):
        return GRUPO_GERAL


@app.route("/api/chat", methods=["POST"])
@requer_login
def api_chat():
    dados = request.get_json(silent=True) or {}
    grupo_id = dados.get("agente")  # nome do campo mantido por compatibilidade com o front-end
    mensagens_cliente = dados.get("mensagens")

    if not grupo_id or grupo_id not in GRUPOS:
        return jsonify({"erro": "Nenhum assistente válido selecionado."}), 400
    if not isinstance(mensagens_cliente, list) or not mensagens_cliente:
        return jsonify({"erro": "Nenhuma mensagem recebida."}), 400

    chave_api = _chave_api_configurada()
    if not chave_api:
        return jsonify({"erro": "Chave da API da Anthropic não configurada ainda — veja o README (data/chave_api.txt)."}), 503

    # Só repassa role/content — nunca confia em campo extra que o
    # cliente possa ter mandado.
    mensagens = [
        {"role": m.get("role"), "content": m.get("content")}
        for m in mensagens_cliente[-MAXIMO_MENSAGENS_HISTORICO:]
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    if not mensagens:
        return jsonify({"erro": "Nenhuma mensagem válida recebida."}), 400

    cliente = anthropic.Anthropic(api_key=chave_api)

    especialistas = _especialistas_do_grupo_com_descricao(grupo_id)
    especialista_id = escolher_especialista(cliente, grupo_id, especialistas, mensagens)

    if especialista_id == GRUPO_GERAL:
        grupo = GRUPOS[grupo_id]
        prompt_sistema = (
            f"Você é um assistente do escritório de contabilidade Lucrattiva, "
            f"especialista em {grupo['nome']}: {grupo['descricao']} Responda de "
            "forma geral e, se a dúvida for bem específica, sugira que a pessoa "
            "detalhe mais pra receber uma resposta mais precisa."
        )
        nome_especialista_exibido = f"{grupo['nome']} (resposta geral)"
    else:
        agente = buscar_agente(especialista_id)
        prompt_sistema = agente["prompt_sistema"]
        nome_especialista_exibido = agente["nome"]

    # Catálogo de rotinas do RPA (dominio-automation-engine) — mesmo
    # bloco pra todos os 57 agentes + fallback geral, acrescentado aqui
    # em vez de duplicado nos 57 arquivos .md. Pedido do usuário,
    # 06/10/2026: agentes aprendem a SUGERIR automação (texto), nunca a
    # executar — ver docstring de `catalogo_rpa.py` pro desenho completo
    # e a trava de segurança combinada no outro projeto.
    prompt_sistema += bloco_prompt_rpa()

    def gerar():
        """Gera linhas NDJSON (uma por evento) — formato escolhido em
        vez de SSE "de verdade" porque é mais simples de ler no
        front-end com `fetch` puro, sem precisar de `EventSource`
        (que não aceita cabeçalho de sessão/cookie do jeito que
        `fetch` aceita). Primeiro evento manda qual especialista
        respondeu (front-end já pode mostrar o rótulo antes do texto
        chegar); depois um evento "delta" por pedaço de texto que
        chega da API, conforme é gerado — é isso que faz a resposta
        aparecer "ao vivo" em vez de tudo de uma vez só no final."""
        yield json.dumps({"tipo": "especialista", "valor": nome_especialista_exibido}) + "\n"
        try:
            with cliente.messages.stream(
                model=MODELO_RESPOSTA,
                max_tokens=MAX_TOKENS_RESPOSTA,
                system=prompt_sistema,
                messages=mensagens,
            ) as stream:
                for texto in stream.text_stream:
                    yield json.dumps({"tipo": "delta", "texto": texto}) + "\n"
            yield json.dumps({"tipo": "fim"}) + "\n"
        except anthropic.AuthenticationError:
            yield json.dumps({"tipo": "erro", "mensagem": "Chave da API inválida — confira data/chave_api.txt."}) + "\n"
        except anthropic.RateLimitError:
            yield json.dumps({"tipo": "erro", "mensagem": "Limite de uso da API atingido — tente de novo em instantes."}) + "\n"
        except anthropic.APIConnectionError:
            yield json.dumps({"tipo": "erro", "mensagem": "Não consegui conectar à API da Anthropic — confira a internet desta máquina."}) + "\n"
        except anthropic.APIStatusError as erro:
            yield json.dumps({"tipo": "erro", "mensagem": f"Erro da API da Anthropic: {erro.message}"}) + "\n"

    return Response(stream_with_context(gerar()), mimetype="application/x-ndjson")


if __name__ == "__main__":
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    if not _senha_configurada():
        print(f"AVISO: nenhuma senha configurada ainda. Crie {ARQUIVO_SENHA} com uma senha dentro.")
    if not _chave_api_configurada():
        print(f"AVISO: nenhuma chave de API configurada ainda. Crie {ARQUIVO_CHAVE_API} com a chave dentro.")
    # 0.0.0.0 — acessível de outros computadores da MESMA rede local.
    # Não expõe pra internet por si só (precisaria de port forward no
    # roteador, que ninguém deve fazer aqui), mas qualquer um na mesma
    # rede Wi-Fi/cabo alcança — ver aviso de segurança no README.
    app.run(host="0.0.0.0", port=5000, debug=False)
