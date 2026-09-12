"""Scan Git objects without printing source values or sensitive filenames."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import PurePosixPath

BLOCKED_DIRS = {"claims", "dataset_raw", "evaluation_results", "reference_snapshots"}
BLOCKED_SUFFIXES = {".tif", ".tiff", ".pdf", ".zip", ".7z", ".tar", ".gz", ".dcm"}
IDENTIFIER = re.compile(
    rb'(?i)["\x27]?(?:patient_name|patient_dob|member_id|insured_id_number|ssn)'
    rb'["\x27]?\s*[:=]\s*["\x27]([^"\x27\r\n]{2,100})["\x27]'
)


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL)


def classify(path: str, data: bytes) -> set[str]:
    parts = PurePosixPath(path.lower()).parts
    reasons = set()
    if BLOCKED_DIRS.intersection(parts) or any(p.startswith(".pytest") for p in parts):
        reasons.add("PRIVATE_DATA_PATH")
    if PurePosixPath(path.lower()).suffix in BLOCKED_SUFFIXES:
        reasons.add("DOCUMENT_OR_ARCHIVE")
    if data.startswith((b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+", b"%PDF-", b"PK\x03\x04")):
        reasons.add("DOCUMENT_MAGIC")
    # Data exports are not source schemas. No literal values are logged.
    if (PurePosixPath(path.lower()).suffix in {".json", ".jsonl", ".csv", ".tsv", ".txt"}
            and IDENTIFIER.search(data)):
        reasons.add("POSSIBLE_PHI")
    if PurePosixPath(path.lower()).suffix in {".csv", ".tsv"}:
        header, _, body = data.partition(b"\n")
        if body.strip() and re.search(rb"(?i)(patient_name|patient_dob|member_id|insured_id_number|ssn)", header):
            reasons.add("POSSIBLE_PHI")
    return reasons


def scan(history: bool = False, removal_paths: set[str] | None = None, ref: str | None = None) -> dict:
    revision = git("rev-parse", "--verify", "--end-of-options", ref + "^{commit}").decode().strip() if ref else "--all"
    if history:
        objects = git("rev-list", "--objects", revision).splitlines()
        candidates = [line.split(b" ", 1) for line in objects if b" " in line]
    else:
        candidates = []
        for entry in git("ls-files", "--stage", "-z").split(b"\x00"):
            if entry:
                metadata, path = entry.split(b"\t", 1)
                candidates.append([metadata.split()[1], path])
    findings = []
    if history:
        # rev-list assigns one name to reused blobs; inspect every historical name too.
        names = git("log", revision, "--format=", "--name-only", "-z", "--no-renames").split(b"\x00")
        for raw_path in {name.lstrip(b"\n") for name in names if name.strip()}:
            path = raw_path.decode("utf-8", errors="surrogateescape")
            reasons = classify(path, b"")
            if reasons:
                if removal_paths is not None:
                    removal_paths.add(path)
                findings.append({"path_sha256": hashlib.sha256(raw_path).hexdigest(),
                                 "reasons": sorted(reasons)})
    batch = subprocess.run(["git", "cat-file", "--batch"],
                           input=b"\n".join(oid for oid, _ in candidates) + b"\n",
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True).stdout
    offset = 0
    for oid, raw_path in candidates:
        end = batch.index(b"\n", offset)
        _, kind, size = batch[offset:end].split()
        offset = end + 1
        data = batch[offset:offset + int(size)]
        offset += int(size) + 1
        sha = oid.decode("ascii")
        if kind != b"blob":
            continue
        path = raw_path.decode("utf-8", errors="surrogateescape")
        reasons = classify(path, data)
        if reasons:
            if removal_paths is not None:
                removal_paths.add(path)
            findings.append({"object": sha, "path_sha256": hashlib.sha256(raw_path).hexdigest(),
                             "reasons": sorted(reasons)})
    return {"status": "BLOCKED" if findings else "PASS", "scope": ("SELECTED_ANCESTRY" if ref else "ALL_LOCAL_REFS") if history else "INDEX",
            "finding_count": len(findings), "findings": findings,
            "categories": dict(Counter(r for f in findings for r in f["reasons"]))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--ref", help="Restrict history audit to this commit ancestry; default audits all refs")
    args = parser.parse_args()
    report = scan(args.history, ref=args.ref)
    print(json.dumps(report, indent=2))
    return int(report["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
