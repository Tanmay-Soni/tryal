import React from "react";
import ReactDOM from "react-dom/client";
import {
  AlertTriangle,
  Beaker,
  BookOpenCheck,
  Brain,
  CalendarClock,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  DatabaseZap,
  FileText,
  FlaskConical,
  Gauge,
  Layers3,
  Loader2,
  SearchCheck,
  ShieldAlert,
  ShieldCheck,
  Upload,
} from "lucide-react";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

const DEMO_SOP = `ONCO-301 SITE STANDARD OPERATING PROCEDURE

Section 1 - Laboratory Monitoring

1.1 Active participants receiving investigational treatment must have
a CBC collected at intervals no greater than 24 hours.

1.2 A CBC used for treatment clearance must have been collected within
72 hours before administration of investigational product.

1.3 Platelet count must be at least 100,000/uL before investigational
product administration.

Section 2 - Informed Consent

2.1 Valid informed consent must be obtained before any study-specific
research procedure is performed.

2.2 The currently approved informed consent form version must be used.

Section 3 - Personnel

3.1 Staff performing investigational-product administration must have
active delegation for that activity on the date it is performed.

3.2 Staff must complete training on the active protocol version before
performing protocol-specific activities.

Section 4 - Safety Follow-up

4.1 If ALT exceeds 3 times the upper limit of normal, repeat
liver-function testing must occur within 48 hours.`;

const DEMO_EVIDENCE = `Patient P001 had a CBC collected on August 12 2026 at 8:00 AM.
Patient P001 had a CBC collected on August 13 2026 at 10:30 AM.

Patient P002 had a CBC collected on August 10 2026 at 8:00 AM.
Dr. Lee administered investigational therapy to Patient P002 on August 13 2026 at 1:00 PM.

Patient P003 had a study-specific research procedure performed on August 13 2026 at 10:00 AM.
Patient P003 signed informed consent on August 13 2026 at 11:00 AM.

Patient P004 Platelets 92 x10^3/uL on August 13 2026 at 8:00 AM.`;

type ViewKey =
  | "overview"
  | "rules"
  | "evidence"
  | "findings"
  | "timeline"
  | "context";

type Project = {
  project_id: string;
  name: string;
  knowledge_sources: KnowledgeSource[];
  rules: Rule[];
  events: TrialEvent[];
  findings: Finding[];
  context: ProjectContext;
};

type KnowledgeSource = {
  source_id: string;
  type: string;
  title: string;
  content: string;
};

type Rule = {
  rule_id: string;
  name: string;
  description: string;
  rule_type: string;
  parameters: Record<string, unknown>;
  severity: string;
  human_review_required: boolean;
  source: {
    title: string;
    section?: string | null;
    text: string;
  };
};

type Measurement = {
  name: string;
  value: number;
  unit: string;
};

type TrialEvent = {
  event_id: string;
  participant_id?: string | null;
  actor_id?: string | null;
  event_type: string;
  timestamp?: string | null;
  attributes: Record<string, unknown>;
  measurements: Measurement[];
  source: {
    source_type: string;
    filename?: string | null;
    raw_text?: string | null;
    page?: number | null;
  };
  extraction_confidence: number;
  human_verification_required: boolean;
};

type Finding = {
  finding_id: string;
  participant_id?: string | null;
  rule_id: string;
  rule_name: string;
  severity: string;
  status: "PASS" | "WARNING" | "FAIL" | "REVIEW" | string;
  expected: string;
  observed: string;
  difference?: Record<string, unknown> | null;
  evidence: Record<string, unknown>;
  explanation: string;
  human_review_required: boolean;
  next_due_at?: string | null;
};

type ProjectContext = {
  indication?: string | null;
  target?: string | null;
  investigational_product?: string | null;
  sponsor?: string | null;
  phase?: string | null;
  convoke_programs: ConvokeProgram[];
};

type ConvokeProgram = {
  drug_name?: string | null;
  organization?: string | null;
  target?: string | null;
  indication?: string | null;
  phase?: string | null;
  status?: string | null;
};

type ToastState = {
  kind: "info" | "error" | "success";
  text: string;
} | null;

type TryalStatus =
  | "evidence_located"
  | "no_evidence_found"
  | "human_review_required"
  | "potential_issue"
  | "potential_issue_high";

const TRYAL_STATUS: Record<TryalStatus, { label: string; token: "verified" | "none" | "review" | "potential" | "critical" }> = {
  evidence_located: { label: "Evidence Located", token: "verified" },
  no_evidence_found: { label: "No Evidence Found", token: "none" },
  human_review_required: { label: "Human Review Required", token: "review" },
  potential_issue: { label: "Potential Issue", token: "potential" },
  potential_issue_high: { label: "Potential Issue - High", token: "critical" },
};

const navItems: Array<{ key: ViewKey; label: string; icon: React.ElementType }> = [
  { key: "overview", label: "Overview", icon: Gauge },
  { key: "rules", label: "Compliance Rules", icon: BookOpenCheck },
  { key: "evidence", label: "Evidence", icon: FileText },
  { key: "findings", label: "Findings", icon: ShieldAlert },
  { key: "timeline", label: "Event Timeline", icon: CalendarClock },
  { key: "context", label: "Program Context", icon: DatabaseZap },
];

function App() {
  const [activeView, setActiveView] = React.useState<ViewKey>("overview");
  const [project, setProject] = React.useState<Project | null>(null);
  const [rules, setRules] = React.useState<Rule[]>([]);
  const [events, setEvents] = React.useState<TrialEvent[]>([]);
  const [findings, setFindings] = React.useState<Finding[]>([]);
  const [context, setContext] = React.useState<ProjectContext | null>(null);
  const [sopText, setSopText] = React.useState(DEMO_SOP);
  const [evidenceText, setEvidenceText] = React.useState(DEMO_EVIDENCE);
  const [demoSteps, setDemoSteps] = React.useState<string[]>([]);
  const [loadingLabel, setLoadingLabel] = React.useState<string | null>(null);
  const [toast, setToast] = React.useState<ToastState>(null);
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);

  const metrics = React.useMemo(() => {
    const potentialGaps = findings.filter((finding) => finding.status === "FAIL" && !isVerificationFinding(finding)).length;
    const reviewCount =
      findings.filter((finding) => finding.human_review_required).length +
      events.filter((event) => event.human_verification_required).length +
      findings.filter(isVerificationFinding).length;
    return {
      potentialGaps,
      activeRules: rules.length,
      eventsAnalyzed: events.length,
      requiresReview: reviewCount,
    };
  }, [events, findings, rules]);

  async function refreshAll(projectId: string) {
    const [projectPayload, rulePayload, eventPayload, findingPayload, contextPayload] =
      await Promise.all([
        api<Project>(`/projects/${projectId}`),
        api<Rule[]>(`/projects/${projectId}/rules`),
        api<TrialEvent[]>(`/projects/${projectId}/events`),
        api<Finding[]>(`/projects/${projectId}/findings`),
        api<ProjectContext>(`/projects/${projectId}/context`),
      ]);
    setProject(projectPayload);
    setRules(rulePayload);
    setEvents(eventPayload);
    setFindings(findingPayload);
    setContext(contextPayload);
    if (projectPayload.knowledge_sources[0]?.content) {
      setSopText(projectPayload.knowledge_sources[0].content);
    }
  }

  async function loadDemo() {
    setToast(null);
    setDemoSteps([]);
    try {
      setLoadingLabel("Creating project...");
      pushStep("Creating project...");
      const created = await api<Project>("/projects", {
        method: "POST",
        body: { name: "ONCO-301" },
      });
      setProject(created);

      setLoadingLabel("Loading compliance knowledge...");
      pushStep("Loading compliance knowledge...");
      await api<KnowledgeSource>(`/projects/${created.project_id}/knowledge`, {
        method: "POST",
        body: {
          type: "sop",
          title: "ONCO-301 demo SOP",
          content: DEMO_SOP,
        },
      });

      setLoadingLabel("Compiling rules...");
      pushStep("Compiling rules...");
      const compiledRules = await api<Rule[]>(`/projects/${created.project_id}/compile-rules`, {
        method: "POST",
      });
      setRules(compiledRules);

      setLoadingLabel("Normalizing evidence...");
      pushStep("Normalizing evidence...");
      await api<TrialEvent[]>(`/projects/${created.project_id}/evidence/text`, {
        method: "POST",
        body: { content: DEMO_EVIDENCE },
      });
      setLoadingLabel("Running deterministic checks...");
      pushStep("Running deterministic checks...");

      await refreshAll(created.project_id);
      setEvidenceText(DEMO_EVIDENCE);
      setSopText(DEMO_SOP);
      setActiveView("findings");
      setToast({ kind: "success", text: "Demo loaded. Findings are ready for review." });
    } catch (error) {
      setToast({ kind: "error", text: errorMessage(error) });
    } finally {
      setLoadingLabel(null);
    }
  }

  function pushStep(step: string) {
    setDemoSteps((steps) => [...steps, step]);
  }

  async function compileRules() {
    if (!project) {
      setToast({ kind: "error", text: "Load or create a project first." });
      return;
    }
    try {
      setLoadingLabel("Compiling rules...");
      const latestKnowledge = project.knowledge_sources[project.knowledge_sources.length - 1];
      if (!latestKnowledge || latestKnowledge.content !== sopText) {
        await api<KnowledgeSource>(`/projects/${project.project_id}/knowledge`, {
          method: "POST",
          body: { type: "sop", title: "Compliance knowledge", content: sopText },
        });
      }
      const compiled = await api<Rule[]>(`/projects/${project.project_id}/compile-rules`, {
        method: "POST",
      });
      setRules(compiled);
      await refreshAll(project.project_id);
      setToast({ kind: "success", text: `${compiled.length} executable rules generated.` });
    } catch (error) {
      setToast({ kind: "error", text: errorMessage(error) });
    } finally {
      setLoadingLabel(null);
    }
  }

  async function analyzeEvidence() {
    if (!project) {
      setToast({ kind: "error", text: "Load Demo first, or create a project before analyzing evidence." });
      return;
    }
    try {
      setLoadingLabel("Normalizing evidence...");
      await api<TrialEvent[]>(`/projects/${project.project_id}/evidence/text`, {
        method: "POST",
        body: { content: evidenceText },
      });
      await refreshAll(project.project_id);
      setActiveView("findings");
      setToast({ kind: "success", text: "Evidence analyzed with deterministic rule evaluation." });
    } catch (error) {
      setToast({ kind: "error", text: errorMessage(error) });
    } finally {
      setLoadingLabel(null);
    }
  }

  async function uploadEvidence(file: File) {
    if (!project) {
      setToast({ kind: "error", text: "Load Demo first, or create a project before uploading evidence." });
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    try {
      setLoadingLabel("Uploading and normalizing evidence...");
      await fetch(`${API_BASE}/projects/${project.project_id}/evidence/file`, {
        method: "POST",
        body: formData,
      }).then(handleResponse<TrialEvent[]>);
      await refreshAll(project.project_id);
      setActiveView("findings");
      setToast({ kind: "success", text: `${file.name} analyzed.` });
    } catch (error) {
      setToast({ kind: "error", text: errorMessage(error) });
    } finally {
      setLoadingLabel(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function enrichProgramContext() {
    if (!project) {
      setToast({ kind: "error", text: "Load Demo first." });
      return;
    }
    try {
      setLoadingLabel("Querying Program Tracker...");
      const enriched = await api<ProjectContext>(`/projects/${project.project_id}/enrich/convoke`, {
        method: "POST",
        body: { indication: "non-small cell lung cancer", target: "PD-1" },
      });
      setContext(enriched);
      setActiveView("context");
      setToast({ kind: "success", text: "Program context enriched." });
    } catch (error) {
      setToast({
        kind: "error",
        text: `Program context is unavailable. ${errorMessage(error)}`,
      });
    } finally {
      setLoadingLabel(null);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-mark">
            <ShieldCheck size={22} />
          </div>
          <div>
            <div className="brand-name">TRYAL</div>
            <div className="brand-subtitle">Clinical operations</div>
          </div>
        </div>
        <nav className="nav-list">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                className={activeView === item.key ? "nav-item active" : "nav-item"}
                onClick={() => setActiveView(item.key)}
                type="button"
              >
                <Icon size={18} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="sidebar-note">
          <span>AI interprets.</span>
          <span>Code verifies.</span>
          <span>Humans decide.</span>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <div className="eyebrow">ONCO-301</div>
            <h1>Continuous Compliance Monitoring</h1>
            <p>AI interprets. Code verifies. Humans decide.</p>
          </div>
          <div className="topbar-actions">
            <button className="secondary-button" type="button" onClick={() => setActiveView("evidence")}>
              <FileText size={17} />
              Evidence
            </button>
            <button className="primary-button" type="button" onClick={loadDemo} disabled={Boolean(loadingLabel)}>
              {loadingLabel ? <Loader2 className="spin" size={17} /> : <DatabaseZap size={17} />}
              Load Demo
            </button>
          </div>
        </header>

        {toast && <StatusToast toast={toast} onClose={() => setToast(null)} />}
        {loadingLabel && <ProgressPanel current={loadingLabel} steps={demoSteps} />}

        {activeView === "overview" && (
          <Overview
            metrics={metrics}
            findings={findings}
            rules={rules}
            events={events}
            onLoadDemo={loadDemo}
            loading={Boolean(loadingLabel)}
          />
        )}
        {activeView === "rules" && (
          <RulesView rules={rules} sopText={sopText} setSopText={setSopText} onCompile={compileRules} />
        )}
        {activeView === "evidence" && (
          <EvidenceView
            evidenceText={evidenceText}
            setEvidenceText={setEvidenceText}
            onAnalyze={analyzeEvidence}
            onUpload={uploadEvidence}
            fileInputRef={fileInputRef}
            loading={Boolean(loadingLabel)}
          />
        )}
        {activeView === "findings" && <FindingsView findings={findings} rules={rules} events={events} />}
        {activeView === "timeline" && <TimelineView events={events} />}
        {activeView === "context" && (
          <ProgramContextView context={context} onEnrich={enrichProgramContext} loading={Boolean(loadingLabel)} />
        )}
      </main>
    </div>
  );
}

function Overview({
  metrics,
  findings,
  rules,
  events,
  onLoadDemo,
  loading,
}: {
  metrics: { potentialGaps: number; activeRules: number; eventsAnalyzed: number; requiresReview: number };
  findings: Finding[];
  rules: Rule[];
  events: TrialEvent[];
  onLoadDemo: () => void;
  loading: boolean;
}) {
  const latestFindings = findings
    .filter((finding) => finding.status === "FAIL" && !isVerificationFinding(finding))
    .slice(0, 3);
  return (
    <section className="view-stack">
      <div className="summary-band">
        <div>
          <div className="eyebrow">Executive summary</div>
          <h2>ONCO-301</h2>
          <p>Continuous compliance monitoring for clinical trials.</p>
        </div>
        <button className="primary-button" onClick={onLoadDemo} disabled={loading} type="button">
          {loading ? <Loader2 className="spin" size={17} /> : <DatabaseZap size={17} />}
          Load Demo
        </button>
      </div>

      <div className="metric-grid">
        <MetricCard label="Potential Gaps" value={metrics.potentialGaps} tone="danger" icon={ShieldAlert} />
        <MetricCard label="Active Rules" value={metrics.activeRules} tone="blue" icon={BookOpenCheck} />
        <MetricCard label="Events Analyzed" value={metrics.eventsAnalyzed} tone="teal" icon={SearchCheck} />
        <MetricCard label="Requires Review" value={metrics.requiresReview} tone="amber" icon={AlertTriangle} />
      </div>

      <div className="two-column">
        <section className="panel priority-panel">
          <div className="panel-heading">
            <div>
              <h3>Compliance Monitoring Status</h3>
              <p>Latest potential compliance gaps from deterministic rule evaluation.</p>
            </div>
            <StatusBadge tone={metrics.potentialGaps > 0 ? "potential_issue" : "evidence_located"} />
          </div>
          {latestFindings.length ? (
            <div className="compact-finding-list">
              {latestFindings.map((finding) => (
                <FindingRow key={finding.finding_id} finding={finding} />
              ))}
            </div>
          ) : (
            <EmptyState icon={CheckCircle2} title="No findings yet" text="Load the demo to populate rule evaluation results." />
          )}
        </section>

        <section className="panel">
          <div className="panel-heading">
            <div>
              <h3>Monitoring Architecture</h3>
              <p>AI converts inputs into structured facts. Deterministic rules evaluate those facts continuously.</p>
            </div>
          </div>
          <ArchitectureFlow />
          <div className="overview-footnotes">
            <span>{rules.length || 0} executable rules</span>
            <span>{events.length || 0} AI-extracted evidence events</span>
          </div>
        </section>
      </div>
    </section>
  );
}

function MetricCard({
  label,
  value,
  tone,
  icon: Icon,
}: {
  label: string;
  value: number;
  tone: "danger" | "blue" | "teal" | "amber";
  icon: React.ElementType;
}) {
  return (
    <div className={`metric-card ${tone}`}>
      <div className="metric-icon">
        <Icon size={20} />
      </div>
      <div>
        <div className="metric-value">{value}</div>
        <div className="metric-label">{label}</div>
      </div>
    </div>
  );
}

function RulesView({
  rules,
  sopText,
  setSopText,
  onCompile,
}: {
  rules: Rule[];
  sopText: string;
  setSopText: (value: string) => void;
  onCompile: () => void;
}) {
  return (
    <section className="view-stack">
      <div className="section-header">
        <div>
          <div className="eyebrow">Compliance knowledge</div>
          <h2>Executable Rules</h2>
          <p>AI converts natural-language requirements into validated structured rules.</p>
        </div>
        <button className="primary-button" onClick={onCompile} type="button">
          <Brain size={17} />
          Compile Rules
        </button>
      </div>

      <section className="panel">
        <textarea
          className="sop-editor"
          value={sopText}
          onChange={(event) => setSopText(event.target.value)}
          aria-label="SOP text"
        />
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h3>{rules.length} executable rules generated</h3>
            <p>Human review flags identify rules requiring verification before operational use.</p>
          </div>
        </div>
        {rules.length ? (
          <div className="rules-table">
            <div className="table-header">Name</div>
            <div className="table-header">Rule Type</div>
            <div className="table-header">Requirement</div>
            <div className="table-header">Severity</div>
            <div className="table-header">Human Review</div>
            {rules.map((rule) => (
              <React.Fragment key={rule.rule_id}>
                <div className="table-cell strong">
                  <div className="rule-name-cell">
                    <span>{friendlyRuleName(rule)}</span>
                    <Prov kind="rule">{shortRuleId(rule.rule_id)}</Prov>
                  </div>
                </div>
                <div className="table-cell mono">{rule.rule_type}</div>
                <div className="table-cell">{requirementSummary(rule)}</div>
                <div className="table-cell">{rule.severity}</div>
                <div className="table-cell">
                  {rule.human_review_required ? (
                    <span className="review-pill">Requires human review</span>
                  ) : (
                    <span className="verified-pill">Validated structure</span>
                  )}
                </div>
              </React.Fragment>
            ))}
          </div>
        ) : (
          <EmptyState icon={BookOpenCheck} title="No rules compiled" text="Load the demo or compile the SOP text." />
        )}
      </section>
    </section>
  );
}

function EvidenceView({
  evidenceText,
  setEvidenceText,
  onAnalyze,
  onUpload,
  fileInputRef,
  loading,
}: {
  evidenceText: string;
  setEvidenceText: (value: string) => void;
  onAnalyze: () => void;
  onUpload: (file: File) => void;
  fileInputRef: React.MutableRefObject<HTMLInputElement | null>;
  loading: boolean;
}) {
  return (
    <section className="view-stack">
      <div className="section-header">
        <div>
          <div className="eyebrow">AI-extracted evidence</div>
          <h2>Evidence Intake</h2>
          <p>AI extracts structured trial events. Rule evaluation results are produced by deterministic checks.</p>
        </div>
        <div className="topbar-actions">
          <button className="secondary-button" onClick={() => fileInputRef.current?.click()} type="button">
            <Upload size={17} />
            Upload File
          </button>
          <button className="primary-button" onClick={onAnalyze} disabled={loading} type="button">
            {loading ? <Loader2 className="spin" size={17} /> : <SearchCheck size={17} />}
            Analyze Evidence
          </button>
        </div>
      </div>

      <input
        ref={fileInputRef}
        className="hidden-input"
        type="file"
        accept=".txt,.csv,.pdf"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onUpload(file);
        }}
      />
      <section className="panel">
        <textarea
          className="evidence-editor"
          value={evidenceText}
          onChange={(event) => setEvidenceText(event.target.value)}
          aria-label="Evidence text"
        />
      </section>
    </section>
  );
}

function FindingsView({
  findings,
  rules,
  events,
}: {
  findings: Finding[];
  rules: Rule[];
  events: TrialEvent[];
}) {
  const sorted = [...findings].sort((left, right) => statusRank(left.status) - statusRank(right.status));
  return (
    <section className="view-stack">
      <div className="section-header">
        <div>
          <div className="eyebrow">Rule evaluation</div>
          <h2>Potential Compliance Gaps</h2>
          <p>Deterministic findings generated from executable rules and structured events.</p>
        </div>
        <div className="finding-count">
          {findings.filter((finding) => finding.status === "FAIL" && !isVerificationFinding(finding)).length} open gaps
        </div>
      </div>
      {sorted.length ? (
        <div className="finding-grid">
          {sorted.map((finding) => (
            <FindingCard
              key={finding.finding_id}
              finding={finding}
              rule={rules.find((rule) => rule.rule_id === finding.rule_id)}
              events={events}
            />
          ))}
        </div>
      ) : (
        <EmptyState icon={ShieldAlert} title="No findings yet" text="Load the demo to run deterministic checks." />
      )}
    </section>
  );
}

function FindingCard({ finding, rule, events }: { finding: Finding; rule?: Rule; events: TrialEvent[] }) {
  const evidenceIds = Array.isArray(finding.evidence.event_ids) ? (finding.evidence.event_ids as string[]) : [];
  const evidenceEvents = evidenceIds.map((id) => events.find((event) => event.event_id === id)).filter(Boolean) as TrialEvent[];
  const displayStatus = statusForFinding(finding);
  return (
    <article className={`finding-card ${displayStatus}`}>
      <div className="finding-card-head">
        <div className="finding-provenance-row">
          <StatusBadge finding={finding} />
          <Prov kind="rule">{shortRuleId(finding.rule_id)}</Prov>
        </div>
        <span className="severity-label">{finding.severity}</span>
      </div>
      <h3>{findingTitle(finding)}</h3>
      <p className="finding-claim">{hedgedFindingClaim(finding)}</p>
      <div className="finding-detail-grid">
        <Detail label="Participant" value={finding.participant_id ?? "Study level"} />
        <Detail label="Expected" value={humanExpected(finding.expected)} />
        <Detail label="Observed" value={humanObserved(finding.observed)} />
        <Detail label="Source rule" value={rule?.source.section ? `${rule.source.title} - ${rule.source.section}` : rule?.source.title ?? "Stored rule"} />
      </div>
      {finding.next_due_at && (
        <div className="next-due">
          <CalendarClock size={16} />
          <span>Next required CBC: {formatDateTime(finding.next_due_at)}</span>
        </div>
      )}
      {finding.human_review_required && <span className="review-pill">Requires human review</span>}
      {isVerificationFinding(finding) && <span className="review-pill">Requires verification</span>}
      {evidenceEvents.length > 0 && (
        <div className="evidence-chip-row" aria-label="Source evidence references">
          {evidenceEvents.map((event) => (
            <button className="evidence-chip" key={event.event_id} type="button" title={event.source.raw_text ?? event.event_type}>
              {shortEventId(event.event_id)}
            </button>
          ))}
        </div>
      )}
      {evidenceEvents.length > 0 && (
        <details className="evidence-detail">
          <summary>Source evidence</summary>
          {evidenceEvents.map((event) => (
            <div className="source-evidence-row" key={event.event_id}>
              <p>{event.source.raw_text ?? event.event_type}</p>
              <div className="provenance-line">
                <Prov kind="ai">AI-INFERRED</Prov>
                <Confidence value={event.extraction_confidence} />
              </div>
            </div>
          ))}
        </details>
      )}
    </article>
  );
}

function TimelineView({ events }: { events: TrialEvent[] }) {
  const grouped = groupEvents(events);
  return (
    <section className="view-stack">
      <div className="section-header">
        <div>
          <div className="eyebrow">AI-extracted evidence</div>
          <h2>Event Timeline</h2>
          <p>Canonical trial events sorted by participant and time.</p>
        </div>
      </div>
      {Object.keys(grouped).length ? (
        <div className="timeline-board">
          {Object.entries(grouped).map(([participant, participantEvents]) => (
            <section className="timeline-group" key={participant}>
              <h3>{participant}</h3>
              <div className="timeline-list">
                {participantEvents.map((event) => (
                  <div className="timeline-item" key={event.event_id}>
                    <div className="timeline-time">{formatShortDate(event.timestamp)}</div>
                    <div>
                      <div className="timeline-title">{eventLabel(event)}</div>
                      <div className="timeline-meta">
                        <Prov kind="ai">AI-INFERRED</Prov>
                        <Confidence value={event.extraction_confidence} />
                        {event.actor_id && <span>Performed by {event.actor_id}</span>}
                        {event.human_verification_required && <span className="verify-text">Requires verification</span>}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <EmptyState icon={CalendarClock} title="No events yet" text="Analyze evidence to populate the timeline." />
      )}
    </section>
  );
}

function ProgramContextView({
  context,
  onEnrich,
  loading,
}: {
  context: ProjectContext | null;
  onEnrich: () => void;
  loading: boolean;
}) {
  const programs = context?.convoke_programs?.slice(0, 5) ?? [];
  return (
    <section className="view-stack">
      <div className="section-header">
        <div>
          <div className="eyebrow">Secondary enrichment</div>
          <h2>Program Context</h2>
          <p>Structured biopharma program context, separate from compliance rule evaluation.</p>
        </div>
        <button className="secondary-button" onClick={onEnrich} disabled={loading} type="button">
          {loading ? <Loader2 className="spin" size={17} /> : <FlaskConical size={17} />}
          Enrich Context
        </button>
      </div>
      <section className="panel">
        {programs.length ? (
          <>
            <div className="context-summary">
              <Detail label="Indication" value={context?.indication ?? "Not set"} />
              <Detail label="Target" value={context?.target ?? "Not set"} />
              <Detail label="Phase" value={context?.phase ?? "Not set"} />
            </div>
            <div className="program-table">
              <div className="table-header">Drug</div>
              <div className="table-header">Organization</div>
              <div className="table-header">Target</div>
              <div className="table-header">Phase</div>
              <div className="table-header">Status</div>
              {programs.map((program, index) => (
                <React.Fragment key={`${program.drug_name}-${index}`}>
                  <div className="table-cell strong">{program.drug_name ?? "Unknown"}</div>
                  <div className="table-cell">{program.organization ?? "Not available"}</div>
                  <div className="table-cell">{program.target ?? "Not available"}</div>
                  <div className="table-cell">{program.phase ?? "Not available"}</div>
                  <div className="table-cell">{program.status ?? "Not available"}</div>
                </React.Fragment>
              ))}
            </div>
            <p className="powered-note">Powered by Convoke Program Tracker</p>
          </>
        ) : (
          <EmptyState
            icon={Layers3}
            title="No program context loaded"
            text="Compliance monitoring works without Convoke. Enrichment is optional."
          />
        )}
      </section>
    </section>
  );
}

function ProgressPanel({ current, steps }: { current: string; steps: string[] }) {
  return (
    <div className="progress-panel">
      <Loader2 className="spin" size={18} />
      <div>
        <strong>{current}</strong>
        <div className="step-list">
          {steps.map((step) => (
            <span key={step}>{step}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

function StatusToast({ toast, onClose }: { toast: NonNullable<ToastState>; onClose: () => void }) {
  return (
    <button className={`toast ${toast.kind}`} onClick={onClose} type="button">
      {toast.text}
    </button>
  );
}

function ArchitectureFlow() {
  const groups = [
    ["Documents + SOPs", "AI Rule Compiler", "Executable Rules"],
    ["Trial Evidence", "AI Fact Extraction", "Structured Events"],
    ["Rules + Events", "Deterministic Engine", "Potential Compliance Gaps"],
  ];
  return (
    <div className="architecture-flow">
      {groups.map((group) => (
        <div className="flow-row" key={group[0]}>
          {group.map((item, index) => (
            <React.Fragment key={item}>
              <span>{item}</span>
              {index < group.length - 1 && <ChevronRight size={15} />}
            </React.Fragment>
          ))}
        </div>
      ))}
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function StatusBadge({ status, tone, finding }: { status?: string; tone?: TryalStatus; finding?: Finding }) {
  const statusKey = tone ?? (finding ? statusForFinding(finding) : statusForRaw(status ?? ""));
  const meta = TRYAL_STATUS[statusKey];
  return (
    <span className={`pill pill--${meta.token}`}>
      <span className="dot" aria-hidden="true" />
      {meta.label}
    </span>
  );
}

function Prov({ kind, children }: { kind: "ai" | "rule" | "human"; children: React.ReactNode }) {
  return <span className={`prov prov--${kind}`}>{children}</span>;
}

function Confidence({ value }: { value: number }) {
  const normalized = Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
  return (
    <span className="conf">
      <span className="conf__track" aria-hidden="true">
        <span className="conf__fill" style={{ width: `${normalized * 100}%` }} />
      </span>
      <span className="conf__value">{normalized.toFixed(2)}</span>
    </span>
  );
}

function FindingRow({ finding }: { finding: Finding }) {
  return (
    <div className="finding-row">
      <StatusBadge finding={finding} />
      <div>
        <strong>{findingTitle(finding)}</strong>
        <p>{finding.observed}</p>
      </div>
    </div>
  );
}

function EmptyState({ icon: Icon, title, text }: { icon: React.ElementType; title: string; text: string }) {
  return (
    <div className="empty-state">
      <Icon size={28} />
      <strong>{title}</strong>
      <span>{text}</span>
    </div>
  );
}

async function api<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: options.method ?? "GET",
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  return handleResponse<T>(response);
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      if (payload.detail) message = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail);
    } catch {
      // Preserve HTTP status message.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Unexpected error";
}

function statusRank(status: string) {
  if (status === "FAIL") return 0;
  if (status === "REVIEW") return 1;
  if (status === "WARNING") return 2;
  return 3;
}

function statusForRaw(status: string): TryalStatus {
  if (status === "PASS") return "evidence_located";
  if (status === "REVIEW") return "human_review_required";
  if (status === "WARNING") return "potential_issue";
  if (status === "FAIL") return "potential_issue";
  return "no_evidence_found";
}

function statusForFinding(finding: Finding): TryalStatus {
  if (isVerificationFinding(finding)) return "no_evidence_found";
  if (finding.human_review_required || finding.status === "REVIEW") return "human_review_required";
  if (finding.status === "PASS") return "evidence_located";
  if (finding.status === "FAIL") {
    const severity = finding.severity.toLowerCase();
    return severity.includes("critical") || severity.includes("high") ? "potential_issue_high" : "potential_issue";
  }
  if (finding.status === "WARNING") return "potential_issue";
  return "no_evidence_found";
}

function groupEvents(events: TrialEvent[]) {
  return [...events]
    .sort((a, b) => new Date(a.timestamp ?? 0).getTime() - new Date(b.timestamp ?? 0).getTime())
    .reduce<Record<string, TrialEvent[]>>((groups, event) => {
      const key = event.participant_id ?? "Study level";
      groups[key] = groups[key] ?? [];
      groups[key].push(event);
      return groups;
    }, {});
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatShortDate(value?: string | null) {
  if (!value) return "Time not captured";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function eventLabel(event: TrialEvent) {
  if (event.event_type === "blood_draw") return `${String(event.attributes.sample_type ?? "Blood")} collected`;
  if (event.event_type === "study_drug_administration") return "Investigational therapy";
  if (event.event_type === "research_procedure") return "Research procedure";
  if (event.event_type === "consent_signed") return "Consent signed";
  if (event.event_type === "lab_result") {
    const measurement = event.measurements[0];
    return measurement ? `${humanMeasurement(measurement.name)} ${formatNumber(measurement.value)} ${measurement.unit}` : "Lab result";
  }
  return event.event_type.replace(/_/g, " ");
}

function friendlyRuleName(rule: Rule) {
  if (rule.rule_type === "recurring_event") return "CBC monitoring frequency";
  if (rule.rule_type === "preceding_event_window") return "Treatment clearance CBC";
  if (rule.rule_type === "numeric_threshold" && String(rule.parameters.measurement_name) === "platelet_count") {
    return "Platelet treatment threshold";
  }
  if (rule.rule_type === "prerequisite") return "Consent prerequisite";
  if (rule.rule_type === "authorization_window") return "Delegation authorization";
  if (rule.rule_type === "qualification_match") return "Protocol training";
  return rule.name;
}

function requirementSummary(rule: Rule) {
  if (rule.rule_type === "recurring_event") return "<=24 hours";
  if (rule.rule_type === "preceding_event_window") return "<=72 hours";
  if (rule.rule_type === "numeric_threshold" && String(rule.parameters.measurement_name) === "platelet_count") {
    return ">=100000 /uL";
  }
  if (rule.rule_type === "prerequisite") return "Consent before procedure";
  if (rule.rule_type === "authorization_window") return "Active delegation";
  if (rule.rule_type === "qualification_match") return "Training before protocol activity";
  if (rule.rule_type === "version_match") return "Approved version match";
  return "Structured rule";
}

function findingTitle(finding: Finding) {
  if (finding.expected.includes("Interval")) return "CBC collection interval exceeded";
  if (finding.expected.includes("72 hours")) return "Treatment clearance CBC too old";
  if (finding.expected.includes("consent_signed")) return "Consent prerequisite timing issue";
  if (finding.expected.includes("platelet_count")) return "Platelet threshold not met";
  if (finding.expected.includes("Active delegation")) return "Delegation not verified";
  if (finding.expected.includes("Protocol training")) return "Protocol training not verified";
  return finding.rule_name;
}

function hedgedFindingClaim(finding: Finding) {
  if (isVerificationFinding(finding)) return "The required supporting evidence could not be located in the submitted trial evidence.";
  if (finding.expected.includes("Interval")) return "The observed CBC collection interval appears longer than the configured rule allows.";
  if (finding.expected.includes("72 hours")) return "The treatment-clearance CBC appears outside the configured lookback window.";
  if (finding.expected.includes("consent_signed")) return "The consent timestamp appears later than the study-specific procedure timestamp.";
  if (finding.expected.includes("platelet_count")) return "The extracted platelet value appears below the configured treatment threshold.";
  return "The structured evidence appears inconsistent with the configured rule.";
}

function isVerificationFinding(finding: Finding) {
  return finding.expected.includes("Active delegation") || finding.expected.includes("Protocol training");
}

function humanExpected(value: string) {
  return value
    .replace("Interval <=", "<=")
    .replace("blood_draw within", "CBC within")
    .replace("study_drug_administration", "dosing")
    .replace("consent_signed", "Consent")
    .replace("research_procedure", "procedure")
    .replace("platelet_count", "Platelets");
}

function humanObserved(value: string) {
  return value
    .replace("study_drug_administration", "dosing")
    .replace("consent_signed", "consent")
    .replace("research_procedure", "procedure")
    .replace("platelet_count", "platelets");
}

function humanMeasurement(name: string) {
  if (name === "platelet_count") return "Platelets";
  return name.replace(/_/g, " ");
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value);
}

function shortRuleId(value: string) {
  return value.replace(/_/g, "-").slice(0, 18).toUpperCase();
}

function shortEventId(value: string) {
  return `EV-${value.slice(0, 8).toUpperCase()}`;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
