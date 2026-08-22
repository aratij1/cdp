"""Create the independently seeded, frozen Phase-5 engineering holdout once."""

import json

from evaluation.generate_bundle_d_dev_v1 import DEFAULT_UNTOUCHED, generate


if __name__ == "__main__":
    print(json.dumps(generate(
        DEFAULT_UNTOUCHED, documents_per_family=5, seed=928031,
        dataset_id="BUNDLE_D_UNTOUCHED_V1", frozen_holdout=True,
    ), indent=2))
