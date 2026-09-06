"""Kafka topic name constants — the only place topic strings are spelled."""

from enum import StrEnum


class Topic(StrEnum):
    DOCUMENT_RECEIVED = "document.received"
    DOCUMENT_PREPARED = "document.prepared"
    PAGE_CLASSIFICATION_REQUESTED = "page.classification.requested"
    PAGE_SELECTED = "page.selected"
    EXTRACTION_STANDARD_REQUESTED = "extraction.standard.requested"
    EXTRACTION_UNSTRUCTURED_REQUESTED = "extraction.unstructured.requested"
    EXTRACTION_COMPLETED = "extraction.completed"
    VALIDATION_REQUESTED = "validation.requested"
    VALIDATION_COMPLETED = "validation.completed"
    FIELD_RETRY_REQUESTED = "field.retry.requested"
    HANDWRITING_EXTRACTION_REQUESTED = "handwriting.extraction.requested"
    VLM_REQUESTED = "vlm.requested"
    HUMAN_REVIEW_REQUESTED = "human.review.requested"
    CLAIM_REVALIDATION_REQUESTED = "claim.revalidation.requested"
    CLAIM_VALIDATED = "claim.validated"
    CLAIM_COMPLETED = "claim.completed"
    OUTPUT_REQUESTED = "output.requested"
    OUTPUT_COMPLETED = "output.completed"
    PROCESSING_DLQ = "processing.dlq"


ALL_TOPICS: list[str] = [t.value for t in Topic]

# Topics whose consumers are CPU-bound preprocessing/routing (KEDA CPU pool)
CPU_PREP_TOPICS = [Topic.DOCUMENT_RECEIVED, Topic.PAGE_CLASSIFICATION_REQUESTED]

# Topics whose consumers run OCR on CPU (regional PaddleOCR default mode)
CPU_OCR_TOPICS = [Topic.EXTRACTION_STANDARD_REQUESTED, Topic.FIELD_RETRY_REQUESTED]

# Topics whose consumers may use GPU OCR/layout models (LayoutLMv3, Table Transformer)
GPU_OCR_TOPICS = [Topic.EXTRACTION_UNSTRUCTURED_REQUESTED]
HANDWRITING_TOPICS = [Topic.HANDWRITING_EXTRACTION_REQUESTED]

# Topics consumed by the VLM worker pool
VLM_TOPICS = [Topic.VLM_REQUESTED]

# Topics consumed by the output-generation worker pool
OUTPUT_TOPICS = [Topic.OUTPUT_REQUESTED]
