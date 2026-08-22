from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import httpx
from sqlalchemy import create_engine, text

from packages.reference_enrichment.contracts import ReferenceLookupRequest, ReferenceRecord
from packages.reference_enrichment.xlsx_reader import read_sheet


class ReferenceProvider(Protocol):
    name: str
    provider_type: str
    authorized: bool
    test_only: bool

    def lookup(self, request: ReferenceLookupRequest) -> list[ReferenceRecord]: ...


@dataclass(frozen=True)
class DisabledProvider:
    name: str = "disabled"
    provider_type: str = "DISABLED"
    authorized: bool = False
    test_only: bool = False

    def lookup(self, request: ReferenceLookupRequest) -> list[ReferenceRecord]:
        return []


@dataclass
class FixtureProvider:
    records: dict[str, list[ReferenceRecord]]
    name: str = "fixture"
    provider_type: str = "TEST_FIXTURE"
    authorized: bool = True
    test_only: bool = True

    def lookup(self, request: ReferenceLookupRequest) -> list[ReferenceRecord]:
        return list(self.records.get(request.identity_key, []))


def _json_value(value: object, default: object) -> object:
    if value in (None, ""):
        return default
    return json.loads(value) if isinstance(value, str) else value


def _record(row: dict, provider: dict) -> ReferenceRecord:
    safe = dict(row)
    safe["provider_name"] = provider["name"]
    safe["provider_type"] = provider.get("source_kind", provider["type"]).upper()
    safe["provider_authorized"] = bool(provider.get("authorized", False))
    safe["dataset_version"] = provider.get("dataset_version") or safe.get("dataset_version")
    for key in ("source_lineage",):
        safe[key] = _json_value(safe.get(key), [])
    for key in ("reference_attributes", "field_values"):
        safe[key] = _json_value(safe.get(key), {})
    for key in ("source_created_at", "source_finalized_at"):
        if safe.get(key) and not isinstance(safe[key], datetime):
            safe[key] = datetime.fromisoformat(str(safe[key]))
    safe["independent_truth"] = str(safe.get("independent_truth", "")).lower() in {
        "1",
        "true",
        "yes",
    }
    safe["non_circular_lineage"] = str(safe.get("non_circular_lineage", "")).lower() in {
        "1",
        "true",
        "yes",
    }
    safe.setdefault(
        "response_hash",
        hashlib.sha256(json.dumps(safe, sort_keys=True, default=str).encode()).hexdigest(),
    )
    allowed = set(ReferenceRecord.model_fields)
    return ReferenceRecord.model_validate(
        {key: value for key, value in safe.items() if key in allowed}
    )


@dataclass
class BatchProvider:
    config: dict
    name: str
    provider_type: str
    authorized: bool
    test_only: bool = False

    def lookup(self, request: ReferenceLookupRequest) -> list[ReferenceRecord]:
        path = Path(self.config["path"])
        suffix = path.suffix.lower()
        if suffix == ".json":
            rows = json.loads(path.read_text(encoding="utf-8"))
        elif suffix == ".csv":
            with path.open(newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
        elif suffix == ".xlsx":
            rows = read_sheet(path, self.config.get("sheet", "Reference Records"))
        else:
            raise ValueError(f"unsupported batch reference format: {suffix}")
        key = self.config.get("lookup_key", "identity_key")
        return [_record(row, self.config) for row in rows if row.get(key) == request.identity_key]


@dataclass
class RestProvider:
    config: dict
    name: str
    provider_type: str
    authorized: bool
    test_only: bool = False

    def lookup(self, request: ReferenceLookupRequest) -> list[ReferenceRecord]:
        token = os.environ.get(self.config.get("token_env", "REFERENCE_API_TOKEN"))
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        with httpx.Client(
            timeout=float(self.config.get("timeout_seconds", 10)), verify=True
        ) as client:
            response = client.post(
                self.config["url"], json=request.model_dump(mode="json"), headers=headers
            )
            response.raise_for_status()
        payload = response.json()
        rows = payload if isinstance(payload, list) else payload.get("records", [])
        return [_record(row, self.config) for row in rows]


@dataclass
class DatabaseProvider:
    config: dict
    name: str
    provider_type: str
    authorized: bool
    test_only: bool = False

    def lookup(self, request: ReferenceLookupRequest) -> list[ReferenceRecord]:
        query = self.config["query"].strip()
        if not query.lower().startswith("select") or ";" in query.rstrip(";"):
            raise ValueError("reference database connector permits one SELECT statement only")
        dsn = os.environ.get(self.config["dsn_env"])
        if not dsn:
            raise RuntimeError(
                f"missing database secret environment variable {self.config['dsn_env']}"
            )
        engine = create_engine(dsn)
        try:
            with engine.connect() as connection:
                rows = (
                    connection.execute(
                        text(query),
                        {
                            "identity_key": request.identity_key,
                            "document_id": request.document_id,
                            "field_name": request.field_name,
                        },
                    )
                    .mappings()
                    .all()
                )
            return [_record(dict(row), self.config) for row in rows]
        finally:
            engine.dispose()


def configured_providers(config: dict) -> list[ReferenceProvider]:
    providers: list[ReferenceProvider] = []
    for item in config.get("providers", []):
        if not item.get("enabled", False):
            continue
        kind = item.get("type", "disabled")
        if kind != "test_fixture" and not item.get("authorized", False):
            continue
        if kind == "test_fixture":
            providers.append(FixtureProvider(records={}, name=item["name"]))
        elif kind in {"csv", "json", "xlsx"}:
            providers.append(
                BatchProvider(item, item["name"], kind.upper(), bool(item.get("authorized")))
            )
        elif kind == "local_snapshot":
            from packages.reference_data.snapshot import LocalSnapshotProvider

            providers.append(LocalSnapshotProvider(Path(item["path"]), test_only=False))
        elif kind == "rest":
            providers.append(RestProvider(item, item["name"], "REST", bool(item.get("authorized"))))
        elif kind == "database":
            providers.append(
                DatabaseProvider(item, item["name"], "DATABASE", bool(item.get("authorized")))
            )
        else:
            raise ValueError(f"enabled provider type is not implemented or authorized: {kind}")
    return providers
