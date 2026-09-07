"""DEV-only competing pilots. Only the winner is eligible for later replay."""

import re
from datetime import date

from evaluation.non_name_strategy import MemberIdTopology, discover_member_ids


def discover(field, page, tokens):
    if field == "member_id":
        return discover_member_ids(
            tokens,
            form_type=page["form_type"],
            field_name=field,
            width=page["width"],
            height=page["height"],
            topology=MemberIdTopology(),
        )
    values = []
    if field == "patient_dob" and page["form_type"] == "UB":
        for i, t in enumerate(tokens):
            if not (
                0.012 <= t.x0 / page["width"] < t.x1 / page["width"] <= 0.129
                and 0.108 <= t.y0 / page["height"] < t.y1 / page["height"] <= 0.130
            ):
                continue
            m = re.fullmatch(r"([0-9]{8})_?", t.text.strip())
            if not m:
                continue
            raw = m[1]
            try:
                value = date(int(raw[4:]), int(raw[:2]), int(raw[2:4])).isoformat()
            except ValueError:
                continue
            values.append(
                {
                    "field_name": field,
                    "value": value,
                    "token_indices": [i],
                    "review_only": True,
                    "reason": "SOURCE_UB_BOX10_EIGHT_DIGITS_NO_CHARACTER_REPAIR",
                }
            )
    if field == "total_charge" and page["form_type"] == "CMS1500":
        for i, t in enumerate(tokens):
            if (
                0.59 <= t.x0 / page["width"] < t.x1 / page["width"] <= 0.72
                and 0.80 <= t.y0 / page["height"] < t.y1 / page["height"] <= 0.85
                and re.fullmatch(r"\$?[0-9,]+\.[0-9]{2}", t.text.strip())
            ):
                values.append(
                    {
                        "field_name": field,
                        "value": t.text,
                        "token_indices": [i],
                        "review_only": True,
                        "reason": "EXPLICIT_MONEY_ONLY_IN_CMS_CLAIM_TOTAL_CELL",
                    }
                )
    return values
