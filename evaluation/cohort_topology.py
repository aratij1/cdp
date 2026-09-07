"""Source-only repeated topology builder shared by isolated engineering pilots."""

from workers.field_candidates.source_reviewed_anchor import AUTHORITY, SourceReviewedAnchor

# Coordinates are normalized from a 1712 x 2214 reference frame, verified on
# 17 independent CMS pages and six UB pages. No values or claim aliases occur here.
REGIONS = {
    "CMS1500": {
        "patient_name": (40, 290, 605, 402),
        "insured_name": (1010, 290, 1540, 402),
        "member_id": (1010, 250, 1535, 330),
        "total_charge": (1010, 1770, 1230, 1880),
    },
    "UB": {
        "patient_name": (15, 145, 535, 226),
        "insured_name": (25, 1460, 525, 1555),
        "total_charge": (1190, 1250, 1400, 1330),
    },
}


def anchor_for(page, field, tokens):
    region = REGIONS.get(page["form_type"], {}).get(field)
    if region is None:
        return None
    sx, sy = page["width"] / 1712, page["height"] / 2214
    l, t, r, b = region[0] * sx, region[1] * sy, region[2] * sx, region[3] * sy
    label_region = (l, t, r, b)
    if page["form_type"] == "CMS1500" and field.endswith("name"):
        # Locate the source label and following address boundary inside the
        # reviewed form column; never use the other person's name column.
        labels = [
            x
            for x in tokens
            if l <= x.x0 < r
            and 250 * sy < x.y0 < 350 * sy
            and any(part in x.text.lower() for part in ("name", "namo", "namf", "nane", "namel"))
        ]
        if not labels:
            return None
        label = min(labels, key=lambda x: x.y0)
        t = label.y1 - 3 * sy
        boundaries = [
            x.y0
            for x in tokens
            if l <= x.x0 < r
            and t < x.y0 < 420 * sy
            and ("address" in x.text.lower() or x.text.lstrip().startswith(("5.", "7.")))
        ]
        if boundaries:
            b = min(boundaries) + 12 * sy  # OCR glyph boxes can overlap the printed rule.
    return SourceReviewedAnchor(
        page["source_sha256"],
        page["form_type"],
        field,
        label_region,
        (l, t, r, b),
        "form-topology-v1",
        AUTHORITY,
        page["rotation"],
    )
