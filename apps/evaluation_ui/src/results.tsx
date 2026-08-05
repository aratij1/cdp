import { percent } from "./report";
import type { EvaluationReport } from "./types";

export function ResultsTable({ report }: { report: EvaluationReport }) {
  const operations = report.operational_metrics;
  const llmCost = report.llm_processing_cost;
  const llmCostValue = llmCost?.run_cost_usd == null
    ? (report.llm_diverted_fields === 0 ? "$0.000000" : "Not metered")
    : `$${llmCost.run_cost_usd.toFixed(6)}`;
  const llmCostBasis = llmCost?.basis
    ?? (report.llm_diverted_fields === 0
      ? "No LLM-routed fields in the current run"
      : "Provider token usage was not captured");
  const rows = [
    ["Quality", "Current-sample validated accuracy", percent(report.normalized_field_accuracy), "Governed normalized field outcomes"],
    ["Quality", "Local extraction accuracy", percent(report.local_extraction_accuracy ?? report.ocr_deterministic_accuracy), report.local_extraction_definition ?? "OCR, parsing and geometry before external fallback"],
    ["Quality", "Normalized precision", percent(operations?.precision ?? report.normalized_field_accuracy), "Current labelled sample"],
    ["Quality", "Normalized recall", percent(operations?.recall ?? report.normalized_field_accuracy), "Current labelled sample"],
    ["Safety", "Critical false accepts", percent(report.critical_false_accept_rate), "Target: zero"],
    ["Routing", "Optimized LLM diversion", `${report.llm_diverted_fields}/${report.field_count} · ${percent(report.llm_diversion_rate)}`, "Crop-local-first policy replay"],
    ["Cost", "LLM processing cost", llmCostValue, llmCostBasis],
  ];
  return <section className="panel results-table-panel"><div className="panel-heading"><div><p className="eyebrow">Latest benchmark only</p><h2>Submission results</h2></div><span className="submission-ready">Current policy</span></div><div className="table-scroll"><table className="results-table"><thead><tr><th>Category</th><th>Metric</th><th>Latest result</th><th>Scope / basis</th></tr></thead><tbody>{rows.map(([category, metric, value, basis]) => <tr key={`${category}-${metric}`}><td><span className={`result-category ${category.toLowerCase()}`}>{category}</span></td><td><strong>{metric}</strong></td><td className="result-value">{value}</td><td>{basis}</td></tr>)}</tbody></table></div></section>;
}

export function ExtractionAccuracyComparison({ report }: { report: EvaluationReport }) {
  const metrics = report.optimization_metrics;
  const total = report.field_count;
  const localCorrect = report.local_extraction_correct_fields
    ?? Math.round((report.local_extraction_accuracy ?? report.ocr_deterministic_accuracy) * total);
  const llmAttempted = metrics?.llm_attempted_fields ?? report.llm_diverted_fields;
  const llmCorrect = metrics?.llm_incremental_recoveries ?? 0;
  const llmAccuracy = llmAttempted > 0 ? llmCorrect / llmAttempted : null;
  const finalCorrect = Math.round(report.normalized_field_accuracy * total);

  return <section className="panel extraction-comparison">
    <div className="panel-heading">
      <div><p className="eyebrow">Extraction accuracy by stage</p><h2>Local extraction vs. LLM fallback</h2></div>
      <span className="submission-ready">Distinct denominators</span>
    </div>
    <div className="extraction-stage-grid">
      <article className="extraction-stage local-stage"><span>1 · Local extraction</span><strong>{percent(localCorrect / total)}</strong><b>{localCorrect}/{total} fields correct</b><p>OCR, deterministic parsing and form geometry. No LLM, reference verification or semantic projection.</p></article>
      <div className="stage-arrow" aria-hidden="true">→</div>
      <article className="extraction-stage llm-stage"><span>2 · LLM routed-field accuracy</span><strong>{llmAccuracy == null ? "Not used" : percent(llmAccuracy)}</strong><b>{llmCorrect}/{llmAttempted} diverted fields correct</b><p>Accuracy only among fields sent to the crop-level LLM fallback—not across all {total} fields.</p></article>
      <div className="stage-arrow" aria-hidden="true">→</div>
      <article className="extraction-stage combined-stage"><span>3 · Final validated result</span><strong>{percent(report.normalized_field_accuracy)}</strong><b>{finalCorrect}/{total} fields correct</b><p>Governed final outcome after local extraction, selective fallback, approved references and semantic rules.</p></article>
    </div>
    <p className="denominator-note"><strong>How to read this:</strong> local accuracy uses all {total} evaluated fields. LLM accuracy uses only the {llmAttempted} diverted fields, so these percentages must not be added together. LLM diversion is {percent(report.llm_diversion_rate)}.</p>
  </section>;
}
