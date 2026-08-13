from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

from backend.ai.rule_compiler import RuleCompilationError, compile_rules_from_sources
from backend.integrations.convoke import (
    ConvokeIntegrationError,
    discover_tools,
    fetch_programs,
)
from backend.models import (
    ConvokeEnrichmentRequest,
    ConvokeProgram,
    ConvokeToolInfo,
    KnowledgeSource,
    KnowledgeSourceCreate,
    Project,
    ProjectContext,
    ProjectCreate,
    utc_now,
)
from backend.rules.schema import Rule
from backend.storage import JsonProjectStore


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

app = FastAPI(
    title="Clinical Trial Compliance Rule Compiler",
    version="0.1.0",
    description=(
        "Hackathon MVP API for converting compliance knowledge sources into "
        "structured executable rule definitions."
    ),
)

store = JsonProjectStore()


@app.post("/projects", response_model=Project, status_code=201)
def create_project(payload: ProjectCreate) -> Project:
    return store.create_project(payload.name)


@app.get("/projects/{project_id}", response_model=Project)
def get_project(project_id: str) -> Project:
    project = _get_project_or_404(project_id)
    return project


@app.post(
    "/projects/{project_id}/knowledge",
    response_model=KnowledgeSource,
    status_code=201,
)
def add_knowledge_source(
    project_id: str, payload: KnowledgeSourceCreate
) -> KnowledgeSource:
    _get_project_or_404(project_id)
    knowledge_source = KnowledgeSource(**payload.model_dump())
    project = store.add_knowledge_source(project_id, knowledge_source)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return knowledge_source


@app.get(
    "/projects/{project_id}/knowledge",
    response_model=list[KnowledgeSource],
)
def list_knowledge_sources(project_id: str) -> list[KnowledgeSource]:
    return _get_project_or_404(project_id).knowledge_sources


@app.post("/projects/{project_id}/compile-rules", response_model=list[Rule])
def compile_rules(project_id: str) -> list[Rule]:
    project = _get_project_or_404(project_id)
    try:
        rules = compile_rules_from_sources(project.knowledge_sources)
    except RuleCompilationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    updated_project = store.replace_rules(project_id, rules)
    if updated_project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return updated_project.rules


@app.get("/projects/{project_id}/rules", response_model=list[Rule])
def list_rules(project_id: str) -> list[Rule]:
    return _get_project_or_404(project_id).rules


@app.get("/projects/{project_id}/context", response_model=ProjectContext)
def get_project_context(project_id: str) -> ProjectContext:
    return _get_project_or_404(project_id).context


@app.get("/integrations/convoke/tools", response_model=list[ConvokeToolInfo])
def list_convoke_tools() -> list[ConvokeToolInfo]:
    try:
        return discover_tools()
    except ConvokeIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/projects/{project_id}/enrich/convoke",
    response_model=ProjectContext,
)
def enrich_project_with_convoke(
    project_id: str, payload: ConvokeEnrichmentRequest
) -> ProjectContext:
    project = _get_project_or_404(project_id)
    try:
        programs = fetch_programs(payload)
    except ConvokeIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    context = ProjectContext(
        indication=payload.indication or _first_program_value(programs, "indication")
        or project.context.indication,
        target=payload.target or _first_program_value(programs, "target")
        or project.context.target,
        investigational_product=payload.drug_name
        or _first_program_value(programs, "drug_name")
        or project.context.investigational_product,
        sponsor=payload.organization or _first_program_value(programs, "organization")
        or project.context.sponsor,
        phase=_first_program_value(programs, "phase") or project.context.phase,
        convoke_programs=programs,
        convoke_enriched_at=utc_now(),
    )

    updated_project = store.update_context(project_id, context)
    if updated_project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return updated_project.context


def _get_project_or_404(project_id: str) -> Project:
    try:
        project = store.get_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _first_program_value(
    programs: list[ConvokeProgram], field_name: str
) -> str | None:
    for program in programs:
        value = getattr(program, field_name, None)
        if value:
            return value
    return None
