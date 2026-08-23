from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


EvidenceClass = Literal["ENGINEERING_BENCHMARK_ONLY"]


class EngineeringBenchmarkRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    page_id: str
    expected_family: str
    expected_processing_route: str
    source_dataset: str
    synthetic_or_test: bool
    image_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality_bucket: str = "unknown"
    failure_bucket: str | None = None
    truth_fields: dict[str, Any] = Field(default_factory=dict)
    crop_boxes: dict[str, tuple[int, int, int, int]] = Field(default_factory=dict)
    tuning_allowed: bool = False


class EngineeringBenchmarkManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = "ENGINEERING_BENCHMARK_V1"
    schema_version: str = "phase7a13-engineering-manifest-v1"
    evidence_class: EvidenceClass = "ENGINEERING_BENCHMARK_ONLY"
    production_promotion_authority: bool = False
    records: list[EngineeringBenchmarkRecord]
    record_count: int
    manifest_sha256: str = ""

    @model_validator(mode="after")
    def count_matches(self):
        if self.record_count != len(self.records):
            raise ValueError("record_count does not match records")
        return self
