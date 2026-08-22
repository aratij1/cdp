"""Write the current fail-closed Phase 12 production decision."""
from __future__ import annotations
import json
from pathlib import Path
from packages.production_promotion_gate import ProductionEvidence, ProductionPromotionGate

def main() -> int:
    evidence = ProductionEvidence(
        frozen_release_integrity=True,
        full_suite_passed=True,
        unexplained_test_failures=0,
        independent_holdout_frozen=False,
        holdout_is_synthetic=True,
        holdout_documents=120,
        holdout_fields=600,
        overall_accuracy=.37333333333333335,
        critical_accuracy=None,
        critical_false_accept_rate=0,
        total_false_accept_rate=0,
        safe_stp_rate=None,
    )
    result = ProductionPromotionGate.load().evaluate(evidence)
    output = Path("evaluation_results/production_gate_vnext/decision.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"evidence": evidence.model_dump(), "result": result.model_dump(mode="json")}, indent=2), "utf-8")
    print(result.model_dump_json(indent=2))
    return 0 if result.decision.value == "PROMOTABLE" else 2

if __name__ == "__main__":
    raise SystemExit(main())
