// High-End Multi-Bundle & Multi-Field Transformation Engine with Interactive HITL Review

const DOCUMENTS = {
  cms1500_multi: {
    id: "cms1500_multi",
    name: "1. CMS-1500 3-Page Professional Claim Bundle (Primary + Itemized + EOB)",
    pages: [
      {
        pageNumber: 1,
        title: "Page 1: CMS-1500 Primary Claim Form",
        classification: "CMS1500_FORM",
        qualityScore: 0.98,
        fields: [
          {
            id: "total_charge",
            name: "total_charge",
            label: "Total Claim Charge Amount (Box 28)",
            criticality: "CRITICAL",
            requiredThreshold: 0.80,
            pageNumber: 1,
            bbox: { x: 1150, y: 1810, w: 480, h: 80 },
            stages: {
              s1_opencv: { title: "1. OpenCV", status: "completed", method: "Grid Profile", value: "Box Extracted", confidence: 0.99, cropText: "$ 175.OO" },
              s2_ocr: { title: "2. Regional", status: "failed", method: "PaddleOCR", value: "$ 175.OO", confidence: 0.72, error: "Non-numeric characters 'OO' in currency", cropText: "$ 175.OO" },
              s3_retry: { title: "3. Retry", status: "completed", method: "Regex Repair", value: "$175.00", confidence: 0.96, cropText: "$175.00" },
              s4_vlm: { title: "4. Compact", status: "skipped", method: "N/A", value: "N/A", confidence: 1.0 },
              s5_hitl: { title: "5. Human Review", status: "completed", method: "Auto-Validated", value: "$175.00", confidence: 0.96 }
            },
            whyEscalated: "OCR initially read zeroes as uppercase letters 'OO'. Deterministic normalization converted 'OO' to '00.00' and verified $175.00 matched service line items at 96% confidence (>= 80% threshold). Auto-validated without HITL.",
            cost: "$0.0001",
            latency: "110ms"
          },
          {
            id: "patient_name",
            name: "patient_name",
            label: "Patient Full Name (Box 2)",
            criticality: "CRITICAL",
            requiredThreshold: 0.80,
            pageNumber: 1,
            bbox: { x: 50, y: 310, w: 600, h: 90 },
            stages: {
              s1_opencv: { title: "1. OpenCV", status: "completed", method: "Anchor Match", value: "Aligned", confidence: 0.98, cropText: "DOE, J0HN" },
              s2_ocr: { title: "2. Regional", status: "failed", method: "PaddleOCR", value: "DOE, J0HN", confidence: 0.78, error: "Confidence 0.78 < 0.80 Threshold", cropText: "DOE, J0HN" },
              s3_retry: { title: "3. Retry", status: "failed", method: "Sharpening", value: "DOE, J0HN", confidence: 0.79, error: "Confidence 0.79 < 0.80 Threshold", cropText: "DOE, J0HN" },
              s4_vlm: { title: "4. Compact", status: "completed", method: "Qwen2.5-VL", value: "DOE, JOHN", confidence: 0.98, cropText: "DOE, JOHN" },
              s5_hitl: { title: "5. Human Review", status: "completed", method: "VLM Auto-Validated", value: "DOE, JOHN", confidence: 0.98 }
            },
            whyEscalated: "OCR initially misidentified letter 'O' as digit '0', lowering confidence to 0.78 (< 0.80 threshold). Compact Vision-Language Model examined the crop with language context and extracted 'DOE, JOHN' at 0.98 confidence (>= 0.80 threshold). Auto-validated without HITL escalation.",
            cost: "$0.0022",
            latency: "680ms"
          },
          {
            id: "insured_id_number",
            name: "insured_id_number",
            label: "Insured ID Number (Box 1a)",
            criticality: "CRITICAL",
            requiredThreshold: 0.80,
            pageNumber: 1,
            bbox: { x: 980, y: 210, w: 650, h: 70 },
            stages: {
              s1_opencv: { title: "1. OpenCV", status: "completed", method: "Grid Profile", value: "Box Extracted", confidence: 0.99, cropText: "XYZ987654321" },
              s2_ocr: { title: "2. Regional", status: "completed", method: "PaddleOCR", value: "XYZ987654321", confidence: 0.96, cropText: "XYZ987654321" },
              s3_retry: { title: "3. Retry", status: "skipped", method: "N/A", value: "XYZ987654321", confidence: 0.96 },
              s4_vlm: { title: "4. Compact", status: "skipped", method: "N/A", value: "XYZ987654321", confidence: 0.96 },
              s5_hitl: { title: "5. Human Review", status: "completed", method: "Auto-Validated", value: "XYZ987654321", confidence: 0.96 }
            },
            whyEscalated: "Extracted cleanly with high confidence (96% >= 80% threshold). Auto-validated without HITL.",
            cost: "$0.0001",
            latency: "32ms"
          },
          {
            id: "federal_tax_id",
            name: "federal_tax_id",
            label: "Federal Tax ID (Box 25)",
            criticality: "CRITICAL",
            requiredThreshold: 0.80,
            pageNumber: 1,
            bbox: { x: 50, y: 1810, w: 550, h: 80 },
            stages: {
              s1_opencv: { title: "1. OpenCV", status: "completed", method: "Grid Profile", value: "Box Extracted", confidence: 0.99, cropText: "12-3456789" },
              s2_ocr: { title: "2. Regional", status: "completed", method: "PaddleOCR", value: "12-3456789", confidence: 0.97, cropText: "12-3456789" },
              s3_retry: { title: "3. Retry", status: "skipped", method: "N/A", value: "12-3456789", confidence: 0.97 },
              s4_vlm: { title: "4. Compact", status: "skipped", method: "N/A", value: "12-3456789", confidence: 0.97 },
              s5_hitl: { title: "5. Human Review", status: "completed", method: "Auto-Validated", value: "12-3456789", confidence: 0.97 }
            },
            whyEscalated: "Passed 9-digit EIN syntax validation at 97% confidence (>= 80% threshold). Auto-validated.",
            cost: "$0.0001",
            latency: "28ms"
          },
          {
            id: "npi",
            name: "rendering_provider_npi",
            label: "Rendering Provider NPI (Box 33a)",
            criticality: "CRITICAL",
            requiredThreshold: 0.80,
            pageNumber: 1,
            bbox: { x: 50, y: 1950, w: 550, h: 80 },
            stages: {
              s1_opencv: { title: "1. OpenCV", status: "completed", method: "ORB Homography", value: "Grid Aligned", confidence: 0.99, cropText: "1234567890" },
              s2_ocr: { title: "2. Regional", status: "failed", method: "PaddleOCR", value: "1234567890", confidence: 0.78, error: "Failed Luhn Checksum (mod 10 fail)", cropText: "1234567890" },
              s3_retry: { title: "3. Retry", status: "completed", method: "Binarize", value: "1234567893", confidence: 0.96, cropText: "1234567893" },
              s4_vlm: { title: "4. Compact", status: "skipped", method: "Qwen2.5-VL", value: "N/A (Resolved Stage 3)", confidence: 1.0 },
              s5_hitl: { title: "5. Human Review", status: "completed", method: "Auto-Validated", value: "1234567893", confidence: 0.96 }
            },
            whyEscalated: "Initial OCR read digit '0' instead of '3' at position 10. The deterministic NPI Luhn checksum rule flagged the value, triggering a targeted crop retry (Stage 3) which corrected the character to 1234567893 at 96% confidence (>= 80% threshold). Auto-validated without HITL.",
            cost: "$0.0001",
            latency: "142ms"
          }
        ]
      },
      {
        pageNumber: 2,
        title: "Page 2: Itemized Service Line Attachment",
        classification: "ATTACHMENT_ITEMIZED_STATEMENT",
        qualityScore: 0.95,
        fields: [
          {
            id: "line1_cpt",
            name: "service_line[1].cpt",
            label: "Line 1 CPT Code (Box 24D)",
            criticality: "CRITICAL",
            requiredThreshold: 0.80,
            pageNumber: 2,
            bbox: { x: 900, y: 1150, w: 150, h: 70 },
            stages: {
              s1_opencv: { title: "1. OpenCV", status: "completed", method: "Table Cell Grid", value: "Cell Box", confidence: 0.99, cropText: "99214" },
              s2_ocr: { title: "2. Regional", status: "completed", method: "PaddleOCR", value: "99214", confidence: 0.97, cropText: "99214" },
              s3_retry: { title: "3. Retry", status: "skipped", method: "N/A", value: "99214", confidence: 0.97 },
              s4_vlm: { title: "4. Compact", status: "skipped", method: "N/A", value: "99214", confidence: 0.97 },
              s5_hitl: { title: "5. Human Review", status: "completed", method: "Auto-Validated", value: "99214", confidence: 0.97 }
            },
            whyEscalated: "Standard PaddleOCR extracted '99214' with high confidence (97% >= 80% required). Auto-validated.",
            cost: "$0.0000",
            latency: "28ms"
          }
        ]
      },
      {
        pageNumber: 3,
        title: "Page 3: Clinical Notes & Provider Signature",
        classification: "CLINICAL_NOTES",
        qualityScore: 0.91,
        fields: [
          {
            id: "provider_signature",
            name: "provider_signature",
            label: "Attending Provider Signature (Box 31)",
            criticality: "CRITICAL",
            requiredThreshold: 0.80,
            pageNumber: 3,
            bbox: { x: 1050, y: 1150, w: 600, h: 100 },
            stages: {
              s1_opencv: { title: "1. OpenCV", status: "completed", method: "Bounding Box", value: "Box Extracted", confidence: 0.99, cropText: "[Cursive Script]" },
              s2_ocr: { title: "2. Regional", status: "failed", method: "PaddleOCR", value: "J. S... MD", confidence: 0.35, error: "Handwriting OCR failure", cropText: "[Cursive Script]" },
              s3_retry: { title: "3. Retry", status: "failed", method: "TrOCR Adapter", value: "Dr. John Smith", confidence: 0.68, error: "Confidence 0.68 < 0.80 Threshold", cropText: "[Cursive Script]" },
              s4_vlm: { title: "4. Compact", status: "failed", method: "Qwen2.5-VL", value: "Dr. John Smith, MD", confidence: 0.74, error: "Confidence 0.74 < 0.80 Threshold", cropText: "[Cursive Script]" },
              s5_hitl: { title: "5. Human Review", status: "active", method: "HUMAN REVIEW REQUIRED", value: "Awaiting Reviewer Action", confidence: 0.0 }
            },
            whyEscalated: "Requires Human Review: Cursive handwriting confidence (0.74) is below the 0.80 threshold. Use the interactive HITL review box below to approve or correct the value.",
            cost: "$0.1522",
            latency: "1450ms"
          }
        ]
      }
    ]
  }
};

let state = {
  doc: DOCUMENTS.cms1500_multi,
  currentPageIdx: 0,
  currentField: DOCUMENTS.cms1500_multi.pages[0].fields[0],
  currentStageIdx: 0,
  zoomLevel: 1.0
};

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  renderDocSelectorOptions();
  renderPageTabBar();
  renderFieldList();
  renderCanvas();
  renderPipeline();
  renderDiagnostics();
  renderCostLadder();
  setupEventListeners();
});

function initTheme() {
  const savedTheme = localStorage.getItem('theme');
  if (savedTheme === 'light') {
    document.body.classList.add('light-theme');
  }
}

function toggleTheme() {
  document.body.classList.toggle('light-theme');
  const isLight = document.body.classList.contains('light-theme');
  localStorage.setItem('theme', isLight ? 'light' : 'dark');
}

function renderDocSelectorOptions() {
  const sel = document.getElementById("doc-selector");
  if (!sel) return;
  sel.innerHTML = Object.values(DOCUMENTS).map(d => `
    <option value="${d.id}" ${d.id === state.doc.id ? 'selected' : ''}>${d.name}</option>
  `).join("");
}

function changeDocument(docId) {
  if (DOCUMENTS[docId]) {
    state.doc = DOCUMENTS[docId];
    state.currentPageIdx = 0;
    state.currentField = state.doc.pages[0].fields[0];
    state.currentStageIdx = 0;
    renderPageTabBar();
    renderFieldList();
    renderCanvas();
    renderPipeline();
    renderDiagnostics();
    renderCostLadder();
  }
}

function selectPage(pageIdx) {
  state.currentPageIdx = pageIdx;
  const page = state.doc.pages[pageIdx];
  if (page && page.fields.length > 0) {
    state.currentField = page.fields[0];
  }
  state.currentStageIdx = 0;
  
  renderPageTabBar();
  renderFieldList();
  renderCanvas();
  renderPipeline();
  renderDiagnostics();
  renderCostLadder();
}

function selectField(fieldId) {
  let foundField = null;
  state.doc.pages.forEach(p => {
    const f = p.fields.find(field => field.id === fieldId);
    if (f) foundField = f;
  });
  
  if (foundField) {
    state.currentField = foundField;
    state.currentStageIdx = 0;
    renderFieldList();
    updateBBoxOverlay();
    renderPipeline();
    renderDiagnostics();
    renderCostLadder();
  }
}

function renderPageTabBar() {
  const container = document.getElementById("page-tab-bar");
  if (!container) return;
  container.innerHTML = state.doc.pages.map((p, idx) => `
    <div class="page-tab ${idx === state.currentPageIdx ? 'active' : ''}" onclick="selectPage(${idx})">
      <span>${p.title}</span>
      <span class="page-badge">${p.classification}</span>
    </div>
  `).join("");

  const pageLabel = document.getElementById("current-page-label");
  if (pageLabel) pageLabel.innerText = `Page ${state.currentPageIdx + 1}`;
}

function renderFieldList() {
  const container = document.getElementById("field-list");
  if (!container) return;
  const currentPageFields = state.doc.pages[state.currentPageIdx].fields;

  if (currentPageFields.length === 0) {
    container.innerHTML = `<div style="padding: 1rem; color: var(--text-secondary); font-size: 0.8rem;">No extracted fields on this page.</div>`;
    return;
  }

  container.innerHTML = currentPageFields.map(f => {
    const confPct = Math.round(f.stages.s5_hitl.confidence * 100);
    const confColor = f.stages.s5_hitl.confidence >= f.requiredThreshold ? "#10b981" : "#f43f5e";

    return `
      <div class="field-card ${f.id === state.currentField.id ? 'active' : ''}" onclick="selectField('${f.id}')">
        <div class="field-card-header">
          <span class="field-name">${f.label}</span>
          <span class="badge ${f.criticality === 'CRITICAL' ? 'badge-critical' : 'badge-noncritical'}">${f.criticality}</span>
        </div>
        <div class="field-card-value">${f.stages.s5_hitl.value}</div>
        <div class="confidence-bar-bg">
          <div class="confidence-bar-fill" style="width: ${confPct}%; background: ${confColor};"></div>
        </div>
        <div class="field-card-meta">
          <span>Req. Conf: ${(f.requiredThreshold * 100).toFixed(0)}%</span>
          <span style="font-weight: 700; color: ${confColor}">${f.stages.s5_hitl.status.toUpperCase()}</span>
        </div>
      </div>
    `;
  }).join("");
}

function renderCanvas() {
  const holder = document.getElementById("svg-canvas-holder");
  if (!holder) return;
  const page = state.doc.pages[state.currentPageIdx];

  let pageContent = "";
  if (state.doc.id.includes("ub04")) {
    pageContent = `
      <rect x="0" y="0" width="1712" height="2214" fill="#f8fafc" />
      <rect x="50" y="50" width="1612" height="100" fill="#cbd5e1" rx="4" />
      <text x="80" y="110" font-family="sans-serif" font-size="32" font-weight="bold" fill="#0f172a">UB-04 INSTITUTIONAL CLAIM (CMS-1450) — PAGE ${page.pageNumber}</text>
      <rect x="50" y="180" width="1612" height="1800" fill="#ffffff" stroke="#cbd5e1" stroke-width="2" />
      <text x="1200" y="260" font-family="sans-serif" font-size="28" font-weight="bold" fill="#0284c7">FL 56 NPI: 1987654321</text>
      <text x="1400" y="150" font-family="sans-serif" font-size="28" font-weight="bold" fill="#0284c7">FL 4 TOB: 0111</text>
    `;
  } else {
    pageContent = `
      <rect x="0" y="0" width="1712" height="2214" fill="#f8fafc" />
      <rect x="50" y="50" width="1612" height="100" fill="#e2e8f0" rx="4" />
      <text x="80" y="110" font-family="sans-serif" font-size="32" font-weight="bold" fill="#0f172a">HEALTH INSURANCE CLAIM FORM (NUCC 02/12) — PAGE ${page.pageNumber}</text>
      
      <!-- Box 1a Insured ID -->
      <rect x="980" y="210" width="650" height="70" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.5" rx="4"/>
      <text x="1000" y="255" font-family="sans-serif" font-size="28" font-weight="bold" fill="#0284c7">1a. INSURED ID: XYZ987654321</text>
      
      <!-- Box 2 Patient Name -->
      <rect x="50" y="310" width="600" height="90" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.5" rx="4"/>
      <text x="70" y="340" font-family="sans-serif" font-size="20" font-weight="bold" fill="#334155">2. PATIENT'S NAME</text>
      <text x="80" y="380" font-family="sans-serif" font-size="32" font-weight="bold" fill="#0284c7">DOE, JOHN</text>
      
      <!-- Box 24D CPT Code -->
      <rect x="50" y="1100" width="1612" height="150" fill="#f8fafc" stroke="#94a3b8" stroke-width="1.5" rx="4"/>
      <rect x="900" y="1150" width="150" height="70" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.5" rx="4"/>
      <text x="70" y="1140" font-family="sans-serif" font-size="20" font-weight="bold" fill="#334155">24. A-J SERVICE LINES</text>
      <text x="920" y="1195" font-family="sans-serif" font-size="28" font-weight="bold" fill="#0284c7">99214</text>

      <!-- Box 25 Federal Tax ID -->
      <rect x="50" y="1810" width="550" height="80" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.5" rx="4"/>
      <text x="70" y="1860" font-family="sans-serif" font-size="28" font-weight="bold" fill="#0284c7">25. TAX ID: 12-3456789</text>

      <!-- Box 28 Total Charge -->
      <rect x="1150" y="1810" width="480" height="80" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.5" rx="4"/>
      <text x="1180" y="1860" font-family="sans-serif" font-size="28" font-weight="bold" fill="#0284c7">28. TOTAL: $ 175.00</text>
      
      <!-- Box 31 Signature -->
      <rect x="1050" y="1150" width="600" height="100" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.5" rx="4"/>
      <text x="1070" y="1185" font-family="sans-serif" font-size="20" font-weight="bold" fill="#334155">31. SIGNATURE OF PHYSICIAN</text>
      <path d="M 1100 1230 Q 1150 1200 1200 1230 T 1300 1220 T 1400 1240" fill="transparent" stroke="#0284c7" stroke-width="4"/>

      <!-- Box 33a NPI -->
      <rect x="50" y="1950" width="550" height="80" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.5" rx="4"/>
      <text x="70" y="2000" font-family="sans-serif" font-size="28" font-weight="bold" fill="#0284c7">33a. NPI: 1234567893</text>
    `;
  }

  holder.innerHTML = `
    <svg class="claim-img" viewBox="0 0 1712 2214" width="580" height="750">
      ${pageContent}
    </svg>
  `;

  updateBBoxOverlay();
}

function updateBBoxOverlay() {
  const overlay = document.getElementById("bbox-overlay");
  const field = state.currentField;
  if (!overlay) return;

  if (!field || field.pageNumber !== state.currentPageIdx + 1) {
    overlay.style.display = "none";
    return;
  }

  overlay.style.display = "block";
  const canvasWidth = 1712;
  const canvasHeight = 2214;
  
  overlay.style.left = `${(field.bbox.x / canvasWidth) * 100}%`;
  overlay.style.top = `${(field.bbox.y / canvasHeight) * 100}%`;
  overlay.style.width = `${(field.bbox.w / canvasWidth) * 100}%`;
  overlay.style.height = `${(field.bbox.h / canvasHeight) * 100}%`;
}

function zoomIn() {
  state.zoomLevel = Math.min(state.zoomLevel + 0.2, 2.5);
  applyZoom();
}

function zoomOut() {
  state.zoomLevel = Math.max(state.zoomLevel - 0.2, 0.6);
  applyZoom();
}

function resetZoom() {
  state.zoomLevel = 1.0;
  applyZoom();
}

function applyZoom() {
  const wrapper = document.getElementById("canvas-wrapper");
  if (wrapper) wrapper.style.transform = `scale(${state.zoomLevel})`;
  const txt = document.getElementById("zoom-level-text");
  if (txt) txt.innerText = `${Math.round(state.zoomLevel * 100)}%`;
}

function renderPipeline() {
  const container = document.getElementById("pipeline-container");
  const field = state.currentField;
  if (!container || !field) return;

  const stages = [
    field.stages.s1_opencv,
    field.stages.s2_ocr,
    field.stages.s3_retry,
    field.stages.s4_vlm,
    field.stages.s5_hitl
  ];

  container.innerHTML = stages.map((s, idx) => {
    let statusClass = "";
    if (idx < state.currentStageIdx) statusClass = "completed";
    else if (idx === state.currentStageIdx) statusClass = "active";
    if (s.status === "failed") statusClass += " failed";

    return `
      <div class="pipeline-stage ${statusClass}">
        <div class="stage-number">STAGE ${idx + 1}</div>
        <div class="stage-title">${s.title}</div>
        <div class="stage-crop-preview">${s.cropText || s.value}</div>
        <div class="stage-details">
          <div class="stage-detail-row">
            <span>Method:</span>
            <span class="stage-detail-val">${s.method}</span>
          </div>
          <div class="stage-detail-row">
            <span>Conf:</span>
            <span class="stage-detail-val" style="color: ${s.confidence >= field.requiredThreshold ? '#10b981' : '#f43f5e'}">
              ${(s.confidence * 100).toFixed(0)}%
            </span>
          </div>
        </div>
      </div>
    `;
  }).join("");
}

function completeHitlReview() {
  const field = state.currentField;
  const inputEl = document.getElementById("hitl-input-value");
  const val = inputEl ? inputEl.value.trim() : "Dr. John Smith, MD";

  field.stages.s5_hitl.value = val;
  field.stages.s5_hitl.confidence = 1.0;
  field.stages.s5_hitl.status = "completed";
  field.stages.s5_hitl.method = "APPROVED_BY_OPERATOR";
  field.whyEscalated = `✓ HITL Review Completed & Approved by Human Operator ("${val}"). Confidence set to 100%. Task closed.`;

  // Send async POST request to backend API
  fetch("/review-api/review-tasks/task-4a76425e/decision", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision: "APPROVE", value: val })
  }).catch(() => {});

  renderFieldList();
  renderPipeline();
  renderDiagnostics();
  renderCostLadder();
}

function renderDiagnostics() {
  const container = document.getElementById("diagnostic-box");
  const field = state.currentField;
  if (!container || !field) return;

  const stage = Object.values(field.stages)[state.currentStageIdx];

  let boxClass = "success";
  if (stage.status === "failed" || stage.status === "active") boxClass = "danger";

  const isHitlActive = field.stages.s5_hitl.status === "active" || field.stages.s5_hitl.method === "APPROVED_BY_OPERATOR";
  const defaultHitlValue = field.stages.s4_vlm.value && field.stages.s4_vlm.value !== "N/A" ? field.stages.s4_vlm.value : "Dr. John Smith, MD";

  container.className = `diagnostic-box ${boxClass}`;
  container.innerHTML = `
    <div class="diag-header">
      <span>${field.label} (Page ${field.pageNumber}) — Stage ${state.currentStageIdx + 1}: ${stage.title}</span>
    </div>
    <div class="diag-reason">
      <strong>Current Value:</strong> <code style="color: var(--cyan-bright)">${stage.value}</code><br>
      <strong>Confidence:</strong> ${(stage.confidence * 100).toFixed(0)}% (Required: ${(field.requiredThreshold * 100).toFixed(0)}%)
      ${stage.error ? `<br><span style="color: var(--rose-bright)">⚠️ ${stage.error}</span>` : ''}
    </div>

    ${isHitlActive ? `
      <div style="margin: 0.85rem 0; padding: 0.75rem; background: rgba(15, 23, 42, 0.8); border: 1px solid var(--cyan-bright); border-radius: 8px;">
        <div style="font-size: 0.78rem; font-weight: 700; color: var(--cyan-bright); margin-bottom: 0.4rem;">
          ✋ INTERACTIVE HUMAN-IN-THE-LOOP (HITL) REVIEW
        </div>
        <label style="font-size: 0.72rem; color: var(--text-secondary); display: block; margin-bottom: 0.3rem;">
          Verified / Corrected Value:
        </label>
        <input id="hitl-input-value" type="text" value="${stage.value !== 'Awaiting Reviewer Action' ? stage.value : defaultHitlValue}" 
               style="width: 100%; padding: 0.45rem 0.75rem; background: #020617; border: 1px solid var(--border-glass); border-radius: 6px; color: #ffffff; font-family: 'JetBrains Mono', monospace; font-size: 0.82rem; margin-bottom: 0.6rem; outline: none;" />
        
        <button onclick="completeHitlReview()" style="width: 100%; padding: 0.5rem 1rem; background: linear-gradient(135deg, #10b981, #059669); color: #ffffff; font-weight: 700; border: none; border-radius: 6px; cursor: pointer; font-size: 0.82rem; box-shadow: 0 0 12px rgba(16, 185, 129, 0.4);">
          ✓ Complete HITL Review & Save Decision
        </button>
      </div>
    ` : ''}

    <div style="font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 0.3rem;">
      <strong>Why Escalated / Transformation Notes:</strong>
    </div>
    <p style="font-size: 0.8rem; line-height: 1.35; color: var(--text-primary);">
      ${field.whyEscalated}
    </p>
  `;
}

function renderCostLadder() {
  const container = document.getElementById("cost-ladder");
  const currentStage = state.currentStageIdx;
  if (!container) return;
  
  const ladder = [
    { name: "1. OpenCV Alignment", cost: "$0.0000", time: "8ms" },
    { name: "2. Regional PaddleOCR", cost: "$0.0001", time: "35ms" },
    { name: "3. Preprocessing Retry", cost: "$0.0002", time: "65ms" },
    { name: "4. Compact Vision-LLM", cost: "$0.0022", time: "420ms" },
    { name: "5. Human Review (HITL)", cost: "$0.1500", time: "45000ms" }
  ];

  container.innerHTML = ladder.map((item, idx) => `
    <div class="ladder-item ${idx === currentStage ? 'active' : ''}">
      <span class="ladder-name">${item.name}</span>
      <div>
        <span style="color: var(--text-secondary); font-size: 0.7rem; margin-right: 0.4rem">${item.time}</span>
        <span class="ladder-cost">${item.cost}</span>
      </div>
    </div>
  `).join("");
}

function setupEventListeners() {
  const btnPrev = document.getElementById("btn-prev");
  const btnNext = document.getElementById("btn-next");

  if (btnPrev) {
    btnPrev.addEventListener("click", () => {
      if (state.currentStageIdx > 0) {
        state.currentStageIdx--;
        renderPipeline();
        renderDiagnostics();
        renderCostLadder();
      }
    });
  }

  if (btnNext) {
    btnNext.addEventListener("click", () => {
      if (state.currentStageIdx < 4) {
        state.currentStageIdx++;
        renderPipeline();
        renderDiagnostics();
        renderCostLadder();
      }
    });
  }
}
