import json
from pathlib import Path

from backend.models import Finding, KnowledgeSource, Project, ProjectContext, TrialEvent
from backend.rules.schema import Rule


class JsonProjectStore:
    def __init__(self, base_dir: Path | str = "backend/data/projects") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_project(self, name: str) -> Project:
        project = Project(name=name)
        self.save_project(project)
        return project

    def get_project(self, project_id: str) -> Project | None:
        path = self._project_path(project_id)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as project_file:
            return Project.model_validate(json.load(project_file))

    def save_project(self, project: Project) -> None:
        path = self._project_path(project.project_id)
        with path.open("w", encoding="utf-8") as project_file:
            json.dump(project.model_dump(mode="json"), project_file, indent=2)

    def add_knowledge_source(
        self, project_id: str, knowledge_source: KnowledgeSource
    ) -> Project | None:
        project = self.get_project(project_id)
        if project is None:
            return None
        project.knowledge_sources.append(knowledge_source)
        self.save_project(project)
        return project

    def replace_rules(self, project_id: str, rules: list[Rule]) -> Project | None:
        project = self.get_project(project_id)
        if project is None:
            return None
        project.rules = rules
        self.save_project(project)
        return project

    def update_context(
        self, project_id: str, context: ProjectContext
    ) -> Project | None:
        project = self.get_project(project_id)
        if project is None:
            return None
        project.context = context
        self.save_project(project)
        return project

    def add_events(self, project_id: str, events: list[TrialEvent]) -> Project | None:
        project = self.get_project(project_id)
        if project is None:
            return None
        project.events.extend(events)
        self.save_project(project)
        return project

    def replace_findings(
        self, project_id: str, findings: list[Finding]
    ) -> Project | None:
        project = self.get_project(project_id)
        if project is None:
            return None
        project.findings = findings
        self.save_project(project)
        return project

    def _project_path(self, project_id: str) -> Path:
        if "/" in project_id or "\\" in project_id or project_id in {".", ".."}:
            raise ValueError("invalid project_id")
        return self.base_dir / f"{project_id}.json"
