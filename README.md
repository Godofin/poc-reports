# Relatórios semanais de PoCs (CrewAI + GitHub)

Gera toda semana um **rascunho de relatório de status por PoC**, para o cliente,
a partir da atividade nos repositórios do GitHub (commits, PRs e issues).
Usa o **Groq** (tier gratuito, Llama 3.3 70B) como LLM e roda no **GitHub Actions**.

> O GitHub Models, usado na primeira versão, foi descontinuado pelo GitHub em 30/07/2026.

```
pocs.yaml ──► coleta (API GitHub, sem LLM) ──► Crew ──► reports/<cliente>/<poc>/<ano-Wsemana>.md
                                               │                         │
                                               ├ Analista Técnico        └► issue de revisão
                                               └ Redator de Status          (checklist p/ o responsável)
```

- **Só metadados vão para o LLM**: mensagens de commit, títulos e descrições de PRs e issues. O código (diff) nunca é enviado.
- O relatório é um **rascunho**: a issue de revisão serve para o responsável ajustar o texto antes de enviar ao cliente.
- Uma semana sem atividade gera o relatório sem chamar o LLM e marca isso como ponto de atenção.

## Estrutura

| Arquivo | O que faz |
|---|---|
| `pocs.yaml` | Lista de PoCs: cliente, repositórios, objetivo, responsável, notas da semana |
| `poc_reports/collector.py` | Busca a atividade da semana na API do GitHub |
| `poc_reports/crew.py` | Agentes, tarefas e configuração do LLM |
| `poc_reports/report.py` | Monta o Markdown final (cabeçalho, métricas) |
| `poc_reports/__main__.py` | Ponto de entrada (`python -m poc_reports`) |
| `poc_reports/review_issue.py` | Abre a issue de revisão com os relatórios |
| `.github/workflows/weekly-report.yml` | Agendamento semanal (sexta 09:00 BRT) e execução manual |

## Configuração no GitHub

1. **Crie um repositório central** (privado), por exemplo `consultoria/poc-reports`, e envie este projeto para ele.
2. **Crie uma chave do Groq** em https://console.groq.com/keys (gratuita) e cadastre-a no repositório central como o secret **`LLM_API_KEY`** (*Settings → Secrets and variables → Actions → New repository secret*).
3. **Crie um token de leitura dos repositórios das PoCs** (fine-grained PAT):
   - GitHub → Settings → Developer settings → Fine-grained tokens → *Generate new token*
   - *Resource owner*: a organização das PoCs (pode exigir aprovação de um admin da org)
   - *Repository access*: os repositórios das PoCs
   - *Permissions*: **Contents**, **Pull requests** e **Issues**, todas em *Read-only*
   - Cadastre-o como o secret `POC_GITHUB_TOKEN`.
   - Se as PoCs estiverem em repositórios **públicos**, isso não é necessário: o `GITHUB_TOKEN` automático do Actions já consegue lê-los.
4. Em *Settings → Actions → General*, deixe as Actions habilitadas.
5. Edite o `pocs.yaml` com as PoCs reais.
6. Teste em *Actions → Relatório semanal das PoCs → Run workflow*.

## Rodar localmente

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
```

Defina a chave do Groq e, se as PoCs forem privadas, um token GitHub com leitura nos repositórios:

```powershell
$env:LLM_API_KEY = "gsk_..."
$env:GITHUB_TOKEN = "github_pat_..."
```

```bash
python -m poc_reports --dry-run            # só mostra a atividade coletada, sem LLM
python -m poc_reports                      # gera os relatórios em reports/
python -m poc_reports --poc chatbot --days 14
```

## Limites do tier gratuito

O tier gratuito do Groq tem limites de requisições e de tokens por minuto e por dia. O projeto já respeita esses limites:

- A atividade enviada é cortada em cerca de 12 mil caracteres por PoC; as descrições longas de PR são resumidas.
- O crew usa `max_rpm=10` e há uma pausa entre as PoCs.
- Cada PoC usa cerca de 2 ou 3 chamadas de LLM.

Com muitas PoCs (dezenas), o limite diário pode ser atingido. Nesse caso, divida a execução em grupos (`--poc`) ou migre para uma API paga.

Confira os limites atuais em https://console.groq.com/settings/limits.

## Trocar o modelo / migrar para o Claude

O modelo é definido por variáveis de ambiente, sem mudar o código:

| Variável | Padrão (Groq) | Gemini (gratuito) | Claude (pago) |
|---|---|---|---|
| `LLM_MODEL` | `openai/llama-3.3-70b-versatile` | `openai/gemini-2.5-flash` | `anthropic/claude-haiku-4-5-20251001` |
| `LLM_BASE_URL` | `https://api.groq.com/openai/v1` | `https://generativelanguage.googleapis.com/v1beta/openai/` | *(vazio)* |
| `LLM_API_KEY` | chave do Groq | chave do Google AI Studio | chave da Anthropic |

No Actions, `LLM_MODEL` e `LLM_BASE_URL` vêm de *Settings → Secrets and variables → Actions → Variables*, e a chave vem do secret `LLM_API_KEY`. Para o Claude, remova o `LLM_BASE_URL` do workflow e adicione `crewai[anthropic]` ao `requirements.txt`.

> O prefixo `openai/` no `LLM_MODEL` faz o CrewAI usar o cliente compatível com OpenAI; o restante é o id do modelo no provedor. Os ids de modelo mudam com o tempo: confira os disponíveis no console do provedor.
>
> Atenção: no tier gratuito do Gemini, o Google pode usar os dados enviados para melhorar os produtos dele. Considere isso antes de usar com PoCs reais.

## Dicas para relatórios melhores

- Preencha bem o `contexto` de cada PoC (objetivo e critério de sucesso). É o que permite ao LLM relacionar o progresso com o objetivo.
- Use o campo `notas` para o que não aparece no GitHub: reuniões, decisões, bloqueios do lado do cliente.
- Incentive mensagens de commit e descrições de PR descritivas. "wip" e "fix" geram relatórios pobres.
