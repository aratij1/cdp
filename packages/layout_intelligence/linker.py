from __future__ import annotations

from packages.layout_intelligence.datatypes import valid
from packages.layout_intelligence.labels import label_firewall
from packages.layout_intelligence.models import (
    CanonicalLayoutCandidate, LabelMatch, LabelValueLinkEvidence, LayoutLine,
)


def link_values(label: LabelMatch, lines: list[LayoutLine], *, datatype: str,
                vocabulary: set[str]) -> list[CanonicalLayoutCandidate]:
    candidates = []
    label_line = lines[label.line_index]
    for index, line in enumerate(lines):
        if index == label.line_index:
            # Text following a colon is the only safe same-line value.
            parts = line.text.split(":", 1)
            texts = [parts[1].strip()] if len(parts) == 2 and parts[1].strip() else []
            relationship = "LABEL_RIGHT_VALUE"
        elif 0 < index - label.line_index <= 2:
            texts = [line.text.strip()]
            relationship = "LABEL_BELOW_VALUE"
        else:
            continue
        for text in texts:
            if not label_firewall(text, vocabulary):
                continue
            datatype_ok = valid(text, datatype)
            horizontal = max(0.0, line.bbox.x0 - label.bbox.x1)
            vertical = max(0.0, line.bbox.y0 - label.bbox.y1)
            same_row = abs((line.bbox.y0 + line.bbox.y1) - (label.bbox.y0 + label.bbox.y1)) <= max(12, label.bbox.y1-label.bbox.y0)
            same_column = abs(line.bbox.x0 - label.bbox.x0) <= max(40, (label.bbox.x1-label.bbox.x0) * .35)
            spatial = 1.0 if index == label.line_index else max(.35, .85 - .2 * (index-label.line_index-1))
            score = min(1.0, .32 * label.similarity + .38 * spatial + .30 * int(datatype_ok))
            evidence = LabelValueLinkEvidence(
                field_name=label.field_name, label_text=label.text, label_bbox=label.bbox,
                candidate_text=text, candidate_bbox=line.bbox,
                horizontal_distance=horizontal, vertical_distance=vertical,
                same_row=same_row, same_column=same_column, datatype_valid=datatype_ok,
                label_similarity=label.similarity, spatial_score=spatial,
                total_score=score, relationship=relationship,
            )
            candidates.append(CanonicalLayoutCandidate(
                field_name=label.field_name, value=text, confidence=score,
                bbox=line.bbox, original_label=label.text, matched_alias=label.alias,
                mapping_confidence=label.similarity, datatype_valid=datatype_ok,
                relationship_evidence=evidence,
            ))
    return sorted(candidates, key=lambda item: item.confidence, reverse=True)
