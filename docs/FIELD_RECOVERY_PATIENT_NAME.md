# Field Recovery: `patient_name`

> Synthetic benchmark diagnosis. Do not treat these measurements as production accuracy.

- Families: {'CMS1500': 60, 'UB04': 60}
- Frozen baseline accuracy: 77/120 (64.17%)
- Final accuracy: 117/120 (97.50%)
- Error count: 3
- Root causes: {'OCR_ENGINE_FAILURE': 3}
- Crop states: {'CROP_CORRECT_TEXT_VISIBLE': 3}

## Measured conclusion

The dominant failures occur with the target crop present; benchmark field-specific OCR next.

## Required next experiment

Run one isolated change, compare this field and overall accuracy, preserve zero false accepts, and reject the change if a frozen strong field regresses.
