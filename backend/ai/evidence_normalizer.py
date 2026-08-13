import csv
import io
import os
import re
from datetime import datetime, timezone
from typing import Any

from dateutil import parser as date_parser

from backend.models import Measurement, SourceEvidence, TrialEvent


SUPPORTED_EVENT_TYPES = {
    "blood_draw",
    "lab_result",
    "consent_signed",
    "study_drug_administration",
    "research_procedure",
    "protocol_training_completed",
    "delegation_started",
    "delegation_ended",
}


class EvidenceNormalizationError(RuntimeError):
    pass


def normalize_text_evidence(
    project_id: str,
    content: str,
    source_type: str = "text",
    filename: str | None = None,
    page: int | None = None,
    source_id: str | None = None,
) -> list[TrialEvent]:
    events = _normalize_with_strands_if_configured(
        project_id=project_id,
        content=content,
        source_type=source_type,
        filename=filename,
        page=page,
        source_id=source_id,
    )
    if events is not None:
        return events

    return _heuristic_normalize_text(
        project_id=project_id,
        content=content,
        source_type=source_type,
        filename=filename,
        page=page,
        source_id=source_id,
    )


def normalize_csv_evidence(
    project_id: str,
    content: str,
    filename: str | None = None,
) -> list[TrialEvent]:
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return normalize_text_evidence(project_id, content, source_type="csv", filename=filename)

    events: list[TrialEvent] = []
    for row_number, row in enumerate(reader, start=2):
        row_text = " ".join(
            f"{key}: {value}" for key, value in row.items() if value is not None
        )
        event = _event_from_structured_row(project_id, row, filename, row_number)
        if event is not None:
            events.append(event)
            continue
        events.extend(
            _heuristic_normalize_text(
                project_id=project_id,
                content=row_text,
                source_type="csv",
                filename=filename,
                source_id=f"row-{row_number}",
            )
        )
    return events


def normalize_pdf_evidence(
    project_id: str,
    content: bytes,
    filename: str | None = None,
) -> list[TrialEvent]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise EvidenceNormalizationError(
            "PDF support requires pypdf. Install dependencies with python3 -m pip install -r requirements.txt"
        ) from exc

    reader = PdfReader(io.BytesIO(content))
    events: list[TrialEvent] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if not text.strip():
            continue
        events.extend(
            normalize_text_evidence(
                project_id=project_id,
                content=text,
                source_type="pdf",
                filename=filename,
                page=page_number,
            )
        )
    return events


def _normalize_with_strands_if_configured(
    project_id: str,
    content: str,
    source_type: str,
    filename: str | None,
    page: int | None,
    source_id: str | None,
) -> list[TrialEvent] | None:
    if os.getenv("USE_STRANDS_EVIDENCE_NORMALIZER") != "true":
        return None
    # Placeholder adapter boundary. The local fallback below remains deterministic
    # and does not make compliance decisions.
    return None


def _heuristic_normalize_text(
    project_id: str,
    content: str,
    source_type: str,
    filename: str | None = None,
    page: int | None = None,
    source_id: str | None = None,
) -> list[TrialEvent]:
    events: list[TrialEvent] = []
    for segment in _segments(content):
        event = _event_from_segment(
            project_id=project_id,
            segment=segment,
            source_type=source_type,
            filename=filename,
            page=page,
            source_id=source_id,
        )
        if event is not None:
            events.append(event)
    return events


def _event_from_segment(
    project_id: str,
    segment: str,
    source_type: str,
    filename: str | None,
    page: int | None,
    source_id: str | None,
) -> TrialEvent | None:
    lowered = segment.lower()
    event_type = _infer_event_type(lowered)
    measurements = _measurements_from_text(segment)
    if event_type is None and measurements:
        event_type = "lab_result"
    if event_type is None:
        return None

    attributes = _attributes_from_text(event_type, segment)
    confidence = _confidence_for_event(event_type, segment)
    return TrialEvent(
        project_id=project_id,
        participant_id=_participant_id(segment),
        actor_id=_actor_id(segment),
        event_type=event_type,
        timestamp=_timestamp(segment),
        attributes=attributes,
        measurements=measurements,
        source=SourceEvidence(
            source_type=source_type,
            filename=filename,
            raw_text=segment,
            page=page,
            source_id=source_id,
        ),
        extraction_confidence=confidence,
        human_verification_required=confidence < 0.80,
    )


def _event_from_structured_row(
    project_id: str,
    row: dict[str, Any],
    filename: str | None,
    row_number: int,
) -> TrialEvent | None:
    normalized = {_clean_key(key): value for key, value in row.items()}
    event_type = _clean_value(normalized.get("event_type") or normalized.get("type"))
    row_text = " ".join(str(value) for value in row.values() if value)
    if event_type not in SUPPORTED_EVENT_TYPES:
        return None

    measurement = None
    if normalized.get("measurement_name") and normalized.get("value"):
        measurement = Measurement(
            name=_measurement_name(str(normalized["measurement_name"])),
            value=_measurement_value(
                str(normalized["measurement_name"]),
                str(normalized["value"]),
                str(normalized.get("unit") or ""),
            ),
            unit=_measurement_unit(str(normalized["measurement_name"]), str(normalized.get("unit") or "")),
            reference_upper_limit=_optional_float(normalized.get("reference_upper_limit")),
            reference_lower_limit=_optional_float(normalized.get("reference_lower_limit")),
        )

    return TrialEvent(
        project_id=project_id,
        participant_id=_clean_value(normalized.get("participant_id")),
        actor_id=_clean_value(normalized.get("actor_id")),
        event_type=event_type,
        timestamp=_timestamp(str(normalized.get("timestamp") or row_text)),
        attributes={
            key: value
            for key, value in normalized.items()
            if key
            not in {
                "event_type",
                "type",
                "participant_id",
                "actor_id",
                "timestamp",
                "measurement_name",
                "value",
                "unit",
                "reference_upper_limit",
                "reference_lower_limit",
            }
            and value not in (None, "")
        },
        measurements=[measurement] if measurement else [],
        source=SourceEvidence(
            source_type="csv",
            filename=filename,
            raw_text=row_text,
            source_id=f"row-{row_number}",
        ),
        extraction_confidence=0.95,
        human_verification_required=False,
    )


def _segments(content: str) -> list[str]:
    protected = content.replace("Dr. ", "Dr ")
    lines = [line.strip() for line in protected.splitlines() if line.strip()]
    raw_segments: list[str] = []
    for line in lines or [content]:
        raw_segments.extend(re.split(r"(?<=[.!?])\s+", line))
    return [segment.strip(" -") for segment in raw_segments if len(segment.strip()) >= 4]


def _infer_event_type(lowered: str) -> str | None:
    if "cbc" in lowered and any(term in lowered for term in ("collected", "drawn", "blood draw")):
        return "blood_draw"
    if any(term in lowered for term in ("platelet", "alt ", "lab result", "hemoglobin")):
        return "lab_result"
    if "consent" in lowered and any(term in lowered for term in ("signed", "obtained")):
        return "consent_signed"
    if any(term in lowered for term in ("administered investigational", "investigational therapy", "study drug", "investigational product")):
        return "study_drug_administration"
    if "procedure" in lowered and any(term in lowered for term in ("research", "study-specific", "performed")):
        return "research_procedure"
    if "training" in lowered and any(term in lowered for term in ("completed", "complete")):
        return "protocol_training_completed"
    if "delegation" in lowered and any(term in lowered for term in ("started", "active", "began")):
        return "delegation_started"
    if "delegation" in lowered and any(term in lowered for term in ("ended", "expired")):
        return "delegation_ended"
    return None


def _attributes_from_text(event_type: str, segment: str) -> dict[str, Any]:
    lowered = segment.lower()
    attributes: dict[str, Any] = {}
    if event_type == "blood_draw" and "cbc" in lowered:
        attributes["sample_type"] = "CBC"
    if "protocol version" in lowered:
        version = _version(segment)
        if version:
            attributes["protocol_version"] = version
    if "consent form version" in lowered or "icf version" in lowered:
        version = _version(segment)
        if version:
            attributes["consent_form_version"] = version
    if "current approved" in lowered:
        attributes["current_approved"] = True
    return attributes


def _measurements_from_text(segment: str) -> list[Measurement]:
    measurements: list[Measurement] = []
    platelet_match = re.search(
        r"\bplatelets?(?:\s+count)?\s*[:=]?\s*([\d,.]+)\s*(?:x\s*10\^?3|k)?\s*/?\s*(?:uL|µL|ul)?",
        segment,
        re.IGNORECASE,
    )
    if platelet_match:
        raw_value = platelet_match.group(1)
        unit_text = segment[platelet_match.end() - 12 : platelet_match.end() + 10]
        measurements.append(
            Measurement(
                name="platelet_count",
                value=_measurement_value("platelet_count", raw_value, unit_text),
                unit="/uL",
            )
        )
    return measurements


def _measurement_name(value: str) -> str:
    lowered = value.lower().strip()
    if "platelet" in lowered:
        return "platelet_count"
    return re.sub(r"[^a-z0-9_]+", "_", lowered).strip("_")


def _measurement_value(name: str, value: str, unit: str) -> float:
    numeric = float(value.replace(",", ""))
    if "platelet" in name.lower() and ("10^3" in unit or "x10" in unit.lower() or numeric < 1000):
        return numeric * 1000
    return numeric


def _measurement_unit(name: str, unit: str) -> str:
    if "platelet" in name.lower():
        return "/uL"
    return unit or "unknown"


def _participant_id(text: str) -> str | None:
    match = re.search(r"\b(?:patient|participant|subject)\s+([A-Za-z]*\d+)\b", text, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"\b(P\d{3,})\b", text, re.IGNORECASE)
    return match.group(1).upper() if match else None


def _actor_id(text: str) -> str | None:
    match = re.search(r"\bDr\.?\s+([A-Z][A-Za-z-]+)\b", text)
    if match:
        return f"Dr. {match.group(1)}"
    match = re.search(r"\bstaff\s+([A-Z][A-Za-z-]+)\b", text)
    if match:
        return match.group(1)
    return None


def _timestamp(text: str) -> datetime | None:
    patterns = [
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}(?:\s+(?:at\s+)?\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)?",
        r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            parsed = date_parser.parse(match.group(0), fuzzy=True)
        except (ValueError, OverflowError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _version(text: str) -> str | None:
    match = re.search(r"\bversion\s+([A-Za-z0-9_.-]+)\b", text, re.IGNORECASE)
    return match.group(1) if match else None


def _confidence_for_event(event_type: str, segment: str) -> float:
    if event_type == "lab_result" and _measurements_from_text(segment):
        return 0.95
    if _timestamp(segment) is None:
        return 0.78
    return 0.90


def _clean_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (value or "").strip().lower()).strip("_")


def _clean_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(str(value).replace(",", ""))
