"""CMS-1500 02/12 value boxes in normalized public NUCC reference coordinates.

These are form geometry, never regions fitted to engineering source labels.
The caller must register to the integrity-checked public canonical image first.
Box 24J is row-scoped: conflicting rendering NPIs cannot become one header value.
"""
from __future__ import annotations

from packages.templates.models import FieldRegion, Template

CANONICAL_IMAGE_SHA256 = "8b77133ac2fc84817d855073f0e26b7ecd20f1da6b6a6a099c01d06f565d113e"
CANONICAL_PIXEL_SHA256 = "c2aaa950399cb151836097f472b51dfbfc162d6feafcbd6b512bd334e416ac8e"
GEOMETRY_VERSION = "cms1500-nucc-02-12-value-boxes-v4"
# field: (printed box, processor, normalized subregions)
BOXES = {
    "patient_name": ("2", "text", ((.092,.192,.389,.207),)),
    "patient_dob": ("3", "date", ((.399,.198,.500,.207),)),
    "insured_name": ("4", "text", ((.605,.192,.917,.207),)),
    "insured_id_number": ("1a", "text", ((.605,.167,.917,.180),)),
    "patient_address": ("5", "text", ((.092,.219,.389,.238),(.092,.245,.389,.264),(.092,.275,.221,.291))),
    "insured_address": ("7", "text", ((.605,.219,.917,.238),(.605,.245,.917,.264),(.605,.275,.735,.291))),
    "principal_diagnosis": ("21A", "code", ((.108,.583,.225,.601),)),
    "provider_npi": ("24J", "npi", tuple((.791,.666+i*.02765,.919,.680+i*.02765) for i in range(6))),
    "federal_tax_no": ("25", "tax_id", ((.092,.830,.252,.846),)),
    "total_charge": ("28", "currency", ((.604,.830,.720,.846),)),
    "provider_name": ("31", "text", ((.090,.884,.310,.911),)),
}


def regions(template: Template) -> dict[str, tuple[FieldRegion, ...]]:
    width=template.reference_dimensions.width_px
    height=template.reference_dimensions.height_px
    return {name:tuple(FieldRegion(field_name=name,field_type=processor,
        x0=round(box[0]*width),y0=round(box[1]*height),
        x1=round(box[2]*width),y1=round(box[3]*height),padding_px=0)
        for box in boxes) for name,(_,processor,boxes) in BOXES.items()}


def value_template(template: Template) -> Template:
    grouped=regions(template)
    fields=[FieldRegion(field_name=name,field_type=parts[0].field_type,padding_px=0,
        x0=min(p.x0 for p in parts), y0=min(p.y0 for p in parts),
        x1=max(p.x1 for p in parts), y1=max(p.y1 for p in parts))
        for name,parts in grouped.items()]
    return template.model_copy(update={"field_regions":fields})


# Unshaded value columns of public Box 24, independently of legacy ROI files.
SERVICE_COLUMNS = {
    "date_from": ("date", .092, .178),
    "date_to": ("date", .181, .272),
    "place_of_service": ("code", .276, .306),
    "emg": ("checkbox", .309, .337),
    "cpt_hcpcs": ("code", .343, .410),
    "modifier": ("code", .421, .546),
    "diagnosis_pointer": ("code", .550, .599),
    "charges": ("currency", .606, .692),
    "units": ("text", .697, .733),
    "rendering_provider_npi": ("npi", .791, .919),
}


def service_regions(template: Template, row_index: int) -> tuple[FieldRegion, ...]:
    if row_index not in range(6):
        raise ValueError("CMS1500_SERVICE_ROW_OUT_OF_RANGE")
    width=template.reference_dimensions.width_px
    height=template.reference_dimensions.height_px
    _, y0, _, y1=BOXES["provider_npi"][2][row_index]
    return tuple(FieldRegion(field_name=name,field_type=kind,padding_px=0,
        x0=round(x0*width),x1=round(x1*width),y0=round(y0*height),y1=round(y1*height))
        for name,(kind,x0,x1) in SERVICE_COLUMNS.items())


# Label-free interiors of the hash-bound public NUCC blank. These are guards,
# not fitted source coordinates. Diagnosis remains unchanged.
SAFE_INTERIORS = {
    "patient_name": ((.089, .191, .3895, .2073),),
    "patient_dob": ((.396, .197, .504, .2073),),
    "patient_address": ((.089,.219,.3895,.238),(.089,.245,.3895,.264),(.089,.275,.223,.291)),
    "insured_address": ((.602,.219,.918,.238),(.602,.245,.918,.264),(.602,.275,.737,.291)),
    "provider_name": ((.089,.881,.314,.911),),
    "provider_npi": tuple((.790,.6655+i*.02765,.9195,.680+i*.02765) for i in range(6)),
    "federal_tax_no": ((.089,.830,.254,.846),),
    "total_charge": ((.604,.830,.721,.846),),
}
# Pixel expansion is bounded and scales with the public reference resolution.
EXPANSION = {"patient_name": (5,3), "patient_dob": (5,3),
    "patient_address": (5,2), "insured_address": (5,2),
    "provider_name": (5,6), "provider_npi": (2,2),
    "federal_tax_no": (5,2), "total_charge": (2,2)}


def ocr_regions(template: Template) -> dict[str, tuple[FieldRegion, ...]]:
    result = regions(template)
    w = template.reference_dimensions.width_px
    h = template.reference_dimensions.height_px
    for name, boundaries in SAFE_INTERIORS.items():
        dx, dy = EXPANSION[name]
        dx, dy = round(dx*w/1712), round(dy*h/2214)
        parts = []
        for region, boundary in zip(result[name], boundaries, strict=True):
            x0,y0,x1,y1 = (round(boundary[0]*w),round(boundary[1]*h),
                           round(boundary[2]*w),round(boundary[3]*h))
            if not (x0 <= region.x0 < region.x1 <= x1 and y0 <= region.y0 < region.y1 <= y1):
                raise ValueError("CANONICAL_REGION_OUTSIDE_SAFE_INTERIOR")
            parts.append(region.model_copy(update={
                "x0": max(x0,region.x0-dx), "y0": max(y0,region.y0-dy),
                "x1": min(x1,region.x1+dx), "y1": min(y1,region.y1+dy)}))
        result[name] = tuple(parts)
    return result
