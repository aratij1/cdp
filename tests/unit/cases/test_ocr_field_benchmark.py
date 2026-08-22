from evaluation.ocr_field_benchmark import character_error_rate, summarize


def test_character_error_rate_is_normalized_and_bounded_for_insertions():
    assert character_error_rate("AB-12", "AB12") == 0
    assert character_error_rate("AB12", "ABX12") == 0.25


def test_summary_keeps_field_engine_denominators_separate():
    rows = [
        {"field_name": "member_id", "engine": "rapidocr", "exact": True,
         "character_error_rate": 0, "latency_ms": 10, "crop_correct": True},
        {"field_name": "member_id", "engine": "tesseract", "exact": False,
         "character_error_rate": .1, "latency_ms": 5, "crop_correct": True},
    ]
    result = summarize(rows)
    assert result[0]["exact_accuracy"] == 1
    assert result[1]["exact_accuracy"] == 0
