# Assistente Fiscal Lucrattiva

Chat web local pra equipe do escritório conversar com qualquer um dos
57 agentes fiscais (os mesmos usados no Claude Code,
`~/.claude/agents`) sem precisar instalar Claude Code, terminal ou
VS Code — só um navegador.

**Estado: nunca rodou em uso real.** Construído e testado isoladamente
numa sessão só (carregamento dos 57 agentes, login, validação de
entrada da API) — a chamada de verdade pra API da Anthropic nunca foi
testada com uma pergunta real, nem com mais de uma pessoa usando ao
mesmo tempo.

## Diferença importante de segurança em relação ao resto do ecossistema

O projeto irmão (`dominio-automation-engine`) nunca expõe nada pra
rede — roda inteiro numa máquina só. **Este projeto aqui expõe uma
porta HTTP pra rede local** (`0.0.0.0:5000`), porque esse é o pedido:
outras pessoas do escritório, de outros computadores, acessando pelo
navegador. Isso muda a superfície de risco de verdade:

- **Sem HTTPS.** Numa rede Wi-Fi do escritório que já é de confiança,
  isso costuma ser um risco aceito pra ferramenta interna — mas é
  diferente de "só roda nesta máquina". Se a rede do escritório não
  for confiável (Wi-Fi compartilhado com visitantes, por exemplo),
  reconsidere antes de usar assim.
- **Senha única compartilhada**, não um login por pessoa — suficiente
  pra controlar acesso, mas sem rastro de quem perguntou o quê.
- **Uma chave de API só, uso de todo mundo contabilizado junto** — sem
  limite por pessoa. Acompanhe o consumo pelo painel da Anthropic
  (console.anthropic.com) periodicamente.
- **Não exposto à internet** — só à rede local (LAN). Não configure
  redirecionamento de porta no roteador pra isso.

## Instalação

```bash
cd lucrattiva-assistente-fiscal
pip install -r requirements.txt
```

### Configurar a senha de acesso

Crie `data/senha.txt` com a senha dentro (uma linha, sem mais nada):

```bash
echo "sua-senha-aqui" > data/senha.txt
```

### Configurar a chave da API

Pegue uma chave em <https://console.anthropic.com/settings/keys> e
salve em `data/chave_api.txt` (uma linha só, sem mais nada):

```bash
echo "sk-ant-..." > data/chave_api.txt
```

Os dois arquivos ficam só nesta máquina (`data/` é gitignored, nunca
sobe pro GitHub).

## Como rodar

```bash
python app.py
```

- Nesta máquina: <http://127.0.0.1:5000>
- De outro computador na mesma rede: `http://<IP desta máquina>:5000`
  (descubra o IP com `ipconfig` no Windows, geralmente algo como
  `192.168.x.x`)

## Como funciona

- `agentes.py` lê os arquivos `.md` de `~/.claude/agents` direto (não
  copia nada) — o campo `description:` vira o resumo mostrado na
  lista, o corpo do arquivo vira o prompt de sistema mandado pra API.
  Uma correção feita nos agentes (como as já feitas no projeto
  `dominio-automation-engine`) aparece aqui automaticamente.
- `app.py` — servidor Flask: login por sessão, `/api/agentes` lista os
  57, `/api/chat` recebe `{agente, mensagens}` e chama
  `client.messages.create()` (modelo `claude-opus-5-5`) com o prompt
  do agente escolhido como `system`.
- **Sem banco de dados.** O histórico da conversa fica só na memória
  do navegador (a cada pergunta, o front-end manda a conversa inteira
  de novo) — recarregar a página apaga a conversa. Decisão de
  simplicidade da v1, não uma limitação técnica definitiva.
- **Streaming de verdade** (`cliente.messages.stream()`, NDJSON entre
  back-end e front-end) — a resposta aparece progressivamente, token a
  token, não tudo de uma vez no final.
- **Markdown renderizado** (`marked` + `DOMPurify`, via CDN) — tabela,
  título, negrito, checklist das respostas dos agentes aparecem
  formatados de verdade, não como texto cru com `|` e `#` literais
  (achado real, 05/10/2026 — primeira resposta real mostrou isso feio).

## Dashboard DRE + Balancete (`/dashboard`)

Gera uma apresentação visual (pra imprimir/exportar em PDF pelo
navegador, botão "Imprimir / Salvar PDF") com a identidade visual real
da LuCrattiva — logo e cores (`#004aab` azul, `#a37b26` dourado)
extraídas direto do site oficial, paleta validada contra
daltonismo/contraste.

**Preenchimento manual ou por upload com IA** — formulário com todos
os campos de DRE/Balancete, ou envie PDF/Excel (pode selecionar
**vários arquivos de uma vez**, ex.: DRE e Balancete juntos) na seção
"Enviar arquivo(s)" no topo. `extrator_ia.py` manda o PDF direto pro
Claude entender (documento nativo, não texto já extraído — tabela com
várias colunas por linha, conta agrupada em categoria, tudo isso o
modelo entende de verdade) e devolve os campos já calculados, inclusive
nome do cliente e competência. Sempre destacado em amarelo pra
conferência — nunca usado sem revisão humana, mesmo a IA acertando.

Validado contra 2 arquivos reais (DRE e Balancete da BRLOIO
AGROPECUARIA, 05/10/2026): 12 de 12 campos bateram exatamente com o
documento depois de um ajuste de instrução (a primeira versão pegou um
subtotal de subcategoria aninhada em "Despesas Operacionais" — corrigido
e reconfirmado). A versão anterior (busca de texto por rótulo,
`leitor_arquivos.sugerir_campos()`) errou feio contra os mesmos
arquivos — pegou a coluna "Crédito" em vez de "Saldo Atual" no
balancete — por isso foi substituída.

**O que o dashboard mostra:**
- KPIs (receita líquida, lucro líquido — com variação vs. período
  anterior quando disponível —, margens, liquidez corrente, patrimônio
  líquido).
- **Gráfico de tendência** (linha) de Receita Líquida e Lucro Líquido
  ao longo dos períodos já gerados pra aquele cliente — some sozinho,
  sem digitar nada, puxado do histórico local (ver abaixo).
- **Donut "pra onde foi cada R$ 1,00 de receita"** — composição entre
  custos, despesas, impostos e lucro líquido.
- **Velocímetro de liquidez corrente**, com faixa de cor (vermelho
  abaixo de 1, amarelo entre 1 e 1,5, verde acima).
- Composição do DRE em barras proporcionais e do Balancete (Ativo ×
  Passivo+PL), com alerta visual se o balancete não fechar.
- **Comentário do contador sugerido por IA** (botão "✨ Sugerir com
  IA" no formulário, a partir dos números preenchidos) — sempre um
  rascunho editável, nunca enviado ao cliente sem revisão humana.

**Histórico por cliente** (`historico_dashboards.py`,
`data/historico_dashboards.json`, local e gitignored — tem número
financeiro real): cada dashboard gerado fica salvo, casado por CNPJ
(ou nome, se não tiver CNPJ). Da segunda geração em diante pro mesmo
cliente, a tendência aparece sozinha e os campos de "período anterior"
se auto-preenchem com o último período já gerado, se você deixar em
branco. Sobrevive a fechar o servidor — é só um arquivo em disco, não
se perde reiniciando `python app.py`. Fica só nesta máquina (não sobe
pro GitHub); mudar de computador começa o histórico vazio.

## Limitações conhecidas (v1)

- Conversa não é salva — fecha a aba, perde o histórico.
- Sem controle de qual pessoa está logada (senha única).
- Sem limite de uso por pessoa (só o limite geral da chave de API).
- Resposta não é revisada por contador antes de aparecer pra quem
  perguntou — é orientação de um assistente de IA, não um parecer
  técnico. Vale reforçar isso pra equipe antes de liberar o uso.
- Nunca testado com uso real (múltiplas pessoas, perguntas de verdade).
