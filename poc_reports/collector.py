"""Coleta a atividade semanal das PoCs na API do GitHub (sem LLM).

Vão para o LLM: mensagens de commit, títulos e descrições de PRs e issues,
um resumo dos arquivos alterados (pastas e contagens) e trechos dos documentos
Markdown alterados no período. O código-fonte (diff) nunca é enviado.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from github import Auth, Github
from github.GithubException import GithubException

from .config import Poc

# O tier gratuito do Groq (gpt-oss-120b) permite ~8k tokens por minuto, somando
# entrada e saída. ~15k caracteres (~4,5k tokens) de contexto deixam folga para
# os prompts dos agentes e para a resposta.
MAX_ACTIVITY_CHARS = 8_000
MAX_DOCS_CHARS = 10_000
MAX_BODY_CHARS = 200
MAX_COMMIT_MESSAGE_CHARS = 1_000
MAX_COMMITS_WITH_FILES = 30  # cada commit detalhado custa uma chamada à API do GitHub
MAX_DOCS = 8
DOC_EXTENSIONS = (".md", ".markdown")
# Seções de documentação mais úteis para um relatório de status vêm primeiro;
# as de instruções operacionais são descartadas.
DOC_PRIORITY = ("resultad", "métric", "metric", "indicador", "conclus", "decis",
                "limita", "próximo", "proximo", "risco", "objetivo", "resumo", "visão geral")
DOC_SKIP = ("como reproduzir", "artefato", "ambiente", "instala", "setup", "estrutura",
            "como rodar", "como usar", "licen", "contribu")


@dataclass
class RepoActivity:
    repo: str
    commits: list[dict] = field(default_factory=list)
    prs_merged: list[dict] = field(default_factory=list)
    prs_open: list[dict] = field(default_factory=list)
    issues_closed: list[dict] = field(default_factory=list)
    issues_opened: list[dict] = field(default_factory=list)
    docs: list[dict] = field(default_factory=list)
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
            "files_changed": sum(c.get("files_count", 0) for r in self.repos for c in r.commits),
        }

    def to_prompt_text(self) -> str:
        """Texto da atividade e da documentação, limitado para caber no contexto do LLM."""
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
                for c in r.commits:
                    lines.append(f"- {c['date']} {c['author']}: {c['message']}")
                    if c.get("files"):
                        lines.append(f"  Arquivos alterados: {c['files']}")
            parts.append("\n".join(lines))
        text = _truncate("\n\n".join(parts), MAX_ACTIVITY_CHARS, "atividade")

        docs = [d for r in self.repos for d in r.docs]
        if docs:
            per_doc = MAX_DOCS_CHARS // len(docs)
            doc_parts = [f"### {d['repo']}: {d['path']}\n{_doc_excerpt(d['content'], per_doc)}"
                         for d in docs]
            text += "\n\n## Documentação criada/alterada no período (trechos)\n\n" + "\n\n".join(doc_parts)
        return text


def _truncate(text: str, limit: int, what: str) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[... {what} truncado(a) por limite de tamanho ...]"


def _body(item: dict) -> str:
    body = re.sub(r"<!--.*?-->", "", item.get("body") or "", flags=re.S).strip()  # templates de PR
    if not body:
        return ""
    body = " ".join(body.split())
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + "..."
    return f" — {body}"


def _commit_message(message: str) -> str:
    """Título + corpo da mensagem de commit, em formato compacto, sem trailers."""
    lines = [ln.rstrip() for ln in message.strip().splitlines()
             if ln.strip() and not TRAILER.match(ln.strip())]
    if not lines:
        return ""
    text = lines[0]
    if len(lines) > 1:
        text += "\n" + "\n".join(f"    {ln.strip()}" for ln in lines[1:])
    return _truncate(text, MAX_COMMIT_MESSAGE_CHARS, "mensagem")


TRAILER = re.compile(r"^(Co-Authored-By|Signed-off-by):", re.I)


def _files_summary(files) -> str:
    """Agrupa os arquivos por pasta de primeiro nível: 'docs/ (12 arq., +900/-10)'."""
    groups: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for f in files:
        top = f.filename.split("/")[0] + "/" if "/" in f.filename else f.filename
        g = groups[top]
        g[0] += 1
        g[1] += f.additions
        g[2] += f.deletions
    ordered = sorted(groups.items(), key=lambda kv: (-kv[1][0], kv[0]))[:10]
    return "; ".join(
        f"{name} ({n} arq., +{add}/-{rem})" if n > 1 else f"{name} (+{add}/-{rem})"
        for name, (n, add, rem) in ordered
    )


def _clean_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # imagens
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _doc_excerpt(text: str, limit: int) -> str:
    """Trecho do documento priorizando seções de resultados, decisões e limitações."""
    sections = [sec.strip() for sec in re.split(r"(?m)^(?=#{1,3} )", text) if sec.strip()]
    if not sections:
        return ""
    # A primeira seção é o título do documento (e a introdução, se houver).
    out, rest = sections[0], sections[1:]
    if len(out) > limit // 3:
        out = out[: limit // 3] + " [...]"

    def heading(sec: str) -> str:
        return sec.splitlines()[0].lower()

    useful = [sec for sec in rest if not any(k in heading(sec) for k in DOC_SKIP)]
    first = [sec for sec in useful if any(k in heading(sec) for k in DOC_PRIORITY)]
    ordered = first + [sec for sec in useful if sec not in first]
    for sec in ordered:
        remaining = limit - len(out) - 2
        if remaining < 200:
            break
        out += "\n\n" + (sec if len(sec) <= remaining else sec[:remaining] + " [...]")
    return out


def collect_repo(gh: Github, full_name: str, since: datetime, until: datetime,
                 branch: str | None, include_docs: bool) -> RepoActivity:
    act = RepoActivity(repo=full_name)
    try:
        repo = gh.get_repo(full_name)
        ref = branch or repo.default_branch
        # Documentos alterados: caminho -> (sha do commit mais recente, linhas adicionadas)
        changed_docs: dict[str, tuple[str, int]] = {}

        for i, c in enumerate(repo.get_commits(sha=ref, since=since, until=until)):
            msg = _commit_message(c.commit.message)
            if msg.lower().startswith("merge "):
                continue  # o PR correspondente já aparece na lista de PRs
            item = {
                "date": c.commit.author.date.strftime("%d/%m"),
                "author": c.author.login if c.author else c.commit.author.name,
                "message": msg,
            }
            if i < MAX_COMMITS_WITH_FILES:
                files = list(c.files)
                item["files"] = _files_summary(files)
                item["files_count"] = len(files)
                for f in files:
                    if (include_docs and f.filename.lower().endswith(DOC_EXTENSIONS)
                            and f.status != "removed" and f.filename not in changed_docs):
                        changed_docs[f.filename] = (c.sha, f.additions)
            act.commits.append(item)

        # Os documentos com mais linhas novas primeiro, até MAX_DOCS.
        top_docs = sorted(changed_docs.items(), key=lambda kv: -kv[1][1])[:MAX_DOCS]
        for path, (sha, _) in top_docs:
            try:
                content = repo.get_contents(path, ref=sha).decoded_content.decode("utf-8", "replace")
            except GithubException:
                continue
            act.docs.append({"repo": full_name, "path": path, "content": _clean_markdown(content)})

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
    repos = [collect_repo(gh, name, since, until, poc.branch, poc.incluir_docs) for name in poc.repos]
    return PocActivity(poc=poc, since=since, until=until, repos=repos)
