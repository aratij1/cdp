"""Unstructured fallback when CMS-1500 template registration fails.

Hard blind REG is not always "bad geometry on a CMS-1500". Some pages are
freeform handwritten claim notes with **no form grid** (e.g. HJHO.015). SIFT /
LightGlue / DI page-corners cannot invent a template warp for those pages.

Stack for this path (cost-gated, never common path):
1. Azure DI prebuilt-read on the full page → observed ink text
2. Optional Azure OpenAI gpt-4o **text** JSON extract of critical fields from
   that DI text (not a geometry agent; not full-page vision by default)
3. Deterministic ``semantic_accept`` / span shaping before any STP accept

A vision geometry agent is the wrong tool here — there is no form to align.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from typing import Any

from PIL import Image, ImageOps

from packages.extraction_recovery.field_cascade import semantic_accept
from packages.extraction_recovery.span_selection import select_field_span

_CRITICAL = (
    "patient_name",
    "insured_name",
    "patient_dob",
    "insured_id_number",
    "total_charge",
)

_build_azure_review_adapter: Callable[[Any], Any] | None = None


def configure_azure_review_adapter_factory(factory: Callable[[Any], Any]) -> None:
    """Composition root injects Azure review VLM adapter construction."""
    global _build_azure_review_adapter
    _build_azure_review_adapter = factory


@dataclass(frozen=True)
class UnstructuredRegFallbackResult:
    attempted: bool
    configured: bool
    reason: str
    di_text: str | None = None
    fields: dict[str, str] = field(default_factory=dict)
    field_reasons: dict[str, str] = field(default_factory=dict)
    agent_used: bool = False


def unstructured_reg_fallback_enabled() -> bool:
    raw = (os.environ.get("CDP_UNSTRUCTURED_REG_FALLBACK") or "1").strip().casefold()
    return raw not in {"0", "false", "no", "off"}


def _agent_enabled() -> bool:
    raw = (os.environ.get("CDP_UNSTRUCTURED_REG_AGENT") or "1").strip().casefold()
    return raw not in {"0", "false", "no", "off"}


def _shape_field(field_name: str, raw: str | None) -> tuple[str | None, str]:
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text:
        return None, "EMPTY"
    datatype = {
        "patient_name": "PERSON_NAME",
        "insured_name": "PERSON_NAME",
        "patient_dob": "DATE",
        "insured_id_number": "ALPHANUMERIC_ID",
        "total_charge": "CURRENCY",
    }.get(field_name, "")
    span = select_field_span(text, datatype, field_name)
    selected = re.sub(r"\s+", " ", str(span.selected_text or text)).strip()
    ok, reason = semantic_accept(field_name, selected)
    if ok:
        return selected, f"SHAPED:{reason}"
    return None, f"UNSHAPED:{reason}"


_MAILROOM_SEP = re.compile(
    r"document\s*separator|\bDOCSEP\b|\*00BREAK00\*|"
    r"used\s+to\s+separate\s+each\s+transaction",
    re.IGNORECASE,
)
_MAILROOM_COVER = re.compile(
    r"\bunique\s*id\b|\blast\s*name\b|\bfirst\s*name\b|\brecvdate\b|"
    r"\barrival\s*date\b|\btracking\s*no\b",
    re.IGNORECASE,
)
_CLAIM_INK = re.compile(
    r"CMS-?\s*1500|UB-?\s*04|CMS-?\s*1450|TYPE\s*OF\s*BILL|"
    r"BIRTHDATE|PATIENT\s*NAME|TOTAL\s*CHARGE|NUCC|HCFA|"
    r"INSURED'?S?\s*UNIQUE\s*ID|BOX\s*28",
    re.IGNORECASE,
)
_BAD_NAME = re.compile(
    r"united\s*healthcare|martin,?\s*inc|buford|p\.?\s*o\.?\s*box|salt\s*lake|"
    r"sourcehov|tracking\s*no|recvdate|patch\s*ii|medicaid\s*resub|"
    r"insured.?s?\s*(?:i\.?d|name|unique)|patient.?s?\s*name|"
    r"illness|injury|pregnancy|\blmp\b|current\s*illness|"
    r"document\s*separator|unique\s*id|fax\s*(?:image|patch)|print\s*options|"
    r"\bof\s*b[il]{2,}\b|\bmed\.?\s*rec\b|\bmedical\s*rec|"
    r"therefore\s+better|original\s+source|image\s+quality|"
    r"\bifyes\b|\breturn\s+to\b|pompano\s*beach|procesunes|seinvices|"
    r"\breset\s*form\b|\bchampus\b|\bnucaag\b|"
    r"\b(?:hospital|hosp|medical\s*center|foundation|university|presbyterian|"
    r"columbia|kaiser|northern\s*light|mayo|counseling\s*center|corp\.?\s*dba|"
    r"llc|inc\.?|street|avenue|ave\b|road|rd\b|blvd|suite|floor)\b|"
    r"\b(?:npi|cpt|hcpcs|rev\s*cd|payer\s*name|group\s*name|employer)\b",
    re.IGNORECASE,
)
_NAME_STOP = {
    "OF",
    "BILL",
    "BLL",
    "THE",
    "AND",
    "FOR",
    "MED",
    "REC",
    "TOTAL",
    "PAGE",
    "FROM",
    "THROUGH",
    "CODE",
    "DATE",
    "TYPE",
    "BOX",
    "SEE",
    "USE",
    "OTHER",
    "PROCEDURE",
    "INSURANCE",
    "GROUP",
    "NO",
    "NUMBER",
    "UNIQUE",
    "PATIENT",
    "INSURED",
    "ADDRESS",
    "BIRTHDATE",
    "OCCURRENCE",
    "CONDITION",
    "PRINCIPAL",
    "ATTENDING",
    "OPERATING",
    "REMARKS",
    "VALUE",
    "CODES",
    "AMOUNT",
    "PAYER",
    "HEALTH",
    "PLAN",
    "TREATMENT",
    "AUTHORIZATION",
    "DOCUMENT",
    "CONTROL",
    "EMPLOYER",
    "ADMIT",
    "REASON",
    "PRINT",
    "OPTIONS",
    "FAX",
    "IMAGE",
    "ORIGINAL",
    "SOURCE",
    "STATE",
    "ACDT",
    "SEX",
    "PRO",
    "FEE",
    "ROOM",
    "BOARD",
    "SERV",
    "UNITS",
    "DESC",
    "DESCRIPTION",
    "BAD",
    "THEREFORE",
    "BETTER",
    "QUALITY",
    "CANNOT",
    "OBTAINED",
    "ORIGINAL",
    "SOURCE",
    "MAY",
    "BE",
    "FAX",
    "IMAGE",
    "IFYES",
    "RETURN",
    "YES",
    "POMPANO",
    "BEACH",
    "COMPLETE",
    "ITEM",
    "PLACE",
    "BELAREL",
    "FED",
    "TAX",
    "OMB",
    "NUCC",
    "HCFA",
    "CMS",
    "STATEMENT",
    "COVERS",
    "PERIOD",
    "SERVICES",
    "RESERVED",
    "LOCAL",
}


def _is_mailroom_only_page(di_text: str) -> bool:
    """True for DOCSEP / Patch-II covers with no claim form ink."""
    if _CLAIM_INK.search(di_text or ""):
        return False
    if _MAILROOM_SEP.search(di_text or ""):
        return True
    # Blank Unique-ID / Last-Name / First-Name mail covers (JJBP-class).
    hits = len(_MAILROOM_COVER.findall(di_text or ""))
    return hits >= 3 and not re.search(r"\b\d{2,5}\.\d{2}\b", di_text or "")


_US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}


def _looks_like_person_name(text: str) -> bool:
    raw = re.sub(r"\s+", " ", (text or "")).strip(" .|`^\t#-")
    if not raw or len(raw) < 4 or len(raw) > 60:
        return False
    if _BAD_NAME.search(raw):
        return False
    if re.search(r"\d", raw):  # any digit → not a clean person name
        return False
    if re.search(r"\b\d{5}(-\d{4})?\b", raw):
        return False
    tokens = [t.upper() for t in re.findall(r"[A-Za-z]{2,}", raw)]
    tokens = [t for t in tokens if t not in _NAME_STOP]
    if len(tokens) < 2:
        return False
    # Require LAST, FIRST (comma form) — facility OCR almost never has this.
    if "," in raw:
        left, _, right = raw.partition(",")
        left_toks = [t for t in re.findall(r"[A-Za-z]{2,}", left) if t.upper() not in _NAME_STOP]
        right_toks = [t for t in re.findall(r"[A-Za-z]{2,}", right) if t.upper() not in _NAME_STOP]
        if not (left_toks and right_toks and len(left_toks[0]) >= 2 and len(right_toks[0]) >= 2):
            return False
        # ``HEMPSTEAD, NY`` / ``BRONX, NY`` city-state addresses.
        if len(right_toks) == 1 and right_toks[0].upper() in _US_STATES:
            return False
        return True
    # Non-comma: both tokens ≥3 chars; reject long label phrases.
    if len(tokens) > 3:
        return False
    return all(len(t) >= 3 for t in tokens[:2])


def _heuristic_fields_from_di_text(di_text: str) -> dict[str, str]:
    """Cheap first pass: line-oriented heuristics before calling the agent."""
    out: dict[str, str] = {}
    if _is_mailroom_only_page(di_text):
        return out
    lines = [ln.strip() for ln in di_text.splitlines() if ln.strip()]

    # --- DOB: prefer lines near BIRTHDATE, then whole-line / inline / compact ---
    # DI often emits colon/pipe cell separators + sex suffix: ``02:28:1967MX``,
    # ``11 : 06 | 96``. Span assemble already shapes those; candidates must feed them.
    # ``!`` is a common OCR sub for ``/`` on handwritten Box 3 (``06:09! 18``).
    _dob_sep = r"[\s/.\-:|!]"
    dob_pats = (
        rf"\b\d{{1,2}}{_dob_sep}\d{{1,2}}{_dob_sep}\d{{2,4}}[MmFfXx]{{0,2}}\b",
        r"\b\d{1,2}\s+\d{1,2}\s+\d{2}\b",
    )
    dob_priority: list[str] = []
    for i, ln in enumerate(lines):
        if re.search(r"birth\s*date|birthdate|\bdob\b", ln, re.IGNORECASE):
            # UB-04 Box 10 ink is often several lines below the printed label.
            dob_priority.extend(lines[i : i + 20])
    # Second pool: compact MMDDYYYY(+sex) anywhere — only if priority pass fails.
    compact_pool = list(lines)

    def _dob_candidates_from_line(ln: str) -> list[str]:
        candidates: list[str] = []
        # Whole line first — assemble handles ``02:28:1967MX`` / ``11 | 06 : 96``.
        candidates.append(ln)
        if re.fullmatch(rf"\d{{1,2}}{_dob_sep}\d{{1,2}}{_dob_sep}\d{{2,4}}[MmFfXx]{{0,2}}", ln):
            candidates.append(ln)
        # Compact MMDDYYYY on its own line (UB-04 box 10), optional trailing sex.
        if re.fullmatch(r"\d{8}[MmFf]?", ln):
            candidates.append(ln[:8])
        # ``071220071M`` / ``05041977M`` — 8-digit DOB + optional junk digit + sex.
        for m in re.finditer(r"\b(\d{8})\d?[MmFf]\b", ln):
            candidates.append(m.group(1))
        # CMS Box 3 DI garble: checkbox/stem digit between MM and DD then year —
        # ``06113 /1992MX`` → 06/13/1992; also clean ``0613 /1992MX``.
        for m in re.finditer(
            r"\b(\d{2})1(\d{2})\s*/\s*(\d{4})[MmFfXx]{0,2}\b", ln
        ):
            candidates.append(f"{m.group(1)}/{m.group(2)}/{m.group(3)}")
        for m in re.finditer(
            r"\b(\d{2})(\d{2})\s*/\s*(\d{4})[MmFfXx]{0,2}\b", ln
        ):
            candidates.append(f"{m.group(1)}/{m.group(2)}/{m.group(3)}")
        for pat in dob_pats:
            candidates.extend(re.findall(pat, ln))
        # Compact handwritten MMDDYY / MMDDYYYY often glued (``092767`` / ``0927671``).
        for tok in re.findall(r"\b\d{6,8}\b", ln):
            if len(tok) == 7 and tok.startswith("0"):
                candidates.append(tok[:6])
            candidates.append(tok)
        return candidates

    def _try_shape_dob(raw: str, *, max_year: int) -> str | None:
        shaped, reason = _shape_field("patient_dob", raw)
        if not shaped or "FUTURE" in reason:
            return None
        year = re.findall(r"\d{4}", shaped)
        if year and int(year[-1]) > max_year:
            return None
        if year and int(year[-1]) < 1920:
            return None
        return shaped

    # Birthdate-proximate lines may be pediatric (through current year). Unlabeled
    # general scan keeps a stricter cap so fax/claim dates (``08/18/2026``) stay out.
    _year_now = date.today().year
    _year_labeled = _year_now
    _year_general = min(2015, _year_now)

    def _scan_dob_lines(pool: list[str], *, max_year: int) -> str | None:
        seen: set[str] = set()
        for ln in pool:
            if ln in seen:
                continue
            seen.add(ln)
            if re.search(
                r"recv|arrival|tracking|patch\s*ii|creation\s*date|\bfax\b",
                ln,
                re.IGNORECASE,
            ):
                continue
            for raw in _dob_candidates_from_line(ln):
                shaped = _try_shape_dob(raw, max_year=max_year)
                if shaped:
                    return shaped
        return None

    if dob_priority:
        got = _scan_dob_lines(dob_priority, max_year=_year_labeled)
        if got:
            out["patient_dob"] = got
    if "patient_dob" not in out:
        got = _scan_dob_lines(lines[:80], max_year=_year_general)
        if got:
            out["patient_dob"] = got
    # Compact MMDDYYYY(+sex) full-document pass when label-proximate scan missed.
    if "patient_dob" not in out:
        for ln in compact_pool:
            if re.search(r"recv|arrival|tracking|patch\s*ii|creation\s*date|omb\b", ln, re.IGNORECASE):
                continue
            # Prefer clean standalone compact DOB lines only (high precision).
            if not re.fullmatch(r"\d{8}[MmFf]?", ln.strip()):
                # Also accept ``04121987 OCCURRENCE`` style.
                m = re.match(r"^(\d{8})[MmFf]?(?:\s|$)", ln.strip())
                if not m:
                    continue
                raw = m.group(1)
            else:
                raw = ln.strip()[:8]
            # Compact 8-digit lines are high precision — allow pediatric years.
            shaped = _try_shape_dob(raw, max_year=_year_labeled)
            if shaped:
                out["patient_dob"] = shaped
                break

    # --- ID: prefer tokens near INSURED'S UNIQUE ID; reject NPI / EIN / zip ---
    id_priority: list[str] = []
    for i, ln in enumerate(lines):
        if re.search(
            r"unique\s*id|insured.?s?\s*i\.?d|member\s*id|1a\.\s*insured",
            ln,
            re.IGNORECASE,
        ):
            # CMS 1a labels often span many checkbox lines before the ink id.
            seen_patient = False
            for ln2 in lines[i : i + 24]:
                id_priority.append(ln2)
                if re.search(r"patient'?s?\s*name|2\.\s*patient", ln2, re.IGNORECASE):
                    seen_patient = True
                    break
            if seen_patient:
                continue
    id_candidates: list[tuple[int, str]] = []  # (priority_rank, value)

    def _consider_id(tok: str, rank: int) -> None:
        # NPI is 10 digits starting 1–7; keep 0/8/9-leading member ids.
        digits = re.sub(r"\D", "", tok)
        if len(digits) == 10 and digits[0] in "1234567" and tok.isdigit():
            return
        if len(digits) == 9 and digits.startswith("58"):  # EIN-ish
            return
        if len(digits) == 7:  # truncated EIN / noise
            return
        # Pure 9-digit zip / EIN soup loses to alphanumeric CMS 1a ids.
        shaped, _ = _shape_field("insured_id_number", tok)
        if shaped:
            id_candidates.append((rank, shaped))

    for rank, pool in ((0, id_priority), (1, lines)):
        for ln in pool:
            if re.search(
                r"\bnpi\b|\btax\b|fed\.?\s*tax|federal\s*tax|buford|martin,?\s*inc|\bhealthcare\b|"
                r"tracking|sourcehov|patch\s*ii|salt\s*lake|p\.?\s*o\.?\s*box|"
                r"optum|united\s*behavioral|zip\s*code|account\s*no",
                ln,
                re.IGNORECASE,
            ):
                continue
            address_line = bool(
                re.search(
                    r"\b(?:street|avenue|ave\b|road|rd\b|blvd|suite|bronx|brooklyn|"
                    r"sacramento|atlanta|hempstead)\b",
                    ln,
                    re.IGNORECASE,
                )
            )
            # Digit member ids + alphanumeric CMS 1a ids (``M01406484``, ``OSC76422826``)
            # + hyphenated SSN-shaped 1a ink (``569-90-4716``).
            toks = re.findall(r"\b\d{7,12}\b", ln)
            toks.extend(re.findall(r"\b[A-Za-z]{1,3}\d{6,11}\b", ln))
            toks.extend(re.findall(r"\b\d{3}-\d{2}-\d{4}\b", ln))
            if address_line:
                # Freeform CMS notes put member id at the start of an address soup line.
                if toks and ln.lstrip().startswith(toks[0]):
                    _consider_id(toks[0], rank)
                continue
            for tok in toks:
                _consider_id(tok, rank)
    # Drop DOB-shaped digit strings that leaked into the ID pool.
    dob_digits = re.sub(r"\D", "", out.get("patient_dob") or "")
    dob_compact = {dob_digits, dob_digits[-6:]} if len(dob_digits) >= 6 else set()
    id_candidates = [
        pair
        for pair in id_candidates
        if re.sub(r"\D", "", pair[1]) not in dob_compact
        and not (
            # Compact MMDDYYYY / MMDDYY alone is a DOB, not a member id.
            # Alphanumeric CMS 1a ids (``M01406484``) must not be stripped.
            pair[1].isdigit()
            and len(re.sub(r"\D", "", pair[1])) in {6, 8}
            and re.fullmatch(r"\d{6}|\d{8}", re.sub(r"\D", "", pair[1]))
            and int(re.sub(r"\D", "", pair[1])[:2]) <= 12
        )
    ]
    if id_candidates:
        id_candidates.sort(
            key=lambda pair: (
                pair[0],
                # Prefer letter+digit CMS 1a ids (``M01406484``, ``OSC76422826``)
                # over account nos (``P153…``) and over zip/EIN digit soup.
                (
                    0
                    if re.fullmatch(r"[A-Za-z]{1,3}\d{6,11}", pair[1])
                    and pair[1][0].upper() in "MWHKC"
                    else 1
                    if re.fullmatch(r"[A-Za-z]{1,3}\d{6,11}", pair[1])
                    else 2
                ),
                0 if pair[1].startswith("0") else 1,
                abs(len(re.sub(r"\D", "", pair[1])) - 9),
                len(pair[1]),
            )
        )
        out["insured_id_number"] = id_candidates[0][1]

    # --- Name: prefer LAST, FIRST islands; never facility / form-label soup ---
    name_priority: list[str] = []
    for i, ln in enumerate(lines):
        if re.search(
            r"patient'?s?\s*name|insured'?s?\s*name|patient\s*address",
            ln,
            re.IGNORECASE,
        ):
            name_priority.extend(lines[i : i + 6])
    name_scan = name_priority + lines[:80]

    def _name_candidates(ln: str) -> list[str]:
        cleaned = re.sub(r"^\s*[a-dA-D0-9|^`.\-]\s+", "", ln).strip()
        cleaned = re.sub(r"^\s*[a-d]\s+", "", cleaned).strip()
        out_c: list[str] = []
        for m in re.finditer(
            r"\b([A-Za-z][A-Za-z'\-]{1,24},\s*[A-Za-z][A-Za-z'\-]+(?:\s+[A-Z]\.?)?)",
            cleaned,
        ):
            out_c.append(m.group(1))
        # Freeform ``ATTA Dee-Dee`` / ``ATTA Dec-Dee`` → normalize to comma form.
        m = re.match(
            r"^([A-Z]{2,})\s+([A-Z][a-z]{1,20}(?:-[A-Z][a-z]{1,20})?)\b",
            cleaned,
        )
        if m:
            out_c.append(f"{m.group(1)}, {m.group(2).upper()}")
        if not out_c:
            out_c.append(cleaned)
        return out_c

    picked_name = False
    # Pass 1: comma-form person names only (high precision).
    for ln in name_scan:
        if "," not in ln:
            continue
        for probe in _name_candidates(ln):
            if "," not in probe or not _looks_like_person_name(probe):
                continue
            shaped, _ = _shape_field("patient_name", probe)
            if shaped and _looks_like_person_name(shaped):
                out["patient_name"] = shaped
                out["insured_name"] = shaped
                picked_name = True
                break
        if picked_name:
            break
    # Pass 2: non-comma FIRST LAST — labels first, then short freeform header lines.
    if not picked_name:
        freeform_headers = []
        for ln in lines[:25]:
            name_prefix = bool(
                re.match(
                    r"^[A-Z]{2,}\s+[A-Z][a-z]{1,20}(?:-[A-Z][a-z]{1,20})?\b",
                    ln,
                )
            )
            if name_prefix:
                freeform_headers.append(ln)
                continue
            if len(ln) <= 40 and not re.search(
                r"\d{5}|\bstreet\b|\bavenue\b|\bblvd\b|united|optum|box", ln, re.I
            ):
                freeform_headers.append(ln)
        for ln in name_priority + freeform_headers:
            if "," in ln and not re.match(
                r"^[A-Z]{2,}\s+[A-Z][a-z]", ln
            ):
                # Comma lines handled in pass 1; allow LAST First-Second still.
                continue
            for probe in _name_candidates(ln):
                if not _looks_like_person_name(probe):
                    continue
                shaped, _ = _shape_field("patient_name", probe)
                if shaped and _looks_like_person_name(shaped):
                    out["patient_name"] = shaped
                    out["insured_name"] = shaped
                    break
            if "patient_name" in out:
                break

    # Charge: prefer TOTAL CHARGE / Box 28 / UB-04 box 47 totals.
    # DI often emits ``780 00`` / ``231-00`` / ``$ 780 00`` instead of ``780.00``.
    # Space/dash decimals are ONLY accepted on total/$ cue lines (never on DOB soup).
    # Do NOT use bare ``$\\d`` as a cue — service-line date rows (``$11 01 24``) and
    # diagnosis crumbs (``F 43.24``) otherwise become false Box 28 totals.
    cue_idx = [
        i
        for i, ln in enumerate(lines)
        if re.search(
            r"total\s*charge|box\s*28|totals?['’s]?t?i?\b|pro\s*fee",
            ln,
            re.IGNORECASE,
        )
    ]
    # CMS freeform: service-line totals like ``315 00 0 00 315 00``.
    for i, ln in enumerate(lines):
        if re.search(r"\b\d{2,5}\s+00\s+0\s+00\s+\d{2,5}\s+00\b", ln):
            cue_idx.append(i)
    cue_lines: list[str] = []
    seen_cue: set[str] = set()
    for i in sorted(set(cue_idx)):
        # Amount may sit above the TOTAL CHARGE label (DI reading order).
        for ln in lines[max(0, i - 8) : i + 4]:
            if ln not in seen_cue:
                seen_cue.add(ln)
                cue_lines.append(ln)
    # Also promote standalone dollar stems that sit after repeated line charges
    # (``220 00`` × N then bare ``1320`` / ``1320 00| 3`` / ``23700.``).
    # Never promote DOB soup (``06113 /1992MX`` / bare ``11992`` year fragments).
    dob_line_idx = {
        i
        for i, ln in enumerate(lines)
        if re.search(r"birth\s*date|birthdate|\bdob\b", ln, re.IGNORECASE)
    }
    dob_near: set[str] = set()
    for i in dob_line_idx:
        dob_near.update(lines[max(0, i - 1) : i + 12])

    def _is_date_like_charge_line(ln: str) -> bool:
        if re.search(r"/\s*(?:19|20)\d{2}|[MmFfXx]{1,2}\s*$", ln):
            return True
        if ln in dob_near and re.fullmatch(r"\d{4,5}", ln):
            # Bare year / year-with-leading-stem next to DOB labels (``11992``).
            # Do not reject legitimate bare totals like ``1320`` in the same window.
            try:
                n = int(ln)
            except ValueError:
                return False
            if 1900 <= n <= 2099:
                return True
            if len(ln) == 5 and 1900 <= int(ln[1:]) <= 2099:
                return True
        return False

    labeled_charge_locked = False
    for i, ln in enumerate(lines):
        if _is_date_like_charge_line(ln):
            continue
        if re.fullmatch(r"\$?\s*\d{3,6}(?:\s*00)?(?:\s*[|./].*)?", ln):
            m = re.match(r"\$?\s*(\d{3,6})(?:\s*00)?", ln)
            stem = m.group(1) if m else ""
            if 3 <= len(stem) <= 6 and not (stem.startswith("9") and len(stem) == 5):
                if ln not in seen_cue:
                    seen_cue.add(ln)
                    cue_lines.append(ln)
        # ``$ 300 100`` / ``$ 300`` far from Box 28 label (DI reading-order drift).
        if re.fullmatch(r"\$\s*\d{1,5}(?:\s+\d{2,4})?\s*\$?", ln):
            if ln not in seen_cue:
                seen_cue.add(ln)
                cue_lines.append(ln)
    charge_lines = cue_lines + [
        ln for ln in lines if re.search(r"\bcharge\b", ln, re.IGNORECASE)
    ]
    seen_charge: set[str] = set()
    # 0 = labeled Box 28 / TOTAL CHARGE; 1 = opportunistic bare stem / scan.
    best_charge_rank = 99

    def _take_charge(
        raw: str, *, allow_tiny: bool = False, rank: int = 1
    ) -> None:
        nonlocal out, best_charge_rank, labeled_charge_locked
        if raw in seen_charge or raw == "0.00":
            return
        # Diagnosis crumbs (``F43.24`` / ``F 43.24``) and CPT codes are not totals.
        if re.fullmatch(r"9\d{4}(?:\.00)?", re.sub(r"[^\d.]", "", raw) or ""):
            return
        seen_charge.add(raw)
        shaped, reason = _shape_field("total_charge", raw)
        if not shaped and allow_tiny and reason.startswith("UNSHAPED:"):
            # UB-04 session fees ($1–$12) on TOTALS cue — semantic_accept rejects
            # as TINY / POS_LIKE without geometry; cue corroboration is enough.
            if "TINY" in reason or "POS_LIKE" in reason:
                try:
                    amt = float(raw)
                except ValueError:
                    amt = None
                if amt is not None and 0.01 <= amt <= 500.0:
                    shaped, reason = raw, f"SHAPED:UNSTRUCTURED_TOTALS_CUE:{reason}"
        if not shaped:
            return
        # Reject CPT-shaped 90xxx soups, not legitimate mid/large claim totals.
        try:
            digits_only = re.sub(r"\D", "", shaped)
            if len(digits_only) == 5 and digits_only.startswith("9") and shaped.endswith(".00"):
                return
            if float(shaped) >= 500000:
                return
        except ValueError:
            pass
        prev = out.get("total_charge")
        if prev is None:
            out["total_charge"] = shaped
            best_charge_rank = rank
            if rank == 0:
                labeled_charge_locked = True
            return
        # Labeled Box 28 / TOTAL CHARGE wins over larger opportunistic stems
        # (``11992`` DOB year must not beat ``$ 23300`` → 233.00).
        if rank < best_charge_rank:
            out["total_charge"] = shaped
            best_charge_rank = rank
            if rank == 0:
                labeled_charge_locked = True
            return
        if labeled_charge_locked and rank > 0:
            return
        if rank > best_charge_rank:
            return
        try:
            if float(shaped) >= float(prev):
                out["total_charge"] = shaped
        except ValueError:
            pass

    for ln in cue_lines:
        # Skip DOB-shaped colon fragments and ICD diagnosis crumbs.
        if re.search(r"\b\d{1,2}:\d{2}:\d{2,4}", ln):
            continue
        if re.search(r"\bF\s*\d{2}\.\d{2}\b", ln, re.IGNORECASE):
            continue
        if _is_date_like_charge_line(ln):
            continue
        labeled = bool(
            re.search(r"total\s*charge|box\s*28|totals?['’s]?t?i?\b", ln, re.I)
        )
        rank = 0 if labeled else 1
        for m in re.finditer(r"\$?\s*(\d{1,5})[.,;:](\d{2})\b", ln):
            _take_charge(f"{m.group(1)}.{m.group(2)}", allow_tiny=True, rank=rank)
        for m in re.finditer(r"\$?\s*(\d{1,5})[ \-](\d{2})(?![\d-])\b", ln):
            # Reject SSN-shaped ``569-90-4716`` (dash then more digits).
            whole = int(m.group(1))
            if whole > 20000:
                continue
            _take_charge(f"{m.group(1)}.{m.group(2)}", allow_tiny=True, rank=rank)
        # DI often drops the decimal on Box 28: ``$ 23700`` / ``TOTAL CHARGE 23700``.
        for m in re.finditer(r"\$\s*(\d{3,6})\b", ln):
            digits = m.group(1)
            if len(digits) >= 4 and digits.endswith("00"):
                dollars, cents = digits[:-2], digits[-2:]
                try:
                    if 1 <= int(dollars) <= 200000:
                        # Dollar stem on cue lines is strong Box 28 evidence.
                        _take_charge(
                            f"{int(dollars)}.{cents}", allow_tiny=True, rank=0
                        )
                except ValueError:
                    pass
        # ``$ 300 100`` — dollars + OCR junk trail (≥100), not space-cents / glued.
        for m in re.finditer(r"\$\s*(\d{1,5})\s+(\d{3,4})\b", ln):
            dollars = int(m.group(1))
            try:
                if 1 <= dollars <= 200000:
                    _take_charge(f"{dollars}.00", allow_tiny=True, rank=0)
            except ValueError:
                pass
        for m in re.finditer(
            r"(?:total\s*charge|box\s*28)\D{0,12}(\d{3,6})\b", ln, re.IGNORECASE
        ):
            digits = m.group(1)
            if len(digits) >= 4 and digits.endswith("00"):
                dollars, cents = digits[:-2], digits[-2:]
                try:
                    if 1 <= int(dollars) <= 200000:
                        _take_charge(
                            f"{int(dollars)}.{cents}", allow_tiny=True, rank=0
                        )
                except ValueError:
                    pass
        # Bare dollars on the line after TOTAL CHARGE cue (``1320`` / ``1320 00| 3``).
        # Also ``23700`` / ``23700.`` when DI drops the decimal on Box 28.
        # Never treat form labels (``28. TOTAL CHARGE``) as the amount itself.
        bare = re.match(r"\$?\s*(\d{2,6})(?:\s*00)?(?:\s*[|./].*)?$", ln)
        if bare and not re.search(r"[A-Za-z]{3,}", ln):
            digits = bare.group(1)
            if digits.startswith("9") and len(digits) == 5:
                continue  # CPT
            if len(digits) >= 4 and digits.endswith("00"):
                dollars, cents = digits[:-2], digits[-2:]
            else:
                dollars, cents = digits, "00"
            try:
                if 1 <= int(dollars) <= 200000:
                    _take_charge(
                        f"{int(dollars)}.{cents}", allow_tiny=True, rank=rank
                    )
            except ValueError:
                pass
        # UB-04 ``TOTALS 2420968`` — amount stored as integer cents.
        for m in re.finditer(r"totals?t?i?\s+(\d{4,8})\b", ln, re.IGNORECASE):
            digits = m.group(1)
            if len(digits) < 4:
                continue
            dollars, cents = digits[:-2], digits[-2:]
            if dollars.startswith("0") and len(dollars) > 1:
                continue
            try:
                if int(dollars) > 200000:
                    continue
            except ValueError:
                continue
            _take_charge(f"{int(dollars)}.{cents}", allow_tiny=True, rank=0)
    if "total_charge" not in out:
        for ln in charge_lines + lines:
            # Never harvest colon-date fragments or ICD crumbs as currency.
            if re.search(r"\b\d{1,2}:\d{2}(?::\d{2,4})?\b", ln) and not re.search(
                r"total\s*charge|\$\s*\d", ln, re.IGNORECASE
            ):
                continue
            if re.search(r"\bF\s*\d{2}\.\d{2}\b", ln, re.IGNORECASE):
                continue
            if re.search(r"\bF\d{2}|cpt\b|908\d{2}|ndc\b", ln, re.IGNORECASE):
                if not re.search(r"total\s*charge", ln, re.IGNORECASE):
                    continue
            for m in re.finditer(r"\$?\s*(\d{1,5})[.,;:](\d{2})\b", ln):
                dollars, cents = int(m.group(1)), int(m.group(2))
                # Without a TOTAL CHARGE cue, MM.DD DOB fragments (``02.28``)
                # must not become Box 28 — keep HITL rather than false STP.
                if not cue_lines and dollars <= 12 and 1 <= cents <= 31:
                    continue
                _take_charge(f"{m.group(1)}.{m.group(2)}")
            if "total_charge" in out and ln in (charge_lines[:5] or lines[:5]):
                break
    # FA=0: if DOB never shaped, drop tiny MM.DD-like charges that leaked from
    # birthdate ink (``02.28``) even when a weak cue admitted them.
    charge = out.get("total_charge")
    if charge and "patient_dob" not in out:
        m = re.fullmatch(r"(\d{1,2})\.(\d{2})", charge)
        if m and int(m.group(1)) <= 12 and 1 <= int(m.group(2)) <= 31:
            try:
                if float(charge) < 13.0:
                    del out["total_charge"]
            except ValueError:
                pass
    return out


def _agent_should_run(fields: dict[str, str]) -> bool:
    if not _agent_enabled():
        return False
    if "patient_dob" not in fields or "patient_name" not in fields:
        return True
    if "insured_id_number" not in fields or "total_charge" not in fields:
        return True
    id_digits = re.sub(r"\D", "", fields.get("insured_id_number") or "")
    # Phone (10) or truncated EIN fragments (7) are suspicious — ask the agent.
    if len(id_digits) in {7, 10} or not (8 <= len(id_digits) <= 12):
        return True
    charge = fields.get("total_charge") or ""
    return bool(re.fullmatch(r"\$?\d{1,2}\.\d{2}", charge))


def _shape_agent_json(parsed: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(parsed, dict):
        return out
    for key in _CRITICAL:
        raw = parsed.get(key)
        if raw is None:
            continue
        shaped, _ = _shape_field(key, str(raw))
        if shaped:
            out[key] = shaped
    return out


def _agent_prompt(di_text: str) -> str:
    return (
        "Extract CMS-1500 critical claim fields from the OCR text of a medical "
        "claim page that may be freeform (not a filled form grid). "
        "Return strict JSON with keys: patient_name, insured_name, patient_dob, "
        "insured_id_number, total_charge. Use null when not clearly present. "
        "Do not invent values. Dates as MM/DD/YYYY when possible. "
        "insured_id_number is the subscriber/member id (not phone, NPI, or tax id). "
        "total_charge is the claim total (not a diagnosis code).\n\nOCR text:\n"
        f"{di_text[:6000]}"
    )


def _agent_fields_via_azure(di_text: str, cfg: Any) -> dict[str, str]:
    if _build_azure_review_adapter is None:
        return {}
    if not getattr(cfg, "azure_ai_evaluation_enabled", False):
        return {}
    try:
        adapter = _build_azure_review_adapter(cfg)
    except (OSError, ValueError, RuntimeError, TypeError, AttributeError, KeyError):
        return {}
    client = getattr(adapter, "_client", None)
    endpoint = getattr(adapter, "_endpoint", None)
    deployment = getattr(adapter, "_deployment", None) or getattr(
        cfg, "azure_ai_evaluation_deployment", None
    )
    api_version = getattr(cfg, "azure_openai_api_version", None) or "2024-10-21"
    if client is None or not endpoint or not deployment:
        return {}
    url = (
        f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions"
        f"?api-version={api_version}"
    )
    payload = {
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": "You extract claim fields. Reply with JSON only.",
            },
            {"role": "user", "content": _agent_prompt(di_text)},
        ],
        "response_format": {"type": "json_object"},
    }
    try:
        response = client.post(url, json=payload)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return _shape_agent_json(json.loads(content))
    except Exception:  # noqa: BLE001 — 401/timeout/parse must not crash REG path
        return {}


def _agent_fields_via_claude(di_text: str, cfg: Any) -> dict[str, str]:
    """Text-only Claude fallback when Azure OpenAI review key is unavailable."""
    api_key = (
        getattr(cfg, "anthropic_api_key", None)
        or os.environ.get("ANTHROPIC_API_KEY")
        or ""
    ).strip()
    if not api_key:
        return {}
    model = (
        getattr(cfg, "anthropic_model", None)
        or os.environ.get("ANTHROPIC_MODEL")
        or "claude-sonnet-4-6"
    )
    endpoint = (
        getattr(cfg, "anthropic_messages_endpoint", None)
        or os.environ.get("ANTHROPIC_MESSAGES_ENDPOINT")
        or "https://api.anthropic.com/v1/messages"
    )
    try:
        import httpx
    except ImportError:
        return {}
    payload = {
        "model": model,
        "max_tokens": 512,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": (
                    "You extract claim fields. Reply with JSON only.\n\n"
                    + _agent_prompt(di_text)
                ),
            }
        ],
    }
    try:
        with httpx.Client(timeout=45.0) as client:
            response = client.post(
                endpoint.rstrip("/"),
                json=payload,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            response.raise_for_status()
            body = response.json()
        text_parts = [
            block.get("text") or ""
            for block in (body.get("content") or [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        raw = "\n".join(text_parts).strip()
        # Tolerate optional markdown fences.
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        return _shape_agent_json(json.loads(raw))
    except Exception:  # noqa: BLE001
        return {}


def _local_ocr_cms_box3_text(image: Image.Image) -> str:
    """Tesseract a CMS-1500 Box 2–3 crop when DI leaves DOB blank.

    Azure DI sometimes splits handwritten ``06/09/18`` into ``09 --`` + ``18 M``
    and drops the month. Include patient-name columns — MM digits OCR more
    reliably next to the name than in a DOB-only slice.
    """
    try:
        rgb = image.convert("RGB")
        # Bi-level WhiteIsZero scans need inversion for Tesseract.
        extrema = rgb.convert("L").getextrema()
        work = (
            ImageOps.invert(rgb)
            if extrema and extrema[0] < 32 and extrema[1] > 220
            else rgb
        )
        w, h = work.size
        if w < 80 or h < 80:
            return ""
        # Patient name (Box 2) through DOB/sex (Box 3).
        box = (
            int(w * 0.02),
            int(h * 0.10),
            int(w * 0.72),
            int(h * 0.24),
        )
        crop = work.crop(box)
        crop = crop.resize((max(1, crop.width * 2), max(1, crop.height * 2)))
        texts: list[str] = []
        with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp:
            crop.save(tmp.name, format="PNG")
            for psm in ("6", "11"):
                proc = subprocess.run(
                    ["tesseract", tmp.name, "stdout", "--psm", psm],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
                chunk = (proc.stdout or "").strip()
                if chunk:
                    texts.append(chunk)
        return "\n".join(texts)
    except Exception:  # noqa: BLE001
        return ""


def _dob_from_local_box3(image: Image.Image) -> str | None:
    """Return a shaped patient_dob from local Box 3 OCR, or None."""
    text = _local_ocr_cms_box3_text(image)
    if not text:
        return None
    # Prefer birthdate-labeled fragment; otherwise scan the crop text alone.
    labeled = "3. PATIENT'S BIRTH DATE\n" + text
    fields = _heuristic_fields_from_di_text(labeled)
    dob = fields.get("patient_dob")
    if dob:
        return dob
    fields = _heuristic_fields_from_di_text(text)
    return fields.get("patient_dob")


def _agent_fields_from_di_text(di_text: str, *, settings: Any | None = None) -> dict[str, str]:
    """Text JSON extract from DI ink (Azure gpt-4o, then Claude if needed)."""
    try:
        from packages.settings import get_settings
    except ImportError:
        return {}
    cfg = settings or get_settings()
    out = _agent_fields_via_azure(di_text, cfg)
    if out:
        return out
    return _agent_fields_via_claude(di_text, cfg)


def run_unstructured_reg_fallback(
    image: Image.Image,
    *,
    settings: Any | None = None,
) -> UnstructuredRegFallbackResult:
    """Full-page DI (+ optional text agent) after template registration fails."""
    if not unstructured_reg_fallback_enabled():
        return UnstructuredRegFallbackResult(
            attempted=False,
            configured=False,
            reason="UNSTRUCTURED_REG_FALLBACK_DISABLED",
        )
    try:
        from packages.azure_di_contracts import (
            azure_document_intelligence_configured,
            build_azure_read_engine,
        )
        from packages.recovery.azure_di_meter import record_azure_di_call
        from packages.settings import get_settings
    except Exception as exc:  # noqa: BLE001
        return UnstructuredRegFallbackResult(
            attempted=False,
            configured=False,
            reason=f"IMPORT_ERROR:{type(exc).__name__}",
        )
    cfg = settings or get_settings()
    if not azure_document_intelligence_configured(cfg):
        return UnstructuredRegFallbackResult(
            attempted=False,
            configured=False,
            reason="AZURE_DI_NOT_CONFIGURED",
        )
    try:
        engine = build_azure_read_engine(cfg)
        backend = getattr(engine, "_backend", None)
        if backend is None or not hasattr(backend, "analyze_raw"):
            return UnstructuredRegFallbackResult(
                attempted=False,
                configured=True,
                reason="AZURE_DI_BACKEND_NO_RAW",
            )
        stream = BytesIO()
        image.convert("RGB").save(stream, format="PNG")
        payload = backend.analyze_raw(stream.getvalue())
        record_azure_di_call(kind="other", ok=True, detail="UNSTRUCTURED_REG_PAGE_READ")
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(Exception):
            record_azure_di_call(
                kind="other",
                ok=False,
                detail=f"UNSTRUCTURED_REG_ERROR:{type(exc).__name__}",
            )
        return UnstructuredRegFallbackResult(
            attempted=True,
            configured=True,
            reason=f"AZURE_DI_ERROR:{type(exc).__name__}:{str(exc)[:120]}",
        )

    di_text = str((payload.get("analyzeResult") or {}).get("content") or "").strip()
    if not di_text:
        return UnstructuredRegFallbackResult(
            attempted=True,
            configured=True,
            reason="AZURE_DI_EMPTY_CONTENT",
            di_text=None,
        )

    fields = _heuristic_fields_from_di_text(di_text)
    agent_used = False
    if _agent_should_run(fields):
        try:
            agent_fields = _agent_fields_from_di_text(di_text, settings=cfg)
        except Exception:  # noqa: BLE001
            agent_fields = {}
        if agent_fields:
            agent_used = True
            # Agent wins on gaps, form-junk names, suspicious phone-as-ID / tiny charge.
            for key, value in agent_fields.items():
                if key not in fields:
                    fields[key] = value
                    continue
                if key in {"patient_name", "insured_name"} and (
                    _BAD_NAME.search(fields[key] or "")
                    or not _looks_like_person_name(fields[key])
                ):
                    fields[key] = value
                elif key == "insured_id_number":
                    cur = re.sub(r"\D", "", fields[key])
                    if len(cur) in {7, 10} or not (8 <= len(cur) <= 12):
                        fields[key] = value
                elif key == "total_charge" and re.fullmatch(
                    r"\$?\d{1,2}\.\d{2}", fields[key]
                ):
                    fields[key] = value

    # DI often blanks handwritten Box 3 (``09 --`` / ``18 M``). Local crop OCR
    # recovers month+day+year from ink when the text agent still has no DOB.
    if "patient_dob" not in fields:
        local_dob = _dob_from_local_box3(image)
        if local_dob:
            fields["patient_dob"] = local_dob

    if not fields:
        return UnstructuredRegFallbackResult(
            attempted=True,
            configured=True,
            reason="UNSTRUCTURED_NO_SHAPED_FIELDS",
            di_text=di_text,
            agent_used=agent_used,
        )
    # Product FA=0: drop placeholder / form-junk before promote.
    try:
        from packages.product_gates.accuracy_accept_policy import filter_auto_fields

        fields, blocked = filter_auto_fields(fields)
        if blocked and not fields:
            return UnstructuredRegFallbackResult(
                attempted=True,
                configured=True,
                reason="PRODUCT_ACCURACY_ACCEPT_POLICY:" + ",".join(blocked),
                di_text=di_text,
                agent_used=agent_used,
            )
    except Exception:  # noqa: BLE001
        blocked = ()
    reasons = {k: "UNSTRUCTURED_DI_SHAPED" for k in fields}
    for code in blocked:
        reasons[f"_policy:{code}"] = code
    return UnstructuredRegFallbackResult(
        attempted=True,
        configured=True,
        reason="UNSTRUCTURED_REG_FALLBACK_OK",
        di_text=di_text,
        fields=fields,
        field_reasons=reasons,
        agent_used=agent_used,
    )
