"""Abre uma issue de revisão no repositório central com os relatórios da semana.

Uso: python -m poc_reports.review_issue generated.json
Requer GITHUB_TOKEN (com issues: write) e GITHUB_REPOSITORY (owner/nome),
ambos já disponíveis dentro do GitHub Actions.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

from github import Auth, Github

MAX_ISSUE_CHARS = 60_000  # limite do GitHub é 65.536


def main() -> int:
    manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    generated, failures = manifest["generated"], manifest["failures"]
    if not generated and not failures:
        print("Nada para revisar.")
        return 0

    repo_name = os.environ["GITHUB_REPOSITORY"]
    branch = os.getenv("GITHUB_REF_NAME", "main")
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")

    mentions = sorted({f"@{g['responsavel_github']}" for g in generated if g["responsavel_github"]})
    lines = [
        "Relatórios semanais gerados automaticamente. **Revise e ajuste antes de enviar ao cliente.**",
        "",
        "Checklist:",
    ]
    for g in generated:
        url = f"{server}/{repo_name}/blob/{branch}/{g['path']}"
        flag = " _(sem atividade na semana)_" if g["empty"] else ""
        lines.append(f"- [ ] **{g['cliente']}** — [{g['poc']}]({url}){flag}")
    if failures:
        lines += ["", "### ⚠️ Falhas", *[f"- {f['poc']}: `{f['error'][:300]}`" for f in failures]]
    if mentions:
        lines += ["", "Responsáveis: " + " ".join(mentions)]

    # Conteúdo completo de cada relatório, para revisar sem sair da issue.
    for g in generated:
        content = Path(g["path"]).read_text(encoding="utf-8")
        lines += ["", f"<details><summary>{g['cliente']} — {g['poc']}</summary>", "", content, "</details>"]

    body = "\n".join(lines)
    if len(body) > MAX_ISSUE_CHARS:
        body = body[:MAX_ISSUE_CHARS] + "\n\n_(conteúdo truncado; veja os arquivos pelos links)_"

    gh = Github(auth=Auth.Token(os.environ["GITHUB_TOKEN"]))
    issue = gh.get_repo(repo_name).create_issue(
        title=f"Revisão dos relatórios semanais — {date.today():%d/%m/%Y}",
        body=body,
    )
    print(f"Issue de revisão: {issue.html_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
