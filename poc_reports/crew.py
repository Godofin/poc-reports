from __future__ import annotations

from crewai import LLM, Agent, Crew, Process, Task

from .collector import PocActivity
from .config import Settings


def build_llm(settings: Settings) -> LLM:
    if not settings.llm_api_key:
        raise RuntimeError(
            "Nenhuma chave de LLM encontrada. Defina LLM_API_KEY (ex.: chave do Groq)."
        )
    # max_retries alto: no tier gratuito o limite de tokens por minuto estoura com
    # frequência (HTTP 429) e o cliente espera o tempo indicado pelo provedor.
    common = dict(api_key=settings.llm_api_key, temperature=0.2, max_retries=6)
    if settings.llm_base_url:
        return LLM(model=settings.llm_model, custom_openai=True,
                   base_url=settings.llm_base_url, **common)
    return LLM(model=settings.llm_model, **common)


def build_crew(llm: LLM) -> Crew:
    analista = Agent(
        role="Analista Técnico de PoCs",
        goal="Extrair dos dados do GitHub um levantamento detalhado e fiel do que a equipe entregou",
        backstory=(
            "Você é um tech lead de consultoria que acompanha várias PoCs. Lê commits, "
            "PRs, issues e documentação e identifica entregas, abordagens técnicas, "
            "resultados e métricas. Ignora ruído (typos, formatação, dependências) e "
            "nunca afirma algo que não esteja nos dados."
        ),
        llm=llm,
        allow_delegation=False,
        max_iter=3,
        verbose=False,
    )
    redator = Agent(
        role="Redator de Status para Clientes",
        goal="Escrever um relatório semanal detalhado, claro e fiel aos fatos para o cliente",
        backstory=(
            "Você é gerente de projetos de uma consultoria. Escreve relatórios semanais "
            "ricos em conteúdo: explica o que foi feito, como e qual o resultado, com "
            "números concretos sempre que existirem. Escreve para gestores com alguma "
            "familiaridade técnica: cita técnicas e ferramentas quando ajudam a entender "
            "o valor, mas sem nomes de arquivos ou detalhes de código. Nunca inventa "
            "fatos e sinaliza riscos com transparência."
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
            "Dados do GitHub no período (commits com arquivos alterados, PRs, issues e "
            "trechos da documentação):\n{atividade}\n\n"
            "Faça um levantamento detalhado. Para cada entrega identificada, registre:\n"
            "- o que foi feito e com qual objetivo;\n"
            "- a abordagem, técnicas e ferramentas usadas;\n"
            "- resultados e métricas citados (valores exatos, como aparecem nos dados);\n"
            "- limitações, decisões ou pendências mencionadas.\n"
            "Liste também o trabalho em andamento, os próximos passos mencionados nos dados "
            "e riscos/bloqueios (ex.: pouca atividade, bugs abertos, PRs parados). "
            "Use somente o que está nos dados: se algo não aparece, não afirme."
        ),
        expected_output=(
            "Levantamento estruturado por entrega (objetivo, abordagem, resultados/métricas, "
            "limitações), seguido de: em andamento, próximos passos citados, riscos."
        ),
        agent=analista,
    )
    relatorio = Task(
        description=(
            "Com base no levantamento, escreva o relatório semanal da PoC {nome} para o "
            "cliente {cliente}, em português do Brasil, em Markdown, com estas seções:\n\n"
            "## Resumo executivo\n"
            "Um parágrafo de 4 a 6 frases: o que avançou, como isso se relaciona com o "
            "objetivo da PoC e a situação geral.\n\n"
            "## Entregas realizadas\n"
            "Um subtítulo (###) por entrega, com 2 a 4 frases ou tópicos explicando o que "
            "foi feito, a abordagem e o resultado obtido.\n\n"
            "## Resultados e indicadores\n"
            "Tabela ou lista com os números concretos encontrados (métricas de modelos, "
            "quantidades, comparações). Se não houver números nos dados, escreva "
            "'Sem indicadores quantitativos registrados no período.'\n\n"
            "## Em andamento\n\n"
            "## Próximos passos\n"
            "Priorize os citados nos dados. Sugestões suas devem ser marcadas com "
            "'(sugestão)'.\n\n"
            "## Riscos e pontos de atenção\n"
            "Escreva 'Nenhum identificado' se não houver.\n\n"
            "Regras: não invente fatos (ex.: não diga que algo foi entregue, apresentado "
            "ou validado com o cliente se os dados não disserem isso); não use nomes de "
            "arquivos; não inclua título principal nem metadados, eles são adicionados depois."
        ),
        expected_output="Relatório em Markdown com as 6 seções pedidas, detalhado e fiel aos dados.",
        agent=redator,
        context=[analise],
    )

    # max_rpm respeita o limite de requisições por minuto dos tiers gratuitos.
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
