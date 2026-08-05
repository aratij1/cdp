"""Service layer for Output API."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.ingestion_api.db.models import DocumentORM
from packages.domain.common import ObjectRef
from packages.storage.object_store import ObjectStore


class OutputService:
    def __init__(self, session: Session, object_store: ObjectStore, bucket: str = "idp-documents") -> None:
        self._session = session
        self._object_store = object_store
        self._bucket = bucket

    def list_claims(
        self, tenant_id: str | None = None, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[DocumentORM], int]:
        stmt = select(DocumentORM)
        if tenant_id:
            stmt = stmt.where(DocumentORM.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(DocumentORM.status == status)

        count_stmt = select(DocumentORM)
        if tenant_id:
            count_stmt = count_stmt.where(DocumentORM.tenant_id == tenant_id)
        if status:
            count_stmt = count_stmt.where(DocumentORM.status == status)

        total = len(self._session.execute(count_stmt).scalars().all())
        rows = self._session.execute(
            stmt.order_by(DocumentORM.received_at.desc()).limit(limit).offset(offset)
        ).scalars().all()

        return list(rows), total

    def get_claim(self, document_or_claim_id: UUID) -> DocumentORM | None:
        row = self._session.get(DocumentORM, document_or_claim_id)
        if row:
            return row
        stmt = select(DocumentORM).where(DocumentORM.claim_id == document_or_claim_id)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_available_outputs(self, doc: DocumentORM) -> list[str]:
        claim_id = doc.claim_id or doc.document_id
        prefix = f"outputs/{doc.tenant_id}/{claim_id}"
        types = []
        for name, key_suffix in [
            ("canonical_json", "canonical_claim.json"),
            ("evidence_manifest", "evidence_manifest.json"),
            ("reconciliation_report", "reconciliation_report.json"),
            ("nsf", "claim_output.nsf"),
        ]:
            if self._object_store.exists(self._bucket, f"{prefix}/{key_suffix}"):
                types.append(name)
        return types

    def generate_download_url(self, doc: DocumentORM, output_type: str) -> tuple[str, str] | None:
        claim_id = doc.claim_id or doc.document_id
        type_map = {
            "canonical_json": "canonical_claim.json",
            "evidence_manifest": "evidence_manifest.json",
            "reconciliation_report": "reconciliation_report.json",
            "nsf": "claim_output.nsf",
        }
        suffix = type_map.get(output_type)
        if not suffix:
            return None

        object_key = f"outputs/{doc.tenant_id}/{claim_id}/{suffix}"
        if not self._object_store.exists(self._bucket, object_key):
            return None

        ref = ObjectRef(bucket=self._bucket, key=object_key)
        url = self._object_store.signed_get_url(ref)
        return object_key, url
