from pathlib import Path


def test_only_decision_service_constructs_final_document_routing_decision():
    producers = []
    for root in (Path("packages"), Path("workers")):
        for path in root.rglob("*.py"):
            if "return DocumentRoutingDecision(" in path.read_text("utf-8"):
                producers.append(path.as_posix())
    assert producers == ["packages/document_routing/decision_service.py"]


def test_worker_contains_no_standard_verification_thresholds():
    text = Path("workers/page_detection/consumer.py").read_text("utf-8")
    assert "verification_score" not in text
    assert "StandardFormStatus.VERIFIED" not in text
    assert "DocumentRoutingDecisionService" in text


def test_visual_and_classifiers_cannot_import_extractor_dispatch():
    paths = [*Path("packages/document_routing/visual").glob("*.py"),
             *Path("packages/document_routing/ml").glob("*.py")]
    text = "\n".join(path.read_text("utf-8") for path in paths)
    assert "extraction_routing" not in text
    assert "ProcessingRoute" not in text
