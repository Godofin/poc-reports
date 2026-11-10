from __future__ import annotations

from crewai import LLM, Agent, Crew, Process, Task

from .collector import PocActivity
from .config import Settings


def build_llm(settings: Settings) -> LLM:
    if not settings.llm_api_key:
        raise RuntimeError(
            "Nenhuma chave de LLM encontrada. Defina GITHUB_TOKEN (GitHub Models) ou LLM_API_KEY."
        )
    if settings.llm_base_url:
        return LLM(
            model=settings.llm_model,
            custom_openai=True,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            temperature=0.2,
        )
    return LLM(model=settings.llm_model, api_key=settings.llm_api_key, temperature=0.2)


def build_crew(llm: LLM) -> Crew:
    analista = Agent(
        role="Analista Técnico de PoCs",
        goal="Transformar a atividade bruta do GitHub em uma visão clara do que a equipe realmente entregou",
        backstory=(
            "Você é um tech lead de consultoria que acompanha várias PoCs. Sabe ler "
            "commits, PRs e issues e agrupá-los em entregas com significado, ignorando "
            "ruído como ajustes de formatação, typos e mudanças de dependência."
        ),
        llm=llm,
        allow_delegation=False,
        max_iter=3,
        verbose=False,
    )
    redator = Agent(
        role="Redator de Status para Clientes",
        goal="Escrever um relatório semanal claro, honesto e não técnico para o cliente",
        backstory=(
            "Você é gerente de projetos de uma consultoria. Escreve relatórios semanais "
            "para clientes: objetivos, sem jargão, focados em progresso em relação ao "
            "objetivo da PoC. Nunca inventa entregas e sinaliza riscos com transparência."
        ),
        llm=llm,
        allow_delegation=False,
        max_iter=3,
        verbose=False,
    )

    analise = Task(
        description=(
            "PoC: {nome} (cliente: {cliente})\n"
            "Objetivo da PoC: {contexto}\n"
            "Período: {periodo}\n"
            "Notas da equipe: {notas}\n\n"
            "Atividade no GitHub no período:\n{atividade}\n\n"
            "Agrupe a atividade em entregas concluídas, trabalho em andamento e "
            "possíveis riscos ou bloqueios (ex.: pouca atividade, issues de bug abertas, "
            "PRs parados). Use apenas o que está nos dados acima."
        ),
        expected_output=(
            "Lista estruturada com: entregas concluídas (com referência a PRs/commits), "
            "itens em andamento, riscos/bloqueios identificados."
        ),
        agent=analista,
    )
    relatorio = Task(
        description=(
            "Com base na análise, escreva o relatório semanal da PoC {nome} para o "
            "cliente {cliente}, em português do Brasil, em Markdown, com exatamente "
            "estas seções:\n"
            "## Resumo da semana (2 a 3 frases, relacionando com o objetivo da PoC)\n"
            "## Entregas realizadas\n"
            "## Em andamento\n"
            "## Próximos passos\n"
            "## Riscos e pontos de atenção (escreva 'Nenhum identificado' se não houver)\n\n"
            "Linguagem de negócio, sem nomes de arquivos ou detalhes de código. "
            "Não inclua título principal nem metadados; eles são adicionados depois."
        ),
        expected_output="Relatório em Markdown com as 5 seções pedidas.",
        agent=redator,
        context=[analise],
    )

    # max_rpm respeita o limite de requisições por minuto do GitHub Models gratuito.
    return Crew(
        agents=[analista, redator],
        tasks=[analise, relatorio],
        process=Process.sequential,
        max_rpm=10,
        verbose=False,
    )


def generate_report_body(activity: PocActivity, llm: LLM) -> str:
    poc = activity.poc
    periodo = f"{activity.since:%d/%m/%Y} a {activity.until:%d/%m/%Y}"
    result = build_crew(llm).kickoff(inputs={
        "nome": poc.nome,
        "cliente": poc.cliente,
        "contexto": poc.contexto.strip() or "não informado",
        "notas": poc.notas.strip() or "nenhuma",
        "periodo": periodo,
        "atividade": activity.to_prompt_text(),
    })
    return result.raw.strip()
