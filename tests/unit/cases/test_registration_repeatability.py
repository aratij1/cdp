from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from workers.page_detection.template_alignment import DEFAULT_REGISTRATION_POLICY, _sift_alignment


def test_registration_is_repeatable_after_other_opencv_rng_consumers():
    reference = np.random.default_rng(13).integers(0, 256, (360, 360), dtype=np.uint8)
    transform = np.array([[1., .012, 5.], [.005, 1., -3.], [.00001, -.00002, 1.]])
    candidate = cv2.warpPerspective(reference, transform, (360, 360), borderValue=255)
    def run(seed):
        cv2.setRNGSeed(seed)
        unrelated = np.empty((80, 80), np.float32)
        cv2.randu(unrelated, 0, 1)
        result = _sift_alignment(candidate, reference, DEFAULT_REGISTRATION_POLICY)
        assert result.accepted
        return result.homography, result.warped.tobytes(), result.evidence.inlier_count
    first = run(41)
    with ThreadPoolExecutor(max_workers=3) as executor:
        later = list(executor.map(run, [7, 109, 991]))
    for matrix, pixels, inliers in later:
        np.testing.assert_array_equal(matrix, first[0])
        assert pixels == first[1]
        assert inliers == first[2]


def test_registration_hypotheses_never_select_high_scoring_rejected_fit(monkeypatch):
    from packages.domain.registration import RegistrationEvidence
    from workers.page_detection import template_alignment as module
    results = iter([(False, .99), (True, .60), (True, .75)])
    def hypothesis(candidate, reference, policy):
        accepted, confidence = next(results)
        evidence = RegistrationEvidence(algorithm='synthetic', accepted=accepted,
            alignment_confidence=confidence, rejection_reason=None if accepted else 'unsafe_perspective_distortion')
        return module.AlignmentResult(accepted, confidence, 20, np.eye(3), None,
            'synthetic', accepted=accepted, evidence=evidence)
    monkeypatch.setattr(module, '_seeded_sift_alignment', hypothesis)
    result = module._sift_alignment(np.zeros((2,2)), np.zeros((2,2)), DEFAULT_REGISTRATION_POLICY)
    assert result.accepted and result.evidence.selected_seed == 2
    assert [h.accepted for h in result.evidence.hypotheses] == [False, True, True]


def test_all_rejected_registration_hypotheses_remain_rejected(monkeypatch):
    from packages.domain.registration import RegistrationEvidence
    from workers.page_detection import template_alignment as module
    def hypothesis(candidate, reference, policy):
        return module.AlignmentResult(False, .9, 20, np.eye(3), None, 'synthetic',
            accepted=False, evidence=RegistrationEvidence(algorithm='synthetic', accepted=False,
                alignment_confidence=.9, rejection_reason='unsafe_perspective_distortion'))
    monkeypatch.setattr(module, '_seeded_sift_alignment', hypothesis)
    result = module._sift_alignment(np.zeros((2,2)), np.zeros((2,2)), DEFAULT_REGISTRATION_POLICY)
    assert not result.accepted and not result.evidence.accepted
