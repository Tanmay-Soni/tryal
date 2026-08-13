import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.app as app_module
from backend.storage import JsonProjectStore


class ApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        app_module.store = JsonProjectStore(Path(self.temp_dir.name))
        self.client = TestClient(app_module.app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_project_knowledge_compile_rules_flow(self) -> None:
        project_response = self.client.post("/projects", json={"name": "Demo"})
        self.assertEqual(project_response.status_code, 201)
        project_id = project_response.json()["project_id"]

        knowledge_response = self.client.post(
            f"/projects/{project_id}/knowledge",
            json={
                "type": "sop",
                "title": "Site Training SOP",
                "content": (
                    "Investigators must complete protocol training before "
                    "performing any study procedure. Signed informed consent "
                    "must be documented before screening. Serious adverse "
                    "events must be reported within 24 hours after awareness "
                    "if applicable. The approved protocol version must match "
                    "the version filed in the investigator site file before "
                    "enrollment."
                ),
            },
        )
        self.assertEqual(knowledge_response.status_code, 201)

        compile_response = self.client.post(f"/projects/{project_id}/compile-rules")
        self.assertEqual(compile_response.status_code, 200)
        rules = compile_response.json()
        self.assertGreaterEqual(len(rules), 1)
        rule_types = {rule["rule_type"] for rule in rules}
        self.assertIn("qualification_match", rule_types)
        self.assertIn("version_match", rule_types)
        uncertain_rules = [rule for rule in rules if rule["human_review_required"]]
        self.assertEqual(uncertain_rules[0]["parameters"]["duration"]["unit"], "hour")

        rules_response = self.client.get(f"/projects/{project_id}/rules")
        self.assertEqual(rules_response.status_code, 200)
        self.assertEqual(len(rules_response.json()), len(rules))

    def test_convoke_mock_enrichment_flow(self) -> None:
        project_response = self.client.post("/projects", json={"name": "Context Demo"})
        self.assertEqual(project_response.status_code, 201)
        project_id = project_response.json()["project_id"]

        context_response = self.client.get(f"/projects/{project_id}/context")
        self.assertEqual(context_response.status_code, 200)
        self.assertEqual(context_response.json()["convoke_programs"], [])

        with patch.dict("os.environ", {"CONVOKE_MOCK": "true"}):
            enrich_response = self.client.post(
                f"/projects/{project_id}/enrich/convoke",
                json={
                    "indication": "non-small cell lung cancer",
                    "target": "PD-1",
                    "drug_name": "CTX-101",
                    "organization": "Convoke Demo Bio",
                },
            )

        self.assertEqual(enrich_response.status_code, 200)
        context = enrich_response.json()
        self.assertEqual(context["indication"], "non-small cell lung cancer")
        self.assertEqual(context["target"], "PD-1")
        self.assertEqual(context["investigational_product"], "CTX-101")
        self.assertEqual(context["sponsor"], "Convoke Demo Bio")
        self.assertEqual(context["phase"], "Phase 2")
        self.assertIsNotNone(context["convoke_enriched_at"])
        self.assertEqual(len(context["convoke_programs"]), 1)
        self.assertEqual(
            context["convoke_programs"][0]["raw_data"]["source"], "convoke_mock"
        )

        persisted_context_response = self.client.get(f"/projects/{project_id}/context")
        self.assertEqual(persisted_context_response.status_code, 200)
        self.assertEqual(persisted_context_response.json(), context)

    def test_convoke_enrichment_requires_filter(self) -> None:
        project_response = self.client.post("/projects", json={"name": "Bad Request"})
        project_id = project_response.json()["project_id"]

        response = self.client.post(
            f"/projects/{project_id}/enrich/convoke",
            json={},
        )

        self.assertEqual(response.status_code, 422)

    def test_demo_sop_evidence_flow_creates_required_failures(self) -> None:
        project_response = self.client.post("/projects", json={"name": "ONCO-301"})
        project_id = project_response.json()["project_id"]

        with open("demo_sop.txt", "r", encoding="utf-8") as demo_file:
            sop_content = demo_file.read()

        knowledge_response = self.client.post(
            f"/projects/{project_id}/knowledge",
            json={
                "type": "sop",
                "title": "ONCO-301 demo SOP",
                "content": sop_content,
            },
        )
        self.assertEqual(knowledge_response.status_code, 201)
        compile_response = self.client.post(f"/projects/{project_id}/compile-rules")
        self.assertEqual(compile_response.status_code, 200)

        evidence = (
            "Patient P001 had a CBC collected on August 12 2026 at 8:00 AM.\n"
            "Patient P001 had a CBC collected on August 13 2026 at 10:30 AM.\n"
            "Patient P002 had a CBC collected on August 10 2026 at 8:00 AM.\n"
            "Dr. Lee administered investigational therapy to Patient P002 on August 13 2026 at 1:00 PM.\n"
            "Patient P003 had a study-specific research procedure performed on August 13 2026 at 10:00 AM.\n"
            "Patient P003 signed informed consent on August 13 2026 at 11:00 AM.\n"
            "Patient P004 Platelets 92 x10^3/uL on August 13 2026 at 8:00 AM."
        )
        evidence_response = self.client.post(
            f"/projects/{project_id}/evidence/text",
            json={"content": evidence},
        )
        self.assertEqual(evidence_response.status_code, 200)
        self.assertGreaterEqual(len(evidence_response.json()), 7)

        findings_response = self.client.get(f"/projects/{project_id}/findings")
        self.assertEqual(findings_response.status_code, 200)
        failed = [
            finding
            for finding in findings_response.json()
            if finding["status"] == "FAIL"
        ]
        observed_text = "\n".join(finding["observed"] for finding in failed)
        self.assertIn("26.5 hours", observed_text)
        self.assertIn("77 hours", observed_text)
        self.assertTrue(
            any("consent_signed" in finding["expected"] for finding in failed)
        )
        self.assertIn("92000", observed_text)


if __name__ == "__main__":
    unittest.main()
