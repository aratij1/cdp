# CDP Phase 7A.13 Routing Confusion Matrix

Full JSON matrices: `evaluation_results/phase7a13/confusion_matrix.json`.

```json
{
  "top_level_taxonomy": {
    "CLAIM": {
      "CLAIM": 699,
      "UNKNOWN": 317
    },
    "CLAIM_SUPPORT": {
      "UNKNOWN": 76
    },
    "NON_CLAIM": {
      "NON_CLAIM": 11,
      "UNKNOWN": 52
    },
    "UNKNOWN": {
      "UNKNOWN": 75
    }
  },
  "standard_family_nomination": {
    "CMS1500": {
      "CMS1500": 325,
      "NON_STANDARD": 85
    },
    "NON_STANDARD": {
      "NON_STANDARD": 310
    },
    "UB04": {
      "NON_STANDARD": 136,
      "UB04": 374
    }
  },
  "final_processing_route": {
    "CMS_STANDARD_EXTRACTOR": {
      "CMS_STANDARD_EXTRACTOR": 166,
      "LAYOUT_STRUCTURED_EXTRACTOR": 236,
      "UNSTRUCTURED_EXTRACTOR": 8
    },
    "LAYOUT_STRUCTURED_EXTRACTOR": {
      "LAYOUT_STRUCTURED_EXTRACTOR": 140,
      "UNSTRUCTURED_EXTRACTOR": 41
    },
    "STOP_NON_CLAIM": {
      "LAYOUT_STRUCTURED_EXTRACTOR": 20,
      "STOP_NON_CLAIM": 11,
      "UNSTRUCTURED_EXTRACTOR": 32
    },
    "UB_STANDARD_EXTRACTOR": {
      "LAYOUT_STRUCTURED_EXTRACTOR": 340,
      "UB_STANDARD_EXTRACTOR": 143,
      "UNSTRUCTURED_EXTRACTOR": 27
    },
    "UNSTRUCTURED_EXTRACTOR": {
      "UNSTRUCTURED_EXTRACTOR": 66
    }
  }
}
```
