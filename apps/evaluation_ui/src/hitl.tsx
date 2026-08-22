import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

type TaskSummary = { task_id: string; claim_id: string; field_name: string; created_at: string; version: number };
type Evidence = { engine?: string; source?: string; value?: string; confidence?: number; reason_code?: string };
type TaskDetail = TaskSummary & { document_id: string; page_number: number; crop_signed_url: string | null; ocr_candidates: string[]; vlm_candidate: string | null; validation_errors: string[]; review_reason_codes: string[]; candidate_evidence: Evidence[]; reference_evidence: Evidence[]; registration_evidence: Record<string, unknown>; system_recommendation: string | null; evidence_versions: Record<string, string> };
const headers = { "X-User-Role": "reviewer" };
const schema = z.object({ reviewer: z.string().email(), newValue: z.string().trim().min(1), reason: z.string().trim().min(3) });
type Values = z.infer<typeof schema>;

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}

export function HitlInspector() {
  const cache = useQueryClient();
  const [selectedId, setSelectedId] = useState<string>();
  const [zoomed, setZoomed] = useState(false);
  const [editing, setEditing] = useState(false);
  const tasks = useQuery({ queryKey: ["review-tasks"], queryFn: () => getJson<TaskSummary[]>("/review-api/review-tasks") });
  const detail = useQuery({ queryKey: ["review-task", selectedId], queryFn: () => getJson<TaskDetail>(`/review-api/review-tasks/${selectedId}`), enabled: Boolean(selectedId) });
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { reviewer: "reviewer@company.com", newValue: "", reason: "Verified against visible source evidence" } });
  useEffect(() => {
    if (detail.data) form.setValue("newValue", detail.data.system_recommendation ?? detail.data.vlm_candidate ?? detail.data.ocr_candidates[0] ?? "");
  }, [detail.data, form]);

  const mutation = useMutation({
    mutationFn: async ({ action, values, reason }: { action: "correct" | "reject"; values: Values; reason?: string }) => {
      if (!detail.data) throw new Error("No task selected");
      const body = action === "correct" ? { new_value: values.newValue, reason: reason ?? values.reason, expected_version: detail.data.version } : { reason: reason ?? values.reason, expected_version: detail.data.version };
      const response = await fetch(`/review-api/review-tasks/${detail.data.task_id}/${action}?reviewer=${encodeURIComponent(values.reviewer)}`, { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!response.ok) throw new Error(await response.text());
    },
    onSuccess: async () => { setSelectedId(undefined); setEditing(false); setZoomed(false); await cache.invalidateQueries({ queryKey: ["review-tasks"] }); },
  });

  function submit(action: "accept" | "edit" | "reject" | "unable") {
    if (action === "edit") { setEditing(true); return; }
    void form.handleSubmit((values) => mutation.mutate({ action: action === "accept" ? "correct" : "reject", values, reason: action === "accept" ? "ACCEPTED_SYSTEM_RECOMMENDATION" : action === "unable" ? "UNABLE_TO_DETERMINE" : undefined }))();
  }
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (!detail.data || event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      const action = ({ a: "accept", e: "edit", r: "reject", n: "unable" } as const)[event.key.toLowerCase()];
      if (action) { event.preventDefault(); submit(action); }
      if (event.code === "Space") { event.preventDefault(); setZoomed((value) => !value); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  });

  const selected = detail.data;
  return <section className="hitl-layout"><aside className="panel hitl-queue"><div className="panel-heading"><div><p className="eyebrow">Open queue</p><h2>Field reviews</h2></div><span className="count">{tasks.data?.length ?? 0}</span></div>{tasks.isError && <p className="error-banner">{String(tasks.error)}</p>}{(tasks.data ?? []).map((task) => <button className={selectedId === task.task_id ? "hitl-task active" : "hitl-task"} key={task.task_id} onClick={() => setSelectedId(task.task_id)}><strong>{task.field_name.replaceAll("_", " ")}</strong><small>{task.claim_id.slice(0, 8)} · {new Date(task.created_at).toLocaleString()}</small></button>)}</aside>
    <section className="panel hitl-inspector"><div className="panel-heading"><div><p className="eyebrow">Human decision</p><h2>Evidence inspector</h2></div></div>{!selected ? <div className="empty">Select a field to inspect its evidence.</div> : <>
      <div className="hitl-evidence">{selected.crop_signed_url ? <button className="crop-zoom" onClick={() => setZoomed(!zoomed)} aria-label="Toggle crop zoom"><img style={{ transform: zoomed ? "scale(2)" : "scale(1)" }} src={selected.crop_signed_url} alt={`Crop for ${selected.field_name}`} /></button> : <div className="empty">Crop unavailable</div>}<div><span>Field</span><strong>{selected.field_name}</strong><span>Review reason</span><strong>{selected.review_reason_codes.join(", ") || "Unspecified"}</strong><span>Recommendation</span><strong>{selected.system_recommendation ?? "Abstain"}</strong><span>Validation</span><strong>{selected.validation_errors.join(", ") || "Passed"}</strong></div></div>
      <div className="hitl-evidence-grid"><div><h3>OCR candidates</h3>{selected.candidate_evidence.length ? selected.candidate_evidence.map((item, i) => <p key={i}><b>{item.engine ?? item.source}</b>: {item.value ?? "—"} {item.confidence == null ? "" : `(${Math.round(item.confidence * 100)}%)`}</p>) : <p>{selected.ocr_candidates.join(" | ") || "None"}</p>}</div><div><h3>Reference evidence</h3>{selected.reference_evidence.length ? selected.reference_evidence.map((item, i) => <p key={i}><b>{item.source}</b>: {item.value ?? item.reason_code}</p>) : <p>None</p>}</div><div><h3>Registration</h3><p>{JSON.stringify(selected.registration_evidence)}</p></div><div><h3>Versions</h3>{Object.entries(selected.evidence_versions).map(([key, value]) => <p key={key}><b>{key}</b>: {value}</p>)}</div></div>
      <form className="hitl-form" onSubmit={(event) => event.preventDefault()}><label>Reviewer<input {...form.register("reviewer")} /></label><label>Final value<input autoFocus={editing} readOnly={!editing} {...form.register("newValue")} /></label><label>Reason<textarea {...form.register("reason")} /></label>{Object.values(form.formState.errors).map((error, i) => <p className="error-banner" key={i}>{error?.message}</p>)}<div><button onClick={() => submit("accept")}>Accept [A]</button><button onClick={() => submit("edit")}>Edit [E]</button><button onClick={() => submit("reject")}>Reject [R]</button><button onClick={() => submit("unable")}>Unable [N]</button></div><small>Space toggles crop zoom. Decisions are field-scoped, validated, versioned, and audited.</small></form>{mutation.isError && <p className="error-banner">{String(mutation.error)}</p>}</>}</section></section>;
}
