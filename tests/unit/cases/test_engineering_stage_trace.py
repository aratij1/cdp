import pytest

from evaluation.engineering_stage_trace import STAGES, first_failure


@pytest.mark.parametrize('earlier', STAGES[:3])
def test_unproven_preconditions_cannot_be_attributed_to_ocr(earlier):
    stages = dict.fromkeys(STAGES, True)
    stages[earlier] = None
    stages['DIRECT_RECOGNIZER_RECOVERS_VALUE'] = False
    assert first_failure(stages)['root_cause'] == 'OTHER'
    assert first_failure(stages)['first_stage'] == earlier


def test_first_failure_wins_over_all_later_failures():
    stages = dict.fromkeys(STAGES, False)
    assert first_failure(stages)['root_cause'] == 'FORM_ROUTING'


def test_ocr_requires_all_three_preconditions():
    stages = dict.fromkeys(STAGES, True)
    stages['DIRECT_RECOGNIZER_RECOVERS_VALUE'] = False
    assert first_failure(stages)['root_cause'] == 'OCR_RECOGNITION'


def test_source_value_in_different_role_does_not_blame_correct_crop():
    stages = dict.fromkeys(STAGES, True)
    stages['CANONICAL_BOX_CONTAINS_VALUE'] = False
    assert first_failure(stages, source_field_binding_verified=False)['root_cause'] == 'OTHER'


def test_later_execution_failure_does_not_override_earlier_failure():
    stages = dict.fromkeys(STAGES, True)
    stages['PAGE_REGISTRATION'] = False
    result = first_failure(stages, execution_failure_at='FIELD_ASSEMBLY_SELECTS_VALUE')
    assert result['root_cause'] == 'PAGE_REGISTRATION'


def test_execution_failure_at_first_stage_is_reported():
    assert first_failure(dict.fromkeys(STAGES), execution_failure_at=STAGES[0])['root_cause'] == 'EXECUTION_FAILURE'


def test_missing_stage_is_rejected():
    with pytest.raises(ValueError, match='STAGE_SET_INCOMPLETE'):
        first_failure({})
