from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Poc:
    nome: str
    cliente: str
    repos: list[str]
    contexto: str = ""
    responsavel: str = ""
    responsavel_github: str = ""
    branch: str | None = None
    notas: str = ""
    ativo: bool = True


@dataclass
class Settings:
    # Token para ler os repositórios das PoCs (PAT com leitura nos repos).
    github_token: str | None
    # Configuração do LLM. Padrão: Groq (tier gratuito, API compatível com OpenAI).
    llm_model: str
    llm_base_url: str | None
    llm_api_key: str | None


def load_pocs(path: str | Path) -> list[Poc]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    pocs = []
    for i, raw in enumerate(data.get("pocs", [])):
        missing = [k for k in ("nome", "cliente", "repos") if not raw.get(k)]
        if missing:
            raise ValueError(f"PoC #{i + 1} em {path}: campos obrigatórios ausentes: {missing}")
        pocs.append(Poc(**{k: v for k, v in raw.items() if v is not None}))
    return [p for p in pocs if p.ativo]


def load_settings() -> Settings:
    github_token = os.getenv("POC_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN")
    # LLM_BASE_URL vazio = usa o provedor nativo indicado no LLM_MODEL (ex.: anthropic/...).
    base_url = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1") or None
    return Settings(
        github_token=github_token,
        # O prefixo "openai/" diz ao CrewAI para usar o cliente compatível com OpenAI;
        # o restante ("llama-3.3-70b-versatile") é o id do modelo no provedor.
        llm_model=os.getenv("LLM_MODEL") or "openai/llama-3.3-70b-versatile",
        llm_base_url=base_url,
        llm_api_key=os.getenv("LLM_API_KEY"),
    )
