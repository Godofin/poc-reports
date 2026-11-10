"""Uso: python -m poc_reports [--days 7] [--poc "nome"] [--manifest generated.json]"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .collector import collect_poc
from .config import load_pocs, load_settings
from .crew import build_llm, generate_report_body
from .report import empty_week_body, render, write


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # console do Windows
    parser = argparse.ArgumentParser(description="Gera relatórios semanais das PoCs.")
    parser.add_argument("--config", default="pocs.yaml")
    parser.add_argument("--out", default="reports")
    parser.add_argument("--days", type=int, default=7, help="tamanho do período em dias")
    parser.add_argument("--poc", help="gera só a PoC com este nome (contém, sem diferenciar maiúsculas)")
    parser.add_argument("--manifest", help="grava a lista de relatórios gerados neste JSON")
    parser.add_argument("--dry-run", action="store_true",
                        help="só coleta e mostra a atividade, sem chamar o LLM")
    args = parser.parse_args()

    settings = load_settings()
    pocs = load_pocs(args.config)
    if args.poc:
        pocs = [p for p in pocs if args.poc.lower() in p.nome.lower()]
    if not pocs:
        print("Nenhuma PoC ativa encontrada.", file=sys.stderr)
        return 1

    until = datetime.now(timezone.utc)
    since = until - timedelta(days=args.days)
    llm = None if args.dry_run else build_llm(settings)
    generated, failures = [], []

    for i, poc in enumerate(pocs):
        print(f"[{i + 1}/{len(pocs)}] {poc.nome} ({poc.cliente})")
        activity = collect_poc(poc, since, until, settings.github_token)
        for r in activity.repos:
            status = r.error or f"{len(r.commits)} commits, {len(r.prs_merged)} PRs mergeados"
            print(f"    {r.repo}: {status}")

        if args.dry_run:
            print(activity.to_prompt_text() or "(sem atividade)")
            continue

        try:
            if activity.is_empty:
                body = empty_week_body(activity)  # não gasta chamada de LLM
            else:
                body = generate_report_body(activity, llm)
                time.sleep(5)  # folga para o limite por minuto do tier gratuito
        except Exception as e:  # uma PoC com erro não deve derrubar as demais
            print(f"    ERRO ao gerar relatório: {e}", file=sys.stderr)
            failures.append({"poc": poc.nome, "error": str(e)})
            continue

        path = write(activity, render(activity, body, settings.llm_model), Path(args.out))
        print(f"    -> {path}")
        generated.append({
            "poc": poc.nome,
            "cliente": poc.cliente,
            "responsavel_github": poc.responsavel_github,
            "path": path.as_posix(),
            "empty": activity.is_empty,
        })

    if args.manifest:
        Path(args.manifest).write_text(
            json.dumps({"generated": generated, "failures": failures}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 1 if failures and not generated else 0


if __name__ == "__main__":
    sys.exit(main())
