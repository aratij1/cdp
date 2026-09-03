"""Append one adjudicated claim to the protected shadow evidence ledger."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from packages.shadow_evaluation import AppendOnlyShadowClaimSink, ClaimShadowObservation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("observation", type=Path, help="single ClaimShadowObservation JSON")
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--identity-key-env", default="SHADOW_IDENTITY_KEY")
    args = parser.parse_args()
    secret = os.environ.get(args.identity_key_env, "")
    if not secret:
        parser.error(f"{args.identity_key_env} must contain a non-empty secret")
    observation = ClaimShadowObservation.model_validate_json(
        args.observation.read_text(encoding="utf-8")
    )
    event = AppendOnlyShadowClaimSink(
        args.ledger, identity_key=secret.encode("utf-8")
    ).append(observation)
    print(json.dumps({
        "event_hash": event["event_hash"],
        "promotion_authority": False,
        "status": "CAPTURED",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
