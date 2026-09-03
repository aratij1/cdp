"""Tamper-evident, PHI-safe persistence for adjudicated shadow claims."""

from __future__ import annotations

import json
import threading
from hashlib import sha256
from hmac import new as hmac_new
from pathlib import Path

from packages.shadow_evaluation.models import ClaimShadowObservation


def identity_fingerprint(value: str, key: bytes) -> str:
    if not key:
        raise ValueError("a non-empty identity key is required")
    return hmac_new(key, value.encode("utf-8"), sha256).hexdigest()


class AppendOnlyShadowClaimSink:
    """Hash-chain observations while excluding raw claim/source identifiers."""

    def __init__(self, path: Path, *, identity_key: bytes) -> None:
        if not identity_key:
            raise ValueError("a non-empty identity key is required")
        self.path = path
        self.identity_key = identity_key
        self._lock = threading.Lock()
        self._known_claim_ids: set[str] | None = None
        self._last_event_hash: str | None = None

    @staticmethod
    def _canonical(payload: dict) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def _events(self) -> list[dict]:
        if not self.path.is_file():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def append(self, observation: ClaimShadowObservation) -> dict:
        if not observation.shadow_only:
            raise ValueError("only non-authoritative shadow observations may be persisted")
        deidentified = observation.model_copy(update={
            "claim_id": identity_fingerprint(observation.claim_id, self.identity_key),
            "source_group_id": identity_fingerprint(
                observation.source_group_id, self.identity_key
            ),
        })
        with self._lock:
            if self._known_claim_ids is None:
                events = self._events()
                self._known_claim_ids = {
                    event["observation"]["claim_id"] for event in events
                }
                self._last_event_hash = events[-1]["event_hash"] if events else "0" * 64
            if deidentified.claim_id in self._known_claim_ids:
                raise ValueError("duplicate claim_id in shadow capture")
            event = {
                "schema_version": "shadow-claim-capture-v1",
                "promotion_authority": False,
                "previous_event_hash": self._last_event_hash,
                "observation": deidentified.model_dump(mode="json"),
            }
            event["event_hash"] = sha256(self._canonical(event).encode()).hexdigest()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, sort_keys=True) + "\n")
            self._known_claim_ids.add(deidentified.claim_id)
            self._last_event_hash = event["event_hash"]
        return event

    def verify(self) -> bool:
        previous_hash = "0" * 64
        try:
            events = self._events()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False
        seen: set[str] = set()
        for event in events:
            event_hash = event.pop("event_hash", None)
            claim_id = event.get("observation", {}).get("claim_id")
            if (
                event.get("previous_event_hash") != previous_hash
                or event.get("promotion_authority") is not False
                or claim_id in seen
                or sha256(self._canonical(event).encode()).hexdigest() != event_hash
            ):
                return False
            seen.add(claim_id)
            previous_hash = event_hash
        return True

    def observations(self) -> list[ClaimShadowObservation]:
        if not self.verify():
            raise ValueError("shadow capture hash chain is invalid")
        return [
            ClaimShadowObservation.model_validate(event["observation"])
            for event in self._events()
        ]
