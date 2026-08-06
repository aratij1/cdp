import { useCallback, useEffect, useState } from "react";

type TaskSummary = { task_id: string; claim_id: string; field_name: string; status: string; created_at: string };
type TaskDetail = TaskSummary & { document_id: string; page_number: number; crop_signed_url: string | null; ocr_candidates: string[]; vlm_candidate: string | null; validation_errors: string[] };
type PromotionCandidate = { field_name: string; observed: string; corrected: string; occurrences: number; distinct_documents: number; distinct_reviewers: number; agreement_ratio: number; promotion_eligible: boolean };
const reviewerHeaders = { "X-User-Role": "reviewer" };

export function HitlInspector() {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [selected, setSelected] = useState<TaskDetail | null>(null);
  const [patterns, setPatterns] = useState<PromotionCandidate[]>([]);
  const [reviewer, setReviewer] = useState("reviewer@company.com");
  const [newValue, setNewValue] = useState("");
  const [reason, setReason] = useState("Verified against the source crop");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [confidenceThreshold, setConfidenceThreshold] = useState(80);
  const refresh = useCallback(async () => {
    const response = await fetch("/review-api/review-tasks", { headers: reviewerHeaders });
    if (!response.ok) throw new Error(`Unable to load review tasks (${response.status})`);
    setTasks(await response.json());
    const patternResponse = await fetch("/review-api/correction-promotion-candidates", { headers: reviewerHeaders });
    if (patternResponse.ok) setPatterns(await patternResponse.json());
  }, []);
  useEffect(() => { refresh().catch((value) => setError(String(value))); }, [refresh]);
  async function inspect(task: TaskSummary) {
    setMessage(""); setError("");
    const response = await fetch(`/review-api/review-tasks/${task.task_id}`, { headers: reviewerHeaders });
    if (!response.ok) { setError(`Unable to load task (${response.status})`); return; }
    const detail: TaskDetail = await response.json();
    setSelected(detail); setNewValue(detail.vlm_candidate ?? detail.ocr_candidates[0] ?? "");
  }
  async function decide(action: "correct" | "reject") {
    if (!selected || !reviewer.trim() || !reason.trim() || (action === "correct" && !newValue.trim())) {
      setError("Reviewer, reason, and corrected value are required."); return;
    }
    const body = action === "correct" ? { new_value: newValue, reason } : { reason };
    const response = await fetch(
      `/review-api/review-tasks/${selected.task_id}/${action}?reviewer=${encodeURIComponent(reviewer.trim())}`,
      { method: "POST", headers: { ...reviewerHeaders, "Content-Type": "application/json" }, body: JSON.stringify(body) },
    );
    if (!response.ok) { setError(await response.text()); return; }
    setMessage(action === "correct" ? "Correction approved and saved to feedback memory." : "Task rejected and audited.");
    setSelected(null); await refresh();
  }
  return <><div className="scope-banner"><span>Review requirement</span><strong>{tasks.length} live open tasks</strong><p>Fields requiring reviewer correction in the production queue.</p></div><section className="hitl-layout">
    <aside className="panel hitl-queue"><div className="panel-heading"><div><p className="eyebrow">Open queue</p><h2>Review requirements</h2></div><span className="count">{tasks.length}</span></div>{tasks.length === 0 ? <div className="empty">No open review tasks.</div> : tasks.map((task) => <button className={selected?.task_id === task.task_id ? "hitl-task active" : "hitl-task"} key={task.task_id} onClick={() => inspect(task)}><strong>{task.field_name.replaceAll("_", " ")}</strong><small>{task.claim_id.slice(0, 8)} · {new Date(task.created_at).toLocaleString()}</small></button>)}</aside>
    <section className="panel hitl-inspector"><div className="panel-heading"><div><p className="eyebrow">Human correction</p><h2>Field inspector</h2></div></div>{message && <p className="success-banner">{message}</p>}{error && <p className="error-banner">{error}</p>}{!selected ? <div className="empty">Select a review-required field to inspect its evidence.</div> : <><div className="hitl-evidence">{selected.crop_signed_url ? <img src={selected.crop_signed_url} alt={`Crop for ${selected.field_name}`} /> : <div className="empty">Crop unavailable</div>}<div><span>Document</span><strong>{selected.document_id}</strong><span>Page / field</span><strong>{selected.page_number} · {selected.field_name}</strong><span>Validation failures</span><strong>{selected.validation_errors.join(", ") || "Unspecified"}</strong><span>OCR candidates</span><strong>{selected.ocr_candidates.join(" | ") || "None"}</strong></div></div><div className="hitl-form"><label>Reviewer<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label><label>Corrected value<input value={newValue} onChange={(event) => setNewValue(event.target.value)} /></label><label>Reason<textarea value={reason} onChange={(event) => setReason(event.target.value)} /></label><div><button onClick={() => decide("reject")}>Reject field</button><button className="primary-button" onClick={() => decide("correct")}>Approve correction</button></div></div><p className="family-report-scope">Approved corrections are field-scoped prompt examples and never bypass validation.</p></>}</section>
  </section><section className="panel promotion-patterns"><div className="panel-heading"><div><p className="eyebrow">Correction learning</p><h2>Promotion readiness</h2><p className="group-accuracy-note">Patterns require 5 documents, 2 reviewers and 95% agreement before holdout testing.</p></div><span className="count">{patterns.filter((pattern) => pattern.promotion_eligible).length} ready</span></div>
</section>

<section className="panel confidence-report" style={{ marginTop: "24px" }}>
  <div className="panel-heading">
    <div>
      <p className="eyebrow">Insights & Recommendations</p>
      <h2>Confidence Improvement Report</h2>
      <p className="group-accuracy-note">Architectural strategies to push the confidence of difficult fields above the {confidenceThreshold}% threshold.</p>
    </div>
    <div style={{ display: "flex", alignItems: "center", gap: "16px", marginTop: "16px" }}>
      <label style={{ fontSize: "14px", color: "#94a3b8", fontWeight: 600 }}>Target Confidence: {confidenceThreshold}%</label>
      <input type="range" min="0" max="100" value={confidenceThreshold} onChange={(e) => setConfidenceThreshold(parseInt(e.target.value))} style={{ cursor: "pointer", flex: 1 }} />
    </div>
  </div>
  <div className="hitl-form" style={{ padding: "0 24px 24px 24px", lineHeight: "1.6" }}>
    <h4 style={{ color: "#e2e8f0", marginTop: "16px", marginBottom: "8px" }}>1. Implement Multi-Model Consensus (Ensembling)</h4>
    <p style={{ color: "#94a3b8", fontSize: "14px" }}>Route crops to multiple engines simultaneously (e.g., Tesseract + Google Cloud Vision + AWS Textract) and check for agreement. If 3 separate engines transcribe a messy name as "DOE, JOHN", the confidence can safely be upgraded to 95%+.</p>
    
    <h4 style={{ color: "#e2e8f0", marginTop: "16px", marginBottom: "8px" }}>2. Cross-Reference against Authoritative Databases (Grounding)</h4>
    <p style={{ color: "#94a3b8", fontSize: "14px" }}>Ping a real-time 270/271 Eligibility API. If "DOE, J0HN" resolves to "DOE, JOHN" in the payer's database, auto-correct the typo. Cross-reference signature crops with the NPPES NPI Registry.</p>

    <h4 style={{ color: "#e2e8f0", marginTop: "16px", marginBottom: "8px" }}>3. Image Pre-Processing Specialization</h4>
    <p style={{ color: "#94a3b8", fontSize: "14px" }}>Apply adaptive binarization & deskewing. Run a lightweight YOLO model trained to identify the boundaries of cursive signatures and send only that crop to a specialized Handwriting Recognition (HTR) model.</p>

    <h4 style={{ color: "#e2e8f0", marginTop: "16px", marginBottom: "8px" }}>4. Fine-Tune the Vision-LLM</h4>
    <p style={{ color: "#94a3b8", fontSize: "14px" }}>Fine-tune a localized adapter specifically on historical rejected claims and human-corrected HITL values to learn the specific handwriting quirks of frequent submitters.</p>
  </div>
</section>
</>;
}
