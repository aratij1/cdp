# Field Recovery: `federal_tax_no`

> Synthetic benchmark diagnosis. Do not treat these measurements as production accuracy.

- Families: {'UB04': 60}
- Frozen baseline accuracy: 0/60 (0.00%)
- Final accuracy: 58/60 (96.67%)
- Error count: 2
- Root causes: {'OCR_CHARACTER_ERROR': 2}
- Crop states: {'CROP_CORRECT_TEXT_VISIBLE': 2}

## Measured conclusion

The dominant failures occur with the target crop present; benchmark field-specific OCR next.

## Required next experiment

Run one isolated change, compare this field and overall accuracy, preserve zero false accepts, and reject the change if a frozen strong field regresses.
