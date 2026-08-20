"""Build the silent 13-scene, 5:30 hackathon demo video."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "demo-output"
REPORT = ROOT / "apps/evaluation_ui/public/reports/evaluation.json"

WIDTH, HEIGHT, FPS, DURATION = 1920, 1080, 2, 330
NAVY, PANEL, TEAL = "#071725", "#10283A", "#42D7B3"
BLUE, WHITE, MUTED, LINE, RED = "#63A8FF", "#F3F8FC", "#A4B6C7", "#29465B", "#FF8995"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "arialbd.ttf" if bold else "arial.ttf"
    return ImageFont.truetype(str(Path("C:/Windows/Fonts") / name), size)


def text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, size: int,
         color: str = WHITE, bold: bool = False, width: int | None = None,
         spacing: int = 8) -> int:
    x, y = xy
    lines = textwrap.wrap(value, width=width, break_long_words=False) if width else value.splitlines()
    for line in lines or [""]:
        draw.text((x, y), line, font=font(size, bold), fill=color)
        y += size + spacing
    return y


def base(scene: int, label: str, title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), NAVY)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 10), fill=TEAL)
    text(draw, (36, 28), "CLAIMS INTELLIGENCE", 15, TEAL, True)
    text(draw, (1705, 28), f"{label}  -  Scene {scene:02d}/13", 14, MUTED, True)
    text(draw, (36, 82), title, 36, WHITE, True)
    text(draw, (36, 130), subtitle, 18, BLUE, True)
    text(draw, (36, 1048), "Current governed sample  -  30 pages  -  239 fields  -  Healthcare Claims Intelligence", 11, MUTED)
    return image, draw


def bullets(draw: ImageDraw.ImageDraw, items: list[str], box=(36, 190, 1884, 990), columns=1) -> None:
    draw.rounded_rectangle(box, radius=14, fill=PANEL, outline=LINE, width=2)
    x1, y1, x2, _ = box
    col_width = (x2 - x1 - 70) // columns
    rows = (len(items) + columns - 1) // columns
    for index, item in enumerate(items):
        col, row = index // rows, index % rows
        x, y = x1 + 34 + col * col_width, y1 + 38 + row * (700 // max(rows, 1))
        draw.ellipse((x, y + 8, x + 10, y + 18), fill=TEAL)
        text(draw, (x + 25, y), item, 20, MUTED, width=max(32, col_width // 12), spacing=7)


def cards(draw: ImageDraw.ImageDraw, rows: list[tuple[str, str]], columns=3) -> None:
    margin, gap, top, bottom = 36, 18, 220, 940
    card_width = (WIDTH - margin * 2 - gap * (columns - 1)) // columns
    row_count = (len(rows) + columns - 1) // columns
    card_height = (bottom - top - gap * (row_count - 1)) // row_count
    for index, (title, body) in enumerate(rows):
        col, row = index % columns, index // columns
        x, y = margin + col * (card_width + gap), top + row * (card_height + gap)
        draw.rounded_rectangle((x, y, x + card_width, y + card_height), radius=14, fill=PANEL, outline=LINE, width=2)
        text(draw, (x + 24, y + 25), title, 20, TEAL, True, width=30)
        text(draw, (x + 24, y + 74), body, 17, MUTED, width=48, spacing=7)


def app_scene(scene: int, title: str, subtitle: str, screenshot: str) -> Image.Image:
    image, draw = base(scene, "APP DEMO", title, subtitle)
    source = Image.open(OUTPUT / screenshot).convert("RGB")
    source = source.crop((0, 0, source.width, min(source.height, 760)))
    source.thumbnail((1840, 790), Image.Resampling.LANCZOS)
    x, y = (WIDTH - source.width) // 2, 205
    draw.rounded_rectangle((x - 5, y - 30, x + source.width + 5, y + source.height + 5), radius=10, fill="#030B12", outline=LINE, width=2)
    draw.ellipse((x + 15, y - 19, x + 25, y - 9), fill="#FF6B6B")
    draw.ellipse((x + 33, y - 19, x + 43, y - 9), fill="#FBBF24")
    draw.ellipse((x + 51, y - 19, x + 61, y - 9), fill=TEAL)
    text(draw, (x + 78, y - 23), "localhost:8180", 11, MUTED)
    image.paste(source, (x, y))
    return image


def build_scenes(report: dict) -> list[Image.Image]:
    local = report["local_extraction_accuracy"]
    llm_cost = report["llm_processing_cost"]["run_cost_usd"]
    scenes: list[Image.Image] = []

    image, draw = base(1, "PPT", "Healthcare Claims Intelligence", "Evidence-first IDP - current application demonstration")
    text(draw, (70, 270), "Validated, traceable claim extraction", 52, WHITE, True)
    text(draw, (70, 355), "Local-first processing. Selective LLM fallback. Fail-closed safety.", 28, BLUE, True)
    cards(draw, [
        ("GOVERNED SAMPLE", "30 pages / 239 evaluated fields"),
        ("FINAL ACCURACY", f"{report['normalized_field_accuracy']:.1%}"),
        ("LOCAL ACCURACY", f"{local:.2%}"),
        ("LLM DIVERSION", f"{report['llm_diverted_fields']}/239 fields ({report['llm_diversion_rate']:.2%})"),
        ("LLM RUN COST", f"${llm_cost:.6f} estimated"),
        ("CRITICAL FALSE ACCEPTS", f"{report['critical_false_accept_rate']:.1%}"),
    ])
    scenes.append(image)

    image, draw = base(2, "PPT", "The Problem", "Structured forms, messy reality")
    bullets(draw, [
        "CMS-1500 and UB-04 forms arrive with invoices, notes, statements and attachments.",
        "Skew, compression, handwriting, checkboxes, clipping and repeated labels break flat OCR.",
        "A plausible string can still belong to the wrong field, component, page or person.",
        "Critical identity and clinical fields need evidence and provenance - not confidence alone.",
    ])
    scenes.append(image)

    image, draw = base(3, "PPT", "Why Traditional OCR Is Not Enough", "Flat text vs. evidence-first extraction")
    cards(draw, [
        ("FLAT OCR", "Loses form geometry; selects text from the wrong page; confuses labels with values; over-routes to review."),
        ("THIS PLATFORM", "Field-level geometry; per-field page routing; validation before acceptance; evidence-backed confidence."),
    ], columns=2)
    scenes.append(image)

    image, draw = base(4, "PPT", "Our Solution", "A six-stage hybrid evidence pipeline")
    cards(draw, [
        ("1 PREPARE", "Decode, orient, deskew and assess quality."),
        ("2 ROUTE", "Classify every page and align standard forms."),
        ("3 EXTRACT", "Generate regional OCR and geometry evidence."),
        ("4 ESCALATE", "Send only unresolved crops to the LLM."),
        ("5 VALIDATE", "Apply field rules, semantics and references."),
        ("6 FINALIZE", "Reconcile, abstain or govern review."),
    ])
    scenes.append(image)

    image, draw = base(5, "PPT", "Architecture at a Glance", "Stateless, event-driven system")
    cards(draw, [
        ("1 INGESTION API", "Idempotent upload, hash and object URI."),
        ("2 OBJECT STORAGE", "Originals, pages, crops and evidence."),
        ("3 PREPARATION", "Decode, orient and normalize."),
        ("4 CLASSIFY + ALIGN", "Family routing and template geometry."),
        ("5 CANDIDATE PROVIDERS", "PaddleOCR, Tesseract and parsers."),
        ("6 VALIDATE + RECONCILE", "Eligibility, dominance and safety rules."),
        ("7 REFERENCE / REVIEW", "Fail-closed exception handling."),
        ("8 OUTPUT", "JSON, CSV and fixed-width projections."),
    ], columns=4)
    scenes.append(image)

    image, draw = base(6, "PPT", "Governed Automation", "Reduce LLM and review without hiding uncertainty")
    bullets(draw, [
        "98.74% local extraction accuracy on the current labelled sample.",
        "Only 5 of 239 fields route to crop-level LLM fallback.",
        "$0.019200 optimized LLM run-cost estimate; token-derived, not invoice data.",
        "Reviewer corrections become structured feedback exemplars for future difficult fields.",
        "Unsupported routes terminate in governed review instead of hanging or fabricating output.",
    ])
    scenes.append(image)

    scenes.append(app_scene(7, "Overview / Submission Results", "Current governed metrics and LLM processing cost", "overview.png"))
    scenes.append(app_scene(8, "Upload Claim Document", "Real ingestion API - PNG, JPEG, TIFF and PDF", "process.png"))
    scenes.append(app_scene(9, "Field Evidence", "Value, confidence, page, method and image lineage", "evidence.png"))
    scenes.append(app_scene(10, "HITL Inspector", "Difficult fields, reviewer correction and structured feedback memory", "hitl.png"))
    scenes.append(app_scene(11, "OCR and LLM Flow", "Local-first cascade with selective governed escalation", "flow.png"))

    image, draw = base(12, "APP DEMO", "Governance and Submission", "Tuning controls, HOTL roadmap and submission evidence")
    for index, filename in enumerate(("tuning.png", "submission.png")):
        source = Image.open(OUTPUT / filename).convert("RGB")
        source.thumbnail((890, 720), Image.Resampling.LANCZOS)
        x = 40 + index * 930
        draw.rounded_rectangle((x - 4, 215, x + 894, 219 + source.height), radius=10, fill="#030B12", outline=LINE, width=2)
        image.paste(source, (x, 219))
    scenes.append(image)

    image, draw = base(13, "CONCLUSION", "Closing", "Accuracy, economics and an honest safety model")
    bullets(draw, [
        "Local-first processing keeps the common path fast, deterministic and inexpensive.",
        "Cloud AI is reserved for the genuinely uncertain remainder.",
        "Every value carries evidence lineage for audit and compliance.",
        "Critical fields fail closed instead of guessing.",
        "Production accuracy requires untouched holdout validation and controlled canary promotion.",
        "Deployment code and Docker configuration are packaged and ready.",
    ])
    scenes.append(image)
    return scenes


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    scenes = build_scenes(report)
    for index, scene in enumerate(scenes, 1):
        scene.save(OUTPUT / f"scene-{index:02d}.png")

    target = OUTPUT / "IDP_Claims_Intelligence_Demo_v2_source.mp4"
    writer = cv2.VideoWriter(str(target), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError("Could not initialize MP4 writer")
    total_frames = FPS * DURATION
    per_scene, remainder = divmod(total_frames, len(scenes))
    for index, scene in enumerate(scenes):
        frame = cv2.cvtColor(np.asarray(scene), cv2.COLOR_RGB2BGR)
        for _ in range(per_scene + (1 if index < remainder else 0)):
            writer.write(frame)
    writer.release()
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
