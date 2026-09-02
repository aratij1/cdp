import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, useRef } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

type TaskSummary = { 
  task_id: string; 
  claim_id: string; 
  field_name: string; 
  status: string;
  created_at: string; 
  version: number;
  priority?: "HIGH" | "MEDIUM" | "LOW";
  assigned_reviewer?: string;
  page_count?: number;
  filename?: string;
  confidence?: number;
  review_reason?: string;
};

type Evidence = { 
  engine?: string; 
  source?: string; 
  value?: string; 
  confidence?: number; 
  reason_code?: string; 
};

type TaskDetail = TaskSummary & { 
  document_id: string; 
  page_number: number; 
  crop_signed_url: string | null; 
  ocr_candidates: string[]; 
  vlm_candidate: string | null; 
  validation_errors: string[]; 
  review_reason_codes: string[]; 
  candidate_evidence: Evidence[]; 
  reference_evidence: Evidence[]; 
  system_recommendation: string | null; 
  evidence_versions: Record<string, string>;
  assigned_to: string | null;
  patient_name: string | null;
};

// Coordinate maps simulating a real CMS-1500 document coordinates layout (1000x1300 scale)
const CMS1500_COORDINATES: Record<string, { x: number; y: number; w: number; h: number; page: number }> = {
  patient_name: { x: 5, y: 15, w: 40, h: 5, page: 1 },
  patient_dob: { x: 50, y: 15, w: 20, h: 5, page: 1 },
  insured_id_number: { x: 75, y: 8, w: 20, h: 5, page: 1 },
  billing_provider_npi: { x: 5, y: 85, w: 40, h: 5, page: 1 },
  rendering_provider_npi: { x: 50, y: 85, w: 40, h: 5, page: 1 },
  total_charge: { x: 75, y: 78, w: 20, h: 5, page: 1 },
  date_of_service: { x: 5, y: 45, w: 20, h: 5, page: 2 },
  place_of_service: { x: 28, y: 45, w: 8, h: 5, page: 2 },
  diagnosis_code_1: { x: 5, y: 65, w: 30, h: 5, page: 2 },
  procedure_code_1: { x: 60, y: 45, w: 12, h: 5, page: 2 },
  provider_signature: { x: 75, y: 45, w: 20, h: 8, page: 3 }
};

const headers = { "X-User-Role": "reviewer" };
const schema = z.object({
  reviewer: z.string().email(),
  newValue: z.string().trim().min(1),
  reason: z.string().trim().min(3)
});
type Values = z.infer<typeof schema>;

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}

export function HitlInspector({ initialTaskId, onBackToQueue }: { initialTaskId?: string; onBackToQueue?: () => void }) {
  const cache = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | undefined>(initialTaskId);
  
  // Viewer Canvas State
  const [zoom, setZoom] = useState(100);
  const [rotation, setRotation] = useState(0);
  const [activePage, setActivePage] = useState(1);
  const [activeFieldKey, setActiveFieldKey] = useState<string>("patient_name");
  const [isEditing, setIsEditing] = useState(false);
  const [successToast, setSuccessToast] = useState<string | null>(null);
  const [claimError, setClaimError] = useState<string | null>(null);
  
  const canvasRef = useRef<HTMLDivElement>(null);

  // Read reviewer context and settings
  const form = useForm<Values>({
    defaultValues: {
      reviewer: "aarati.joshi@company.com", // Matches default Aarati Joshi profile footer
      newValue: "",
      reason: "Verified against visible source evidence"
    }
  });

  const reviewerEmail = form.watch("reviewer") || "aarati.joshi@company.com";
  const isLuhnEnabled = localStorage.getItem("idp_settings_luhn_validation") !== "false";

  // Queries
  const tasks = useQuery({ 
    queryKey: ["review-tasks"], 
    queryFn: () => getJson<TaskSummary[]>("/review-api/review-tasks") 
  });
  
  const detail = useQuery({ 
    queryKey: ["review-task", selectedId], 
    queryFn: async () => {
      try {
        return await getJson<TaskDetail>(`/review-api/review-tasks/${selectedId}`);
      } catch (err) {
        return null;
      }
    }, 
    enabled: Boolean(selectedId) 
  });

  const effectiveDocumentId = detail.data?.document_id || (selectedId && !selectedId.startsWith("CLM-") ? selectedId : undefined);

  const docResults = useQuery({
    queryKey: ["document-results", effectiveDocumentId],
    queryFn: () => getJson<{ document: any; fields: Array<{ field_name: string; value: string; normalized_value: string | null; confidence: number; page_number: number; validation_status: string; extraction_method: string }> }>(`/api/documents/${effectiveDocumentId}/results`),
    enabled: Boolean(effectiveDocumentId)
  });

  const getLiveValue = (fieldName: string, fallback: string = "") => {
    const f = docResults.data?.fields?.find((x: any) => x.field_name === fieldName);
    return f ? (f.normalized_value || f.value) : fallback;
  };

  // Locking Mutation (Priority 2 & 11)
  const claimMutation = useMutation({
    mutationFn: async ({ taskId, reviewer, version }: { taskId: string; reviewer: string; version: number }) => {
      const response = await fetch(`/review-api/review-tasks/${taskId}/claim`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer, expected_version: version })
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      return response.json();
    },
    onSuccess: () => {
      setClaimError(null);
      cache.invalidateQueries({ queryKey: ["review-task", selectedId] });
      cache.invalidateQueries({ queryKey: ["review-tasks"] });
    },
    onError: (err: any) => {
      setClaimError(err.message || "Failed to acquire lock. Another user may have claimed this task.");
    }
  });

  // Automatically update selected ID if initialized externally
  useEffect(() => {
    if (initialTaskId) {
      setSelectedId(initialTaskId);
    }
  }, [initialTaskId]);

  // Reset form and editing state when selected claim changes (prevents cross-claim data leakage)
  useEffect(() => {
    setIsEditing(false);
    setClaimError(null);
    form.reset({
      reviewer: reviewerEmail,
      newValue: "",
      reason: "ACCEPTED_SYSTEM_RECOMMENDATION"
    });
  }, [selectedId, reviewerEmail]);

  // Handle selected task detail updates & Trigger real-time lock claim
  useEffect(() => {
    if (detail.data) {
      const activeFieldName = detail.data.field_name;
      setActiveFieldKey(activeFieldName);
      setActivePage(detail.data.page_number || CMS1500_COORDINATES[activeFieldName]?.page || 1);
      const defaultOcr = (detail.data.ocr_candidates && detail.data.ocr_candidates.length > 0)
        ? detail.data.ocr_candidates[0]
        : "";
      form.setValue("newValue", detail.data.system_recommendation ?? detail.data.vlm_candidate ?? defaultOcr ?? "");
      
      // Call claim endpoint if not already assigned
      if (selectedId && !detail.data.assigned_to && detail.data.status === "OPEN") {
        claimMutation.mutate({ taskId: selectedId, reviewer: reviewerEmail, version: detail.data.version });
      }
    }
  }, [detail.data, selectedId]);

  // Submit corrections / rejections
  const mutation = useMutation({
    mutationFn: async ({ action, values, reason }: { action: "correct" | "reject"; values: Values; reason?: string }) => {
      if (!detail.data) throw new Error("No task selected");
      const body = action === "correct" 
        ? { new_value: values.newValue, reason: reason ?? values.reason, expected_version: detail.data.version } 
        : { reason: reason ?? values.reason, expected_version: detail.data.version };
      
      const response = await fetch(`/review-api/review-tasks/${detail.data.task_id}/${action}?reviewer=${encodeURIComponent(values.reviewer)}`, { 
        method: "POST", 
        headers: { ...headers, "Content-Type": "application/json" }, 
        body: JSON.stringify(body) 
      });
      if (!response.ok) {
        throw new Error(await response.text() || "Failed to submit correction to backend");
      }
      return response.json();
    },
    onSuccess: async () => {
      setSuccessToast(`Correction successfully applied and saved to audit ledger!`);
      setTimeout(() => setSuccessToast(null), 4000);
      setSelectedId(undefined);
      setIsEditing(false);
      await cache.invalidateQueries({ queryKey: ["review-tasks"] });
      if (onBackToQueue) {
        onBackToQueue();
      }
    },
  });

  // Guard against other reviewer locks
  const isLockedByOther = Boolean(
    detail.data?.assigned_to && 
    detail.data.assigned_to !== reviewerEmail
  );

  function submit(action: "accept" | "edit" | "reject" | "unable") {
    if (isLockedByOther) return; // Prevent action on other reviewer locks
    if (action === "edit") { 
      setIsEditing(true); 
      return; 
    }
    void form.handleSubmit((values) => 
      mutation.mutate({ 
        action: action === "accept" ? "correct" : "reject", 
        values, 
        reason: action === "accept" ? "ACCEPTED_SYSTEM_RECOMMENDATION" : action === "unable" ? "UNABLE_TO_DETERMINE" : undefined 
      })
    )();
  }

  // Keyboard Shortcuts Handler
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (!detail.data || isLockedByOther || event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      const key = event.key.toLowerCase();
      if (key === "a") { event.preventDefault(); submit("accept"); }
      if (key === "e") { event.preventDefault(); submit("edit"); }
      if (key === "r") { event.preventDefault(); submit("reject"); }
      if (key === "n") { event.preventDefault(); submit("unable"); }
      if (event.code === "Space") { 
        event.preventDefault(); 
        setZoom((z) => (z === 100 ? 150 : 100)); 
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  });

  const selected = detail.data;

  // Zoom / Navigation actions
  const handleZoomIn = () => setZoom((z) => Math.min(z + 25, 300));
  const handleZoomOut = () => setZoom((z) => Math.max(z - 25, 50));
  const handleRotate = () => setRotation((r) => (r + 90) % 360);
  const handleFitPage = () => { setZoom(100); setRotation(0); };

  // Two-way sync: Select coordinate bounding box from canvas clicks
  const handleCanvasClick = (fieldKey: string) => {
    setActiveFieldKey(fieldKey);
    const coord = CMS1500_COORDINATES[fieldKey];
    if (coord) {
      setActivePage(coord.page);
    }
  };

  // Luhn Algorithm Verification for NPI
  const checkLuhn = (val: string): boolean => {
    if (!/^\d{10}$/.test(val)) return false;
    let sum = 0;
    const digits = "80840" + val; // NPI prefix code helper
    for (let i = 0; i < digits.length; i++) {
      let d = parseInt(digits[i], 10);
      if (i % 2 === 0) {
        d *= 2;
        if (d > 9) d -= 9;
      }
      sum += d;
    }
    return sum % 10 === 0;
  };

  const isNpiValid = (fieldName: string, value: string) => {
    if (!isLuhnEnabled) return true; // Settings Toggle check (Priority 8)
    if (!fieldName.includes("npi")) return true;
    return checkLuhn(value);
  };

  // Render Row Card
  const renderFieldRow = (fieldKey: string, displayName: string, defaultVal: string, defaultConf: number) => {
    const isActive = activeFieldKey === fieldKey;
    const value = form.watch("newValue");
    const isNpi = fieldKey.includes("npi");
    const isValid = isNpi ? isNpiValid(fieldKey, isActive ? value : defaultVal) : true;

    return (
      <div 
        className={`field-row-card ${isActive ? "focused" : ""} ${!isValid ? "invalid" : ""}`}
        onClick={() => {
          setActiveFieldKey(fieldKey);
          const coord = CMS1500_COORDINATES[fieldKey];
          if (coord) {
            setActivePage(coord.page);
          }
        }}
        key={fieldKey}
        style={{
          background: !isValid ? "rgba(239, 68, 68, 0.12)" : isActive ? "var(--hover-bg)" : "var(--panel-bg)",
          border: !isValid ? "1px solid var(--danger)" : isActive ? "1px solid var(--cyan)" : "1px solid var(--line-color)",
          borderRadius: "10px",
          padding: "12px",
          marginBottom: "10px",
          cursor: isLockedByOther ? "not-allowed" : "pointer",
          opacity: isLockedByOther ? 0.65 : 1,
          transition: "all 0.15s ease"
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "var(--text-secondary)", fontWeight: "600" }}>
            <span>{displayName}</span>
            <span className={`badge ${defaultConf >= 90 ? "complete" : "warning"}`} style={{ padding: "2px 6px" }}>{defaultConf}%</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <strong style={{ color: "var(--text-primary)", fontSize: "14px" }}>
              {isActive ? value || "(blank)" : defaultVal}
            </strong>
            {isNpi && !isValid && <span style={{ color: "var(--danger-bright)", fontSize: "10px", fontWeight: "700" }}>⚠ Luhn check fail</span>}
            {isNpi && isValid && <span style={{ color: "var(--cyan)", fontSize: "10px", fontWeight: "700" }}>✓ Luhn check passed</span>}
          </div>
          {isActive && !isLockedByOther && (
            <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginTop: "8px" }} onClick={(e) => e.stopPropagation()}>
              <input 
                className="field-input-box"
                autoFocus 
                value={value} 
                onChange={(e) => form.setValue("newValue", e.target.value)}
                placeholder="Enter corrected value"
                style={{
                  width: "100%",
                  padding: "8px",
                  borderRadius: "6px",
                  border: "1px solid var(--line-color)",
                  background: "var(--input-bg)",
                  color: "var(--text-primary)"
                }}
              />
              <div style={{ display: "flex", gap: "6px" }}>
                <button 
                  className="primary-button" 
                  style={{ flex: 1, padding: "6px 12px", fontSize: "12px" }}
                  onClick={() => submit("accept")}
                >
                  Accept [A]
                </button>
                <button 
                  className="primary-button" 
                  style={{ flex: 1, padding: "6px 12px", fontSize: "12px", background: "var(--button-bg)" }}
                  onClick={() => submit("reject")}
                >
                  Reject [R]
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  };

  // Loading & Error Panel States (Priority 11)
  if (selectedId && detail.isLoading) {
    return (
      <div style={{ display: "grid", placeItems: "center", padding: "80px", color: "var(--text-secondary)", background: "var(--panel-bg)", borderRadius: "12px" }}>
        <div style={{ fontSize: "14px", fontWeight: "700", animation: "pulse 1.5s infinite" }}>🔄 Fetching Claims Task Metadata & Claiming Lock...</div>
      </div>
    );
  }

  if (selectedId && detail.isError) {
    return (
      <div className="panel" style={{ padding: "40px", textAlign: "center", border: "1px solid var(--danger)", background: "rgba(239, 68, 68, 0.08)" }}>
        <h3 style={{ color: "var(--danger-bright)" }}>⚠️ Failed to Retrieve Task Detail</h3>
        <p style={{ color: "var(--text-secondary)", marginTop: "8px" }}>{detail.error instanceof Error ? detail.error.message : "Internal Review API Error"}</p>
        <button className="primary-button" style={{ marginTop: "15px" }} onClick={() => detail.refetch()}>Retry Connection</button>
      </div>
    );
  }

  if (!selectedId) {
    return (
      <div style={{ display: "grid", placeItems: "center", padding: "80px", color: "var(--text-secondary)", background: "var(--panel-bg)", borderRadius: "12px" }}>
        <h3>No Task Active</h3>
        <p style={{ color: "var(--text-tertiary)", marginTop: "6px" }}>Please select a task with status "Needs Review" from the Ingestion Work Queue.</p>
        {onBackToQueue && (
          <button className="primary-button" style={{ marginTop: "15px" }} onClick={onBackToQueue}>Go to Work Queue</button>
        )}
      </div>
    );
  }

  return (
    <section className="hitl-layout" style={{ display: "grid", gridTemplateColumns: "1fr 450px", gap: "20px" }}>
      {successToast && (
        <div style={{
          position: "fixed",
          top: "20px",
          right: "20px",
          background: "var(--cyan)",
          color: "#fff",
          padding: "12px 24px",
          borderRadius: "8px",
          zIndex: 9999,
          fontWeight: "700",
          boxShadow: "0 10px 25px rgba(0,0,0,0.3)"
        }}>
          {successToast}
        </div>
      )}
      
      {/* LEFT COLUMN: DOCUMENT VIEWER */}
      <section className="panel document-viewer-panel" style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: "680px" }}>
        <div className="panel-heading" style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid var(--line-color)", paddingBottom: "12px", marginBottom: "15px" }}>
          <div>
            <p className="eyebrow" style={{ margin: 0 }}>Interactive Viewer</p>
            <h2 style={{ margin: "4px 0" }}>Document Viewer: CMS-1500</h2>
            <small style={{ color: "var(--text-tertiary)" }}>Claim ID: <code>{selected?.claim_id || "Awaiting task..."}</code> · Page {activePage} of 3</small>
          </div>
          
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            {/* Real Lock State display (Priority 2) */}
            {selected && (
              <span className="badge" style={{ 
                background: isLockedByOther ? "rgba(239, 68, 68, 0.15)" : "rgba(16, 185, 129, 0.15)", 
                color: isLockedByOther ? "var(--danger-bright)" : "var(--good-bright)", 
                fontWeight: "700", 
                display: "flex", 
                gap: "6px", 
                alignItems: "center" 
              }}>
                {isLockedByOther 
                  ? `🔒 Locked by ${selected.assigned_to}` 
                  : "✓ Lock Claimed by You"}
              </span>
            )}
          </div>
        </div>

        {claimError && (
          <div style={{ background: "rgba(239, 68, 68, 0.15)", border: "1px solid var(--danger)", color: "var(--danger-bright)", padding: "10px", borderRadius: "8px", marginBottom: "15px", fontSize: "12px" }}>
            ⚠️ Lock Status Error: {claimError}
          </div>
        )}

        <div className="canvas-wrapper-container" style={{ flex: 1, display: "flex", flexDirection: "column", background: "var(--card-bg-2)", borderRadius: "12px", padding: "12px", position: "relative" }}>
          {/* Controls toolbar */}
          <div className="canvas-toolbar" style={{ display: "flex", gap: "8px", justifyContent: "center", marginBottom: "12px" }}>
            <button className="toolbar-btn" onClick={handleZoomOut} style={{ padding: "4px 10px", borderRadius: "6px", border: "1px solid var(--line-color)", background: "var(--button-bg)", color: "var(--text-primary)", cursor: "pointer" }}>-</button>
            <span style={{ minWidth: "50px", textAlign: "center", alignSelf: "center", fontSize: "12px", color: "var(--text-secondary)" }}>{zoom}%</span>
            <button className="toolbar-btn" onClick={handleZoomIn} style={{ padding: "4px 10px", borderRadius: "6px", border: "1px solid var(--line-color)", background: "var(--button-bg)", color: "var(--text-primary)", cursor: "pointer" }}>+</button>
            <button className="toolbar-btn" onClick={handleRotate} style={{ padding: "4px 10px", borderRadius: "6px", border: "1px solid var(--line-color)", background: "var(--button-bg)", color: "var(--text-primary)", cursor: "pointer" }}>Rotate</button>
            <button className="toolbar-btn" onClick={handleFitPage} style={{ padding: "4px 10px", borderRadius: "6px", border: "1px solid var(--line-color)", background: "var(--button-bg)", color: "var(--text-primary)", cursor: "pointer" }}>Reset</button>
          </div>

          {/* Interactive Document Area */}
          <div className="document-container-body" style={{ flex: 1, overflow: "auto", position: "relative", minHeight: "450px", border: "1px solid var(--line-color)", borderRadius: "8px", background: "var(--input-bg)", display: "grid", placeItems: "center" }}>
            <div 
              className="canvas-image-layer"
              style={{
                transform: `scale(${zoom / 100}) rotate(${rotation}deg)`,
                transformOrigin: "center center",
                transition: "transform 0.15s ease",
                position: "relative",
                width: "100%",
                height: "100%",
                maxWidth: "600px",
                aspectRatio: "1/1.3",
                background: "var(--card-bg-1)",
                border: "1px solid var(--line-color)",
                borderRadius: "4px",
                boxShadow: "0 10px 30px rgba(0,0,0,0.15)"
              }}
            >
              {selected?.crop_signed_url ? (
                <div style={{ position: "relative", width: "100%", height: "100%", display: "grid", placeItems: "center" }}>
                  <img 
                    src={selected.crop_signed_url} 
                    alt="Active Claim Field Crop" 
                    className="source-document-img"
                    style={{ maxWidth: "90%", maxHeight: "90%", border: "2px dashed var(--cyan)" }}
                  />
                  <div style={{ position: "absolute", bottom: "10px", left: "10px", fontSize: "10px", background: "rgba(0,0,0,0.6)", padding: "4px 8px", borderRadius: "4px", color: "#fff" }}>
                    Showing isolated high-res crop
                  </div>
                </div>
              ) : (
                <div style={{ width: "100%", height: "100%", position: "relative", padding: "20px", color: "var(--text-secondary)", fontSize: "11px" }}>
                  {/* Simulated Claim Document Background */}
                  <div style={{ borderBottom: "2px solid var(--line-color)", paddingBottom: "10px", marginBottom: "15px", fontWeight: "700", textAlign: "center" }}>
                    HEALTH INSURANCE CLAIM FORM (CMS-1500)
                  </div>
                  
                  <div style={{ border: "1px solid var(--line-color)", padding: "10px", borderRadius: "6px", marginBottom: "10px", background: "var(--bg-deep)" }}>
                    <span style={{ fontSize: "9px", textTransform: "uppercase" }}>1a. Insured ID Number</span>
                    <div style={{ fontSize: "13px", fontWeight: "700", color: "var(--text-primary)" }}>{getLiveValue("insured_id_number") || getLiveValue("insured_id") || "—"}</div>
                  </div>

                  <div style={{ border: "1px solid var(--line-color)", padding: "10px", borderRadius: "6px", marginBottom: "10px", background: "var(--bg-deep)" }}>
                    <span style={{ fontSize: "9px", textTransform: "uppercase" }}>2. Patient Full Name</span>
                    <div style={{ fontSize: "13px", fontWeight: "700", color: "var(--text-primary)" }}>
                      {getLiveValue("patient_name") || 
                       (getLiveValue("patient_last") ? `${getLiveValue("patient_last")}${getLiveValue("patient_first") ? ", " + getLiveValue("patient_first") : ""}` : "") || 
                       detail.data?.patient_name || 
                       docResults.data?.document?.patient_name || 
                       "—"}
                    </div>
                  </div>

                  <div style={{ border: "1px solid var(--line-color)", padding: "10px", borderRadius: "6px", marginBottom: "10px", background: "var(--bg-deep)" }}>
                    <span style={{ fontSize: "9px", textTransform: "uppercase" }}>33a. Billing Provider NPI</span>
                    <div style={{ fontSize: "13px", fontWeight: "700", color: "var(--text-primary)" }}>{getLiveValue("billing_provider_npi") || getLiveValue("provider_npi") || getLiveValue("rendering_provider_npi") || "—"}</div>
                  </div>

                  <div style={{ border: "1px solid var(--line-color)", padding: "10px", borderRadius: "6px", background: "var(--bg-deep)" }}>
                    <span style={{ fontSize: "9px", textTransform: "uppercase" }}>28. Total Claim Charge</span>
                    <div style={{ fontSize: "13px", fontWeight: "700", color: "var(--text-primary)" }}>{getLiveValue("total_charge") || getLiveValue("total_charges") || getLiveValue("claim_charge_amount") || "—"}</div>
                  </div>

                  {/* Dynamic Bounding Box coordinate rectangles */}
                  {Object.entries(CMS1500_COORDINATES).map(([key, value]) => {
                    if (value.page !== activePage) return null;
                    const isActive = activeFieldKey === key;
                    return (
                      <div 
                        key={key}
                        className={`dynamic-bounding-box ${isActive ? "active" : ""}`}
                        style={{
                          position: "absolute",
                          left: `${value.x}%`,
                          top: `${value.y}%`,
                          width: `${value.w}%`,
                          height: `${value.h}%`,
                          border: isActive ? "2px solid #60a5fa" : "1px solid var(--cyan)",
                          background: isActive ? "rgba(96, 165, 250, 0.2)" : "rgba(20, 184, 166, 0.08)",
                          cursor: isLockedByOther ? "not-allowed" : "pointer",
                          borderRadius: "3px",
                          boxShadow: isActive ? "0 0 10px rgba(96, 165, 250, 0.5)" : "none",
                          transition: "all 0.15s ease"
                        }}
                        onClick={() => !isLockedByOther && handleCanvasClick(key)}
                        title={`Field Coordinate: ${key}`}
                      />
                    );
                  })}
                </div>
              )}
            </div>
          </div>
          
          {/* Page index selectors */}
          <div style={{ display: "flex", gap: "6px", justifyContent: "center", marginTop: "12px" }}>
            <button className="primary-button" style={{ fontSize: "11px", padding: "6px 12px", background: activePage === 1 ? "var(--cyan)" : "var(--button-bg)" }} onClick={() => setActivePage(1)}>Page 1</button>
            <button className="primary-button" style={{ fontSize: "11px", padding: "6px 12px", background: activePage === 2 ? "var(--cyan)" : "var(--button-bg)" }} onClick={() => setActivePage(2)}>Page 2</button>
            <button className="primary-button" style={{ fontSize: "11px", padding: "6px 12px", background: activePage === 3 ? "var(--cyan)" : "var(--button-bg)" }} onClick={() => setActivePage(3)}>Page 3</button>
          </div>
        </div>
      </section>

      {/* RIGHT COLUMN: EXTRACTION & REVIEW */}
      <section className="panel extraction-fields-panel" style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: "680px" }}>
        <div className="panel-heading" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid var(--line-color)", paddingBottom: "12px", marginBottom: "15px" }}>
          <div>
            <p className="eyebrow" style={{ margin: 0 }}>Review Column</p>
            <h2 style={{ margin: "4px 0" }}>Claim Extracted Fields</h2>
            <small style={{ color: "var(--text-tertiary)" }}>Auditing active fields inside labeled sample</small>
          </div>
        </div>

        {/* Mutation Submission Warnings (Priority 11) */}
        {mutation.isError && (
          <div style={{ background: "rgba(239, 68, 68, 0.15)", border: "1px solid var(--danger)", color: "var(--danger-bright)", padding: "10px", borderRadius: "8px", marginBottom: "15px", fontSize: "12px" }}>
            ⚠️ Submission Failed: {mutation.error instanceof Error ? mutation.error.message : "Error writing changes back to pipeline."}
          </div>
        )}

        <div className="fields-scroll-container" style={{ flex: 1, overflowY: "auto", paddingRight: "5px", marginBottom: "15px" }}>
          {docResults.data?.fields && docResults.data.fields.length > 0 ? (
            <div>
              <h3 style={{ fontSize: "12px", color: "var(--cyan)", textTransform: "uppercase", letterSpacing: "0.05em", borderBottom: "1px solid var(--line-color)", paddingBottom: "6px", marginBottom: "10px" }}>
                Extracted Claim Fields ({docResults.data.fields.length})
              </h3>
              {docResults.data.fields.map((f, idx) => 
                renderFieldRow(
                  f.field_name,
                  `${f.field_name.replaceAll("_", " ")} (Page ${f.page_number})`,
                  (f.normalized_value || f.value) || "(blank)",
                  Math.round((f.confidence || 0.7) * 100)
                )
              )}
            </div>
          ) : selected ? (
            <div>
              <h3 style={{ fontSize: "12px", color: "var(--cyan)", textTransform: "uppercase", letterSpacing: "0.05em", borderBottom: "1px solid var(--line-color)", paddingBottom: "6px", marginBottom: "10px" }}>
                Active Task: {selected.field_name?.replaceAll("_", " ")}
              </h3>
              {renderFieldRow(
                selected.field_name,
                selected.field_name?.replaceAll("_", " ") || "Field",
                selected.system_recommendation || selected.ocr_candidates?.[0] || "(blank)",
                Math.round((selected.confidence || 0.74) * 100)
              )}
              {selected.ocr_candidates && selected.ocr_candidates.length > 1 && (
                <div style={{ marginTop: "10px", padding: "8px", background: "var(--hover-bg)", borderRadius: "6px" }}>
                  <span style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Alternative OCR Candidates:</span>
                  <ul style={{ margin: "4px 0 0 16px", padding: 0, fontSize: "12px", color: "var(--text-primary)" }}>
                    {selected.ocr_candidates.slice(1).map((c, i) => <li key={i}>{c}</li>)}
                  </ul>
                </div>
              )}
            </div>
          ) : null}
        </div>

        {/* Global actions and shortcuts */}
        <div style={{ borderTop: "1px solid var(--line-color)", paddingTop: "12px", display: "flex", flexDirection: "column", gap: "10px" }}>
          <div style={{ display: "flex", gap: "10px" }}>
            {onBackToQueue && (
              <button className="primary-button" style={{ flex: 1, background: "var(--button-bg)", color: "var(--text-primary)" }} onClick={onBackToQueue}>
                Back to Queue
              </button>
            )}
            <button 
              className="primary-button" 
              style={{ flex: 1, cursor: isLockedByOther ? "not-allowed" : "pointer", opacity: isLockedByOther ? 0.65 : 1 }} 
              onClick={() => submit("accept")}
              disabled={isLockedByOther || mutation.isPending}
            >
              {mutation.isPending ? "Submitting..." : "Submit & Complete ✓"}
            </button>
          </div>
          
          <div style={{ padding: "10px", background: "var(--hover-bg)", borderRadius: "8px", fontSize: "10px", color: "var(--text-tertiary)", textAlign: "center" }}>
            {isLockedByOther 
              ? "🔒 This document is locked by another reviewer. Editing is disabled."
              : "Hotkeys: A Accept · E Edit · R Reject · N Unable · Space Zoom"}
          </div>
        </div>
      </section>
    </section>
  );
}
