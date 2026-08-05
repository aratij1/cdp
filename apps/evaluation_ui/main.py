"""FastAPI server to host the Claims Intelligence Governance Console (evaluation_ui)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from fastapi.middleware.cors import CORSMiddleware

DIST_DIR = Path(__file__).resolve().parent / "dist"
TRANSFORMATION_DIR = Path(__file__).resolve().parent.parent / "transformation_ui"

app = FastAPI(title="IDP Evaluation & Governance Console UI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if (DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

if (DIST_DIR / "reports").exists():
    app.mount("/reports", StaticFiles(directory=DIST_DIR / "reports"), name="reports")

if TRANSFORMATION_DIR.exists():
    app.mount("/transformation-files", StaticFiles(directory=TRANSFORMATION_DIR), name="transformation_files")


@app.get("/review-api/correction-promotion-candidates")
def get_correction_promotion_candidates():
    return [
        {
            "field_name": "patient_name",
            "observed": "DOE, J0HN",
            "corrected": "DOE, JOHN",
            "occurrences": 12,
            "distinct_documents": 8,
            "distinct_reviewers": 3,
            "agreement_ratio": 0.98,
            "promotion_eligible": True
        }
    ]


@app.get("/transformation")
def read_transformation():
    return FileResponse(TRANSFORMATION_DIR / "index.html")


@app.get("/styles.css")
def read_transformation_css():
    return FileResponse(TRANSFORMATION_DIR / "styles.css")


@app.get("/app.js")
def read_transformation_js():
    return FileResponse(TRANSFORMATION_DIR / "app.js")


@app.get("/transformation-files/styles.css")
def read_transformation_css():
    return FileResponse(TRANSFORMATION_DIR / "styles.css")


@app.get("/transformation-files/app.js")
def read_transformation_js():
    return FileResponse(TRANSFORMATION_DIR / "app.js")


@app.get("/review-api/review-tasks")
def get_review_tasks():
    return [
        {
            "task_id": "task-4a76425e",
            "claim_id": "claim-98213",
            "field_name": "provider_signature",
            "status": "OPEN",
            "created_at": "2026-08-05T08:00:00Z"
        },
        {
            "task_id": "task-9b12f88c",
            "claim_id": "claim-98214",
            "field_name": "patient_name",
            "status": "IN_REVIEW",
            "created_at": "2026-08-05T08:15:00Z"
        }
    ]


@app.get("/review-api/review-tasks/{task_id}")
def get_review_task_detail(task_id: str):
    if task_id == "task-4a76425e":
        return {
            "task_id": "task-4a76425e",
            "claim_id": "claim-98213",
            "document_id": "doc-88123",
            "page_number": 3,
            "field_name": "provider_signature",
            "status": "OPEN",
            "created_at": "2026-08-05T08:00:00Z",
            "crop_signed_url": "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='350' height='120' viewBox='0 0 350 120'><rect width='350' height='120' fill='%230f172a' rx='8'/><text x='20' y='70' font-family='cursive, Brush Script MT, sans-serif' font-size='36' fill='%2338bdf8'>Dr. John Smith, MD</text></svg>",
            "ocr_candidates": ["J. S... MD", "Dr. J. Smith"],
            "vlm_candidate": "Dr. John Smith, MD",
            "validation_errors": ["Handwritten cursive signature confidence 0.74 < 0.80 threshold"]
        }
    return {
        "task_id": task_id,
        "claim_id": "claim-98214",
        "document_id": "doc-88124",
        "page_number": 1,
        "field_name": "patient_name",
        "status": "IN_REVIEW",
        "created_at": "2026-08-05T08:15:00Z",
        "crop_signed_url": "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='350' height='120' viewBox='0 0 350 120'><rect width='350' height='120' fill='%230f172a' rx='8'/><text x='20' y='70' font-family='sans-serif' font-size='32' font-weight='bold' fill='%2338bdf8'>DOE, J0HN</text></svg>",
        "ocr_candidates": ["DOE, J0HN"],
        "vlm_candidate": "DOE, JOHN",
        "validation_errors": ["OCR digit '0' in name 'J0HN'"]
    }


@app.post("/review-api/review-tasks/{task_id}/correct")
@app.post("/review-api/review-tasks/{task_id}/reject")
@app.post("/review-api/review-tasks/{task_id}/decision")
@app.post("/review-api/review-tasks/{task_id}/submit")
@app.post("/review-api/review-tasks/{task_id}")
@app.put("/review-api/review-tasks/{task_id}")
def submit_review_decision(task_id: str):
    return {
        "status": "SUCCESS",
        "message": f"HITL review decision for task {task_id} saved successfully.",
        "task_id": task_id
    }


@app.get("/reports/evaluation.json")
def get_evaluation_report():
    report_file = DIST_DIR / "reports" / "evaluation.json"
    if report_file.exists():
        return FileResponse(report_file)
    return {"error": "Report file not found"}


@app.get("/")
def read_root():
    return FileResponse(DIST_DIR / "index.html")


@app.get("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8180)
