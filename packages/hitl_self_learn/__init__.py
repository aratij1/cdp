"""HITL self-learn: mine residual patterns, remember remediations, plan retries.

Never auto-accept field values. Learning is pattern → playbook only; STP flips
must go through reprocess runners with FA=0 gates.
"""

from .memory import HitlLearnMemory, MemoryStore
from .mine import mine_run
from .plan import plan_retries

__all__ = [
    "HitlLearnMemory",
    "MemoryStore",
    "mine_run",
    "plan_retries",
]
