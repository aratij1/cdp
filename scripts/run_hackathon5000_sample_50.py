#!/usr/bin/env python3
"""Hackathon-5000 stratified 50 — FAST (latency) or PRODUCT (STP gate).

Nested sample from sample_1000 (seed 20260925), excluding sample_10:
A34 / B9 / C4 / D3.

Permanent rules (see docs/PRODUCT_RUN_PROFILE_AND_CORPUS_BINDING_V1.md):
  • Always binds dataset_hackathon_5000.yaml to the 5000 Drive zip.
  • FAST (default) is NOT product-gate eligible.
  • --product / --full applies PRODUCT residuals and is gate-eligible.

Usage:
  python3 -u scripts/run_hackathon5000_sample_50.py           # FAST latency
  python3 -u scripts/run_hackathon5000_sample_50.py --product # STP gate run
  python3 -u scripts/run_hackathon5000_sample_50.py --fresh
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

DOCS = ROOT / "docs/metrics/hackathon5000_sample_50_v1/selected_documents.txt"
OUT = ROOT / "evaluation_results/hackathon5000_sample_50_v1"
ZIP = ROOT / "data/Hackathon - 5000 Claims.zip"
DATASET = ROOT / "dataset_hackathon_5000.yaml"


def main() -> int:
    docs = [ln.strip() for ln in DOCS.read_text().splitlines() if ln.strip()]
    assert len(docs) == 50, len(docs)
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
            "runner": "run_hackathon5000_sample_50",
            "docs": len(docs),
            "selection_seed": 20260925,
            "alloc": {"Group A": 34, "Group B": 9, "Group C": 4, "Group D": 3},
            "parent_sample": "hackathon5000_sample_1000_v1",
            "excluded_sample": "hackathon5000_sample_10_v1",
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

    workers = "1"
    if "--workers" in sys.argv:
        i = sys.argv.index("--workers")
        workers = sys.argv[i + 1]

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
        f"Running workers={workers} docs={len(docs)} dataset={DATASET.name} "
        f"profile={profile.name}",
        flush=True,
    )
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
