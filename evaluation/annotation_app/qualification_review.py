"""Local source-only 150-page review UI. Predictions are never loaded by this router."""

from __future__ import annotations

import hashlib
import hmac
import html
import io
import json
import os
import secrets
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from PIL import Image

from evaluation.qualification_state import mapped
from packages.real_data_evaluation.blind_workflow import FIELDS, BlindReviewStore, review_progress

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "evaluation_results/qualification_closure"
router = APIRouter(prefix="/qualification-review", tags=["blind-qualification"])
SESSIONS: dict[str, str] = {}
SESSION_AUTH: dict[str, tuple[str, str]] = {}
SESSION_KEY = secrets.token_bytes(32)


def store() -> BlindReviewStore:
    return BlindReviewStore(mapped(DATA / "blind_reviews.sqlite3"))


def views() -> list[dict]:
    path = mapped(DATA / "blind_source_views.local.json")
    if not path.exists():
        raise HTTPException(503, "Run deterministic source binding first")
    return sorted(json.loads(path.read_text()), key=lambda r: (r["package_id"], r["page_id"]))


def governed_registry() -> dict:
    from evaluation.track_b_inputs import current_registry

    root = DATA.parents[1] if DATA.name == "qualification_closure" else ROOT
    return current_registry(root, DATA)


def access_code(registry: dict, reviewer: str) -> str:
    assignment: dict = next(
        (r for r in registry.get("assignments", []) if r["reviewer_id"] == reviewer), {}
    )
    return os.environ.get(assignment.get("access_token_env", ""), "")


def session_proof(token: str, code: str) -> str:
    return hmac.new(SESSION_KEY, (token + code).encode(), "sha256").hexdigest()


def identity(request: Request, *, writing: bool = False) -> str:
    token = request.cookies.get("qualification_session", "")
    if token not in SESSIONS:
        raise HTTPException(401, "Sign in to local blind review")
    if writing and request.headers.get("X-Review-Session") != token:
        raise HTTPException(403, "Review session mismatch")
    if writing:
        registry = governed_registry()
        code = access_code(registry, SESSIONS[token])
        expected = (registry.get("contract_sha256", ""), session_proof(token, code))
        if (
            registry.get("contract_status") != "VALID"
            or not code
            or SESSION_AUTH.get(token) != expected
        ):
            raise HTTPException(403, "GOVERNED_REVIEWER_REGISTRY_REQUIRED")
    return SESSIONS[token]


def source(index: int) -> dict:
    pages = views()
    if index < 0 or index >= len(pages):
        raise HTTPException(404, "Review page missing")
    return pages[index]


@router.get("/", response_class=HTMLResponse)
def landing():
    return """<meta charset=utf-8><h1>Blind release review</h1>
    <p>Use your assigned reviewer identity. An operator must verify reviewer identities before truth finalization.</p>
    <form method=post action=/qualification-review/login><label>Reviewer ID <input name=reviewer required autocomplete=username></label><label>Assigned access code <input name=access_code type=password autocomplete=current-password></label><button>Resume my review</button></form>"""


@router.post("/login")
async def login(request: Request):
    form = await request.form()
    name = str(form.get("reviewer", "")).strip()
    if not name or len(name) > 128:
        raise HTTPException(400, "Reviewer identity required")
    from packages.hitl_reduction.review_coordination import canonical_reviewer_id

    registry = governed_registry()
    if registry.get("contract_status") != "VALID":
        raise HTTPException(503, "GOVERNED_REVIEWER_REGISTRY_REQUIRED")
    name = canonical_reviewer_id(name)
    expected = access_code(registry, name)
    supplied = str(form.get("access_code", ""))
    if not expected or not secrets.compare_digest(expected, supplied):
        raise HTTPException(403, "Registered identity and assigned access code required")
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = name
    SESSION_AUTH[token] = (registry["contract_sha256"], session_proof(token, expected))
    database = store()
    index = next(
        (
            i
            for i, r in enumerate(views())
            if not (database.own(r["page_id"], name) or {}).get("complete")
        ),
        0,
    )
    result = RedirectResponse(f"/qualification-review/page/{index}", 303)
    # Local loopback HTTP; token is available to same-origin JS for request binding.
    result.set_cookie("qualification_session", token, samesite="strict")
    return result


@router.get("/progress")
def progress(request: Request):
    identity(request)
    rows = views()
    full_registry = governed_registry()
    registry = frozenset(full_registry.get("authorized_reviewers", []))
    report = review_progress(
        store().completed(), {r["page_id"]: r["rendered_page_sha256"] for r in rows}, registry
    )
    # The closure watcher alone owns the authoritative progress artifact. Reading
    # the UI must never overwrite its frozen-truth counters with draft defaults.
    report["adjudications"] = len(store().adjudications())
    from packages.real_data_evaluation.release_truth import trusted_review_counts

    full_registry = governed_registry()
    report.update(
        trusted_review_counts(
            store().completed(),
            {r["page_id"]: r for r in rows},
            full_registry,
            store().adjudications(),
        )
    )
    manifest_path = mapped(DATA / "release_truth_manifest.local.json")
    if manifest_path.exists():
        from packages.real_data_evaluation.blind_workflow import content_digest
        from packages.real_data_evaluation.release_truth import finalize_reviews

        manifest = json.loads(manifest_path.read_text())
        full_registry = governed_registry()
        current = finalize_reviews(
            store().completed(),
            {r["page_id"]: r for r in rows},
            full_registry,
            store().adjudications(),
        )
        sealed = {k: v for k, v in manifest.items() if k != "truth_sha256"}
        if (
            manifest.get("status") == "FROZEN"
            and content_digest(sealed) == manifest.get("truth_sha256")
            and current == manifest
        ):
            report["trusted_labels"] = len(manifest["records"])
            report["truth_status"] = "FROZEN"
    return report


@router.get("/image/{index}")
def image(index: int, request: Request):
    identity(request)
    row = source(index)
    path = Path(row["source_asset_path"]).resolve()
    try:
        path.relative_to((ROOT / "evaluation_data/source_b_1000_claims").resolve())
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["source_asset_sha256"]:
            raise ValueError("changed")
        with Image.open(path) as page:
            page.seek(row["frame_index"])
            from evaluation.reconstruct_source_bindings import rendered_hash

            if rendered_hash(page) != row["rendered_page_sha256"]:
                raise ValueError("changed frame")
            output = io.BytesIO()
            page.convert("RGB").save(output, "PNG")
    except (ValueError, OSError, EOFError) as exc:
        raise HTTPException(409, "Source no longer matches frozen binding") from exc
    return Response(
        output.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"}
    )


@router.get("/draft/{index}")
def draft(index: int, request: Request):
    reviewer = identity(request)
    return store().own(source(index)["page_id"], reviewer) or {"annotation": {}, "complete": False}


@router.post("/draft/{index}")
async def save(index: int, request: Request):
    reviewer = identity(request, writing=True)
    registry = governed_registry()
    contract = mapped(DATA.parents[1] / "config/qualification/reviewer_registry.yaml")
    if contract.exists() and reviewer.strip().lower() not in registry.get(
        "authorized_reviewers", []
    ):
        raise HTTPException(403, "Verified independent reviewer registration required")
    raw = await request.json()
    row = source(index)
    if set(raw) != {"annotation", "complete"} or type(raw["complete"]) is not bool:
        raise HTTPException(400, "Invalid save request")
    existing = store().own(row["page_id"], reviewer)
    if existing and existing["complete"]:
        from packages.real_data_evaluation.blind_workflow import PageAnnotation

        try:
            same = (
                raw["complete"]
                and PageAnnotation.model_validate(raw["annotation"]).model_dump(mode="json")
                == existing["annotation"]
            )
        except ValueError:
            same = False
        if not same:
            raise HTTPException(409, "Completed review is immutable")
        from evaluation.track_b_review_provenance import record
        from packages.hitl_reduction.review_coordination import canonical_reviewer_id

        reviewer_id = canonical_reviewer_id(reviewer)
        assignments = registry.get("authorized_reviewers", [])
        record(
            DATA,
            "REVIEW_COMPLETE",
            row["page_id"],
            reviewer_id,
            row["rendered_page_sha256"],
            existing["annotation"],
            round_name=str(assignments.index(reviewer_id) + 1)
            if reviewer_id in assignments
            else "UNREGISTERED",
        )
        return {"saved": True, "progress": progress(request)}
    try:
        store().save(
            row["page_id"],
            reviewer,
            row["rendered_page_sha256"],
            raw["annotation"],
            complete=raw["complete"],
        )
    except ValueError as exc:
        raise HTTPException(400, "Incomplete annotation or immutable completed review") from exc
    from evaluation.track_b_review_provenance import record
    from packages.hitl_reduction.review_coordination import canonical_reviewer_id

    reviewer_id = canonical_reviewer_id(reviewer)
    assignments = registry.get("authorized_reviewers", [])
    record(
        DATA,
        "REVIEW_COMPLETE" if raw["complete"] else "DRAFT",
        row["page_id"],
        reviewer_id,
        row["rendered_page_sha256"],
        (store().own(row["page_id"], reviewer) or {})["annotation"],
        round_name=str(assignments.index(reviewer_id) + 1)
        if reviewer_id in assignments
        else "UNREGISTERED",
    )
    # Reconcile prerequisites after each completion; never manufacture absent truth.
    if raw["complete"]:
        from evaluation.qualification_closure import refresh

        try:
            refresh()
        except (ValueError, KeyError, OSError, TypeError):
            return {
                "saved": True,
                "qualification_status": "PENDING_INPUT_REPAIR",
                "progress": progress(request),
            }
    return {"saved": True, "progress": progress(request)}


@router.get("/page/{index}", response_class=HTMLResponse)
def page(index: int, request: Request):
    reviewer = identity(request)
    source(index)
    field_options = "".join(f'<option value="{f}">{f}</option>' for f in FIELDS)
    markup = """<!doctype html><meta charset=utf-8><title>Blind qualification review</title>
    <style>body{font:16px system-ui;margin:20px}main{display:grid;grid-template-columns:60% 38%;gap:2%}canvas{max-width:100%;border:1px solid #aaa}input,select,button{font:inherit;margin:8px;padding:6px}label{display:block}#page{cursor:crosshair}#crop{max-height:180px}</style>
    <h1>Blind review Â· page INDEX / TOTAL</h1><p>Reviewer: REVIEWER Â· <span id=progress></span> Â· <span id=status>Loading saved draft</span></p>
    <p><a href=/qualification-review/>Change reviewer</a> | <a href=/qualification-review/second-review-queue>Independent second-review queue</a> | <a href=/qualification-review/adjudication-queue>Adjudication queue</a> Â· <a href=/qualification-review/page/PREV>Previous</a> Â· <a href=/qualification-review/page/NEXT>Next</a></p>
    <main><section><canvas id=page></canvas><p>Drag on the page to select the source region. No model regions or predictions are supplied.</p></section>
    <section><label>Field <select id=field>OPTIONS</select></label><canvas id=crop></canvas>
    <label>Observation <select id=state><option value="">Choose</option><option>VALUE</option><option>BLANK</option><option>SOURCE_CONFLICT</option><option>UNREADABLE</option><option>NOT_PRESENT</option><option>NOT_APPLICABLE</option></select></label>
    <label>Source value <input id=value autocomplete=off></label><button id=nextField>Save field / next (Alt+N)</button>
    <label>Form <select id=form><option value="">Choose</option><option>CMS1500</option><option>UB04</option><option>OTHER_CLAIM_FORM</option><option>SUPPORTING_DOCUMENT</option><option>UNKNOWN</option></select></label>
    <label>Quality <select id=quality><option value="">Choose</option><option>GOOD</option><option>DEGRADED</option><option>UNREADABLE</option><option>UNCERTAIN</option></select></label>
    <label>Claim boundary <select id=boundary><option value="">Choose</option><option>START_CLAIM</option><option>CONTINUATION</option><option>SUPPORTING</option><option>UNCERTAIN</option></select></label>
    <p>Boundary observations do not establish complete claim membership by themselves.</p><button id=complete>Complete page and next (Ctrl+Enter)</button></section></main>
    <script>
    const index=ZERO, fields=[...document.querySelector('#field').options].map(o=>o.value), $=id=>document.getElementById(id);
    let annotation={fields:{},form:'',quality:'',boundary:'',prediction_visible:false},region=null,locked=false,timer,start,saving=Promise.resolve(true),dirty=false,loaded=false;
    const token=document.cookie.split('; ').find(x=>x.startsWith('qualification_session=')).split('=')[1];
    const img=new Image();img.src='/qualification-review/image/'+index;img.onload=()=>{$('page').width=img.width;$('page').height=img.height;draw()};
    function draw(){const crop=$('crop');crop.getContext('2d').clearRect(0,0,crop.width,crop.height);if(!img.complete||!img.naturalWidth)return;const c=$('page').getContext('2d');c.drawImage(img,0,0);if(region){c.strokeStyle='red';c.lineWidth=3;c.strokeRect(region[0]*img.width,region[1]*img.height,(region[2]-region[0])*img.width,(region[3]-region[1])*img.height);const out=$('crop');out.width=500;out.height=160;out.getContext('2d').drawImage(img,region[0]*img.width,region[1]*img.height,(region[2]-region[0])*img.width,(region[3]-region[1])*img.height,0,0,500,160)}}
    function point(e){const r=$('page').getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))]}
    $('page').onpointerdown=e=>{start=point(e);$('page').setPointerCapture(e.pointerId)};
    $('page').onpointerup=e=>{if(!start||locked)return;let p=point(e);region=[Math.min(start[0],p[0]),Math.min(start[1],p[1]),Math.max(start[0],p[0]),Math.max(start[1],p[1])];start=null;draw();queue()};
    function capture(){annotation.fields[$('field').value]={state:$('state').value,value:$('state').value==='VALUE'?$('value').value:null,region};for(const k of ['form','quality','boundary'])annotation[k]=$(k).value}
    function show(){let f=annotation.fields[$('field').value]||{};$('state').value=f.state||'';$('value').value=f.value||'';region=f.region||null;draw();$('value').focus()}
    function persist(complete=false){if(locked)return Promise.resolve(true);if(!loaded)return Promise.resolve(false);capture();clearTimeout(timer);const body=JSON.stringify({annotation,complete});saving=saving.then(async()=>{try{const r=await fetch('/qualification-review/draft/'+index,{method:'POST',headers:{'Content-Type':'application/json','X-Review-Session':token},body});if(r.ok){const result=await r.json();if(result.progress)displayProgress(result.progress)}if(r.ok&&body===JSON.stringify({annotation,complete}))dirty=false;$('status').textContent=r.ok?'Saved':'Save failed: complete each field and select its region';return r.ok}catch(e){$('status').textContent='Save failed: connection unavailable';return false}});return saving}
    function queue(){if(locked||!loaded)return;dirty=true;capture();clearTimeout(timer);timer=setTimeout(()=>persist(),500)}
    for(const k of ['value','state','form','quality','boundary'])$(k).oninput=queue;
    $('field').onchange=()=>show();
    $('nextField').onclick=async()=>{if(await persist()){$('field').selectedIndex=Math.min(fields.length-1,$('field').selectedIndex+1);show()}};
    $('complete').onclick=async()=>{if(await persist(true)){locked=true;location.href='/qualification-review/page/NEXT'}};
    document.onkeydown=e=>{if(e.altKey&&e.key.toLowerCase()==='n'){e.preventDefault();$('nextField').click()}if(e.ctrlKey&&e.key==='Enter'){e.preventDefault();$('complete').click()}};
    fetch('/qualification-review/draft/'+index).then(r=>r.json()).then(d=>{if(Object.keys(d.annotation).length)annotation=d.annotation;locked=d.complete;loaded=true;for(const k of ['form','quality','boundary'])$(k).value=annotation[k]||'';show();$('status').textContent=locked?'Completed; immutable':'Draft restored';if(locked)document.querySelectorAll('input,select,button').forEach(e=>e.disabled=true)});
    for(const link of document.querySelectorAll('a'))link.onclick=async e=>{if(!loaded||locked)return;e.preventDefault();if(await persist())location.href=link.href};
    window.onbeforeunload=e=>{if(dirty){e.preventDefault();e.returnValue=''}};
    function displayProgress(p){$('progress').textContent=p.pages_reviewed+'/'+p.pages_total+' pages reviewed; '+p.fields_reviewed+' field reviews; '+p.critical_fields_dual_reviewed+' critical dual reviews; '+p.agreements+' agreements; '+p.disagreements+' disagreements; '+p.adjudications+' adjudications; '+p.trusted_fields+' trusted fields; '+p.remaining_independent_page_reviews+' independent page reviews remaining'}
    fetch('/qualification-review/progress').then(r=>r.json()).then(displayProgress);
    </script>"""
    for key, value in {
        "REVIEWER": html.escape(reviewer),
        "OPTIONS": field_options,
        "INDEX": str(index + 1),
        "TOTAL": str(len(views())),
        "PREV": str(max(0, index - 1)),
        "NEXT": str(min(len(views()) - 1, index + 1)),
        "ZERO": str(index),
    }.items():
        markup = markup.replace(key, value)
    return HTMLResponse(markup, headers={"Cache-Control": "no-store"})


def adjudication_context(index: int, request: Request):
    from packages.hitl_reduction.review_coordination import canonical_reviewer_id

    reviewer = canonical_reviewer_id(identity(request))
    registry = governed_registry()
    if registry.get("identity_verified") is not True or reviewer not in {
        canonical_reviewer_id(r) for r in registry.get("adjudicators", [])
    }:
        raise HTTPException(403, "Governed adjudicator identity required")
    page_source = source(index)
    authorized = {canonical_reviewer_id(r) for r in registry.get("authorized_reviewers", [])}
    rows = [
        r
        for r in store().completed()
        if r["page_id"] == page_source["page_id"]
        and canonical_reviewer_id(r["reviewer_id"]) in authorized
        and r["source_sha256"] == page_source["rendered_page_sha256"]
    ]
    if len(rows) < 2 or reviewer in {canonical_reviewer_id(r["reviewer_id"]) for r in rows}:
        raise HTTPException(403, "Adjudicator must be independent of both reviewers")
    return reviewer, rows


@router.get("/adjudication/{index}", response_class=HTMLResponse)
def adjudication_page(index: int, request: Request):
    _, rows = adjudication_context(index, request)
    from packages.real_data_evaluation.blind_workflow import content_digest

    evidence = html.escape(json.dumps([r["annotation"] for r in rows], indent=2))
    return HTMLResponse(
        f"""<h1>Independent adjudication</h1><img style="max-width:55%" src=/qualification-review/image/{index}>
    <p>Source and independent annotations only; no CDP predictions.</p><pre>{evidence}</pre>
    <p>Enter field_name and conclusion. A field conclusion has state, value (null for non-value states), region [x0,y0,x1,y1]. For __metadata__, conclusion has form, quality, boundary.</p>
    <label>Adjudication reason <input id=reason required></label><textarea id=entry rows=10 cols=80></textarea><button onclick="save()">Save adjudication</button><p id=status></p><script>
    async function save(){{const token=document.cookie.split('; ').find(x=>x.startsWith('qualification_session=')).split('=')[1];
    const payload=JSON.parse(document.getElementById('entry').value);payload.reason=document.getElementById('reason').value;payload.review_digest='{content_digest(rows)}';
    const r=await fetch('/qualification-review/adjudication/{index}',{{method:'POST',headers:{{'Content-Type':'application/json','X-Review-Session':token}},body:JSON.stringify(payload)}});
    document.getElementById('status').textContent=r.ok?'Saved':'Rejected: check independent scope and conclusion';}}
    </script>""",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/adjudication/{index}")
async def adjudication_save(index: int, request: Request):
    identity(request, writing=True)
    reviewer, rows = adjudication_context(index, request)
    from packages.real_data_evaluation.blind_workflow import (
        FieldAnnotation,
        PageAnnotation,
        content_digest,
    )

    payload = await request.json()
    reason = payload.pop("reason", "")
    if (
        mapped(DATA.parents[1] / "config/qualification/reviewer_registry.yaml")
    ).exists() and not reason.strip():
        raise HTTPException(400, "Adjudication reason required")
    if set(payload) != {"field_name", "conclusion", "review_digest"} or payload[
        "review_digest"
    ] != content_digest(rows):
        raise HTTPException(409, "Adjudication input changed")
    field = payload["field_name"]
    try:
        if field == "__metadata__":
            if set(payload["conclusion"]) != {"form", "quality", "boundary"}:
                raise ValueError("Metadata only")
            PageAnnotation.model_validate({**rows[0]["annotation"], **payload["conclusion"]})
        elif field in FIELDS:
            FieldAnnotation.model_validate(payload["conclusion"])
        else:
            raise ValueError("Unknown field")
        store().adjudicate(
            source(index)["page_id"],
            field,
            reviewer,
            payload["review_digest"],
            payload["conclusion"],
        )
    except ValueError as exc:
        raise HTTPException(400, "Invalid or immutable adjudication") from exc
    from evaluation.track_b_review_provenance import record

    decision = next(
        a
        for a in store().adjudications()
        if a["page_id"] == source(index)["page_id"] and a["field_name"] == field
    )
    record(
        DATA,
        "ADJUDICATION",
        source(index)["page_id"],
        reviewer,
        source(index)["rendered_page_sha256"],
        decision,
        round_name="ADJUDICATION",
        reason=reason,
    )
    from evaluation.qualification_closure import refresh

    try:
        refresh()
    except (ValueError, KeyError, OSError, TypeError):
        return {
            "saved": True,
            "qualification_status": "PENDING_INPUT_REPAIR",
            "progress": progress(request),
        }
    return {"saved": True, "progress": progress(request)}


@router.get("/adjudication-queue", response_class=HTMLResponse)
def adjudication_queue(request: Request):
    identity(request)
    links = []
    for index, _ in enumerate(views()):
        try:
            _, reviews = adjudication_context(index, request)
            from packages.real_data_evaluation.release_truth import finalize_reviews

            registry = governed_registry()
            row = source(index)
            pending = finalize_reviews(
                reviews, {row["page_id"]: row}, registry, store().adjudications()
            ).get("pending", [])
            if not any(
                p["reason"] in {"PAGE_METADATA_DISAGREEMENT", "INDEPENDENT_ADJUDICATION_REQUIRED"}
                for p in pending
            ):
                continue
        except HTTPException as exc:
            if exc.status_code == 403:
                continue
            raise
        links.append(
            f'<li><a href="/qualification-review/adjudication/{index}">Page {index + 1}</a></li>'
        )
    return HTMLResponse(
        "<h1>Independent adjudication queue</h1><p>Only pages within your governed independent scope are shown.</p><ul>"
        + "".join(links)
        + "</ul>",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/second-review-queue", response_class=HTMLResponse)
def second_review_queue(request: Request):
    from packages.hitl_reduction.review_coordination import canonical_reviewer_id

    reviewer = canonical_reviewer_id(identity(request))
    registry = governed_registry()
    authorized = {canonical_reviewer_id(r) for r in registry.get("authorized_reviewers", [])}
    if registry.get("identity_verified") is not True or reviewer not in authorized:
        raise HTTPException(403, "Verified independent reviewer identity required")
    completed = store().completed()
    links = []
    for index, row in enumerate(views()):
        reviewers = {
            canonical_reviewer_id(r["reviewer_id"])
            for r in completed
            if r["page_id"] == row["page_id"]
            and r["source_sha256"] == row["rendered_page_sha256"]
            and canonical_reviewer_id(r["reviewer_id"]) in authorized
        }
        if len(reviewers) == 1 and reviewer not in reviewers:
            links.append(
                f'<li><a href="/qualification-review/page/{index}">Page {index + 1}</a></li>'
            )
    return HTMLResponse(
        "<h1>Independent second-review queue</h1><p>Only source pages are shown. Other reviewer observations remain hidden.</p><ul>"
        + "".join(links)
        + "</ul>",
        headers={"Cache-Control": "no-store"},
    )
