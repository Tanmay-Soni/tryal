from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Iterable

from backend.engine.registry import is_supported_rule_type
from backend.models import Finding, Project, TrialEvent
from backend.rules.schema import Rule, RuleType


def evaluate_project(project: Project) -> list[Finding]:
    findings: list[Finding] = []
    for rule in project.rules:
        if not is_supported_rule_type(rule.rule_type):
            continue
        findings.extend(_evaluate_rule(project, rule))
    return findings


def _evaluate_rule(project: Project, rule: Rule) -> list[Finding]:
    if rule.rule_type == RuleType.RECURRING_EVENT:
        return _evaluate_recurring_event(project, rule)
    if rule.rule_type == RuleType.PRECEDING_EVENT_WINDOW:
        return _evaluate_preceding_event_window(project, rule)
    if rule.rule_type == RuleType.PREREQUISITE:
        return _evaluate_prerequisite(project, rule)
    if rule.rule_type == RuleType.NUMERIC_THRESHOLD:
        return _evaluate_numeric_threshold(project, rule)
    if rule.rule_type == RuleType.VERSION_MATCH:
        return _evaluate_version_match(project, rule)
    if rule.rule_type == RuleType.AUTHORIZATION_WINDOW:
        return _evaluate_authorization_window(project, rule)
    if rule.rule_type == RuleType.QUALIFICATION_MATCH:
        return _evaluate_qualification_match(project, rule)
    return []


def _evaluate_recurring_event(project: Project, rule: Rule) -> list[Finding]:
    event_type = _param(rule, "event_type", "blood_draw")
    max_interval = _duration_hours(
        _param(rule, "max_interval") or _param(rule, "duration") or {"value": 24, "unit": "hour"}
    )
    attribute_filters = _param(rule, "attribute_filters", {})
    events = sorted(
        [
            event
            for event in project.events
            if event.event_type == event_type
            and event.timestamp is not None
            and _matches_attributes(event, attribute_filters)
        ],
        key=lambda event: event.timestamp,
    )

    grouped = _by_participant(events)
    findings: list[Finding] = []
    for participant_id, participant_events in grouped.items():
        if len(participant_events) < 2:
            continue
        latest_next_due_at = participant_events[-1].timestamp + timedelta(hours=max_interval)
        for previous, current in zip(participant_events, participant_events[1:]):
            observed_hours = _hours_between(previous.timestamp, current.timestamp)
            status = "PASS" if observed_hours <= max_interval else "FAIL"
            findings.append(
                _finding(
                    project=project,
                    rule=rule,
                    participant_id=participant_id,
                    status=status,
                    expected=f"Interval <= {max_interval:g} hours",
                    observed=f"Observed interval: {observed_hours:g} hours",
                    difference={
                        "observed_hours": observed_hours,
                        "allowed_hours": max_interval,
                    },
                    evidence={"event_ids": [previous.event_id, current.event_id]},
                    explanation=(
                        f"{rule.name}: observed interval was {observed_hours:g} hours; "
                        f"allowed interval is <= {max_interval:g} hours."
                    ),
                    next_due_at=latest_next_due_at,
                )
            )
    return findings


def _evaluate_preceding_event_window(project: Project, rule: Rule) -> list[Finding]:
    anchor_type = _param(rule, "anchor_event_type", "study_drug_administration")
    required_type = _param(rule, "required_event_type", "blood_draw")
    max_window = _duration_hours(
        _param(rule, "max_window") or _param(rule, "duration") or {"value": 72, "unit": "hour"}
    )
    required_filters = _param(rule, "required_attribute_filters", {})
    anchors = _timestamped(project.events, event_type=anchor_type)
    required_events = _timestamped(project.events, event_type=required_type)
    findings = []
    for anchor in anchors:
        candidates = [
            event
            for event in required_events
            if _same_subject(event, anchor)
            and event.timestamp <= anchor.timestamp
            and _matches_attributes(event, required_filters)
        ]
        latest = max(candidates, key=lambda event: event.timestamp, default=None)
        if latest is None:
            findings.append(
                _finding(
                    project,
                    rule,
                    anchor.participant_id,
                    "FAIL",
                    f"{required_type} within {max_window:g} hours before {anchor_type}",
                    "No qualifying prior event found",
                    None,
                    {"event_ids": [anchor.event_id]},
                    f"{rule.name}: no qualifying prior {required_type} was found.",
                )
            )
            continue
        observed_hours = _hours_between(latest.timestamp, anchor.timestamp)
        status = "PASS" if observed_hours <= max_window else "FAIL"
        findings.append(
            _finding(
                project,
                rule,
                anchor.participant_id,
                status,
                f"{required_type} within {max_window:g} hours before {anchor_type}",
                f"Observed: {observed_hours:g} hours before {anchor_type}",
                {"observed_hours": observed_hours, "allowed_hours": max_window},
                {"event_ids": [latest.event_id, anchor.event_id]},
                f"{rule.name}: observed window was {observed_hours:g} hours; allowed window is <= {max_window:g} hours.",
            )
        )
    return findings


def _evaluate_prerequisite(project: Project, rule: Rule) -> list[Finding]:
    anchor_type = _param(rule, "anchor_event_type", "research_procedure")
    required_type = _param(rule, "required_event_type", "consent_signed")
    anchors = _timestamped(project.events, event_type=anchor_type)
    required_events = _timestamped(project.events, event_type=required_type)
    findings = []
    for anchor in anchors:
        prior = [
            event
            for event in required_events
            if _same_subject(event, anchor) and event.timestamp <= anchor.timestamp
        ]
        status = "PASS" if prior else "FAIL"
        observed = (
            f"{required_type} occurred before {anchor_type}"
            if prior
            else f"No {required_type} before {anchor_type}"
        )
        evidence_ids = [anchor.event_id]
        if prior:
            evidence_ids.insert(0, max(prior, key=lambda event: event.timestamp).event_id)
        findings.append(
            _finding(
                project,
                rule,
                anchor.participant_id,
                status,
                f"{required_type} before {anchor_type}",
                observed,
                None,
                {"event_ids": evidence_ids},
                f"{rule.name}: prerequisite status is {status}.",
            )
        )
    return findings


def _evaluate_numeric_threshold(project: Project, rule: Rule) -> list[Finding]:
    measurement_name = _param(rule, "measurement_name")
    operator = _param(rule, "operator")
    threshold_value = _param(rule, "threshold")
    if not measurement_name or not operator or threshold_value is None:
        return []
    threshold = float(threshold_value)
    findings = []
    for event in project.events:
        for measurement in event.measurements:
            if measurement.name != measurement_name:
                continue
            passed = _compare(measurement.value, operator, threshold)
            status = "PASS" if passed else "FAIL"
            findings.append(
                _finding(
                    project,
                    rule,
                    event.participant_id,
                    status,
                    f"{measurement_name} {operator} {threshold:g} {measurement.unit}",
                    f"Observed: {measurement.value:g} {measurement.unit}",
                    {
                        "observed_value": measurement.value,
                        "threshold": threshold,
                        "operator": operator,
                    },
                    {"event_ids": [event.event_id]},
                    f"{rule.name}: observed {measurement_name} was {measurement.value:g}; required {operator} {threshold:g}.",
                )
            )
    return findings


def _evaluate_version_match(project: Project, rule: Rule) -> list[Finding]:
    attribute_name = _param(rule, "attribute_name", "protocol_version")
    expected_attribute = _param(rule, "expected_attribute", "current_approved_protocol_version")
    findings = []
    for event in project.events:
        observed = event.attributes.get(attribute_name)
        expected = event.attributes.get(expected_attribute)
        if observed is None or expected is None:
            continue
        status = "PASS" if observed == expected else "FAIL"
        findings.append(
            _finding(
                project,
                rule,
                event.participant_id,
                status,
                f"{attribute_name} matches {expected_attribute}",
                f"{attribute_name}={observed}; {expected_attribute}={expected}",
                {"observed": observed, "expected": expected},
                {"event_ids": [event.event_id]},
                f"{rule.name}: version match status is {status}.",
            )
        )
    return findings


def _evaluate_authorization_window(project: Project, rule: Rule) -> list[Finding]:
    anchor_type = _param(rule, "anchor_event_type", "study_drug_administration")
    anchors = _timestamped(project.events, event_type=anchor_type)
    starts = _timestamped(project.events, event_type="delegation_started")
    ends = _timestamped(project.events, event_type="delegation_ended")
    findings = []
    for anchor in anchors:
        active_start = [
            event
            for event in starts
            if _same_actor(event, anchor) and event.timestamp <= anchor.timestamp
        ]
        active_end = [
            event
            for event in ends
            if _same_actor(event, anchor) and event.timestamp <= anchor.timestamp
        ]
        status = "PASS" if active_start and not _ended_after_latest_start(active_start, active_end) else "FAIL"
        findings.append(
            _finding(
                project,
                rule,
                anchor.participant_id,
                status,
                f"Active delegation on date of {anchor_type}",
                "Active delegation found" if status == "PASS" else "No active delegation found",
                None,
                {"event_ids": [anchor.event_id]},
                f"{rule.name}: authorization status is {status}.",
            )
        )
    return findings


def _evaluate_qualification_match(project: Project, rule: Rule) -> list[Finding]:
    anchor_type = _param(rule, "anchor_event_type", "study_drug_administration")
    anchors = _timestamped(project.events, event_type=anchor_type)
    trainings = _timestamped(project.events, event_type="protocol_training_completed")
    findings = []
    for anchor in anchors:
        prior_training = [
            event
            for event in trainings
            if _same_actor(event, anchor) and event.timestamp <= anchor.timestamp
        ]
        status = "PASS" if prior_training else "FAIL"
        findings.append(
            _finding(
                project,
                rule,
                anchor.participant_id,
                status,
                f"Protocol training completed before {anchor_type}",
                "Prior training found" if prior_training else "No prior training found",
                None,
                {"event_ids": [anchor.event_id]},
                f"{rule.name}: qualification status is {status}.",
            )
        )
    return findings


def _finding(
    project: Project,
    rule: Rule,
    participant_id: str | None,
    status: str,
    expected: str,
    observed: str,
    difference: dict[str, Any] | None,
    evidence: dict[str, Any],
    explanation: str,
    next_due_at: datetime | None = None,
) -> Finding:
    return Finding(
        project_id=project.project_id,
        participant_id=participant_id,
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity.value if hasattr(rule.severity, "value") else str(rule.severity),
        status=status,
        expected=expected,
        observed=observed,
        difference=difference,
        evidence=evidence,
        explanation=explanation,
        human_review_required=rule.human_review_required or status == "REVIEW",
        next_due_at=next_due_at,
    )


def _timestamped(events: Iterable[TrialEvent], event_type: str) -> list[TrialEvent]:
    return [
        event
        for event in events
        if event.event_type == event_type and event.timestamp is not None
    ]


def _by_participant(events: Iterable[TrialEvent]) -> dict[str | None, list[TrialEvent]]:
    grouped: dict[str | None, list[TrialEvent]] = defaultdict(list)
    for event in events:
        grouped[event.participant_id].append(event)
    return grouped


def _matches_attributes(event: TrialEvent, filters: dict[str, Any]) -> bool:
    for key, expected in filters.items():
        if str(event.attributes.get(key, "")).lower() != str(expected).lower():
            return False
    return True


def _same_subject(left: TrialEvent, right: TrialEvent) -> bool:
    return left.participant_id == right.participant_id or not left.participant_id or not right.participant_id


def _same_actor(left: TrialEvent, right: TrialEvent) -> bool:
    return left.actor_id == right.actor_id or not left.actor_id or not right.actor_id


def _ended_after_latest_start(starts: list[TrialEvent], ends: list[TrialEvent]) -> bool:
    latest_start = max(starts, key=lambda event: event.timestamp)
    return any(event.timestamp >= latest_start.timestamp for event in ends)


def _duration_hours(duration: Any) -> float:
    if isinstance(duration, dict):
        value = float(duration.get("value", 0))
        unit = str(duration.get("unit", "hour")).lower()
    else:
        value = float(duration)
        unit = "hour"
    if unit.startswith("minute"):
        return value / 60
    if unit.startswith("day"):
        return value * 24
    return value


def _hours_between(start: datetime, end: datetime) -> float:
    return round((end - start).total_seconds() / 3600, 3)


def _compare(value: float, operator: str, threshold: float) -> bool:
    if operator == ">=":
        return value >= threshold
    if operator == ">":
        return value > threshold
    if operator == "<=":
        return value <= threshold
    if operator == "<":
        return value < threshold
    if operator in {"=", "=="}:
        return value == threshold
    return False


def _param(rule: Rule, key: str, default: Any = None) -> Any:
    return rule.parameters.get(key, default)
