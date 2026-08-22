"""Generate a deterministic, non-holdout Bundle-D development corpus."""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "evaluation_data" / "bundle_d_dev_v1"
DEFAULT_UNTOUCHED = ROOT / "evaluation_data" / "bundle_d_untouched_v1"
DEFAULT_UNTOUCHED_V2 = ROOT / "evaluation_data" / "bundle_d_untouched_v2"
FAMILIES = (
    "PROFESSIONAL_CLAIM_LIKE", "INSTITUTIONAL_CLAIM_LIKE", "EOB",
    "ITEMIZED_BILL", "MEDICAL_INVOICE", "LAB_REPORT", "ATTACHMENT",
    "PROVIDER_STATEMENT", "CORRESPONDENCE", "NON_CLAIM",
)


def _font(size: int = 30):
    for candidate in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _draw_words(draw, text: str, xy: tuple[int, int], font, tokens: list[dict]) -> None:
    x, y = xy
    for word in text.split():
        rendered = word + " "
        box = draw.textbbox((x, y), word, font=font)
        draw.text((x, y), rendered, fill=0, font=font)
        tokens.append({"text": word, "bbox": list(box)})
        x += round(draw.textlength(rendered, font=font))


def generate(output: Path = DEFAULT_OUTPUT, documents_per_family: int = 3,
             *, seed: int = 51027, dataset_id: str = "BUNDLE_D_DEV_V1",
             frozen_holdout: bool = False) -> dict:
    randomizer = random.Random(seed)
    output.mkdir(parents=True, exist_ok=True)
    truth = []
    for family in FAMILIES:
        for index in range(documents_per_family):
            prefix = "BDHOLD" if frozen_holdout else "BDDEV"
            document_id = f"{prefix}-{family[:4]}-{index + 1:03d}"
            image = Image.new("L", (1400, 1800), 255)
            draw = ImageDraw.Draw(image)
            x = 70 + (index % 2) * 180
            labels = [
                ("patient_name", "Patient Name", "Jordan Avery"),
                ("insured_id_number", "Member ID", f"M{randomizer.randrange(100000,999999)}"),
                ("provider_npi", "Provider NPI", "1234567893"),
                ("patient_dob", "Date of Birth", "06/17/1981"),
                ("total_charge", "Total Charge", "$125.00"),
            ] if family not in {"NON_CLAIM", "CORRESPONDENCE", "ATTACHMENT"} else []
            font = _font(30 + index % 2 * 4)
            tokens = []
            # Non-text rendering nonce prevents byte-identical sparse pages
            # without leaking document ids into OCR or changing field truth.
            nonce_x = 1100 + randomizer.randrange(0, 180)
            nonce_y = 1600 + randomizer.randrange(0, 120)
            draw.rectangle((nonce_x, nonce_y, nonce_x + 2 + index, nonce_y + 2), fill=210)
            _draw_words(draw, family.replace("_", " "), (x, 70), font, tokens)
            fields = {}
            for row, (field_name, label, value) in enumerate(labels):
                y = 180 + row * (100 + index * 8)
                if index % 2:
                    _draw_words(draw, f"{label}:", (x, y), font, tokens)
                    _draw_words(draw, value, (x + 20, y + 42), font, tokens)
                else:
                    _draw_words(draw, f"{label}: {value}", (x, y), font, tokens)
                fields[field_name] = value
            path = output / f"{document_id}.png"
            image.save(path)
            truth.append({"document_id": document_id, "family": family,
                          "path": path.name, "fields": fields, "tokens": tokens,
                          "image_size": [image.width, image.height]})
    (output / "ground_truth.jsonl").write_text(
        "\n".join(json.dumps(item) for item in truth) + "\n", "utf-8"
    )
    manifest = {"dataset_id": dataset_id, "development_only": not frozen_holdout,
                "frozen_holdout": frozen_holdout, "document_count": len(truth),
                "families": list(FAMILIES), "generator_seed": seed,
                "token_box_annotations": True,
                "tuning_prohibited": frozen_holdout}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), "utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(generate(), indent=2))
