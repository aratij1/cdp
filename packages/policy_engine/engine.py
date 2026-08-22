"""Config-driven selection of the cheapest useful next evidence source."""
from __future__ import annotations
from pathlib import Path
import yaml
from packages.policy_engine.contracts import DecisionContext, PolicyAction, PolicyDecision

DEFAULT_POLICY_PATH=Path(__file__).resolve().parents[2]/"config"/"adaptive_routing.yaml"
_CLOUD={PolicyAction.TEXTRACT,PolicyAction.GEMINI_CHEAP,PolicyAction.GEMINI_STANDARD,PolicyAction.GEMINI_ADVANCED}

class AdaptivePolicyEngine:
    def __init__(self, config: dict): self.config=config
    @classmethod
    def load(cls,path: str|Path=DEFAULT_POLICY_PATH): return cls(yaml.safe_load(Path(path).read_text("utf-8")))
    def decide(self,c: DecisionContext)->PolicyDecision:
        threshold=float(self.config["acceptance_thresholds"].get(c.criticality.lower(),self.config["acceptance_thresholds"]["critical"]))
        if c.evidence_policy_satisfied and all(c.validation_results.values()) and not c.unresolved_contradiction and c.current_confidence>=threshold:
            return self._decision(PolicyAction.ACCEPT,"accept",["evidence_policy_satisfied"])
        if .60<=c.registration_confidence<.80 and PolicyAction.EXPAND_CROP not in c.previous_attempts:
            return self._decision(PolicyAction.EXPAND_CROP,"registration",["bounded_registration_uncertainty"])
        route=self._route(c); skipped=[]
        for name in self.config["routes"][route]:
            action=PolicyAction(name)
            if action in c.previous_attempts: continue
            if action is PolicyAction.REFERENCE_LOOKUP and not c.reference_available: skipped.append("reference_unavailable"); continue
            if action in _CLOUD and not c.cloud_processing_allowed: skipped.append("cloud_processing_disallowed"); continue
            p=self.config["actions"][action.value]
            if p["cost_usd"]>c.remaining_budget: skipped.append("budget_exceeded"); continue
            if p["latency_seconds"]>c.remaining_sla: skipped.append("sla_exceeded"); continue
            return self._decision(action,route,["needs_more_evidence",*sorted(set(skipped))])
        fallback=PolicyAction.HITL if PolicyAction.HITL not in c.previous_attempts else PolicyAction.ABSTAIN
        return self._decision(fallback,route,["automated_routes_exhausted",*sorted(set(skipped))])
    def _route(self,c):
        n=c.field_name.lower()
        if c.is_table_field:return "table"
        if "npi" in n:return "npi"
        if any(x in n for x in ("member_id","subscriber_id","patient_id")):return "member_id"
        if "name" in n:return "name"
        if any(x in n for x in ("date","amount","total","code","quantity","units")):return "constrained"
        return "default"
    def _decision(self,a,r,reasons):
        p=self.config["actions"].get(a.value,{"cost_usd":0,"latency_seconds":0})
        return PolicyDecision(action=a,route=r,reason_codes=reasons,estimated_cost_usd=p["cost_usd"],estimated_latency_seconds=p["latency_seconds"])
