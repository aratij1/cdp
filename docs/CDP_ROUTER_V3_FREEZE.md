# Router V3 Freeze

The authoritative machine-readable record is `config/router_v3_freeze.json`.
Router V3 is disabled by default and authorized only for evaluation. Its source
commit, configuration SHA-256, anchor and zone policy versions, bounded fuzzy
policy, OpenCV structure version, RouteDecision schema, complete development
dataset tree hash and benchmark hash are frozen. Any mismatch blocks the
production-representative routing observation.

The V2 production-representative set has already been observed. Results from
it are regression observations, never untouched estimates, and are prohibited
from changing Router V3 directly.
