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
