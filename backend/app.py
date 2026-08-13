from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from backend.ai.evidence_normalizer import (
    EvidenceNormalizationError,
    normalize_csv_evidence,
    normalize_pdf_evidence,
    normalize_text_evidence,
)
from backend.ai.rule_compiler import RuleCompilationError, compile_rules_from_sources
from backend.engine.evaluator import evaluate_project
from backend.integrations.convoke import (
    ConvokeIntegrationError,
    discover_tools,
    fetch_programs,
)
from backend.models import (
    ConvokeEnrichmentRequest,
    ConvokeProgram,
    ConvokeToolInfo,
    EvidenceTextCreate,
    Finding,
    KnowledgeSource,
    KnowledgeSourceCreate,
    Project,
    ProjectContext,
    ProjectCreate,
    TrialEvent,
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.post("/projects/{project_id}/evidence/text", response_model=list[TrialEvent])
def add_text_evidence(project_id: str, payload: EvidenceTextCreate) -> list[TrialEvent]:
    _get_project_or_404(project_id)
    events = normalize_text_evidence(project_id=project_id, content=payload.content)
    _save_events_and_evaluate(project_id, events)
    return events


@app.post("/projects/{project_id}/evidence/file", response_model=list[TrialEvent])
async def add_file_evidence(
    project_id: str, file: UploadFile = File(...)
) -> list[TrialEvent]:
    _get_project_or_404(project_id)
    filename = file.filename or "uploaded"
    suffix = Path(filename).suffix.lower()
    content = await file.read()
    try:
        if suffix == ".txt":
            events = normalize_text_evidence(
                project_id=project_id,
                content=content.decode("utf-8"),
                source_type="text",
                filename=filename,
            )
        elif suffix == ".csv":
            events = normalize_csv_evidence(
                project_id=project_id,
                content=content.decode("utf-8-sig"),
                filename=filename,
            )
        elif suffix == ".pdf":
            events = normalize_pdf_evidence(
                project_id=project_id,
                content=content,
                filename=filename,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="unsupported file type; accepted extensions are .txt, .csv, .pdf",
            )
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="file must be UTF-8 text") from exc
    except EvidenceNormalizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _save_events_and_evaluate(project_id, events)
    return events


@app.get("/projects/{project_id}/events", response_model=list[TrialEvent])
def list_events(project_id: str) -> list[TrialEvent]:
    return _get_project_or_404(project_id).events


@app.get("/projects/{project_id}/findings", response_model=list[Finding])
def list_findings(project_id: str) -> list[Finding]:
    return _get_project_or_404(project_id).findings


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


def _save_events_and_evaluate(project_id: str, events: list[TrialEvent]) -> None:
    updated_project = store.add_events(project_id, events)
    if updated_project is None:
        raise HTTPException(status_code=404, detail="project not found")
    findings = evaluate_project(updated_project)
    if store.replace_findings(project_id, findings) is None:
        raise HTTPException(status_code=404, detail="project not found")
