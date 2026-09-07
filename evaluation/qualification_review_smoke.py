"""Read-only rendering smoke for the existing blind-review cohort.

This verifies server-side PNG decoding, not a browser's visual presentation.
No reviewer registration, review database access, labels, or source contents are written.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import secrets
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from PIL import Image
from starlette.requests import Request


def run_source_smoke(data: Path | None = None, *, expected_pages: int = 150) -> dict:
    from evaluation.annotation_app import qualification_review as ui

    token = secrets.token_urlsafe(32)
    request = Request(
        {"type": "http", "headers": [(b"cookie", f"qualification_session={token}".encode())]}
    )
    selected = data or ui.DATA
    failures = []
    rendered = shells = 0
    with (
        patch.object(ui, "DATA", selected),
        patch.dict(ui.SESSIONS, {token: "isolated-read-only-smoke"}),
        patch.object(
            ui, "store", side_effect=AssertionError("Read-only smoke cannot access review database")
        ),
    ):
        rows = ui.views()
        for index, row in enumerate(rows):
            try:
                screen = ui.page(index, request)
                markup = screen.body.decode()
                assert screen.status_code == 200
                assert "prediction_visible:false" in markup
                assert "/qualification-review/image/" in markup
                shells += 1
                response = ui.image(index, request)
                assert response.status_code == 200 and response.media_type == "image/png"
                with Image.open(io.BytesIO(response.body)) as decoded:
                    decoded.load()
                    assert decoded.width > 0 and decoded.height > 0
                    # The route checks the native-mode frozen hash before converting to RGB.
                    with Image.open(row["source_asset_path"]) as original:
                        original.seek(row["frame_index"])
                        expected = original.convert("RGB")
                        assert decoded.size == expected.size
                        assert decoded.mode == expected.mode
                        assert decoded.tobytes() == expected.tobytes()
                rendered += 1
            except (
                AssertionError,
                HTTPException,
                OSError,
                ValueError,
                KeyError,
            ) as exc:  # Report no paths, page text, or sensitive payloads.
                failures.append({"index": index, "error_type": type(exc).__name__})
    source_manifest = selected / "blind_source_views.local.json"
    return {
        "status": "PASS"
        if rendered == shells == len(rows) == expected_pages and not failures
        else "FAIL",
        "scope": "existing_source_server_render_read_only",
        "expected_pages": expected_pages,
        "source_pages": len(rows),
        "html_shells_loaded": shells,
        "png_pages_decoded_and_bound": rendered,
        "source_manifest_sha256": hashlib.sha256(source_manifest.read_bytes()).hexdigest(),
        "review_database_accessed": False,
        "labels_created": 0,
        "browser_visual_render_verified": False,
        "prediction_isolation_scope": "source-only route and blank annotation shell; not browser network inspection",
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--expected-pages", type=int, default=150)
    args = parser.parse_args()
    report = run_source_smoke(args.data, expected_pages=args.expected_pages)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
