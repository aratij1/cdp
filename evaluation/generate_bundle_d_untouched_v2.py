"""Uniquely rendered replacement for rejected untouched V1."""

import json

from evaluation.generate_bundle_d_dev_v1 import DEFAULT_UNTOUCHED_V2, generate


if __name__ == "__main__":
    print(json.dumps(generate(
        DEFAULT_UNTOUCHED_V2, documents_per_family=5, seed=7719203,
        dataset_id="BUNDLE_D_UNTOUCHED_V2", frozen_holdout=True,
    ), indent=2))
