# Field Recovery: `insured_id_number`

> Synthetic benchmark diagnosis. Do not treat these measurements as production accuracy.

- Families: {'CMS1500': 60}
- Frozen baseline accuracy: 0/60 (0.00%)
- Final accuracy: 59/60 (98.33%)
- Error count: 1
- Root causes: {'OCR_CHARACTER_ERROR': 1}
- Crop states: {'CROP_CORRECT_TEXT_VISIBLE': 1}

## Measured conclusion

The dominant failures occur with the target crop present; benchmark field-specific OCR next.

## Required next experiment

Run one isolated change, compare this field and overall accuracy, preserve zero false accepts, and reject the change if a frozen strong field regresses.
