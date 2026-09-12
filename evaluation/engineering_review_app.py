"""Loopback-only source review. No prediction loader is imported by this app."""
from __future__ import annotations

import hmac
import html
import io
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from PIL import Image

from evaluation.engineering_review import (
    STATES,
    freeze,
    labels,
    read_manifest,
    save_label,
    source_item,
)


def create_app(reviewer_reference: str, access_token: str) -> FastAPI:
    if not reviewer_reference.strip() or len(access_token)<16:
        raise ValueError("REVIEWER_REFERENCE_AND_PRIVATE_ACCESS_TOKEN_REQUIRED")
    app = FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    sessions: set[str] = set()

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.url.hostname not in {"127.0.0.1","localhost","testserver"}:
            return Response(status_code=403)
        if request.method=="POST" and request.headers.get("origin") and request.headers["origin"] != str(request.base_url).rstrip("/"):
            return Response(status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"]="no-store"
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Referrer-Policy"]="same-origin"
        response.headers["Content-Security-Policy"]="default-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'"
        return response

    def authorized(request: Request):
        if request.cookies.get("engineering_review_session") not in sessions:
            raise HTTPException(401,"Local review sign-in required")

    @app.get("/",response_class=HTMLResponse)
    def landing():
        return '<h1>Engineering source review</h1><p>12 scans. Diagnostic only; no production authority.</p><form method="post" action="/login"><label>Access code <input type="password" name="token" required></label><button>Sign in</button></form>'

    @app.post("/login")
    async def login(request: Request):
        form = await request.form()
        if not hmac.compare_digest(str(form.get("token","")),access_token):
            raise HTTPException(403,"Access denied")
        session = secrets.token_urlsafe(32); sessions.add(session)
        response = RedirectResponse("/fields",status_code=303)
        response.set_cookie("engineering_review_session",session,httponly=True,samesite="strict")
        return response

    @app.get("/fields",response_class=HTMLResponse)
    def fields(request: Request):
        authorized(request)
        try:
            completed = {row["field_id"] for row in labels()}
            rows = read_manifest()["fields"]
        except (ValueError,OSError,KeyError): raise HTTPException(409,"Source review state unavailable or changed") from None
        links = ''.join('<li><a href="/field/'+row["field_id"]+'">'+html.escape(row["field_name"])+
                        '</a> '+('Reviewed' if row["field_id"] in completed else 'Pending')+'</li>' for row in rows)
        return f'<h1>Source-only review: {len(completed)}/21 complete</h1><ul>{links}</ul><form method="post" action="/freeze"><button>Freeze completed engineering truth</button></form>'

    @app.get("/field/{field_id}",response_class=HTMLResponse)
    def field(request: Request, field_id: str):
        authorized(request)
        try: item=source_item(field_id)
        except (ValueError,OSError,KeyError): raise HTTPException(409,"Source binding unavailable or changed") from None
        options=''.join('<option>'+state+'</option>' for state in sorted(STATES))
        return '<h1>'+html.escape(item["field_name"])+"""</h1><p>Read the source image only. Enter the printed value or select a non-value state. No OCR prediction is shown.</p><img style="max-width:100%" src="/source/"""+field_id+""""><form method="post" action="/field/"""+field_id+""""><label>Source state <select name="state">"""+options+"""</select></label><label>Printed value <textarea name="value" autocomplete="off"></textarea></label><p>Source region, fractions of full image (left, top, right, bottom):</p><input name="region" required placeholder="0.1,0.2,0.5,0.3"><label>Is the printed source value valid? <select name="source_validity"><option>UNKNOWN</option><option>VALID</option><option>INVALID</option></select></label><label><input type="checkbox" name="attested" required>I read this value from the source, independently of OCR output.</label><button>Save immutable source review</button></form><a href="/fields">Back</a>"""

    @app.get("/source/{field_id}")
    def source(request: Request, field_id: str):
        authorized(request)
        try:
            item=source_item(field_id)
            with Image.open(Path(item["source_path"])) as scan:
                scan.seek(item["frame"]); stream=io.BytesIO(); scan.convert("RGB").save(stream,format="PNG")
            return Response(stream.getvalue(),media_type="image/png")
        except (ValueError,OSError,KeyError,EOFError): raise HTTPException(409,"Bound source unavailable") from None

    @app.post("/field/{field_id}")
    async def save(request: Request, field_id: str):
        authorized(request)
        try:
            form=await request.form()
            save_label(field_id,{"state":str(form.get("state","")),"value":str(form.get("value","")),
                       "source_region":[float(v) for v in str(form.get("region","")).split(",")],
                       "source_validity":str(form.get("source_validity","UNKNOWN")),
                       "source_only_attested":form.get("attested")=="on"},reviewer_reference)
        except (ValueError,OSError,KeyError): raise HTTPException(409,"Review rejected: verify source state, region, attestation, and immutability") from None
        return RedirectResponse("/fields",status_code=303)

    @app.post("/freeze")
    def finish(request: Request):
        authorized(request)
        try: result=freeze()
        except (ValueError,OSError,KeyError): raise HTTPException(409,"All 21 unchanged source reviews are required") from None
        return {"scope":result["scope"],"production_authority":False,"labels":21,"truth_sha256":result["truth_sha256"]}
    return app


if __name__ == "__main__":
    import argparse
    import os

    import uvicorn
    parser=argparse.ArgumentParser()
    parser.add_argument("--reviewer-reference",required=True)
    parser.add_argument("--port",type=int,default=8766)
    args=parser.parse_args()
    application=create_app(args.reviewer_reference,os.environ.get("CDP_ENGINEERING_REVIEW_TOKEN",""))
    uvicorn.run(application,host="127.0.0.1",port=args.port,access_log=False,log_level="warning")
