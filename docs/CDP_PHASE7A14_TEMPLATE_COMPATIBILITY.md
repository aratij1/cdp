# CDP Phase 7A.14 Template Compatibility

The controlled transforms pass, while the tuning corpus is dominated by a different sparse-fixture lineage. This is not a threshold-tuning result.

```json
{
  "policy_version": "template-compatibility-v1",
  "control_success_rate": 1.0,
  "control_attempts": 14,
  "control_successes": 14,
  "benchmark_status_counts": {
    "INCOMPATIBLE": 64,
    "PARTIALLY_COMPATIBLE": 68
  },
  "benchmark_compatible_rate": 0.0,
  "interpretation": "TEMPLATE_LINEAGE_MISMATCH",
  "controls": {
    "attempts": 14,
    "successes": 14,
    "success_rate": 1.0,
    "outcomes": [
      {
        "family": "CMS1500",
        "transform": "CANONICAL",
        "success": true,
        "method": "edge_phase_correlation",
        "rejection_reason": null,
        "compatibility": null,
        "latency_ms": 242.12229999830015
      },
      {
        "family": "CMS1500",
        "transform": "TRANSLATED",
        "success": true,
        "method": "edge_phase_correlation",
        "rejection_reason": null,
        "compatibility": null,
        "latency_ms": 277.75919999112375
      },
      {
        "family": "CMS1500",
        "transform": "SCALED",
        "success": true,
        "method": "sift_flann_ransac_homography",
        "rejection_reason": null,
        "compatibility": {
          "policy_version": "template-compatibility-v1",
          "family": "CMS1500",
          "family_compatibility": 1.0,
          "aspect_ratio_similarity": 1.0,
          "line_structure_similarity": 0.9415572950385498,
          "edge_projection_similarity": 0.21797948348284416,
          "anchor_visibility": 0.9661525306887443,
          "normalized_layout_similarity": 0.9615963595024521,
          "form_fingerprint_similarity": 0.6269687652936285,
          "compatibility_score": 0.781785476054163,
          "status": "COMPATIBLE",
          "reason_codes": [
            "FORM_STRUCTURE_COMPATIBLE"
          ]
        },
        "latency_ms": 1847.5627999869175
      },
      {
        "family": "CMS1500",
        "transform": "SKEWED",
        "success": true,
        "method": "sift_flann_ransac_homography",
        "rejection_reason": null,
        "compatibility": {
          "policy_version": "template-compatibility-v1",
          "family": "CMS1500",
          "family_compatibility": 1.0,
          "aspect_ratio_similarity": 1.0,
          "line_structure_similarity": 0.9592852431492476,
          "edge_projection_similarity": 0.5553311768797149,
          "anchor_visibility": 0.9836136784393403,
          "normalized_layout_similarity": 0.9779260713296791,
          "form_fingerprint_similarity": 0.7877583688271953,
          "compatibility_score": 0.8744242602928594,
          "status": "COMPATIBLE",
          "reason_codes": [
            "FORM_STRUCTURE_COMPATIBLE"
          ]
        },
        "latency_ms": 1690.548199985642
      },
      {
        "family": "CMS1500",
        "transform": "ROTATED",
        "success": true,
        "method": "sift_flann_ransac_homography",
        "rejection_reason": null,
        "compatibility": {
          "policy_version": "template-compatibility-v1",
          "family": "CMS1500",
          "family_compatibility": 1.0,
          "aspect_ratio_similarity": 1.0,
          "line_structure_similarity": 0.8051631453931741,
          "edge_projection_similarity": 0.17805422716103145,
          "anchor_visibility": 0.9399056455555335,
          "normalized_layout_similarity": 0.9466645857724063,
          "form_fingerprint_similarity": 0.6007899243972877,
          "compatibility_score": 0.7342008430223997,
          "status": "COMPATIBLE",
          "reason_codes": [
            "FORM_STRUCTURE_COMPATIBLE"
          ]
        },
        "latency_ms": 1871.7786000052001
      },
      {
        "family": "CMS1500",
        "transform": "PERSPECTIVE",
        "success": true,
        "method": "sift_flann_ransac_homography",
        "rejection_reason": null,
        "compatibility": {
          "policy_version": "template-compatibility-v1",
          "family": "CMS1500",
          "family_compatibility": 1.0,
          "aspect_ratio_similarity": 1.0,
          "line_structure_similarity": 0.9358839358839359,
          "edge_projection_similarity": 0.30202241935868157,
          "anchor_visibility": 0.9775479936042448,
          "normalized_layout_similarity": 0.9710287483543225,
          "form_fingerprint_similarity": 0.6699759003062842,
          "compatibility_score": 0.8046159281869592,
          "status": "COMPATIBLE",
          "reason_codes": [
            "FORM_STRUCTURE_COMPATIBLE"
          ]
        },
        "latency_ms": 1732.7598000119906
      },
      {
        "family": "CMS1500",
        "transform": "DEGRADED",
        "success": true,
        "method": "sift_flann_ransac_homography",
        "rejection_reason": null,
        "compatibility": {
          "policy_version": "template-compatibility-v1",
          "family": "CMS1500",
          "family_compatibility": 1.0,
          "aspect_ratio_similarity": 1.0,
          "line_structure_similarity": 0.9728716089511188,
          "edge_projection_similarity": 0.9499118058330229,
          "anchor_visibility": 0.9965746538017535,
          "normalized_layout_similarity": 0.9913560665561088,
          "form_fingerprint_similarity": 0.9727061492307203,
          "compatibility_score": 0.9789421248398311,
          "status": "COMPATIBLE",
          "reason_codes": [
            "FORM_STRUCTURE_COMPATIBLE"
          ]
        },
        "latency_ms": 1846.463699999731
      },
      {
        "family": "UB04",
        "transform": "CANONICAL",
        "success": true,
        "method": "edge_phase_correlation",
        "rejection_reason": null,
        "compatibility": null,
        "latency_ms": 264.620499976445
      },
      {
        "family": "UB04",
        "transform": "TRANSLATED",
        "success": true,
        "method": "edge_phase_correlation",
        "rejection_reason": null,
        "compatibility": null,
        "latency_ms": 205.53490001475438
      },
      {
        "family": "UB04",
        "transform": "SCALED",
        "success": true,
        "method": "sift_flann_ransac_homography",
        "rejection_reason": null,
        "compatibility": {
          "policy_version": "template-compatibility-v1",
          "family": "UB04",
          "family_compatibility": 1.0,
          "aspect_ratio_similarity": 1.0,
          "line_structure_similarity": 0.988522932148982,
          "edge_projection_similarity": 0.17507379066009857,
          "anchor_visibility": 0.9530957755804322,
          "normalized_layout_similarity": 0.9489761640367259,
          "form_fingerprint_similarity": 0.6007200960172436,
          "compatibility_score": 0.7775518524933984,
          "status": "COMPATIBLE",
          "reason_codes": [
            "FORM_STRUCTURE_COMPATIBLE"
          ]
        },
        "latency_ms": 1607.335199980298
      },
      {
        "family": "UB04",
        "transform": "SKEWED",
        "success": true,
        "method": "sift_flann_ransac_homography",
        "rejection_reason": null,
        "compatibility": {
          "policy_version": "template-compatibility-v1",
          "family": "UB04",
          "family_compatibility": 1.0,
          "aspect_ratio_similarity": 1.0,
          "line_structure_similarity": 0.993623851193879,
          "edge_projection_similarity": 0.6687140431774681,
          "anchor_visibility": 0.9801973806446406,
          "normalized_layout_similarity": 0.9797485101949052,
          "form_fingerprint_similarity": 0.8397830000370585,
          "compatibility_score": 0.9102240345172369,
          "status": "COMPATIBLE",
          "reason_codes": [
            "FORM_STRUCTURE_COMPATIBLE"
          ]
        },
        "latency_ms": 1667.506899975706
      },
      {
        "family": "UB04",
        "transform": "ROTATED",
        "success": true,
        "method": "sift_flann_ransac_homography",
        "rejection_reason": null,
        "compatibility": {
          "policy_version": "template-compatibility-v1",
          "family": "UB04",
          "family_compatibility": 1.0,
          "aspect_ratio_similarity": 1.0,
          "line_structure_similarity": 0.8117497031792799,
          "edge_projection_similarity": 0.313292495763152,
          "anchor_visibility": 0.9223561950369848,
          "normalized_layout_similarity": 0.9246431188176407,
          "form_fingerprint_similarity": 0.6495353384431208,
          "compatibility_score": 0.7614787079954036,
          "status": "COMPATIBLE",
          "reason_codes": [
            "FORM_STRUCTURE_COMPATIBLE"
          ]
        },
        "latency_ms": 1771.4965000050142
      },
      {
        "family": "UB04",
        "transform": "PERSPECTIVE",
        "success": true,
        "method": "sift_flann_ransac_homography",
        "rejection_reason": null,
        "compatibility": {
          "policy_version": "template-compatibility-v1",
          "family": "UB04",
          "family_compatibility": 1.0,
          "aspect_ratio_similarity": 1.0,
          "line_structure_similarity": 0.9983729827184381,
          "edge_projection_similarity": 0.32572565828556127,
          "anchor_visibility": 0.9786531064067254,
          "normalized_layout_similarity": 0.9716556610449084,
          "form_fingerprint_similarity": 0.6809871598032022,
          "compatibility_score": 0.8250660765123276,
          "status": "COMPATIBLE",
          "reason_codes": [
            "FORM_STRUCTURE_COMPATIBLE"
          ]
        },
        "latency_ms": 1668.7886999861803
      },
      {
        "family": "UB04",
        "transform": "DEGRADED",
        "success": true,
        "method": "sift_flann_ransac_homography",
        "rejection_reason": null,
        "compatibility": {
          "policy_version": "template-compatibility-v1",
          "family": "UB04",
          "family_compatibility": 1.0,
          "aspect_ratio_similarity": 1.0,
          "line_structure_similarity": 0.9726924937337849,
          "edge_projection_similarity": 0.9419265519930076,
          "anchor_visibility": 0.9842621959149009,
          "normalized_layout_similarity": 0.9814427756929693,
          "form_fingerprint_similarity": 0.9636604750279867,
          "compatibility_score": 0.9731854061902547,
          "status": "COMPATIBLE",
          "reason_codes": [
            "FORM_STRUCTURE_COMPATIBLE"
          ]
        },
        "latency_ms": 1720.7864999945741
      }
    ]
  }
}
```
