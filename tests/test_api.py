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


if __name__ == "__main__":
    unittest.main()
