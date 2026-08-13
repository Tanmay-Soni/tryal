import json
import os
import re
from uuid import uuid4

from pydantic import ValidationError

from backend.ai.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from backend.models import KnowledgeSource
from backend.rules.schema import CompiledRulesPayload, Rule, RuleSource, RuleType


class RuleCompilationError(RuntimeError):
    pass


def compile_rules_from_sources(sources: list[KnowledgeSource]) -> list[Rule]:
    if not sources:
        return []

    raw_payload = _compile_with_strands_if_configured(sources)
    if raw_payload is None:
        raw_payload = _mock_compile_rules(sources)

    try:
        return CompiledRulesPayload.model_validate(raw_payload).rules
    except ValidationError as exc:
        raise RuleCompilationError("compiled rules failed schema validation") from exc


def _compile_with_strands_if_configured(
    sources: list[KnowledgeSource],
) -> dict | None:
    if os.getenv("USE_STRANDS_COMPILER") != "true":
        return None

    try:
        from strands import Agent  # type: ignore
    except ImportError:
        return None

    sources_json = json.dumps(
        [source.model_dump(mode="json") for source in sources], indent=2
    )
    prompt = USER_PROMPT_TEMPLATE.format(sources_json=sources_json)
    try:
        agent = Agent(system_prompt=SYSTEM_PROMPT)
        response = agent(prompt)
    except Exception:
        return None

    text = str(response).strip()
    return json.loads(_extract_json_object(text))


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise RuleCompilationError("model response did not contain a JSON object")
    return text[start : end + 1]


def _mock_compile_rules(sources: list[KnowledgeSource]) -> dict:
    rules: list[Rule] = []
    for source in sources:
        for sentence in _candidate_requirement_sentences(source.content):
            rule_type = _infer_rule_type(sentence)
            if rule_type is None:
                continue
            uncertain = _is_uncertain(sentence)
            rules.append(
                Rule(
                    rule_id=f"rule_{uuid4().hex}",
                    name=_make_rule_name(sentence),
                    description=sentence,
                    rule_type=rule_type,
                    trigger=_infer_trigger(sentence),
                    conditions=_infer_conditions(sentence),
                    parameters=_infer_parameters(sentence),
                    severity="medium",
                    enforcement="warning",
                    human_review_required=uncertain,
                    source=RuleSource(
                        source_id=source.source_id,
                        title=source.title,
                        source_type=source.type.value,
                        text=sentence,
                        section=_infer_section(sentence),
                    ),
                    confidence=0.55 if uncertain else 0.75,
                )
            )
    return {"rules": [rule.model_dump(mode="json") for rule in rules]}


def _candidate_requirement_sentences(content: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", content.strip())
    parts = re.split(r"(?<=[.!?])\s+|(?:\n+)", normalized)
    requirement_markers = (
        "must",
        "shall",
        "required",
        "requires",
        "within",
        "before",
        "after",
        "prior to",
        "no later than",
        "at least",
        "not exceed",
        "signed",
        "approved",
        "documented",
        "qualified",
        "authorized",
    )
    sentences = []
    for part in parts:
        sentence = part.strip(" -")
        if len(sentence) < 12:
            continue
        lowered = sentence.lower()
        if any(marker in lowered for marker in requirement_markers):
            sentences.append(sentence)
    return sentences


def _infer_rule_type(sentence: str) -> RuleType | None:
    lowered = sentence.lower()
    if "cbc" in lowered and "interval" in lowered:
        return RuleType.RECURRING_EVENT
    if "consent" in lowered and "before" in lowered and "procedure" in lowered:
        return RuleType.PREREQUISITE
    if lowered.startswith("if ") or " if " in lowered:
        return RuleType.CONDITIONAL_FOLLOWUP
    if any(term in lowered for term in ("platelet", "alt ")) and any(
        term in lowered for term in ("at least", "not exceed", "greater than", "less than", "exceeds")
    ):
        return RuleType.NUMERIC_THRESHOLD
    if "delegation" in lowered:
        return RuleType.AUTHORIZATION_WINDOW
    if any(term in lowered for term in ("authorized", "authorization")):
        return RuleType.AUTHORIZATION_WINDOW
    if any(term in lowered for term in ("qualified", "qualification", "training")):
        return RuleType.QUALIFICATION_MATCH
    if "version" in lowered:
        return RuleType.VERSION_MATCH
    if any(term in lowered for term in ("every ", "recurring", "periodic", "annually")):
        return RuleType.RECURRING_EVENT
    if any(term in lowered for term in ("before", "prior to", "no later than")):
        return RuleType.PRECEDING_EVENT_WINDOW
    if any(term in lowered for term in ("after", "following", "within")):
        return RuleType.FOLLOWING_EVENT_WINDOW
    if any(term in lowered for term in ("requires", "prerequisite", "must have")):
        return RuleType.PREREQUISITE
    if any(term in lowered for term in ("at least", "not exceed", "greater than", "less than")):
        return RuleType.NUMERIC_THRESHOLD
    if any(term in lowered for term in ("document", "signed", "approved", "filed")):
        return RuleType.REQUIRED_DOCUMENT
    if any(term in lowered for term in ("if ", "when ", "unless")):
        return RuleType.CONDITIONAL_FOLLOWUP
    if any(term in lowered for term in ("must", "shall", "required")):
        return RuleType.REQUIRED_DOCUMENT
    return None


def _infer_trigger(sentence: str) -> dict:
    lowered = sentence.lower()
    if "before" in lowered or "prior to" in lowered:
        return {"event_relation": "before"}
    if "after" in lowered or "following" in lowered or "within" in lowered:
        return {"event_relation": "after"}
    if "if " in lowered or "when " in lowered:
        return {"event_relation": "conditional"}
    return {"event_relation": "unspecified"}


def _infer_conditions(sentence: str) -> dict:
    lowered = sentence.lower()
    if "if " in lowered:
        return {"condition_text": sentence}
    if "unless" in lowered:
        return {"exception_text": sentence}
    return {}


def _infer_parameters(sentence: str) -> dict:
    parameters: dict[str, object] = {}
    lowered = sentence.lower()
    duration_match = re.search(
        r"\b(\d+)\s*(calendar\s+)?(minutes?|hours?|days?)\b", sentence, re.IGNORECASE
    )
    if duration_match:
        unit = duration_match.group(3).lower().rstrip("s")
        parameters["duration"] = {"value": int(duration_match.group(1)), "unit": unit}

    if "cbc" in lowered and "interval" in lowered:
        parameters["event_type"] = "blood_draw"
        parameters["attribute_filters"] = {"sample_type": "CBC"}
        if "duration" in parameters:
            parameters["max_interval"] = parameters["duration"]

    if "cbc" in lowered and "before" in lowered and any(
        term in lowered for term in ("administration", "investigational product", "dosing")
    ):
        parameters["anchor_event_type"] = "study_drug_administration"
        parameters["required_event_type"] = "blood_draw"
        parameters["required_attribute_filters"] = {"sample_type": "CBC"}
        if "duration" in parameters:
            parameters["max_window"] = parameters["duration"]

    if "consent" in lowered and "before" in lowered and "procedure" in lowered:
        parameters["anchor_event_type"] = "research_procedure"
        parameters["required_event_type"] = "consent_signed"

    numeric_match = re.search(r"\b(at least|not exceed|less than|greater than)\s+([\d,]+)\b", sentence, re.IGNORECASE)
    if numeric_match:
        parameters["operator_text"] = numeric_match.group(1).lower()
        parameters["threshold"] = int(numeric_match.group(2).replace(",", ""))
        parameters["operator"] = _operator_from_text(numeric_match.group(1).lower())

    if "platelet" in lowered:
        parameters["measurement_name"] = "platelet_count"
        parameters["unit"] = "/uL"
        if "threshold" not in parameters:
            parameters["threshold"] = 100000
            parameters["operator"] = ">="

    if "delegation" in lowered:
        parameters["anchor_event_type"] = "study_drug_administration"

    if "training" in lowered:
        parameters["anchor_event_type"] = "study_drug_administration"

    if "protocol version" in lowered:
        parameters["attribute_name"] = "protocol_version"
        parameters["expected_attribute"] = "current_approved_protocol_version"

    if "consent form version" in lowered or "informed consent form version" in lowered:
        parameters["attribute_name"] = "consent_form_version"
        parameters["expected_attribute"] = "current_approved_consent_form_version"

    return parameters


def _operator_from_text(operator_text: str) -> str:
    if operator_text in {"at least", "greater than"}:
        return ">=" if operator_text == "at least" else ">"
    if operator_text in {"not exceed", "less than"}:
        return "<=" if operator_text == "not exceed" else "<"
    return operator_text


def _infer_section(sentence: str) -> str | None:
    section_match = re.search(r"\b(section|sec\.?)\s+([A-Za-z0-9_.-]+)", sentence, re.IGNORECASE)
    if section_match:
        return f"{section_match.group(1)} {section_match.group(2)}"
    return None


def _is_uncertain(sentence: str) -> bool:
    return any(
        marker in sentence.lower()
        for marker in ("as appropriate", "if applicable", "where possible", "timely", "adequate")
    )


def _make_rule_name(sentence: str) -> str:
    words = re.sub(r"[^A-Za-z0-9 ]+", "", sentence).split()
    return " ".join(words[:8]) or "Compiled compliance rule"
