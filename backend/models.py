from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from backend.rules.schema import Rule


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class KnowledgeSourceType(str, Enum):
    TEXT = "text"
    URL = "url"
    SOP = "sop"
    PROTOCOL = "protocol"
    REGULATION = "regulation"


class KnowledgeSource(BaseModel):
    source_id: str = Field(default_factory=lambda: new_id("ks"))
    type: KnowledgeSourceType
    title: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    url: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)


class ConvokeProgram(BaseModel):
    drug_name: Optional[str] = None
    organization: Optional[str] = None
    target: Optional[str] = None
    indication: Optional[str] = None
    phase: Optional[str] = None
    status: Optional[str] = None
    raw_data: Optional[dict[str, Any]] = None


class ConvokeToolInfo(BaseModel):
    name: str
    description: Optional[str] = None
    input_schema: Optional[dict[str, Any]] = None


class ProjectContext(BaseModel):
    indication: Optional[str] = None
    target: Optional[str] = None
    investigational_product: Optional[str] = None
    sponsor: Optional[str] = None
    phase: Optional[str] = None
    convoke_programs: list[ConvokeProgram] = Field(default_factory=list)
    convoke_enriched_at: Optional[datetime] = None


class Measurement(BaseModel):
    name: str = Field(..., min_length=1)
    value: float
    unit: str = Field(..., min_length=1)
    reference_upper_limit: Optional[float] = None
    reference_lower_limit: Optional[float] = None


class SourceEvidence(BaseModel):
    source_type: str
    filename: Optional[str] = None
    raw_text: Optional[str] = None
    page: Optional[int] = None
    source_id: Optional[str] = None


class TrialEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("evt"))
    project_id: str
    participant_id: Optional[str] = None
    actor_id: Optional[str] = None
    event_type: str = Field(..., min_length=1)
    timestamp: Optional[datetime] = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    measurements: list[Measurement] = Field(default_factory=list)
    source: SourceEvidence
    extraction_confidence: float = Field(..., ge=0.0, le=1.0)
    human_verification_required: bool = False


class Finding(BaseModel):
    finding_id: str = Field(default_factory=lambda: new_id("finding"))
    project_id: str
    participant_id: Optional[str] = None
    rule_id: str
    rule_name: str
    severity: str
    status: str
    expected: str
    observed: str
    difference: Optional[dict[str, Any]] = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    explanation: str
    human_review_required: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    next_due_at: Optional[datetime] = None


class Project(BaseModel):
    project_id: str = Field(default_factory=lambda: new_id("proj"))
    name: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=utc_now)
    context: ProjectContext = Field(default_factory=ProjectContext)
    knowledge_sources: list[KnowledgeSource] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)
    events: list[TrialEvent] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1)


class KnowledgeSourceCreate(BaseModel):
    type: KnowledgeSourceType
    title: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    url: Optional[str] = None


class ConvokeEnrichmentRequest(BaseModel):
    indication: Optional[str] = None
    target: Optional[str] = None
    drug_name: Optional[str] = None
    organization: Optional[str] = None

    @model_validator(mode="after")
    def require_at_least_one_filter(self) -> "ConvokeEnrichmentRequest":
        if not any((self.indication, self.target, self.drug_name, self.organization)):
            raise ValueError(
                "at least one of indication, target, drug_name, or organization is required"
            )
        return self


class EvidenceTextCreate(BaseModel):
    content: str = Field(..., min_length=1)
