from types import SimpleNamespace

import pytest
from PIL import Image

from packages.document_routing import MultiSignalRoute
from workers.page_detection.router import PageRoutingService
from workers.page_detection.text_extraction import ModelNotAvailableError


def decision(route, *, conflicts=None, allowed=False):
    return SimpleNamespace(route=route, scores={'CMS1500': .7, 'UB04': .1},
        conflicting_anchors=conflicts or {}, identity_state={'CMS1500':'UNKNOWN','UB04':'UNKNOWN'},
        localization_allowed=allowed, reason_codes=['SYNTHETIC'], confidence=.9)


class Engine:
    engine_name='synthetic-secondary'
    model_version='1'
    def __init__(self, unavailable=False):self.calls=0;self.unavailable=unavailable
    def extract(self,image):
        self.calls+=1
        if self.unavailable:raise ModelNotAvailableError('SYNTHETIC')
        return ['SECONDARY_ONLY']


class Brain:
    def __init__(self,*results):self.results=iter(results);self.inputs=[]
    def route(self,image,lines):self.inputs.append(lines);return next(self.results)


def service(brain,engine):
    return PageRoutingService(SimpleNamespace(template_id='cms1500'),None,
        multi_signal_router=brain,enable_router_v3=True,secondary_text_extractor=engine)


def test_secondary_must_verify_on_its_own_without_merged_anchors():
    primary=decision(MultiSignalRoute.OTHER_CLAIM_FORM)
    secondary=decision(MultiSignalRoute.CMS1500,allowed=True)
    brain=Brain(primary,secondary);engine=Engine()
    result,attempts=service(brain,engine)._canonical_decision(Image.new('L',(10,10)),['PRIMARY_ONLY'])
    assert result is secondary
    assert brain.inputs==[['PRIMARY_ONLY'],['SECONDARY_ONLY']]
    assert [a['selected'] for a in attempts]==[False,True]
    assert attempts[1]['engine']=='synthetic-secondary'


@pytest.mark.parametrize('route',[MultiSignalRoute.CMS1500,MultiSignalRoute.NON_CLAIM,
                                  MultiSignalRoute.UNKNOWN_UNSTRUCTURED])
def test_conclusive_and_nonclaim_routes_do_not_invoke_secondary(route):
    primary=decision(route);engine=Engine()
    result,_=service(Brain(primary),engine)._canonical_decision(Image.new('L',(10,10)),[])
    assert result is primary and engine.calls==0


def test_primary_context_veto_cannot_be_erased_by_secondary():
    primary=decision(MultiSignalRoute.OTHER_CLAIM_FORM,conflicts={'CMS1500':['SAMPLE_VETO']})
    engine=Engine();result,_=service(Brain(primary),engine)._canonical_decision(Image.new('L',(10,10)),[])
    assert result is primary and engine.calls==0


@pytest.mark.parametrize('route,allowed',[(MultiSignalRoute.OTHER_CLAIM_FORM,False),
    (MultiSignalRoute.CMS1500,False),(MultiSignalRoute.UB04,True)])
def test_inconclusive_unverified_or_opposing_secondary_keeps_primary(route,allowed):
    primary=decision(MultiSignalRoute.OTHER_CLAIM_FORM)
    result,_=service(Brain(primary,decision(route,allowed=allowed)),Engine())._canonical_decision(
        Image.new('L',(10,10)),[])
    assert result is primary


def test_missing_secondary_dependency_preserves_primary_and_records_unavailability():
    primary=decision(MultiSignalRoute.OTHER_CLAIM_FORM)
    result,attempts=service(Brain(primary),Engine(True))._canonical_decision(Image.new('L',(10,10)),[])
    assert result is primary
    assert attempts[-1]['status']=='SECONDARY_OCR_UNAVAILABLE'


def test_multipage_secondary_recovery_does_not_pick_one_of_two_claim_pages():
    brain=Brain(decision(MultiSignalRoute.OTHER_CLAIM_FORM),
                decision(MultiSignalRoute.CMS1500,allowed=True),
                decision(MultiSignalRoute.CMS1500,allowed=True))
    result=service(brain,Engine()).route([Image.new('L',(10,10)),Image.new('L',(10,10))])
    assert result.selected_page_number is None and result.needs_review
    assert len(result.ocr_attempts)==3
