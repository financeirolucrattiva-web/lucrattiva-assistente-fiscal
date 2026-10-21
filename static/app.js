// Chat do Assistente Fiscal — sem framework, JS puro.
//
// Histórico de conversa persiste em `localStorage` desta máquina/navegador
// (uma conversa por assistente, chave por `agente.id`) — sobrevive a
// recarregar a página ou fechar o navegador, mas não sincroniza entre
// máquinas nem pessoas (decisão v1: "pelo menos por máquina", sem banco
// de dados). Trocar de assistente retoma a conversa salva dele, se
// houver; "Nova conversa" apaga só a conversa do assistente atual.

const CHAVE_HISTORICO = "assistente_fiscal_historico_v1";
const CHAVE_ULTIMO_AGENTE = "assistente_fiscal_ultimo_agente_v1";
// Teto de mensagens guardadas por assistente — evita o localStorage
// (limite ~5-10MB) crescer sem fim numa conversa muito longa; mesma
// ideia do MAXIMO_MENSAGENS_HISTORICO do lado do servidor.
const MAXIMO_MENSAGENS_SALVAS = 60;

function lerTodoHistorico() {
  try {
    return JSON.parse(localStorage.getItem(CHAVE_HISTORICO) || "{}");
  } catch (erro) {
    return {}; // localStorage corrompido/bloqueado (aba privada) — começa limpo, nunca quebra o chat
  }
}

function salvarHistoricoDoAgente(agenteId, mensagens) {
  try {
    const todos = lerTodoHistorico();
    todos[agenteId] = mensagens.slice(-MAXIMO_MENSAGENS_SALVAS);
    localStorage.setItem(CHAVE_HISTORICO, JSON.stringify(todos));
  } catch (erro) {
    // Quota cheia ou navegador bloqueando localStorage — a conversa
    // continua funcionando nesta aba, só não persiste. Não quebra o chat.
  }
}

function apagarHistoricoDoAgente(agenteId) {
  try {
    const todos = lerTodoHistorico();
    delete todos[agenteId];
    localStorage.setItem(CHAVE_HISTORICO, JSON.stringify(todos));
  } catch (erro) { /* idem acima */ }
}

let agentes = [];
let agenteAtual = null;
let historico = [];
let enviando = false;

const listaAgentesEl = document.getElementById("lista-agentes");
const buscaAgenteEl = document.getElementById("busca-agente");
const nomeAgenteEl = document.getElementById("nome-agente-atual");
const descricaoAgenteEl = document.getElementById("descricao-agente-atual");
const mensagensEl = document.getElementById("mensagens");
const formEl = document.getElementById("form-enviar");
const campoMensagemEl = document.getElementById("campo-mensagem");
const botaoEnviarEl = document.getElementById("botao-enviar");
const botaoNovaConversaEl = document.getElementById("botao-nova-conversa");

async function carregarAgentes() {
  try {
    const resposta = await fetch("/api/agentes");
    if (!resposta.ok) throw new Error("Falha ao carregar agentes.");
    agentes = await resposta.json();
    renderizarListaAgentes(agentes);

    let ultimoId = null;
    try { ultimoId = localStorage.getItem(CHAVE_ULTIMO_AGENTE); } catch (erro) { /* não crítico */ }
    const ultimoAgente = ultimoId && agentes.find((a) => a.id === ultimoId);
    if (ultimoAgente) selecionarAgente(ultimoAgente);
  } catch (erro) {
    listaAgentesEl.textContent = "Não consegui carregar a lista de assistentes.";
  }
}

function renderizarListaAgentes(lista) {
  listaAgentesEl.innerHTML = "";
  if (lista.length === 0) {
    listaAgentesEl.textContent = "Nenhum assistente encontrado.";
    return;
  }
  for (const agente of lista) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "item-agente";
    if (agenteAtual && agenteAtual.id === agente.id) item.classList.add("selecionado");
    item.innerHTML = `
      <span class="item-agente-nome">${escaparHtml(agente.nome)}</span>
      <span class="item-agente-descricao">${escaparHtml(resumir(agente.descricao, 90))}</span>
    `;
    item.addEventListener("click", () => selecionarAgente(agente));
    listaAgentesEl.appendChild(item);
  }
}

function resumir(texto, maximo) {
  if (!texto) return "";
  return texto.length > maximo ? texto.slice(0, maximo).trim() + "…" : texto;
}

function escaparHtml(texto) {
  const div = document.createElement("div");
  div.textContent = texto || "";
  return div.innerHTML;
}

function selecionarAgente(agente, { manterHistorico = true } = {}) {
  agenteAtual = agente;
  nomeAgenteEl.textContent = agente.nome;
  descricaoAgenteEl.textContent = agente.descricao;
  mensagensEl.innerHTML = "";
  adicionarMensagemSistema(`Conversando com "${agente.nome}". ${agente.descricao}`);

  const salvas = manterHistorico ? (lerTodoHistorico()[agente.id] || []) : [];
  historico = salvas.slice();
  for (const msg of historico) {
    const balao = adicionarMensagem(msg.role, null);
    if (msg.role === "assistant") renderizarMarkdown(balao, msg.content);
    else balao.textContent = msg.content;
  }
  if (historico.length > 0) {
    adicionarMensagemSistema("↑ conversa anterior retomada automaticamente (salva nesta máquina).");
  }

  try { localStorage.setItem(CHAVE_ULTIMO_AGENTE, agente.id); } catch (erro) { /* não crítico */ }

  campoMensagemEl.disabled = false;
  botaoEnviarEl.disabled = false;
  campoMensagemEl.focus();
  renderizarListaAgentes(agentesFiltrados());
}

function agentesFiltrados() {
  const termo = buscaAgenteEl.value.trim().toLowerCase();
  if (!termo) return agentes;
  return agentes.filter(
    (a) => a.nome.toLowerCase().includes(termo) || a.descricao.toLowerCase().includes(termo)
  );
}

buscaAgenteEl.addEventListener("input", () => renderizarListaAgentes(agentesFiltrados()));

botaoNovaConversaEl.addEventListener("click", () => {
  if (!agenteAtual) return;
  apagarHistoricoDoAgente(agenteAtual.id);
  selecionarAgente(agenteAtual, { manterHistorico: false });
});

function adicionarMensagemSistema(texto) {
  const el = document.createElement("p");
  el.className = "mensagem-sistema";
  el.textContent = texto;
  mensagensEl.appendChild(el);
  mensagensEl.scrollTop = mensagensEl.scrollHeight;
}

function adicionarMensagem(role, texto) {
  const el = document.createElement("div");
  el.className = `balao balao-${role}`;
  if (texto) el.textContent = texto;
  mensagensEl.appendChild(el);
  mensagensEl.scrollTop = mensagensEl.scrollHeight;
  return el;
}

// Markdown -> HTML sanitizado — as respostas dos agentes vêm em
// markdown de verdade (tabela, título, negrito, checklist); sem isso
// o chat mostrava o texto cru, com "|" e "#" aparecendo literalmente
// (achado real, pedido do usuário depois de ver uma resposta feia).
// DOMPurify sempre roda em cima do HTML gerado, mesmo o conteúdo vindo
// só da nossa própria API — defesa em profundidade contra prompt
// injection que tente devolver HTML/script na resposta.
function renderizarMarkdown(elemento, textoMarkdown) {
  const html = marked.parse(textoMarkdown, { breaks: true });
  elemento.innerHTML = DOMPurify.sanitize(html);
}

formEl.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  if (enviando || !agenteAtual) return;

  const texto = campoMensagemEl.value.trim();
  if (!texto) return;

  campoMensagemEl.value = "";
  adicionarMensagem("user", texto);
  historico.push({ role: "user", content: texto });
  salvarHistoricoDoAgente(agenteAtual.id, historico);

  enviando = true;
  botaoEnviarEl.disabled = true;
  const balao = adicionarMensagem("assistant", null);
  balao.classList.add("carregando");
  balao.textContent = "Pensando...";

  let textoAcumulado = "";
  let especialisteRecebido = null;
  let recebeuAlgumDelta = false;

  try {
    const resposta = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agente: agenteAtual.id, mensagens: historico }),
    });

    if (!resposta.ok) {
      const dados = await resposta.json().catch(() => ({}));
      throw new Error(dados.erro || "falha desconhecida.");
    }

    const leitor = resposta.body.getReader();
    const decodificador = new TextDecoder();
    let bufer = "";

    while (true) {
      const { done, value } = await leitor.read();
      if (done) break;
      bufer += decodificador.decode(value, { stream: true });
      const linhas = bufer.split("\n");
      bufer = linhas.pop(); // última linha pode estar incompleta — guarda pro próximo pedaço

      for (const linha of linhas) {
        if (!linha.trim()) continue;
        const evt = JSON.parse(linha);

        if (evt.tipo === "especialista") {
          especialisteRecebido = evt.valor;
        } else if (evt.tipo === "delta") {
          if (!recebeuAlgumDelta) {
            balao.classList.remove("carregando");
            balao.textContent = "";
            recebeuAlgumDelta = true;
          }
          textoAcumulado += evt.texto;
          renderizarMarkdown(balao, textoAcumulado);
          mensagensEl.scrollTop = mensagensEl.scrollHeight;
        } else if (evt.tipo === "erro") {
          throw new Error(evt.mensagem);
        }
        // "fim" não precisa de ação — só sinaliza que acabou
      }
    }

    if (especialisteRecebido) {
      const rotulo = document.createElement("span");
      rotulo.className = "rotulo-especialista";
      rotulo.textContent = `respondido por: ${especialisteRecebido}`;
      balao.appendChild(rotulo);
    }
    historico.push({ role: "assistant", content: textoAcumulado });
    salvarHistoricoDoAgente(agenteAtual.id, historico);
  } catch (erro) {
    balao.classList.remove("carregando");
    balao.textContent = `Erro: ${erro.message || "falha de conexão com o servidor."}`;
    balao.classList.add("balao-erro");
  } finally {
    enviando = false;
    botaoEnviarEl.disabled = false;
    campoMensagemEl.focus();
  }
});

// Enter envia, Shift+Enter quebra linha.
campoMensagemEl.addEventListener("keydown", (evento) => {
  if (evento.key === "Enter" && !evento.shiftKey) {
    evento.preventDefault();
    formEl.requestSubmit();
  }
});

carregarAgentes();
