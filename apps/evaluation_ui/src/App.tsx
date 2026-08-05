import { useEffect, useMemo, useState } from "react";
import { AccuracyBars, Empty, GroupAccuracy, MetricCard } from "./components";
import { EvidenceView } from "./evidence";
import { HitlInspector } from "./hitl";
import { PipelineFlow, TuningView } from "./pipeline";
import { ProcessingWorkspace } from "./process";
import { SubmissionView } from "./submission";
import { parseReport, percent, signedDelta } from "./report";
import { ExtractionAccuracyComparison, ResultsTable } from "./results";
import type { EvaluationReport } from "./types";
import "./styles.css";

import { FieldTransformationVisualizer } from "./visualizer";

type ReportTab = "process" | "overview" | "visualizer" | "evidence" | "hitl" | "flow" | "tuning" | "submission";

function readFileText(file: File): Promise<string> {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("Unable to read report."));
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.readAsText(file);
  });
}

function compactDuration(value: number | null | undefined): string {
  return value == null ? "Not metered" : `${value.toFixed(3)}s`;
}

function compactMoney(value: number | null | undefined): string {
  return value == null ? "Not metered" : `$${value.toFixed(6)}`;
}

export default function App() {
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("ALL");
  const [activeTab, setActiveTab] = useState<ReportTab>("overview");

  useEffect(() => {
    if (typeof fetch === "undefined") return;
    fetch("/reports/evaluation.json").then((response) => {
      if (!response.ok) throw new Error("No deployed evaluation report found.");
      return response.json();
    }).then((payload) => setReport(parseReport(payload))).catch(() => undefined);
  }, []);

  async function loadFile(file?: File) {
    if (!file) return;
    try {
      setReport(parseReport(JSON.parse(await readFileText(file))));
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to read report.");
    }
  }

  const categories = useMemo(() => [...new Set(report?.mismatches.map((row) => row.failure_category) ?? [])], [report]);
  const rows = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return (report?.mismatches ?? []).filter((row) => {
      const matchesCategory = category === "ALL" || row.failure_category === category;
      const matchesQuery = !normalizedQuery || [row.document_id, row.field_name, row.form_type, row.extraction_method].join(" ").toLowerCase().includes(normalizedQuery);
      return matchesCategory && matchesQuery;
    });
  }, [report, query, category]);

  const tabTitles: Record<ReportTab, string> = {
    process: "Process new claim documents",
    overview: "Governed extraction results",
    visualizer: "Field transformation & escalation visualizer",
    evidence: "Field-level evidence",
    hitl: "Human review inspector",
    flow: "OCR & LLM cascade",
    tuning: "Tuning & governance",
    submission: "Hackathon submission",
  };

  return (
    <main>
      <header className="topbar">
        <div className="brand"><span className="brand-mark">IDP</span><div><strong>Claims Intelligence</strong><small>Quality & governance console</small></div></div>
        <label className="upload-button">Load evaluation JSON<input type="file" accept="application/json,.json" onChange={(event) => loadFile(event.target.files?.[0])} /></label>
      </header>

      {!report ? <section className="welcome">
        <div className="welcome-copy"><p className="eyebrow">Evidence, not estimates</p><h1>Claims extraction you can explain.</h1><p>Load the evaluation report to inspect measured accuracy, field evidence, the complete OCR/LLM cascade and every production safety control.</p><label className="primary-button">Choose report<input type="file" accept="application/json,.json" onChange={(event) => loadFile(event.target.files?.[0])} /></label>{error && <p className="error-banner">{error}</p>}</div>
        <div className="welcome-visual" aria-hidden="true"><span>SOURCE EVIDENCE</span><i /><span>VALIDATED OUTPUT</span><b>✓</b></div>
      </section> : <>
        <nav className="report-nav" aria-label="Report sections" role="tablist">
          {([["process", "Process claims"], ["overview", "Overview"], ["visualizer", "Field Transformation"], ["evidence", "Field evidence"], ["hitl", "HITL review"], ["flow", "OCR & LLM flow"], ["tuning", "Tuning & governance"], ["submission", "Submission"]] as [ReportTab, string][]).map(([key, label]) => <button aria-selected={activeTab === key} className={activeTab === key ? "active" : ""} key={key} onClick={() => setActiveTab(key)} role="tab">{label}</button>)}
        </nav>
        <section className="hero"><div><p className="eyebrow">Claims IDP / {activeTab}</p><h1>{tabTitles[activeTab]}</h1><p>{report.field_count.toLocaleString()} governed field outcomes</p></div><div className="status-stack"><div className="status-chip"><span className={report.critical_false_accept_rate === 0 ? "status-dot good" : "status-dot danger"} />Critical safety gate</div><small>Current labelled sample</small></div></section>
        {error && <p className="error-banner">{error}</p>}
        {report.report_metadata?.scope === "CURRENT_LABELED_SAMPLE_ONLY" && <div className="scope-banner"><span>Evaluation scope</span><strong>Current labelled sample only</strong><p>Validated benchmark results, not an untouched-holdout or general-production accuracy claim.</p></div>}
        {report.report_metadata?.synthetic_demo && <p className="demo-banner">Synthetic UI preview — these values are not measured platform accuracy.</p>}

        {activeTab === "process" && <ProcessingWorkspace />}

        {activeTab === "visualizer" && <FieldTransformationVisualizer />}

        {activeTab === "overview" && <>
          <ResultsTable report={report} />
          <ExtractionAccuracyComparison report={report} />
          <GroupAccuracy report={report} />
          {report !== null && <section className="metric-grid">
            <MetricCard label="Optimized LLM diversion" value={percent(report.llm_diversion_rate)} hint={`${report.llm_diverted_fields}/${report.field_count} fields · policy replay`} />
          </section>}
          <section className="comparison-grid"><div className="panel fallback-card"><div><p className="eyebrow">Field-level fallback</p><h2>Before vs. after</h2></div><div className="fallback-values"><div><span>Before</span><strong>{percent(report.accuracy_before_fallback)}</strong></div><span className="arrow">→</span><div><span>After</span><strong>{percent(report.accuracy_after_fallback)}</strong></div></div><div className="delta">{signedDelta(report.accuracy_before_fallback, report.accuracy_after_fallback)}</div></div><div className="panel compact-metrics"><div><span>Raw exact match</span><strong>{percent(report.raw_exact_match_accuracy)}</strong></div><div><span>Character error rate</span><strong>{percent(report.character_error_rate)}</strong></div><div><span>Missing-field rate</span><strong>{percent(report.missing_field_rate)}</strong></div><div><span>False-review rate</span><strong>{percent(report.false_review_rate)}</strong></div></div></section>
          <AccuracyBars title="Accuracy by field" values={report.accuracy_by_field} />
        </>}

        {activeTab === "evidence" && <section className="panel comparison-table"><div className="panel-heading table-heading"><div><p className="eyebrow">Side-by-side evidence</p><h2>Expected vs. extracted</h2></div><div className="filters"><input aria-label="Search mismatches" placeholder="Search document or field…" value={query} onChange={(event) => setQuery(event.target.value)} /><select aria-label="Failure category" value={category} onChange={(event) => setCategory(event.target.value)}><option value="ALL">All failures</option>{categories.map((value) => <option key={value}>{value}</option>)}</select></div></div>
          {rows.length === 0 ? <Empty>{report.mismatches.length ? "No mismatches match these filters." : "No mismatches — every evaluated field matched."}</Empty> : <div className="table-scroll"><table><thead><tr><th>Document / field</th><th>Expected</th><th>Extracted</th><th>Normalized</th><th>Confidence</th><th>Validation</th><th>Failure</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.document_id}-${row.field_name}-${index}`}><td><strong>{row.field_name.replaceAll("_", " ")}</strong><small>{row.document_id} · {row.form_type}</small></td><td className="value expected">{row.expected_value ?? "—"}</td><td className="value extracted">{row.extracted_value ?? "—"}<small>{row.extraction_method}</small></td><td className="value">{row.normalized_value ?? "—"}</td><td>{row.ocr_confidence == null ? "—" : percent(row.ocr_confidence)}</td><td><span className={`badge ${row.validation_result.toLowerCase()}`}>{row.validation_result}</span></td><td><span className="badge failure">{row.failure_category}</span></td></tr>)}</tbody></table></div>}
        </section>}
        {activeTab === "evidence" && report.field_evidence && <EvidenceView rows={report.field_evidence} />}
        {activeTab === "hitl" && <HitlInspector />}
        {activeTab === "flow" && <PipelineFlow report={report} />}
        {activeTab === "tuning" && <TuningView />}
        {activeTab === "submission" && <SubmissionView report={report} />}
      </>}
      <footer>Measured results only · Critical fields fail closed · PHI-safe report handling</footer>
    </main>
  );
}
