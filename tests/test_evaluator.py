import unittest
from datetime import datetime, timezone

from backend.engine.evaluator import evaluate_project
from backend.models import Measurement, Project, SourceEvidence, TrialEvent
from backend.rules.schema import Rule, RuleSource


SOURCE = RuleSource(
    source_id="onco-301",
    title="ONCO-301 demo SOP",
    source_type="sop",
    text="ONCO-301 demo SOP test fixture",
)


class EvaluatorTestCase(unittest.TestCase):
    def test_cbc_interval_failure_and_pass(self) -> None:
        rule = _rule(
            "recurring_event",
            "CBC interval <=24 hours",
            {
                "event_type": "blood_draw",
                "attribute_filters": {"sample_type": "CBC"},
                "max_interval": {"value": 24, "unit": "hour"},
            },
        )
        failure = _project(
            rule,
            [
                _event("P001", "blood_draw", "2026-08-12T08:00:00Z", {"sample_type": "CBC"}),
                _event("P001", "blood_draw", "2026-08-13T10:30:00Z", {"sample_type": "CBC"}),
            ],
        )
        failure_finding = evaluate_project(failure)[0]
        self.assertEqual(failure_finding.status, "FAIL")
        self.assertEqual(failure_finding.difference["observed_hours"], 26.5)

        passing = _project(
            rule,
            [
                _event("P001", "blood_draw", "2026-08-12T08:00:00Z", {"sample_type": "CBC"}),
                _event("P001", "blood_draw", "2026-08-13T07:30:00Z", {"sample_type": "CBC"}),
            ],
        )
        self.assertEqual(evaluate_project(passing)[0].status, "PASS")

    def test_cbc_before_dosing_window_failure_and_pass(self) -> None:
        rule = _rule(
            "preceding_event_window",
            "CBC <=72 hours before dosing",
            {
                "anchor_event_type": "study_drug_administration",
                "required_event_type": "blood_draw",
                "required_attribute_filters": {"sample_type": "CBC"},
                "max_window": {"value": 72, "unit": "hour"},
            },
        )
        failure = _project(
            rule,
            [
                _event("P001", "blood_draw", "2026-08-10T08:00:00Z", {"sample_type": "CBC"}),
                _event("P001", "study_drug_administration", "2026-08-13T13:00:00Z"),
            ],
        )
        failure_finding = evaluate_project(failure)[0]
        self.assertEqual(failure_finding.status, "FAIL")
        self.assertEqual(failure_finding.difference["observed_hours"], 77)

        passing = _project(
            rule,
            [
                _event("P001", "blood_draw", "2026-08-10T13:30:00Z", {"sample_type": "CBC"}),
                _event("P001", "study_drug_administration", "2026-08-13T13:00:00Z"),
            ],
        )
        self.assertEqual(evaluate_project(passing)[0].status, "PASS")

    def test_consent_prerequisite_failure_and_pass(self) -> None:
        rule = _rule(
            "prerequisite",
            "Consent before research procedure",
            {
                "anchor_event_type": "research_procedure",
                "required_event_type": "consent_signed",
            },
        )
        failure = _project(
            rule,
            [
                _event("P001", "research_procedure", "2026-08-13T10:00:00Z"),
                _event("P001", "consent_signed", "2026-08-13T11:00:00Z"),
            ],
        )
        self.assertEqual(evaluate_project(failure)[0].status, "FAIL")

        passing = _project(
            rule,
            [
                _event("P001", "consent_signed", "2026-08-13T09:00:00Z"),
                _event("P001", "research_procedure", "2026-08-13T10:00:00Z"),
            ],
        )
        self.assertEqual(evaluate_project(passing)[0].status, "PASS")

    def test_platelet_threshold_failure_and_pass(self) -> None:
        rule = _rule(
            "numeric_threshold",
            "Platelet count >=100000",
            {
                "measurement_name": "platelet_count",
                "operator": ">=",
                "threshold": 100000,
            },
        )
        failure = _project(
            rule,
            [_event("P001", "lab_result", "2026-08-13T08:00:00Z", measurements=[_platelets(92000)])],
        )
        failure_finding = evaluate_project(failure)[0]
        self.assertEqual(failure_finding.status, "FAIL")
        self.assertEqual(failure_finding.difference["observed_value"], 92000)

        passing = _project(
            rule,
            [_event("P001", "lab_result", "2026-08-13T08:00:00Z", measurements=[_platelets(101000)])],
        )
        self.assertEqual(evaluate_project(passing)[0].status, "PASS")


def _rule(rule_type: str, name: str, parameters: dict) -> Rule:
    return Rule(
        rule_id=f"rule-{rule_type}",
        name=name,
        description=name,
        rule_type=rule_type,
        trigger={},
        conditions={},
        parameters=parameters,
        severity="high",
        enforcement="warning",
        human_review_required=False,
        source=SOURCE,
        confidence=1.0,
    )


def _project(rule: Rule, events: list[TrialEvent]) -> Project:
    return Project(name="ONCO-301", rules=[rule], events=events)


def _event(
    participant_id: str,
    event_type: str,
    timestamp: str,
    attributes: dict | None = None,
    measurements: list[Measurement] | None = None,
) -> TrialEvent:
    return TrialEvent(
        project_id="proj-test",
        participant_id=participant_id,
        event_type=event_type,
        timestamp=datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
        attributes=attributes or {},
        measurements=measurements or [],
        source=SourceEvidence(source_type="test", raw_text="test fixture"),
        extraction_confidence=1.0,
        human_verification_required=False,
    )


def _platelets(value: float) -> Measurement:
    return Measurement(name="platelet_count", value=value, unit="/uL")


if __name__ == "__main__":
    unittest.main()
