from pydantic import BaseModel,Field
class VisualRouteEvidence(BaseModel):
    family:str;probability:float=Field(ge=0,le=1);model_version:str;feature_version:str
    top_visual_regions:list[str]=Field(default_factory=list);explanation_codes:list[str]=Field(default_factory=list)
