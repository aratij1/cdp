# CDP Phase 8.3 Final Report

Correctness is frozen as `PHASE8_ACCURACY_CANDIDATE_1` at `ba1c3151006f63ef1ab6fe79f7125617356cc3cd`: CMS 95.09%, UB 96.50%, critical 95.87%, zero canonical/critical false accepts, 100% accepted precision, and zero cloud calls.

The host is **HOST_CPU_SATURATED**. One worker delivers 5.642 pages/min; 8 same-host workers fall to 4.389 pages/min with 9.72% efficiency. Production design uses isolated single-worker pods and queue-driven horizontal scaling.

Canonical EvidenceDecisionService replay: field HITL 70.21%, safe coverage 29.79%, accepted precision 100.00%. Canonical ClaimDecisionService replay: blocking claim HITL 100.00%, STP 0.00%. Perfect extraction remains a separate 63.00% truth metric.

The dominant economic component is HITL (99.77% of modeled fully loaded cost), not OCR compute. No thread profile is promoted unless output and canonical decisions are byte-equivalent to the frozen candidate and throughput improves.
