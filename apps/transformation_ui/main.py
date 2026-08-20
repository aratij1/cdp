"""FastAPI server to host the Field Transformation & Escalation Visualizer UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

UI_DIR = Path(__file__).resolve().parent

app = FastAPI(title="IDP Transformation Visualizer UI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=UI_DIR), name="static")


@app.get("/")
def read_root():
    return FileResponse(UI_DIR / "index.html")


@app.get("/styles.css")
def read_css():
    return FileResponse(UI_DIR / "styles.css")


@app.get("/app.js")
def read_js():
    return FileResponse(UI_DIR / "app.js")


@app.get("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8185)
