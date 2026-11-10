"""Coleta a atividade semanal das PoCs na API do GitHub (sem LLM).

Só metadados vão para o LLM: mensagens de commit, títulos e descrições de PRs
e issues. O código (diff) nunca é enviado.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from github import Auth, Github
from github.GithubException import GithubException

from .config import Poc

# O GitHub Models gratuito aceita ~8k tokens de entrada por requisição.
# ~12k caracteres de atividade deixam folga para os prompts dos agentes.
MAX_ACTIVITY_CHARS = 12_000
MAX_BODY_CHARS = 200


@dataclass
class RepoActivity:
    repo: str
    commits: list[dict] = field(default_factory=list)
    prs_merged: list[dict] = field(default_factory=list)
    prs_open: list[dict] = field(default_factory=list)
    issues_closed: list[dict] = field(default_factory=list)
    issues_opened: list[dict] = field(default_factory=list)
    error: str | None = None


@dataclass
class PocActivity:
    poc: Poc
    since: datetime
    until: datetime
    repos: list[RepoActivity]

    @property
    def is_empty(self) -> bool:
        return not any(
            r.commits or r.prs_merged or r.prs_open or r.issues_closed or r.issues_opened
            for r in self.repos
        )

    def metrics(self) -> dict:
        authors = {c["author"] for r in self.repos for c in r.commits}
        return {
            "commits": sum(len(r.commits) for r in self.repos),
            "prs_merged": sum(len(r.prs_merged) for r in self.repos),
            "prs_open": sum(len(r.prs_open) for r in self.repos),
            "issues_closed": sum(len(r.issues_closed) for r in self.repos),
            "issues_opened": sum(len(r.issues_opened) for r in self.repos),
            "contributors": len(authors),
        }

    def to_prompt_text(self) -> str:
        """Texto compacto da atividade, limitado para caber no contexto do LLM."""
        parts = []
        for r in self.repos:
            lines = [f"## Repositório {r.repo}"]
            if r.error:
                lines.append(f"(não foi possível ler: {r.error})")
            if r.prs_merged:
                lines.append("### PRs mergeados")
                lines += [f"- #{p['number']} {p['title']}{_body(p)}" for p in r.prs_merged]
            if r.prs_open:
                lines.append("### PRs abertos (em andamento)")
                lines += [f"- #{p['number']} {p['title']}{_body(p)}" for p in r.prs_open]
            if r.issues_closed:
                lines.append("### Issues fechadas")
                lines += [f"- #{i['number']} {i['title']}" for i in r.issues_closed]
            if r.issues_opened:
                lines.append("### Issues abertas na semana")
                lines += [f"- #{i['number']} {i['title']}{_body(i)}" for i in r.issues_opened]
            if r.commits:
                lines.append("### Commits")
                lines += [f"- {c['date']} {c['author']}: {c['message']}" for c in r.commits]
            parts.append("\n".join(lines))

        text = "\n\n".join(parts)
        if len(text) > MAX_ACTIVITY_CHARS:
            text = text[:MAX_ACTIVITY_CHARS] + "\n\n[... atividade truncada por limite de tamanho ...]"
        return text


def _body(item: dict) -> str:
    body = re.sub(r"<!--.*?-->", "", item.get("body") or "", flags=re.S).strip()  # templates de PR
    if not body:
        return ""
    body = " ".join(body.split())
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + "..."
    return f" — {body}"


def _first_line(message: str) -> str:
    return message.strip().splitlines()[0] if message.strip() else ""


def collect_repo(gh: Github, full_name: str, since: datetime, until: datetime,
                 branch: str | None) -> RepoActivity:
    act = RepoActivity(repo=full_name)
    try:
        repo = gh.get_repo(full_name)
        sha = branch or repo.default_branch

        for c in repo.get_commits(sha=sha, since=since, until=until):
            msg = _first_line(c.commit.message)
            if msg.lower().startswith("merge "):
                continue  # o PR correspondente já aparece na lista de PRs
            act.commits.append({
                "date": c.commit.author.date.strftime("%d/%m"),
                "author": c.author.login if c.author else c.commit.author.name,
                "message": msg,
            })

        # PRs: ordenados por atualização, então dá para parar ao passar do período.
        for pr in repo.get_pulls(state="all", sort="updated", direction="desc"):
            if pr.updated_at < since:
                break
            item = {"number": pr.number, "title": pr.title, "body": pr.body}
            if pr.merged_at and since <= pr.merged_at <= until:
                act.prs_merged.append(item)
            elif pr.state == "open":
                act.prs_open.append(item)

        for issue in repo.get_issues(state="all", since=since):
            if issue.pull_request:  # a API de issues também devolve PRs
                continue
            item = {"number": issue.number, "title": issue.title, "body": issue.body}
            if issue.closed_at and since <= issue.closed_at <= until:
                act.issues_closed.append(item)
            elif since <= issue.created_at <= until:
                act.issues_opened.append(item)
    except GithubException as e:
        act.error = f"{e.status} {e.data.get('message', '') if isinstance(e.data, dict) else e.data}"
    return act


def collect_poc(poc: Poc, since: datetime, until: datetime, token: str | None) -> PocActivity:
    gh = Github(auth=Auth.Token(token)) if token else Github()
    repos = [collect_repo(gh, name, since, until, poc.branch) for name in poc.repos]
    return PocActivity(poc=poc, since=since, until=until, repos=repos)
