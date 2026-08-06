import type { ReactNode } from "react";
import { percent } from "./report";
import type { EvaluationReport } from "./types";

export function MetricCard({
  label,
  value,
  tone = "default",
  hint,
}: {
  label: string;
  value: string;
  tone?: "default" | "good" | "danger";
  hint?: string;
}) {
  return (
    <article className={`metric-card ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </article>
  );
}

export function AccuracyBars({
  title,
  values,
}: {
  title: string;
  values: Record<string, number>;
}) {
  const entries = Object.entries(values).sort((a, b) => a[1] - b[1]);
  return (
    <section className="panel bars-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Accuracy breakdown</p>
          <h2>{title}</h2>
        </div>
        <span className="count">{entries.length} groups</span>
      </div>
      {entries.length === 0 ? (
        <Empty>No grouped results in this report.</Empty>
      ) : (
        <div className="bars">
          {entries.map(([label, value]) => (
            <div className="bar-row" key={label}>
              <span title={label}>{label.replaceAll("_", " ")}</span>
              <div className="bar-track">
                <div
                  className={value < 0.98 ? "bar-fill warning" : "bar-fill"}
                  style={{ width: `${Math.max(value * 100, 1)}%` }}
                />
              </div>
              <strong>{percent(value)}</strong>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

const groupLabels: Record<string, string> = {
  CMS1500: "CMS-1500 professional claim",
  attachment: "Claim attachment",
  UB04: "UB-04 institutional claim",
  laboratory_invoice: "Laboratory invoice",
};

export function GroupAccuracy({ report }: { report: EvaluationReport }) {
  const evidence = report.field_evidence ?? [];
  const groups = evidence.reduce<Record<string, { fields: number; correct: number; documents: Set<string>; opencvCorrect: number; paddleocrCorrect: number; pyserrectCorrect: number; florenceCorrect: number; hitlCorrect: number; localCorrect: number }>>(
    (result, row) => {
      const group = result[row.form_type] ?? { fields: 0, correct: 0, opencvCorrect: 0, paddleocrCorrect: 0, pyserrectCorrect: 0, florenceCorrect: 0, hitlCorrect: 0, localCorrect: 0, documents: new Set<string>() };
      group.fields += 1;
      
      if (row.correct) {
        group.correct += 1;
        const method = (row.extraction_method || "").toLowerCase();
        if (method.includes('hitl') || method.includes('human')) {
          group.hitlCorrect += 1;
        } else {
          group.localCorrect += 1;
          if (method.includes('florence') || method.includes('vision') || method.includes('vlm')) {
            group.florenceCorrect += 1;
          } else if (method.includes('paddleocr')) {
            group.paddleocrCorrect += 1;
          } else if (method.includes('tesseract')) {
            group.pyserrectCorrect += 1;
          } else {
            group.opencvCorrect += 1;
          }
        }
      }
      
      group.documents.add(row.document_id);
      result[row.form_type] = group;
      return result;
    },
    {},
  );
  const rows = Object.entries(groups).map(([key, value]) => ({
    key,
    localAccuracy: value.fields ? value.correct / value.fields : 0,
    localCorrect: value.localCorrect,
    opencvCorrect: value.opencvCorrect,
    paddleocrCorrect: value.paddleocrCorrect,
    pyserrectCorrect: value.pyserrectCorrect,
    florenceCorrect: value.florenceCorrect,
    hitlCorrect: value.hitlCorrect,
    totalCorrect: value.correct,
    fields: value.fields,
    documents: value.documents.size,
    finalIncorrect: report.mismatches.filter((row) => row.form_type === key).length,
  }));
  const fallbackRows = Object.entries(report.accuracy_by_form_type ?? {})
    .filter(([key]) => key !== "all_document_families")
    .map(([key, accuracy]) => ({ key, localAccuracy: accuracy, localCorrect: null, opencvCorrect: null, paddleocrCorrect: null, pyserrectCorrect: null, florenceCorrect: null, hitlCorrect: null, totalCorrect: null, fields: null, documents: null, finalIncorrect: null }));
  const displayedRows = (rows.length ? rows : fallbackRows).sort((a, b) => a.localAccuracy - b.localAccuracy);

  return (
    <section className="panel group-accuracy">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Accuracy by document group</p>
          <h2>Group-wise accuracy</h2>
          <p className="group-accuracy-note">Local extraction is shown before governed resolution. Final accuracy includes approved references and review closure for this labelled sample only.</p>
        </div>
        <span className="count">{displayedRows.length} groups</span>
      </div>
      {displayedRows.length === 0 ? <Empty>No group-level results in this report.</Empty> : (
        <div className="table-scroll"><table>
          <thead><tr><th>Document group</th><th>Documents</th><th>Evaluated fields</th><th>OpenCV</th><th>PaddleOCR</th><th>PySerrect</th><th>Florence</th><th>Total local</th><th>HITL correct</th><th>Total correct</th><th>Exceptions caught</th><th>Final mismatches</th><th>Local accuracy</th><th>Final governed accuracy</th></tr></thead>
          <tbody>{displayedRows.map((row) => <tr key={row.key}>
            <td><strong>{groupLabels[row.key] ?? row.key.replaceAll("_", " ")}</strong><small>{row.key}</small></td>
            <td>{row.documents ?? "Not reported"}</td>
            <td>{row.fields ?? "Not reported"}</td>
            <td>{row.opencvCorrect ?? "0"}</td>
            <td>{row.paddleocrCorrect ?? "0"}</td>
            <td>{row.pyserrectCorrect ?? "0"}</td>
            <td>{row.florenceCorrect ?? "0"}</td>
            <td>{row.localCorrect ?? "0"}</td>
            <td>{row.hitlCorrect ?? "0"}</td>
            <td>{row.totalCorrect ?? "Not reported"}</td>
            <td>{row.fields != null && row.totalCorrect != null && row.finalIncorrect != null ? row.fields - row.totalCorrect - row.finalIncorrect : "0"}</td>
            <td>{row.finalIncorrect ?? "0"}</td>
            <td><strong className={row.localAccuracy < .98 ? "accuracy-warning" : "accuracy-good"}>{percent(row.localAccuracy)}</strong></td>
            <td><strong className="accuracy-good">{row.fields == null || row.finalIncorrect == null ? "Not reported" : percent((row.fields - row.finalIncorrect) / row.fields)}</strong></td>
          </tr>)}</tbody>
        </table></div>
      )}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
