import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

type ApiDocument = { document_id: string; status: string; detected_format: string; page_count: number; source_filename: string; is_new_document: boolean };
type ApiField = { field_name: string; value: string; normalized_value: string | null; confidence: number; page_number: number; extraction_method: string; validation_status: string; validation_reasons: string[] };
type ApiResult = { document: ApiDocument; fields: ApiField[]; field_count: number; processing_complete: boolean };
type Phase = "READY" | "UPLOADING" | "PROCESSING" | "COMPLETE" | "FAILED";
type UploadJob = { key: string; file: File; previewUrl: string | null; phase: Phase; progress: number; result?: ApiResult; error?: string };

const terminal = new Set(["FAILED", "QUARANTINED", "NEEDS_REVIEW", "COMPLETED", "OUTPUT_GENERATED"]);
const wait = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

async function apiError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return String(body.detail ?? `Request failed (${response.status})`);
  } catch {
    return `Request failed (${response.status})`;
  }
}

export function ProcessingWorkspace() {
  const [jobs, setJobs] = useState<UploadJob[]>([]);
  const [dragging, setDragging] = useState(false);
  const active = jobs.some((job) => job.phase === "UPLOADING" || job.phase === "PROCESSING");
  const completed = useMemo(() => jobs.filter((job) => job.phase === "COMPLETE").length, [jobs]);

  function addFiles(files: FileList | File[]) {
    const accepted = Array.from(files).filter((file) =>
      ["image/png", "image/jpeg", "image/tiff", "application/pdf"].includes(file.type) || /\.(png|jpe?g|tiff?|pdf|\d+)$/i.test(file.name));
    setJobs((current) => [...current, ...accepted.map((file) => ({
      key: `${file.name}-${file.size}-${file.lastModified}-${crypto.randomUUID()}`,
      file,
      previewUrl: file.type.startsWith("image/") ? URL.createObjectURL(file) : null,
      phase: "READY" as const,
      progress: 0,
    }))]);
  }

  function patch(key: string, values: Partial<UploadJob>) {
    setJobs((current) => current.map((job) => job.key === key ? { ...job, ...values } : job));
  }

  const queryClient = useQueryClient();

  async function processJob(job: UploadJob) {
    patch(job.key, { phase: "UPLOADING", progress: 12, error: undefined });
    const form = new FormData();
    form.append("file", job.file);
    const uploaded = await fetch("/api/documents?tenant_id=prototype-ui", { method: "POST", body: form });
    if (!uploaded.ok) throw new Error(await apiError(uploaded));
    const document = await uploaded.json() as ApiDocument;
    patch(job.key, { phase: "PROCESSING", progress: 28, result: { document, fields: [], field_count: 0, processing_complete: false } });

    // Cold CPU workers may need several minutes to initialize OCR models.
    for (let attempt = 0; attempt < 300; attempt += 1) {
      await wait(2000);
      const response = await fetch(`/api/documents/${document.document_id}/results`, { cache: "no-store" });
      if (!response.ok) throw new Error(await apiError(response));
      const result = await response.json() as ApiResult;
      patch(job.key, { phase: "PROCESSING", progress: Math.min(92, 35 + attempt * 2 + (result.document.page_count ? 15 : 0)), result });
      if (result.processing_complete || terminal.has(result.document.status)) {
        if (["FAILED", "QUARANTINED"].includes(result.document.status)) throw new Error(`Pipeline stopped with status ${result.document.status}`);
        patch(job.key, { phase: "COMPLETE", progress: 100, result });
        queryClient.invalidateQueries({ queryKey: ["review-tasks"] });
        return;
      }
    }
    throw new Error("Processing did not finish within ten minutes. The document remains available by ID.");
  }

  async function processAll() {
    for (const job of jobs.filter((item) => item.phase === "READY" || item.phase === "FAILED")) {
      try {
        await processJob(job);
      } catch (reason) {
        patch(job.key, { phase: "FAILED", error: reason instanceof Error ? reason.message : "Processing failed" });
      }
    }
  }

  function clear() {
    jobs.forEach((job) => job.previewUrl && URL.revokeObjectURL(job.previewUrl));
    setJobs([]);
  }

  function download(job: UploadJob) {
    if (!job.result) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(job.result, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${job.file.name.replace(/\.[^.]+$/, "")}-extraction.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return <section className="processing-workspace">
    <style dangerouslySetInnerHTML={{ __html: `
      .processing-workspace {
        margin-top: 30px;
        border-top: 1px solid var(--line-color);
        padding-top: 30px;
      }
      .process-intro {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 20px;
      }
      .process-summary {
        text-align: right;
        background-color: var(--card-bg);
        border: 1px solid var(--line-color);
        padding: 8px 16px;
        border-radius: 8px;
        display: inline-flex;
        flex-direction: column;
        align-items: center;
      }
      .process-summary strong {
        font-size: 18px;
        color: var(--cyan);
      }
      .process-summary span {
        font-size: 9px;
        color: var(--text-secondary);
        text-transform: uppercase;
        font-weight: 700;
        letter-spacing: 0.05em;
      }
      .upload-dropzone {
        border: 2px dashed rgba(20, 184, 166, 0.35);
        background-color: var(--card-bg);
        border-radius: 12px;
        padding: 40px 20px;
        text-align: center;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 12px;
        cursor: pointer;
        transition: all 0.2s ease;
        margin-bottom: 24px;
        margin-top: 15px;
      }
      .upload-dropzone.dragging {
        border-color: var(--cyan);
        background-color: var(--hover-bg);
      }
      .upload-icon {
        font-size: 32px;
        color: var(--cyan);
        margin-bottom: 4px;
        line-height: 1;
      }
      .upload-dropzone h3 {
        font-size: 16px;
        font-weight: 700;
        color: var(--text-primary);
        margin: 0;
      }
      .upload-dropzone p {
        font-size: 12px;
        color: var(--text-secondary);
        margin: 0;
      }
      .upload-file-label {
        position: relative;
        cursor: pointer;
        display: inline-block;
      }
      .upload-file-label input[type="file"] {
        position: absolute;
        width: 0;
        height: 0;
        opacity: 0;
        overflow: hidden;
      }
      .process-toolbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background-color: var(--card-bg);
        border: 1px solid var(--line-color);
        padding: 12px 20px;
        border-radius: 8px;
        margin-bottom: 20px;
        font-size: 13px;
      }
      .process-toolbar button {
        background: transparent;
        border: 0;
        color: var(--text-secondary);
        cursor: pointer;
        font-weight: 600;
        margin-right: 15px;
      }
      .process-toolbar button:hover:not(:disabled) {
        color: var(--cyan);
      }
      .upload-jobs {
        display: grid;
        gap: 16px;
      }
      .upload-job {
        background-color: var(--card-bg);
        border: 1px solid var(--line-color);
        border-radius: 8px;
        padding: 16px;
        display: grid;
        grid-template-columns: 80px 1fr;
        gap: 16px;
      }
      .upload-preview {
        width: 80px;
        height: 80px;
        border-radius: 6px;
        background-color: var(--input-bg);
        display: grid;
        place-items: center;
        overflow: hidden;
        border: 1px solid var(--line-color);
        font-size: 11px;
        font-weight: 700;
        color: var(--text-secondary);
      }
      .upload-preview img {
        width: 100%;
        height: 100%;
        object-fit: cover;
      }
      .job-content {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .job-heading {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
      }
      .job-heading h3 {
        font-size: 14px;
        font-weight: 700;
        color: var(--text-primary);
        margin: 0;
      }
      .job-heading p {
        font-size: 11px;
        color: var(--text-secondary);
        margin: 0;
      }
      .job-status {
        font-size: 10px;
        font-weight: 700;
        text-transform: uppercase;
        padding: 2px 6px;
        border-radius: 4px;
      }
      .job-status.ready { background-color: rgba(148,163,184,0.15); color: var(--text-secondary); }
      .job-status.uploading { background-color: rgba(59,130,246,0.15); color: var(--blue-bright); }
      .job-status.processing { background-color: rgba(245,158,11,0.15); color: var(--warning-bright); }
      .job-status.complete { background-color: rgba(16,185,129,0.15); color: var(--good-bright); }
      .job-status.failed { background-color: rgba(239,68,68,0.15); color: var(--danger-bright); }
      .progress-track {
        height: 6px;
        background-color: var(--input-bg);
        border-radius: 3px;
        overflow: hidden;
      }
      .progress-track i {
        display: block;
        height: 100%;
        background: linear-gradient(90deg, var(--cyan), var(--cyan-bright));
        border-radius: 3px;
        transition: width 0.3s ease;
      }
      .job-meta {
        display: flex;
        flex-wrap: wrap;
        gap: 15px;
        font-size: 11px;
        color: var(--text-secondary);
      }
      .job-meta code {
        background-color: var(--input-bg);
        padding: 1px 4px;
        border-radius: 3px;
        color: var(--text-primary);
      }
      .job-error {
        font-size: 12px;
        color: var(--danger-bright);
        margin: 4px 0 0 0;
      }
      .job-results {
        border-top: 1px solid var(--line-color);
        padding-top: 12px;
        margin-top: 4px;
      }
      .job-results-heading {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
      }
      .job-results-heading h4 {
        font-size: 12px;
        font-weight: 700;
        color: var(--text-primary);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin: 0;
      }
      .job-results-heading button {
        background: transparent;
        border: 0;
        color: var(--cyan);
        font-size: 11px;
        font-weight: 700;
        cursor: pointer;
      }
      .job-results-heading button:hover {
        color: var(--cyan-bright);
        text-decoration: underline;
      }
    ` }} />
    <div className="process-intro">
      <div><p className="eyebrow">Live prototype</p><h2>Upload and process claims</h2><p>PNG, JPEG, TIFF or PDF. Files enter the real asynchronous preparation, routing and regional OCR pipeline.</p></div>
      <div className="process-summary"><strong>{completed}/{jobs.length}</strong><span>completed</span></div>
    </div>
    <div className={`upload-dropzone ${dragging ? "dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); addFiles(event.dataTransfer.files); }}>
      <div className="upload-icon">↑</div><h3>Drop claim images here</h3><p>Multiple files supported. Maximum size follows the ingestion policy.</p><label className="primary-button upload-file-label">Choose files<input multiple type="file" onChange={(event) => { if (event.target.files) addFiles(event.target.files); event.target.value = ""; }} /></label>
    </div>
    {jobs.length > 0 && <div className="process-toolbar"><span>{jobs.length} document{jobs.length === 1 ? "" : "s"} queued</span><div><button onClick={clear}>Clear</button><button className="primary-button" disabled={active || jobs.every((job) => job.phase === "COMPLETE")} onClick={processAll}>{active ? "Processing…" : "Process documents"}</button></div></div>}
    <div className="upload-jobs">{jobs.map((job) => <article className="upload-job" key={job.key}>
      <div className="upload-preview">{job.previewUrl ? <img src={job.previewUrl} alt={`Preview of ${job.file.name}`} /> : <span>PDF</span>}</div>
      <div className="job-content"><div className="job-heading"><div><h3>{job.file.name}</h3><p>{(job.file.size / 1024 / 1024).toFixed(2)} MB · {job.result?.document.detected_format ?? job.file.type}</p></div><span className={`job-status ${job.phase.toLowerCase()}`}>{job.phase}</span></div>
        <div className="progress-track"><i style={{ width: `${job.progress}%` }} /></div>
        {job.result && <div className="job-meta"><span>Document ID <code>{job.result.document.document_id}</code></span><span>Pipeline <strong>{job.result.document.status}</strong></span><span>Pages <strong>{job.result.document.page_count}</strong></span><span>Fields <strong>{job.result.field_count}</strong></span></div>}
        {job.error && <p className="job-error">{job.error}</p>}
        {job.result?.fields.length ? <div className="job-results"><div className="job-results-heading"><h4>Extracted fields</h4><button onClick={() => download(job)}>Download JSON</button></div><div className="table-scroll"><table><thead><tr><th>Field</th><th>Value</th><th>Confidence</th><th>Page</th><th>Validation</th><th>Method</th></tr></thead><tbody>{job.result.fields.map((field, index) => <tr key={`${field.field_name}-${field.page_number}-${index}`}><td><strong>{field.field_name.replaceAll("_", " ")}</strong></td><td>{(field.normalized_value ?? field.value) || "—"}</td><td>{(field.confidence * 100).toFixed(1)}%</td><td>{field.page_number}</td><td><span className={`badge ${field.validation_status.toLowerCase()}`}>{field.validation_status}</span></td><td>{field.extraction_method}</td></tr>)}</tbody></table></div></div> : null}
      </div>
    </article>)}</div>
  </section>;
}
