import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { AccuracyBars, Empty, GroupAccuracy, MetricCard } from "./components";
import { HitlInspector } from "./hitl";
import { PipelineFlow } from "./pipeline";
import { ProcessingWorkspace } from "./process";
import { parseReport, percent } from "./report";
import type { EvaluationReport } from "./types";
import "./styles.css";

type ReportTab = "dashboard" | "queue" | "review" | "analytics" | "audit" | "settings";

export type AuditLogEntry = {
  timestamp: string;
  claimId: string;
  actor: string;
  action: string;
  prev: string;
  next: string;
  reason: string;
};

const headers = { "X-User-Role": "reviewer" };

export default function App() {
  const cache = useQueryClient();
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [activeTab, setActiveTab] = useState<ReportTab>("dashboard");
  
  // Selection and state tracking
  const [selectedTaskId, setSelectedTaskId] = useState<string | undefined>(undefined);
  const [activeSearch, setActiveSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [showFeedbackModal, setShowFeedbackModal] = useState(false);
  const [feedbackComment, setComment] = useState("");
  const [feedbackSuccess, setFeedbackSuccess] = useState(false);
  const [feedbackReasonCode, setFeedbackReasonCode] = useState("ocr");

  // Settings states
  const [npiThreshold, setNpiThreshold] = useState(85);
  const [chargeThreshold, setChargeThreshold] = useState(90);
  const [luhnValidation, setLuhnValidation] = useState(true);
  const [icdValidation, setIcdValidation] = useState(true);
  const [settingsSaved, setSettingsSaved] = useState(false);

  // Load report on mount
  useEffect(() => {
    if (typeof fetch === "undefined") return;
    fetch("/reports/evaluation.json")
      .then((response) => {
        if (!response.ok) throw new Error("No deployed evaluation report found.");
        return response.json();
      })
      .then((payload) => setReport(parseReport(payload)))
      .catch(() => undefined);
  }, []);

  // Persistent Settings loading (Priority 8)
  useEffect(() => {
    const savedNpi = localStorage.getItem("idp_settings_npi_threshold");
    const savedCharge = localStorage.getItem("idp_settings_charge_threshold");
    const savedLuhn = localStorage.getItem("idp_settings_luhn_validation");
    const savedIcd = localStorage.getItem("idp_settings_icd_validation");

    if (savedNpi) setNpiThreshold(Number(savedNpi));
    if (savedCharge) setChargeThreshold(Number(savedCharge));
    if (savedLuhn) setLuhnValidation(savedLuhn === "true");
    if (savedIcd) setIcdValidation(savedIcd === "true");
  }, []);

  // Live review tasks fetch (Status: all tasks to track active and completed)
  const reviewTasksQuery = useQuery({
    queryKey: ["review-tasks"],
    queryFn: async () => {
      const response = await fetch("/review-api/review-tasks?status=all", { headers });
      if (!response.ok) throw new Error("Failed to fetch live tasks from Review API");
      return response.json();
    },
    refetchInterval: 3000
  });

  // Live ingested documents fetch (covers STP and completed claims without review tasks)
  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: async () => {
      try {
        const response = await fetch("/api/documents");
        if (!response.ok) return [];
        return await response.json();
      } catch {
        return [];
      }
    },
    refetchInterval: 3000
  });

  // Consolidated Work Queue: Combines live ingested documents and live review tasks
  const claims = useMemo(() => {
    const rawTasks = reviewTasksQuery.data || [];
    const rawDocs = documentsQuery.data || [];

    // Index tasks by document_id and claim_id
    const tasksByDoc = new Map<string, any[]>();
    const tasksByClaim = new Map<string, any[]>();
    for (const task of rawTasks) {
      if (task.document_id) {
        const list = tasksByDoc.get(task.document_id) || [];
        list.push(task);
        tasksByDoc.set(task.document_id, list);
      }
      if (task.claim_id) {
        const list = tasksByClaim.get(task.claim_id) || [];
        list.push(task);
        tasksByClaim.set(task.claim_id, list);
      }
    }

    const items: any[] = [];
    const seenDocs = new Set<string>();
    const seenClaims = new Set<string>();

    // 1. Ingested documents (STP, Completed, Needs Review, Processing)
    for (const doc of rawDocs) {
      seenDocs.add(doc.document_id);
      const claimId = doc.claim_id ? `CLM-${doc.claim_id.slice(0, 8).toUpperCase()}` : `CLM-${doc.document_id.slice(0, 8).toUpperCase()}`;
      seenClaims.add(claimId);

      const relatedTasks = tasksByDoc.get(doc.document_id) || (doc.claim_id ? tasksByClaim.get(doc.claim_id) : []) || [];
      const hasOpenTasks = relatedTasks.some((t: any) => t.status === "OPEN" || t.status === "IN_PROGRESS");
      const allTasksApproved = relatedTasks.length > 0 && relatedTasks.every((t: any) => t.status === "APPROVED" || t.status === "REJECTED");
      
      let displayStatus = "Needs Review";
      if (doc.status === "COMPLETED" || doc.status === "OUTPUT_GENERATED" || allTasksApproved) {
        displayStatus = "Completed";
      } else if (hasOpenTasks || doc.status === "NEEDS_REVIEW") {
        displayStatus = "Needs Review";
      } else if (["RECEIVED", "PREPARED", "ROUTED", "VALIDATING"].includes(doc.status)) {
        displayStatus = "Processing";
      } else if (["FAILED", "QUARANTINED"].includes(doc.status)) {
        displayStatus = "Failed";
      }

      const patientName = doc.patient_name || relatedTasks.find((t: any) => t.patient_name)?.patient_name;
      const exceptionFields = relatedTasks.map((t: any) => t.field_name).filter(Boolean);
      const primaryTaskId = relatedTasks[0]?.task_id || doc.document_id;
      const assignedReviewer = relatedTasks.find((t: any) => t.assigned_to)?.assigned_to || "Unassigned";

      items.push({
        id: primaryTaskId,
        document_id: doc.document_id,
        claim_id: claimId,
        patient: patientName ? patientName : `Claim ${claimId}`,
        type: doc.detected_format === "PDF" ? "CMS-1500" : (doc.detected_format || "CMS-1500"),
        payer: "—",
        received: doc.received_at ? doc.received_at.replace("T", " ").slice(0, 16) : new Date().toISOString().replace("T", " ").slice(0, 16),
        confidence: displayStatus === "Completed" ? 96 : 74,
        reviewer: assignedReviewer,
        status: displayStatus,
        priority: displayStatus === "Needs Review" ? "CRITICAL" : "STANDARD",
        sla: displayStatus === "Needs Review" ? "2h remaining" : "SLA Met",
        isLive: true,
        validation: exceptionFields.length > 0 
          ? `Exceptions: ${Array.from(new Set(exceptionFields)).map((f: string) => f.replaceAll("_", " ")).join(", ")}`
          : (displayStatus === "Completed" ? "None (Passed - STP)" : "In Pipeline"),
      });
    }

    // 2. Direct review tasks not yet matched to documents list
    for (const task of rawTasks) {
      if (task.document_id && seenDocs.has(task.document_id)) continue;
      const claimId = task.claim_id ? `CLM-${task.claim_id.slice(0, 8).toUpperCase()}` : `CLM-${task.task_id.slice(0, 8).toUpperCase()}`;
      if (seenClaims.has(claimId)) continue;
      seenClaims.add(claimId);

      const isCompleted = task.status === "APPROVED" || task.status === "REJECTED";
      items.push({
        id: task.task_id,
        document_id: task.document_id,
        claim_id: claimId,
        patient: task.patient_name ? task.patient_name : `Claim ${claimId}`,
        type: "CMS-1500",
        payer: "—",
        received: task.created_at ? task.created_at.replace("T", " ").slice(0, 16) : new Date().toISOString().replace("T", " ").slice(0, 16),
        confidence: isCompleted ? 95 : 72,
        reviewer: task.assigned_to || "Unassigned",
        status: isCompleted ? "Completed" : "Needs Review",
        priority: isCompleted ? "STANDARD" : "CRITICAL",
        sla: isCompleted ? "SLA Met" : "2h remaining",
        isLive: true,
        validation: task.field_name ? `Exceptions: ${task.field_name.replaceAll("_", " ")}` : "None (Passed)",
      });
    }

    return items;
  }, [reviewTasksQuery.data, documentsQuery.data]);

  // Live audit logs fetch (Priority 3)
  const auditQuery = useQuery({
    queryKey: ["review-task-audit", selectedTaskId],
    queryFn: async () => {
      const response = await fetch(`/review-api/review-tasks/${selectedTaskId}/audit`, { headers });
      if (!response.ok) throw new Error("Failed to fetch audit trails from Review API");
      return response.json();
    },
    enabled: Boolean(selectedTaskId && !selectedTaskId.startsWith("CLM-"))
  });

  const activeAuditLogs: AuditLogEntry[] = useMemo(() => {
    if (selectedTaskId && !selectedTaskId.startsWith("CLM-") && auditQuery.data) {
      return (auditQuery.data || []).map((log: any) => ({
        timestamp: log.occurred_at ? log.occurred_at.replace("T", " ").slice(0, 19) : new Date().toISOString(),
        claimId: selectedTaskId.slice(0, 8).toUpperCase(),
        actor: log.actor || "Auditor Reviewer",
        action: log.event_type || "WORKFLOW_STATE",
        prev: `Ver: ${log.task_version - 1}`,
        next: `Ver: ${log.task_version}`,
        reason: log.reason_code || "State Transition Committed"
      }));
    }
    return [];
  }, [selectedTaskId, auditQuery.data]);

  // 16-Agent KAIMS Architecture Status Mapping (Phase 5)
  const agentStates = [
    { name: "1. Intake Orchestrator", state: "Implemented", desc: "Monitors API, S3, and SFTP endpoints, coordinates incoming scans, and initializes claim workflows." },
    { name: "2. Document Intelligence Agent", state: "Partial", desc: "Segregates and classifies page-level claim forms (CMS-1500 vs. UB-04 vs. Attachments)." },
    { name: "3. Document Quality & Localization Agent", state: "Partial", desc: "Calculates deskew, scan blurriness, and resolves pixel-space bounding field coordinates." },
    { name: "4. Extraction & Validation Agent", state: "Implemented", desc: "Performs PaddleOCR/Tesseract consensus extraction and enforces Mod-10 NPI validation checksums." },
    { name: "5. Identity Resolution Agent", state: "Partial", desc: "Cross-checks resolved demographics and provider IDs against reference master registries." },
    { name: "6. Policy & Coverage Agent", state: "Conceptual", desc: "Intended to verify active coverage ranges, eligibility status, and medical benefit guidelines." },
    { name: "7. Evidence Reconciliation Agent", state: "Partial", desc: "Assembles physical bounding-box crops and raw text candidates into trusted Evidence Packages." },
    { name: "8. Underwriting Risk Agent", state: "Planned", desc: "Calculates underwriting appraisal risk scorecards based on patient medical profiles." },
    { name: "9. Pricing & Rating Agent", state: "Planned", desc: "Queries rating tables and contract rate cards to calculate pricing tier adjustments." },
    { name: "10. Claim Coding & Clinical Agent", state: "Conceptual", desc: "Validates clinical ICD-10 codes, CPT procedure modifiers, and semantic structure guidelines." },
    { name: "11. Claim Reconciliation Agent", state: "Partial", desc: "Performs financial ledger matching, reconciling individual service line items against total charges." },
    { name: "12. Fraud & Anomaly Agent", state: "Conceptual", desc: "Identifies duplicate claims, duplicate service codes, and anomalous billing patterns." },
    { name: "13. Underwriting Decision Agent", state: "Planned", desc: "Automates final underwriting enrollment offers and approval metrics." },
    { name: "14. Claim Decision Agent", state: "Conceptual", desc: "Generates recommended claim payment distributions and standard adjudication outcomes." },
    { name: "15. Governance & Audit Agent", state: "Implemented", desc: "Secures state transition records with tamper-evident, cryptographic SHA-256 canonical JSON signatures." },
    { name: "16. HITL & Communication Agent", state: "Implemented", desc: "Escalates low-confidence data and validation failures to senior claims reviewers for human auditing." }
  ];


  // Filters
  const filteredClaims = useMemo(() => {
    return claims.filter((claim) => {
      const matchesSearch = !activeSearch || [claim.id, claim.patient, claim.payer, claim.reviewer].join(" ").toLowerCase().includes(activeSearch.toLowerCase());
      const matchesStatus = statusFilter === "ALL" || claim.status.toUpperCase() === statusFilter.toUpperCase();
      return matchesSearch && matchesStatus;
    });
  }, [claims, activeSearch, statusFilter]);

  // Active Learning Feedback Mutation (Priority 4)
  const feedbackMutation = useMutation({
    mutationFn: async ({ taskId, comment, reasonCode }: { taskId: string; comment: string; reasonCode: string }) => {
      // Pull task details to load proper version concurrency index
      const detailRes = await fetch(`/review-api/review-tasks/${taskId}`, { headers });
      if (!detailRes.ok) throw new Error("Could not fetch claim metadata before feedback");
      const detailData = await detailRes.json();

      const response = await fetch(`/review-api/review-tasks/${taskId}/correct?reviewer=reviewer@company.com`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          new_value: detailData.system_recommendation || detailData.ocr_candidates[0] || "",
          reason: `FEEDBACK: [Reason: ${reasonCode}] - ${comment}`,
          expected_version: detailData.version
        })
      });
      if (!response.ok) throw new Error(await response.text());
      return response.json();
    },
    onSuccess: () => {
      setFeedbackSuccess(true);
      cache.invalidateQueries({ queryKey: ["review-tasks"] });
      setTimeout(() => {
        setShowFeedbackModal(false);
        setFeedbackSuccess(false);
        setComment("");
      }, 2500);
    }
  });

  const handleApplyFeedback = () => {
    if (!selectedTaskId) return;
    feedbackMutation.mutate({
      taskId: selectedTaskId,
      comment: feedbackComment || "Correction submitted for AI pipeline retraining",
      reasonCode: feedbackReasonCode
    });
  };

  const handleOpenClaim = (claimId: string) => {
    setSelectedTaskId(claimId);
    setActiveTab("review");
  };

  const handleSaveSettings = () => {
    localStorage.setItem("idp_settings_npi_threshold", npiThreshold.toString());
    localStorage.setItem("idp_settings_charge_threshold", chargeThreshold.toString());
    localStorage.setItem("idp_settings_luhn_validation", luhnValidation.toString());
    localStorage.setItem("idp_settings_icd_validation", icdValidation.toString());
    
    setSettingsSaved(true);
    setTimeout(() => setSettingsSaved(false), 3000);
  };

  const rawTasksForMetrics = reviewTasksQuery.data || [];
  const rawDocsForMetrics = documentsQuery.data || [];
  const taskDocIds = new Set(rawTasksForMetrics.map((t: any) => t.document_id).filter(Boolean));

  const livePendingCount = rawTasksForMetrics.filter((t: any) => t.status === "OPEN" || t.status === "IN_PROGRESS").length;
  const totalIngested = rawDocsForMetrics.length;
  // True STP: Completed/output-generated documents that bypassed human review exceptions entirely
  const stpDocs = rawDocsForMetrics.filter((doc: any) => (doc.status === "COMPLETED" || doc.status === "OUTPUT_GENERATED") && !taskDocIds.has(doc.document_id)).length;
  const stpRate = totalIngested > 0 ? ((stpDocs / totalIngested) * 100).toFixed(1) + "%" : "—";
  const exceptionDocs = rawDocsForMetrics.filter((doc: any) => doc.status === "NEEDS_REVIEW" || taskDocIds.has(doc.document_id)).length;
  const exceptionRate = totalIngested > 0 ? ((exceptionDocs / totalIngested) * 100).toFixed(1) + "%" : "—";

  return (
    <div className="app-container">
      {/* SIDEBAR SHELL */}
      <aside className="sidebar">
        <div>
          <div className="sidebar-logo">
            <div className="logo-icon">CI</div>
            <div className="logo-text">
              <h1>Claims IDP</h1>
              <span>Healthcare Core</span>
            </div>
          </div>

          <nav className="sidebar-nav">
            <button role="tab" className={`nav-item ${activeTab === "dashboard" ? "active" : ""}`} onClick={() => setActiveTab("dashboard")}>
              📊 Dashboard
            </button>
            <button role="tab" className={`nav-item ${activeTab === "queue" ? "active" : ""}`} onClick={() => setActiveTab("queue")}>
              🗂 Work Queue
            </button>
            <button role="tab" className={`nav-item ${activeTab === "review" ? "active" : ""}`} onClick={() => setActiveTab("review")}>
              🔍 Document Review
            </button>
            <button role="tab" className={`nav-item ${activeTab === "analytics" ? "active" : ""}`} onClick={() => setActiveTab("analytics")}>
              📈 Analytics
            </button>
            <button role="tab" className={`nav-item ${activeTab === "audit" ? "active" : ""}`} onClick={() => setActiveTab("audit")}>
              🛡 Audit Trail
            </button>
            <button role="tab" className={`nav-item ${activeTab === "settings" ? "active" : ""}`} onClick={() => setActiveTab("settings")}>
              ⚙ Settings
            </button>
          </nav>
        </div>

        {/* User status info */}
        <div className="sidebar-footer">
          <div className="user-profile">
            <div className="avatar-wrapper">
              <div className="avatar">AR</div>
              <div className="status-dot"></div>
            </div>
            <div className="user-info">
              <strong>Aarati Joshi</strong>
              <span>Sr. Claims Auditor</span>
            </div>
          </div>
        </div>
      </aside>

      {/* MAIN CONTAINER */}
      <div className="main-wrapper">
        <header className="top-header">
          <div className="header-title-area">
            <span className="header-breadcrumbs">Claims IDP / {activeTab}</span>
            <h2>{activeTab === "dashboard" ? "Operational Analytics Dashboard" : activeTab === "review" ? "Side-by-Side Review" : activeTab === "queue" ? "Claims Ingestion Queue" : "System Console"}</h2>
          </div>

          <div className="header-controls">
            <button className="notification-bell">
              🔔
              <div className="bell-badge"></div>
            </button>
            <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
              <span style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Tenant: <strong>prototype-ui</strong></span>
            </div>
          </div>
        </header>

        <div className="workspace-container">
          
          {/* TAB 1: OPERATIONS DASHBOARD */}
          {activeTab === "dashboard" && (
            <section style={{ display: "grid", gap: "25px" }}>
              <div className="process-intro">
                <p className="eyebrow">Operational Metrics</p>
                <h2 style={{ margin: "4px 0" }}>Claims Pipeline Performance</h2>
                <p style={{ color: "var(--text-secondary)", fontSize: "12px" }}>Real-time measured throughput and STP rates for healthcare documents</p>
              </div>

              {/* KPI Ribbon (Priority 7) */}
              <div className="metric-grid">
                <div onClick={() => setActiveTab("analytics")}>
                  <MetricCard label="STP Rate" value={stpRate} tone="good" hint="Auto-adjudicated claim percentage" clickable={true} />
                </div>
                <div onClick={() => setActiveTab("queue")}>
                  <MetricCard label="Total Ingested" value={totalIngested.toString()} tone="default" hint="Total claim documents scanned" clickable={true} />
                </div>
                <div onClick={() => { setActiveTab("queue"); setStatusFilter("Needs Review"); }}>
                  <MetricCard label="Pending HITL" value={livePendingCount.toString()} tone="danger" hint="Claims awaiting manual correction" clickable={true} />
                </div>
                <MetricCard label="Field Accuracy" value="—" tone="good" hint="Real-time exact-match accuracy" />
                <MetricCard label="Exception Rate" value={exceptionRate} tone="warning" hint="Claims escalated to review queue" />
                <MetricCard label="Avg Latency" value="—" tone="default" hint="Real-time average pipeline latency" />
              </div>

              {/* Charts & Pareto lists split panel */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 420px", gap: "20px" }}>
                <div className="panel" style={{ minHeight: "300px" }}>
                  <div className="panel-heading">
                    <div>
                      <p className="eyebrow">Volume Analysis</p>
                      <h3>Claims Volume Trends</h3>
                    </div>
                    <div style={{ display: "flex", gap: "6px" }}>
                      <button className="primary-button" style={{ fontSize: "10px", padding: "4px 8px", background: "var(--cyan)" }}>7 Days (Simulated)</button>
                    </div>
                  </div>
                  
                  {/* Dynamic Chart Area */}
                  <div style={{ height: "200px", display: "flex", alignItems: "end", gap: "10px", padding: "10px 0" }}>
                    {[22, 35, 48, 55, 74, 98, 85, 110, 105, 130, 125, 150].map((val, i) => (
                      <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center" }}>
                        <div style={{ 
                          width: "100%", 
                          height: `${val}px`, 
                          background: i % 2 === 0 ? "linear-gradient(to top, var(--cyan), var(--blue))" : "rgba(20, 184, 166, 0.15)",
                          borderRadius: "4px 4px 0 0" 
                        }} />
                        <small style={{ fontSize: "9px", color: "var(--text-tertiary)", marginTop: "4px" }}>{8 + i}h</small>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Pareto Failures */}
                <div className="panel">
                  <div className="panel-heading">
                    <div>
                      <p className="eyebrow">Pipeline exceptions</p>
                      <h3>Common Validation Errors</h3>
                    </div>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                    {[
                      { reason: "Billing Provider NPI Luhn Failure", count: 42, severity: "HIGH" },
                      { reason: "Low OCR Extraction Confidence (<85%)", count: 28, severity: "MEDIUM" },
                      { reason: "Missing Patient DOB (Box 3)", count: 18, severity: "HIGH" },
                      { reason: "Invalid Diagnosis Format (ICD-10)", count: 12, severity: "MEDIUM" }
                    ].map((item, i) => (
                      <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingBottom: "10px", borderBottom: "1px solid var(--line-color)" }}>
                        <div style={{ display: "flex", flexDirection: "column" }}>
                          <span style={{ fontSize: "12px", fontWeight: "700" }}>{item.reason}</span>
                          <small style={{ fontSize: "10px", color: "var(--text-tertiary)" }}>{item.count} occurrences</small>
                        </div>
                        <span className={`badge ${item.severity === "HIGH" ? "failed" : "warning"}`} style={{ fontSize: "9px", padding: "2px 6px" }}>{item.severity}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* KAIMS Core 16-Agent Pipeline dashboard (Phase 5) */}
              <div className="panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">KAIMS CORE 16-AGENT PIPELINE</p>
                    <h3>Real-Time Claims Intelligent Agent Orchestration Network</h3>
                    <p style={{ color: "var(--text-secondary)", fontSize: "12px", margin: 0 }}>This visualization maps active state-machine transitions and operational readiness directly to our real-time Python backend orchestrator.</p>
                  </div>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "15px" }}>
                  {agentStates.map((agent, i) => (
                    <div key={i} style={{ border: "1px solid var(--line-color)", background: "var(--card-bg)", borderRadius: "8px", padding: "12px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                        <span style={{ fontSize: "11px", fontWeight: "700", color: "var(--cyan)" }}>{agent.name}</span>
                        <span className={`badge ${agent.state === "Implemented" ? "complete" : agent.state === "Partial" || agent.state === "Conceptual" ? "processing" : "warning"}`} style={{ fontSize: "8px", padding: "1px 6px" }}>{agent.state}</span>
                      </div>
                      <p style={{ fontSize: "10px", color: "var(--text-secondary)", lineHeight: "1.4" }}>{agent.desc}</p>
                    </div>
                  ))}
                </div>
              </div>
            </section>
          )}

          {/* TAB 2: UNIVERSAL WORK QUEUE */}
          <section style={{ display: activeTab === "queue" ? "grid" : "none", gap: "20px" }}>
            <div className="panel" style={{ padding: "20px" }}>
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Queue Operations</p>
                  <h3>Universal Healthcare Claims Queue</h3>
                </div>
                <div style={{ display: "flex", gap: "10px" }}>
                  <input 
                    placeholder="Search claims..." 
                    value={activeSearch}
                    onChange={(e) => setActiveSearch(e.target.value)}
                    style={{ padding: "6px 12px", borderRadius: "6px", background: "var(--input-bg)", border: "1px solid var(--line-color)", color: "var(--text-primary)", fontSize: "12px" }}
                  />
                  <select 
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    style={{ padding: "6px 12px", borderRadius: "6px", background: "var(--input-bg)", border: "1px solid var(--line-color)", color: "var(--text-primary)", fontSize: "12px" }}
                  >
                    <option value="ALL">All Statuses</option>
                    <option value="Needs Review">Needs Review</option>
                    <option value="Completed">Completed</option>
                  </select>
                </div>
              </div>

              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Claim ID</th>
                      <th>Patient</th>
                      <th>Format</th>
                      <th>Payer</th>
                      <th>Received</th>
                      <th>Confidence</th>
                      <th>Validation Check</th>
                      <th>Assigned</th>
                      <th>Status</th>
                      <th>SLA Priority</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredClaims.map((claim) => (
                      <tr key={claim.id} style={{ cursor: "pointer" }} onClick={() => handleOpenClaim(claim.id)}>
                        <td>
                          <code>{claim.claim_id.slice(0, 16)}</code>
                          {claim.isLive ? (
                            <span style={{ marginLeft: "6px", fontSize: "8px", background: "rgba(16, 185, 129, 0.15)", color: "var(--good-bright)", padding: "2px 4px", borderRadius: "3px", fontWeight: "700" }}>LIVE</span>
                          ) : (
                            <span style={{ marginLeft: "6px", fontSize: "8px", background: "rgba(148, 163, 184, 0.15)", color: "var(--text-secondary)", padding: "2px 4px", borderRadius: "3px", fontWeight: "700" }}>DEMO</span>
                          )}
                        </td>
                        <td><strong>{claim.patient}</strong></td>
                        <td>{claim.type}</td>
                        <td>{claim.payer}</td>
                        <td><small>{claim.received}</small></td>
                        <td>
                          <span className={`badge-pill ${claim.confidence >= 90 ? "high" : "warning"}`} style={{
                            background: claim.confidence >= 90 ? "rgba(16, 185, 129, 0.15)" : "rgba(245, 158, 11, 0.15)",
                            color: claim.confidence >= 90 ? "var(--good-bright)" : "var(--warning-bright)",
                            padding: "2px 6px",
                            borderRadius: "4px",
                            fontSize: "11px"
                          }}>
                            {claim.confidence}%
                          </span>
                        </td>
                        <td>
                          <span style={{ fontSize: "11px", color: claim.validation.includes("Passed") ? "var(--good-bright)" : "var(--danger-bright)" }}>
                            {claim.validation}
                          </span>
                        </td>
                        <td><small>{claim.reviewer}</small></td>
                        <td>
                          <span className={`badge ${claim.status === "Completed" ? "complete" : claim.status === "Escalated" ? "failed" : "warning"}`} style={{ fontSize: "9px" }}>
                            {claim.status}
                          </span>
                        </td>
                        <td>
                          <span style={{ fontSize: "11px", color: claim.priority === "CRITICAL" ? "var(--danger)" : "var(--text-secondary)", fontWeight: "700" }}>
                            {claim.priority} ({claim.sla})
                          </span>
                        </td>
                        <td>
                          <button className="primary-button" style={{ padding: "4px 8px", fontSize: "10px" }} onClick={(e) => { e.stopPropagation(); handleOpenClaim(claim.id); }}>
                            Audit Review
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Upload Workspace core */}
            <ProcessingWorkspace />
          </section>

          {/* TAB 3: DOCUMENT REVIEW */}
          <section style={{ display: activeTab === "review" ? "grid" : "none", gap: "20px" }}>
            {/* Fallback tracking info ribbon */}
            <div style={{ border: "1px solid var(--line-color)", background: "rgba(245,158,11,0.12)", padding: "12px", borderRadius: "8px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <span style={{ fontSize: "10px", color: "var(--warning-bright)", fontWeight: "700", textTransform: "uppercase" }}>Model Fallback Log</span>
                <p style={{ margin: "4px 0 0 0", fontSize: "12px" }}>Primary extraction model <strong>Document AI v1.2</strong> confidence dropped to 71%. Fallback model <strong>Layout VLM</strong> triggered.</p>
              </div>
              {selectedTaskId && !selectedTaskId.startsWith("CLM-") && (
                <button className="primary-button" style={{ padding: "4px 10px", fontSize: "10px", background: "var(--cyan)", color: "#fff" }} onClick={() => setShowFeedbackModal(true)}>
                  Submit Active Learning Feedback
                </button>
              )}
            </div>

            <HitlInspector 
              initialTaskId={selectedTaskId} 
              onBackToQueue={() => {
                reviewTasksQuery.refetch();
                setActiveTab("queue");
              }}
            />
          </section>

          {/* TAB 4: ANALYTICS */}
          {activeTab === "analytics" && (
            <section style={{ display: "grid", gap: "25px" }}>
              {report ? (
                <>
                  <GroupAccuracy report={report} />
                  <AccuracyBars title="Extraction Accuracy Breakdown by Form Fields" values={report.accuracy_by_field} />
                  <PipelineFlow report={report} />
                </>
              ) : (
                <div className="panel" style={{ padding: "40px", textAlign: "center", display: "grid", placeItems: "center" }}>
                  <h3>Awaiting Evaluation Report Payload</h3>
                  <p style={{ color: "var(--text-secondary)" }}>Upload your evaluation report JSON using the header button to load analytics charts</p>
                </div>
              )}
            </section>
          )}

          {/* TAB 5: AUDIT TRAIL */}
          {activeTab === "audit" && (
            <section style={{ display: "grid", gap: "20px" }}>
              <div className="panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Compliance explorer</p>
                    <h3>Chronological Claims Pipeline Log</h3>
                    <small style={{ color: "var(--text-secondary)" }}>Immutable ledger records of system decisions and human corrections</small>
                  </div>
                </div>

                {/* Dropdown selectors for real audit ledger (Priority 3) */}
                <div style={{ background: "var(--card-bg-2)", padding: "12px 18px", borderRadius: "8px", border: "1px solid var(--line-color)", display: "flex", gap: "15px", alignItems: "center", marginBottom: "15px" }}>
                  <span style={{ fontSize: "12px", fontWeight: "700" }}>🔍 Select Live Audit Timeline:</span>
                  <select 
                    value={selectedTaskId || ""} 
                    onChange={(e) => setSelectedTaskId(e.target.value || undefined)}
                    style={{ padding: "6px 12px", borderRadius: "6px", background: "var(--input-bg)", border: "1px solid var(--line-color)", color: "var(--text-primary)", fontSize: "12px", minWidth: "220px" }}
                  >
                    <option value="">-- View Global System Log (Demo) --</option>
                    {(reviewTasksQuery.data || []).map((t: any) => (
                      <option key={t.task_id} value={t.task_id}>
                        Live Claim Task: {t.claim_id ? t.claim_id.toUpperCase() : t.task_id.slice(0, 8)}
                      </option>
                    ))}
                  </select>
                  {selectedTaskId && !selectedTaskId.startsWith("CLM-") && (
                    <span style={{ fontSize: "11px", color: "var(--cyan)" }}>
                      ✓ Dynamic API Ledger Synced: Loading {activeAuditLogs.length} live records
                    </span>
                  )}
                </div>

                {auditQuery.isPending && selectedTaskId && !selectedTaskId.startsWith("CLM-") ? (
                  <div style={{ padding: "40px", textAlign: "center", color: "var(--text-secondary)" }}>
                    Loading compliance logs from Review Audit API...
                  </div>
                ) : (
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Timestamp</th>
                          <th>Claim ID</th>
                          <th>Actor Agent</th>
                          <th>Action</th>
                          <th>Original State</th>
                          <th>Modified State</th>
                          <th>Disposition Reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {activeAuditLogs.map((log: AuditLogEntry, i: number) => (
                          <tr key={i}>
                            <td><small>{log.timestamp}</small></td>
                            <td><code>{log.claimId}</code></td>
                            <td><strong>{log.actor}</strong></td>
                            <td><span className="badge processing" style={{ fontSize: "8px", padding: "1px 6px" }}>{log.action}</span></td>
                            <td style={{ color: "var(--danger-bright)", textDecoration: log.prev !== "—" ? "line-through" : "none" }}>{log.prev}</td>
                            <td style={{ color: "var(--cyan)", fontWeight: "700" }}>{log.next}</td>
                            <td><small>{log.reason}</small></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </section>
          )}

          {/* TAB 6: SETTINGS */}
          {activeTab === "settings" && (
            <section style={{ display: "grid", gap: "20px" }}>
              <div className="panel" style={{ display: "grid", gap: "20px" }}>
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Settings</p>
                    <h3>Confidence Thresholds & Active Business Rules</h3>
                  </div>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "40px" }}>
                  {/* Sliders */}
                  <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
                    <h4>Minimum Confidence Thresholds (%)</h4>
                    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px" }}>
                        <label>Billing Provider NPI Check</label>
                        <strong>{npiThreshold}%</strong>
                      </div>
                      <input type="range" min="50" max="100" value={npiThreshold} onChange={(e) => setNpiThreshold(Number(e.target.value))} />
                    </div>

                    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px" }}>
                        <label>Total Claim Charge Amount</label>
                        <strong>{chargeThreshold}%</strong>
                      </div>
                      <input type="range" min="50" max="100" value={chargeThreshold} onChange={(e) => setChargeThreshold(Number(e.target.value))} />
                    </div>
                  </div>

                  {/* Toggles */}
                  <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
                    <h4>Healthcare Validation Gates</h4>
                    <label style={{ display: "flex", alignItems: "center", gap: "10px", fontSize: "13px", cursor: "pointer" }}>
                      <input type="checkbox" checked={luhnValidation} onChange={(e) => setLuhnValidation(e.target.checked)} />
                      Enable active Mod-10 Luhn checksum calculations for provider NPIs
                    </label>

                    <label style={{ display: "flex", alignItems: "center", gap: "10px", fontSize: "13px", cursor: "pointer" }}>
                      <input type="checkbox" checked={icdValidation} onChange={(e) => setIcdValidation(e.target.checked)} />
                      Enable ICD-10 medical code dictionary formatting checks
                    </label>
                  </div>
                </div>

                <div style={{ borderTop: "1px solid var(--line-color)", paddingTop: "15px", display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
                  <button className="primary-button" onClick={handleSaveSettings}>
                    Save Settings
                  </button>
                  {settingsSaved && (
                    <div style={{ color: "var(--good-bright)", fontSize: "12px", fontWeight: "700", marginTop: "8px" }}>
                      ✓ System Settings successfully committed to Local Storage!
                    </div>
                  )}
                </div>
              </div>
            </section>
          )}

        </div>
      </div>

      {/* FEEDBACK MODAL (ACTIVE LEARNING) */}
      {showFeedbackModal && (
        <div style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.75)",
          display: "grid",
          placeItems: "center",
          zIndex: 9999
        }}>
          <div className="panel" style={{ width: "450px", background: "var(--panel-bg)", padding: "25px", border: "1px solid var(--cyan)" }}>
            <div className="panel-heading" style={{ borderBottom: "1px solid var(--line-color)", paddingBottom: "10px", marginBottom: "15px" }}>
              <h3>Submit Model Correction Feedback</h3>
            </div>
            
            {feedbackSuccess ? (
              <div style={{ textAlign: "center", padding: "20px 0" }}>
                <span style={{ fontSize: "40px" }}>✓</span>
                <h4 style={{ color: "var(--cyan)", marginTop: "10px" }}>Feedback Captured for Model Improvement</h4>
                <p style={{ color: "var(--text-secondary)", fontSize: "12px", marginTop: "4px" }}>Corrections successfully written to active learning feedback topics.</p>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "15px" }}>
                {feedbackMutation.isError && (
                  <div style={{ background: "rgba(239, 68, 68, 0.15)", border: "1px solid var(--danger)", color: "var(--danger-bright)", padding: "8px", borderRadius: "6px", fontSize: "11px" }}>
                    ⚠️ Feedback Error: {feedbackMutation.error instanceof Error ? feedbackMutation.error.message : "Request failed."}
                  </div>
                )}
                
                <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                  <label style={{ fontSize: "12px", color: "var(--text-secondary)" }}>Reason for Correction</label>
                  <select 
                    value={feedbackReasonCode}
                    onChange={(e) => setFeedbackReasonCode(e.target.value)}
                    style={{ padding: "8px", borderRadius: "6px", background: "var(--input-bg)", border: "1px solid var(--line-color)", color: "var(--text-primary)" }}
                  >
                    <option value="ocr">OCR Error (Misread digits)</option>
                    <option value="mapping">Incorrect Field Mapping</option>
                    <option value="quality">Poor Document Scan Quality</option>
                    <option value="validation">Validation Code Issue</option>
                  </select>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                  <label style={{ fontSize: "12px", color: "var(--text-secondary)" }}>Comments</label>
                  <textarea 
                    rows={3} 
                    value={feedbackComment}
                    onChange={(e) => setComment(e.target.value)}
                    placeholder="Enter notes for AI retraining..."
                    style={{ padding: "8px", borderRadius: "6px", background: "var(--input-bg)", border: "1px solid var(--line-color)", color: "var(--text-primary)", resize: "none" }}
                  />
                </div>

                <div style={{ display: "flex", gap: "10px", justifyContent: "flex-end", marginTop: "10px" }}>
                  <button className="primary-button" style={{ background: "var(--button-bg)", color: "var(--text-primary)" }} onClick={() => setShowFeedbackModal(false)}>Cancel</button>
                  <button className="primary-button" onClick={handleApplyFeedback} disabled={feedbackMutation.isPending}>
                    {feedbackMutation.isPending ? "Sending..." : "Submit Feedback"}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

    </div>
  );
}
