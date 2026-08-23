# Routing Runtime/Evaluation Parity

Runtime and evaluation invoke the same `DocumentRoutingDecisionService`, `StandardFormVerificationService`, family verifiers, and `ProcessingRouteResolver`. `evaluation_only` is provenance and does not change classification, verification, or processing policy. A contract test supplies identical evidence to both contexts and asserts identical `DocumentClassification`, `StandardFormVerification`, and `ProcessingRoute`.
