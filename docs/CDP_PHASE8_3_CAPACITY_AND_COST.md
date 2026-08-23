# CDP Phase 8.3 Capacity and Production Economics

The measured isolated scaling unit is 5.642 pages/min. With 30% normal headroom, 15K pages/day requires 3 isolated pods and 50K requires 9. Both are **CAPACITY_MODELED_NOT_LOAD_VALIDATED** because multiple isolated hosts were unavailable.

Using the configurable engineering node rate of $0.20/hour: throughput-based machine cost/page $0.000591; resource-based compute/page $0.000544; HITL/page $0.301042; fully loaded/page $0.301732; document $0.905197. HITL is 99.77% and machine processing 0.20% of total. Cloud common-path cost remains $0.

The sensitivity grid for 5%, 2%, and 1% field HITL at 3/5/10/20 seconds is in `production_economics.json`; every row is labeled **SCENARIO NOT ACHIEVED**.
