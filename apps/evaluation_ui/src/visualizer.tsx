import { useState } from "react";

interface FieldStage {
  title: string;
  status: "completed" | "failed" | "skipped" | "active";
  method: string;
  value: string;
  confidence: number;
  cropText?: string;
  error?: string;
}

interface FieldData {
  id: string;
  name: string;
  label: string;
  criticality: "CRITICAL" | "NON_CRITICAL";
  requiredThreshold: number;
  pageNumber: number;
  bbox: { x: number; y: number; w: number; h: number };
  stages: {
    s1_opencv: FieldStage;
    s2_ocr: FieldStage;
    s3_retry: FieldStage;
    s4_vlm: FieldStage;
    s5_hitl: FieldStage;
  };
  whyEscalated: string;
  cost: string;
  latency: string;
}

interface PageData {
  pageNumber: number;
  title: string;
  classification: string;
  fields: FieldData[];
}

const MULTI_PAGE_CLAIM: PageData[] = [
  {
    pageNumber: 1,
    title: "Page 1: CMS-1500 Primary Claim Form",
    classification: "CMS1500_FORM",
    fields: [
      {
        id: "patient_name",
        name: "patient_name",
        label: "Patient Full Name",
        criticality: "CRITICAL",
        requiredThreshold: 0.90,
        pageNumber: 1,
        bbox: { x: 55, y: 350, w: 570, h: 70 },
        stages: {
          s1_opencv: { title: "1. OpenCV Alignment & Deskew", status: "completed", method: "Anchor Match", value: "Aligned", confidence: 0.98, cropText: "DOE, J0HN" },
          s2_ocr: { title: "2. Regional PaddleOCR", status: "failed", method: "PaddleOCR", value: "DOE, J0HN", confidence: 0.78, error: "Confidence 0.78 < 0.90 Critical Threshold", cropText: "DOE, J0HN" },
          s3_retry: { title: "3. Preprocessing Retry", status: "failed", method: "Sharpening", value: "DOE, J0HN", confidence: 0.81, error: "Confidence 0.81 < 0.90 Critical Threshold", cropText: "DOE, J0HN" },
          s4_vlm: { title: "4. Compact VLM / LLM", status: "completed", method: "Qwen2.5-VL-3B", value: "DOE, JOHN", confidence: 0.98, cropText: "DOE, JOHN" },
          s5_hitl: { title: "5. Human-In-The-Loop", status: "completed", method: "VLM Confirmed", value: "DOE, JOHN", confidence: 0.98 }
        },
        whyEscalated: "Why LLM was required: Standard OCR misidentified letter 'O' as digit '0', lowering confidence to 0.78 (< 0.90 critical threshold). Compact Vision-Language Model examined the crop with language context and correctly extracted 'DOE, JOHN' at 0.98 confidence.",
        cost: "$0.0022",
        latency: "680ms"
      },
      {
        id: "npi",
        name: "rendering_provider_npi",
        label: "Rendering Provider NPI",
        criticality: "CRITICAL",
        requiredThreshold: 0.92,
        pageNumber: 1,
        bbox: { x: 55, y: 1980, w: 465, h: 60 },
        stages: {
          s1_opencv: { title: "1. OpenCV Alignment", status: "completed", method: "ORB Homography", value: "Grid Aligned", confidence: 0.99, cropText: "1234567890" },
          s2_ocr: { title: "2. Regional PaddleOCR", status: "failed", method: "PaddleOCR", value: "1234567890", confidence: 0.88, error: "Failed Luhn NPI Checksum", cropText: "1234567890" },
          s3_retry: { title: "3. Preprocessing Retry", status: "completed", method: "Contrast Boost", value: "1234567893", confidence: 0.96, cropText: "1234567893" },
          s4_vlm: { title: "4. Compact VLM / LLM", status: "skipped", method: "N/A", value: "N/A", confidence: 1.0 },
          s5_hitl: { title: "5. Human-In-The-Loop", status: "completed", method: "Auto-Validated", value: "1234567893", confidence: 0.96 }
        },
        whyEscalated: "OCR read digit '0' instead of '3' at position 10. The deterministic NPI Luhn checksum rule immediately flagged the value as INVALID, triggering a targeted crop retry (Stage 3) which corrected the character without invoking the expensive LLM.",
        cost: "$0.0001",
        latency: "142ms"
      }
    ]
  },
  {
    pageNumber: 2,
    title: "Page 2: Itemized Service Line Attachment",
    classification: "ATTACHMENT_ITEMIZED_STATEMENT",
    fields: [
      {
        id: "cpt_code",
        name: "service_line[1].cpt",
        label: "Line 1 CPT Code",
        criticality: "CRITICAL",
        requiredThreshold: 0.90,
        pageNumber: 2,
        bbox: { x: 320, y: 450, w: 220, h: 55 },
        stages: {
          s1_opencv: { title: "1. OpenCV Alignment", status: "completed", method: "Table Cell Grid", value: "Box Extracted", confidence: 0.99, cropText: "99214" },
          s2_ocr: { title: "2. Regional PaddleOCR", status: "completed", method: "PaddleOCR", value: "99214", confidence: 0.97, cropText: "99214" },
          s3_retry: { title: "3. Preprocessing Retry", status: "skipped", method: "N/A", value: "99214", confidence: 0.97 },
          s4_vlm: { title: "4. Compact VLM / LLM", status: "skipped", method: "N/A", value: "99214", confidence: 0.97 },
          s5_hitl: { title: "5. Human-In-The-Loop", status: "completed", method: "Auto-Validated", value: "99214", confidence: 0.97 }
        },
        whyEscalated: "Extracted cleanly with high confidence (97% > 90% threshold). Validated against CPT dictionary.",
        cost: "$0.0000",
        latency: "28ms"
      }
    ]
  },
  {
    pageNumber: 3,
    title: "Page 3: Clinical Notes & Provider Signature",
    classification: "CLINICAL_NOTES",
    fields: [
      {
        id: "provider_signature",
        name: "provider_signature",
        label: "Attending Provider Signature",
        criticality: "CRITICAL",
        requiredThreshold: 0.92,
        pageNumber: 3,
        bbox: { x: 1100, y: 1200, w: 550, h: 80 },
        stages: {
          s1_opencv: { title: "1. OpenCV Alignment", status: "completed", method: "Bounding Box", value: "Box Extracted", confidence: 0.99, cropText: "[Cursive Script]" },
          s2_ocr: { title: "2. Regional PaddleOCR", status: "failed", method: "PaddleOCR", value: "J. S... MD", confidence: 0.35, error: "Handwriting OCR failure", cropText: "[Cursive Script]" },
          s3_retry: { title: "3. Preprocessing Retry", status: "failed", method: "TrOCR Adapter", value: "Dr. John Smith", confidence: 0.68, error: "Confidence 0.68 < 0.92", cropText: "[Cursive Script]" },
          s4_vlm: { title: "4. Compact VLM / LLM", status: "failed", method: "Qwen2.5-VL-3B", value: "Dr. John Smith, MD", confidence: 0.74, error: "Confidence 0.74 < 0.92", cropText: "[Cursive Script]" },
          s5_hitl: { title: "5. Human-In-The-Loop", status: "active", method: "HUMAN REVIEW REQUIRED", value: "Awaiting Reviewer Action", confidence: 0.0 }
        },
        whyEscalated: "Why HITL is Required: Cursive handwriting on a critical provider identity field caused printed OCR, TrOCR, and Vision-LLM all to score below the 0.92 confidence threshold. Per platform fail-closed security policy, unresolved critical fields MUST be reviewed by an authorized human operator before claim finalization.",
        cost: "$0.1522",
        latency: "1450ms"
      }
    ]
  }
];

export function FieldTransformationVisualizer() {
  const [currentPageIdx, setCurrentPageIdx] = useState(0);
  const [selectedField, setSelectedField] = useState<FieldData>(MULTI_PAGE_CLAIM[0].fields[0]);
  const [currentStageIdx, setCurrentStageIdx] = useState(0);
  const [zoom, setZoom] = useState(1.0);

  const currentPage = MULTI_PAGE_CLAIM[currentPageIdx];
  const stagesList = [
    selectedField.stages.s1_opencv,
    selectedField.stages.s2_ocr,
    selectedField.stages.s3_retry,
    selectedField.stages.s4_vlm,
    selectedField.stages.s5_hitl,
  ];

  return (
    <section className="flow-view" style={{ gap: "1.25rem" }}>
      {/* Page Tabs */}
      <div style={{ display: "flex", gap: "0.75rem", overflowX: "auto", paddingBottom: "0.5rem" }}>
        {MULTI_PAGE_CLAIM.map((page, idx) => (
          <button
            key={page.pageNumber}
            className={`primary-button ${currentPageIdx === idx ? "active" : ""}`}
            style={{
              background: currentPageIdx === idx ? "rgba(14, 116, 144, 0.3)" : "rgba(30, 41, 59, 0.4)",
              borderColor: currentPageIdx === idx ? "#06b6d4" : "rgba(255, 255, 255, 0.1)",
              color: "#f8fafc",
              padding: "0.5rem 1rem",
              borderRadius: "8px",
              cursor: "pointer"
            }}
            onClick={() => {
              setCurrentPageIdx(idx);
              if (page.fields.length > 0) setSelectedField(page.fields[0]);
              setCurrentStageIdx(0);
            }}
          >
            {page.title} ({page.classification})
          </button>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "300px 1fr 340px", gap: "1.25rem", minHeight: "560px" }}>
        {/* Left: Field List */}
        <div style={{ background: "rgba(15, 23, 42, 0.75)", padding: "1rem", borderRadius: "14px", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
          <h3 style={{ fontSize: "0.9rem", color: "#94a3b8", marginBottom: "0.85rem", textTransform: "uppercase" }}>
            Page {currentPage.pageNumber} Fields
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
            {currentPage.fields.map((f) => (
              <div
                key={f.id}
                onClick={() => { setSelectedField(f); setCurrentStageIdx(0); }}
                style={{
                  padding: "0.75rem",
                  borderRadius: "10px",
                  background: selectedField.id === f.id ? "rgba(14, 116, 144, 0.25)" : "rgba(30, 41, 59, 0.4)",
                  border: selectedField.id === f.id ? "1px solid #06b6d4" : "1px solid rgba(255, 255, 255, 0.08)",
                  cursor: "pointer"
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.3rem" }}>
                  <strong style={{ fontSize: "0.85rem", color: "#f8fafc" }}>{f.label}</strong>
                  <span style={{ fontSize: "0.65rem", padding: "0.15rem 0.4rem", borderRadius: "4px", background: f.criticality === "CRITICAL" ? "rgba(244, 63, 94, 0.2)" : "rgba(148, 163, 184, 0.2)", color: f.criticality === "CRITICAL" ? "#f43f5e" : "#94a3b8" }}>
                    {f.criticality}
                  </span>
                </div>
                <div style={{ fontFamily: "monospace", fontSize: "0.8rem", color: "#06b6d4" }}>{f.stages.s5_hitl.value}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Center: Canvas & 5-Stage Stepper */}
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <div style={{ position: "relative", background: "#090e17", borderRadius: "14px", border: "1px solid rgba(255, 255, 255, 0.08)", padding: "1rem", overflow: "auto", display: "flex", justifyContent: "center", maxHeight: "420px" }}>
            <div style={{ position: "absolute", top: "0.85rem", right: "1rem", zIndex: 10, display: "flex", gap: "0.4rem" }}>
              <button style={{ padding: "0.2rem 0.6rem", background: "rgba(30, 41, 59, 0.8)", border: "1px solid rgba(255, 255, 255, 0.1)", color: "#fff", borderRadius: "4px", cursor: "pointer" }} onClick={() => setZoom(Math.min(zoom + 0.2, 2.0))}>+</button>
              <button style={{ padding: "0.2rem 0.6rem", background: "rgba(30, 41, 59, 0.8)", border: "1px solid rgba(255, 255, 255, 0.1)", color: "#fff", borderRadius: "4px", cursor: "pointer" }} onClick={() => setZoom(Math.max(zoom - 0.2, 0.6))}>-</button>
              <button style={{ padding: "0.2rem 0.6rem", background: "rgba(30, 41, 59, 0.8)", border: "1px solid rgba(255, 255, 255, 0.1)", color: "#fff", borderRadius: "4px", cursor: "pointer" }} onClick={() => setZoom(1.0)}>Fit</button>
            </div>

            <div style={{ transform: `scale(${zoom})`, transformOrigin: "top center", transition: "transform 0.2s ease" }}>
              <svg viewBox="0 0 1712 2214" width="480" height="620" style={{ background: "#ffffff", borderRadius: "4px" }}>
                <rect x="0" y="0" width="1712" height="2214" fill="#f8fafc" />
                <rect x="50" y="50" width="1612" height="100" fill="#e2e8f0" rx="4" />
                <text x="80" y="110" fontFamily="sans-serif" fontSize="32" fontWeight="bold" fill="#0f172a">{currentPage.title}</text>
                
                <rect x="50" y="180" width="1612" height="250" fill="#f1f5f9" stroke="#cbd5e1" strokeWidth="2" />
                <text x="70" y="320" fontFamily="sans-serif" fontSize="22" fontWeight="bold" fill="#334155">2. PATIENT'S NAME</text>
                <text x="80" y="380" fontFamily="sans-serif" fontSize="32" fontWeight="bold" fill="#0284c7">DOE, JOHN</text>
                
                {/* Bounding Box */}
                {selectedField.pageNumber === currentPage.pageNumber && (
                  <rect
                    x={selectedField.bbox.x}
                    y={selectedField.bbox.y}
                    width={selectedField.bbox.w}
                    height={selectedField.bbox.h}
                    fill="rgba(244, 63, 94, 0.25)"
                    stroke="#f43f5e"
                    strokeWidth="4"
                    rx="3"
                  />
                )}
              </svg>
            </div>
          </div>

          {/* Stepper */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "0.5rem" }}>
            {stagesList.map((s, idx) => (
              <div
                key={s.title}
                onClick={() => setCurrentStageIdx(idx)}
                style={{
                  padding: "0.6rem",
                  borderRadius: "10px",
                  background: currentStageIdx === idx ? "rgba(6, 182, 212, 0.15)" : "rgba(15, 23, 42, 0.6)",
                  border: currentStageIdx === idx ? "1px solid #06b6d4" : "1px solid rgba(255, 255, 255, 0.08)",
                  cursor: "pointer"
                }}
              >
                <div style={{ fontSize: "0.6rem", color: "#64748b", fontWeight: 800 }}>STAGE {idx + 1}</div>
                <div style={{ fontSize: "0.75rem", fontWeight: 700, marginBottom: "0.3rem" }}>{s.title.split(" ")[1] || s.title}</div>
                <div style={{ fontFamily: "monospace", fontSize: "0.7rem", color: "#06b6d4", background: "#020617", padding: "0.2rem", borderRadius: "4px", textAlign: "center" }}>
                  {s.cropText || s.value}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right: Diagnostic Panel */}
        <div style={{ background: "rgba(15, 23, 42, 0.75)", padding: "1rem", borderRadius: "14px", border: "1px solid rgba(255, 255, 255, 0.08)", display: "flex", flexDirection: "column", gap: "0.85rem" }}>
          <h3 style={{ fontSize: "0.9rem", color: "#94a3b8", textTransform: "uppercase" }}>Governance Diagnostic</h3>
          <div style={{ padding: "0.85rem", borderRadius: "10px", background: "rgba(30, 41, 59, 0.5)", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
            <strong style={{ fontSize: "0.82rem", color: "#f8fafc" }}>{selectedField.label} — Stage {currentStageIdx + 1}</strong>
            <p style={{ fontSize: "0.8rem", color: "#94a3b8", marginTop: "0.4rem", lineHeight: "1.4" }}>
              {selectedField.whyEscalated}
            </p>
          </div>

          <div style={{ fontSize: "0.8rem", fontWeight: 700, color: "#94a3b8" }}>COST & LATENCY LADDER</div>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
            {[
              ["1. OpenCV Alignment", "$0.0000", "8ms"],
              ["2. Regional PaddleOCR", "$0.0001", "35ms"],
              ["3. Preprocessing Retry", "$0.0002", "65ms"],
              ["4. Vision-LLM (Qwen2.5)", "$0.0022", "420ms"],
              ["5. HITL Operator Review", "$0.1500", "45000ms"],
            ].map(([name, cost, time], idx) => (
              <div key={name} style={{ display: "flex", justifyContent: "space-between", padding: "0.45rem 0.75rem", borderRadius: "6px", background: currentStageIdx === idx ? "rgba(6, 182, 212, 0.15)" : "rgba(15, 23, 42, 0.4)", border: currentStageIdx === idx ? "1px solid #06b6d4" : "1px solid rgba(255, 255, 255, 0.08)", fontSize: "0.75rem" }}>
                <span>{name}</span>
                <span style={{ fontFamily: "monospace", color: "#10b981", fontWeight: 700 }}>{cost} ({time})</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
