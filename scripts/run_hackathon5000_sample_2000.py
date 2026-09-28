#!/usr/bin/env python3
"""Hackathon-5000 stratified 2000 — FAST (latency) or PRODUCT (STP gate).

Permanent rules (see docs/PRODUCT_RUN_PROFILE_AND_CORPUS_BINDING_V1.md):
  • Always binds dataset_hackathon_5000.yaml to the 5000 Drive zip.
  • FAST (default) is NOT product-gate eligible.
  • --product / --full applies PRODUCT residuals and is gate-eligible.

Usage:
  python3 -u scripts/run_hackathon5000_sample_2000.py           # FAST latency
  python3 -u scripts/run_hackathon5000_sample_2000.py --product # STP gate run
  python3 -u scripts/run_hackathon5000_sample_2000.py --fresh
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.corpus_binding import CorpusBindingError, bind_corpus, write_corpus_binding
from packages.run_profiles import apply_profile_env, write_run_manifest

DOCS = ROOT / "docs/metrics/hackathon5000_sample_2000_v1/selected_documents.txt"
OUT = ROOT / "evaluation_results/hackathon5000_sample_2000_v1"
ZIP = ROOT / "data/Hackathon - 5000 Claims.zip"
DATASET = ROOT / "dataset_hackathon_5000.yaml"

ALLOC = {"Group A": 1350, "Group B": 372, "Group C": 172, "Group D": 106}


def main() -> int:
    docs = [ln.strip() for ln in DOCS.read_text().splitlines() if ln.strip()]
    assert len(docs) == 2000, len(docs)
    assert ZIP.is_file(), ZIP
    assert DATASET.is_file(), DATASET
    OUT.mkdir(parents=True, exist_ok=True)

    argv = set(sys.argv[1:])
    product = "--full" in argv or "--product" in argv
    profile_name = "PRODUCT" if product else "FAST"

    try:
        binding = bind_corpus(
            dataset_yaml=DATASET,
            zip_path=ZIP,
            documents=docs,
            require_documents=True,
        )
    except CorpusBindingError as exc:
        print(f"ERROR: corpus binding failed: {exc}", flush=True)
        return 2
    write_corpus_binding(OUT, binding)

    if "--fresh" in argv:
        ledger = OUT / "results.jsonl"
        if ledger.exists():
            ledger.unlink()
        claims = OUT / "claims"
        if claims.exists():
            shutil.rmtree(claims)
        print("cleared prior ledger/claims", flush=True)

    env, profile = apply_profile_env(profile_name, dict(os.environ))
    env["CDP_HACKATHON_ZIP"] = str(ZIP)
    env["CDP_AZURE_DI_METER_PATH"] = str(OUT / "azure_di_meter.jsonl")
    env["CDP_VLM_TOKEN_METER_PATH"] = str(OUT / "vlm_token_meter.jsonl")
    write_run_manifest(
        OUT,
        profile=profile.name,
        dataset_id=binding.dataset_id,
        extra={
            "runner": "run_hackathon5000_sample_2000",
            "docs": len(docs),
            "selection_seed": 20260925,
            "alloc": ALLOC,
        },
    )
    if profile.name == "FAST":
        print(
            "profile=FAST — NOT product-gate eligible "
            "(re-run with --product for STP≥97% scoring)",
            flush=True,
        )
    else:
        print("profile=PRODUCT — residuals on; product-gate eligible", flush=True)

    # Default 2 claim workers on multi-CPU hosts; keep a single OCR spawn
    # (~4 GiB Paddle) so parallel claims overlap DI/VLM without OOM.
    workers = "2"
    if "--workers" in sys.argv:
        i = sys.argv.index("--workers")
        workers = sys.argv[i + 1]
    env.setdefault("CDP_OCR_POOL_WORKERS", "1")

    cmd = [
        sys.executable,
        "-u",
        str(ROOT / "scripts/run_hackathon_1000_cascade.py"),
        "--zip",
        str(ZIP),
        "--dataset",
        str(DATASET),
        "--out-dir",
        str(OUT),
        "--documents",
        ",".join(docs),
        "--workers",
        workers,
        "--resume",
    ]
    print(
        f"Running workers={workers} ocr_pool={env.get('CDP_OCR_POOL_WORKERS')} "
        f"docs={len(docs)} dataset={DATASET.name} profile={profile.name}",
        flush=True,
    )
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
