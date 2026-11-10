from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .collector import PocActivity


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "sem-nome"


def week_label(activity: PocActivity) -> str:
    year, week, _ = activity.until.isocalendar()
    return f"{year}-W{week:02d}"


def report_path(activity: PocActivity, out_dir: Path) -> Path:
    poc = activity.poc
    return out_dir / slugify(poc.cliente) / slugify(poc.nome) / f"{week_label(activity)}.md"


def empty_week_body(activity: PocActivity) -> str:
    erros = [f"- `{r.repo}`: {r.error}" for r in activity.repos if r.error]
    riscos = "Não houve atividade registrada nos repositórios no período."
    if erros:
        riscos += " Alguns repositórios não puderam ser lidos:\n" + "\n".join(erros)
    return (
        "## Resumo da semana\n"
        "Não houve atividade registrada no GitHub nesta semana.\n\n"
        "## Entregas realizadas\n-\n\n"
        "## Em andamento\n-\n\n"
        "## Próximos passos\n_Preencher pelo responsável._\n\n"
        f"## Riscos e pontos de atenção\n{riscos}\n"
    )


def render(activity: PocActivity, body: str, model: str) -> str:
    poc = activity.poc
    m = activity.metrics()
    repos = ", ".join(f"`{r}`" for r in poc.repos)
    erros = [r for r in activity.repos if r.error]
    aviso_erros = ""
    if erros:
        aviso_erros = "\n> ⚠️ Repositórios não lidos: " + ", ".join(
            f"`{r.repo}` ({r.error})" for r in erros
        ) + "\n"
    return f"""<!--
RASCUNHO GERADO AUTOMATICAMENTE — revisar antes de enviar ao cliente.
Modelo: {model}
-->
# Relatório semanal — {poc.nome}

**Cliente:** {poc.cliente}
**Período:** {activity.since:%d/%m/%Y} a {activity.until:%d/%m/%Y} ({week_label(activity)})
**Responsável:** {poc.responsavel or "—"}
{aviso_erros}
{body}

---

<details>
<summary>Métricas da semana</summary>

| Commits | Arquivos alterados | PRs mergeados | PRs abertos | Issues fechadas | Issues abertas | Contribuidores |
|---|---|---|---|---|---|---|
| {m['commits']} | {m['files_changed']} | {m['prs_merged']} | {m['prs_open']} | {m['issues_closed']} | {m['issues_opened']} | {m['contributors']} |

Repositórios: {repos}
</details>
"""


def write(activity: PocActivity, content: str, out_dir: Path) -> Path:
    path = report_path(activity, out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
