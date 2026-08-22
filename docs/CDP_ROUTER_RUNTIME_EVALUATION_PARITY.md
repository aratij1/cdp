# CDP Router Runtime/Evaluation Parity

Runtime and evaluation both call `CanonicalRoutingDecisionService.route` with
the same image, OCR geometry and versioned YAML. The integration contract test
asserts the complete `RouteDecision` objects are equal and separately proves
that `UNKNOWN_STRUCTURED` survives the runtime adapter. Evaluators contain no
local ranking policy.
