"""Build a single combined review image per document for manual ground-truth
verification: top band (patient name, insured ID) stacked over bottom band
(total charge), auto-picking the first page whose top band looks like an
actual CMS1500 form rather than a scanner separator (checked by page size
matching the expected ~1700x2200 form dimensions -- separator/barcode pages
in this dataset are also full-page images, so we instead just render every
page's bands and let the human reviewer pick, capped at first 3 pages).
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

DATASET = Path("dataset_raw")
OUT = Path(".verify50")


def build(doc_id: str, file_name: str) -> None:
    OUT.mkdir(exist_ok=True)
    path = DATASET / file_name
    with Image.open(path) as img:
        n_frames = getattr(img, "n_frames", 1)
        for page in range(min(n_frames, 3)):
            img.seek(page)
            w, h = img.size
            top = img.crop((0, 0, w, int(h * 0.36)))
            bottom = img.crop((0, int(h * 0.75), w, h))
            combo = Image.new("L", (w, top.height + bottom.height), 255)
            combo.paste(top.convert("L"), (0, 0))
            combo.paste(bottom.convert("L"), (0, top.height))
            combo.save(OUT / f"{doc_id[:8]}_p{page+1}.png", optimize=True)
    print(f"{doc_id[:8]}: {n_frames} page(s) rendered")


if __name__ == "__main__":
    doc_id, file_name = sys.argv[1], sys.argv[2]
    build(doc_id, file_name)
