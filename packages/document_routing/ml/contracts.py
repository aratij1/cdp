from pydantic import BaseModel,Field
class MLRouteEvidence(BaseModel):
    family:str;probability:float=Field(ge=0,le=1);model_version:str;feature_version:str
    top_positive_features:list[str]=Field(default_factory=list);top_negative_features:list[str]=Field(default_factory=list)
class FusedEligibilityEvidence(BaseModel):
    family:str;eligible:bool;deterministic_eligible:bool;ml_proposed_eligible:bool
    probability:float;threshold:float;deterministic_support:list[str]=Field(default_factory=list);reason_codes:list[str]=Field(default_factory=list)
