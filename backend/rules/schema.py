from enum import Enum
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class RuleType(str, Enum):
    RECURRING_EVENT = "recurring_event"
    PRECEDING_EVENT_WINDOW = "preceding_event_window"
    FOLLOWING_EVENT_WINDOW = "following_event_window"
    PREREQUISITE = "prerequisite"
    NUMERIC_THRESHOLD = "numeric_threshold"
    VERSION_MATCH = "version_match"
    AUTHORIZATION_WINDOW = "authorization_window"
    QUALIFICATION_MATCH = "qualification_match"
    REQUIRED_DOCUMENT = "required_document"
    CONDITIONAL_FOLLOWUP = "conditional_followup"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Enforcement(str, Enum):
    BLOCKING = "blocking"
    WARNING = "warning"
    MONITORING = "monitoring"


class RuleSource(BaseModel):
    source_id: str
    title: str
    source_type: str
    text: str
    section: Optional[str] = None


class Rule(BaseModel):
    rule_id: str
    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    rule_type: RuleType
    trigger: Dict[str, Any] = Field(default_factory=dict)
    conditions: Dict[str, Any] = Field(default_factory=dict)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    severity: Severity = Severity.MEDIUM
    enforcement: Enforcement = Enforcement.WARNING
    human_review_required: bool = False
    source: RuleSource
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("trigger", "conditions", "parameters")
    @classmethod
    def require_json_object(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("must be a JSON object")
        return value


class CompiledRulesPayload(BaseModel):
    rules: list[Rule]


RuleTypeLiteral = Literal[
    "recurring_event",
    "preceding_event_window",
    "following_event_window",
    "prerequisite",
    "numeric_threshold",
    "version_match",
    "authorization_window",
    "qualification_match",
    "required_document",
    "conditional_followup",
]
