from PIL import Image

from packages.ocr_cache import InMemoryOCRCache, ocr_cache_key
from workers.cascade.instrumented_text_extractor import CachedInstrumentedTextExtractor
from workers.page_detection.text_extraction import TextLine


class Backend:
    engine_name="test"; model_name="test-model"; model_version="1"
    def __init__(self): self.calls=0
    def extract_region(self,image,x0,y0,x1,y1):
        self.calls+=1; return [TextLine("VALUE",0,0,20,10,.9)]
    def extract(self,image): return self.extract_region(image,0,0,image.width,image.height)


def test_cache_key_is_content_and_version_aware():
    args=dict(crop_bytes=b"crop",engine="ocr",model_version="1",
              preprocessing_version="p1",configuration={"psm":7})
    assert ocr_cache_key(**args) == ocr_cache_key(**args)
    assert ocr_cache_key(**args) != ocr_cache_key(**{**args,"model_version":"2"})


def test_same_crop_configuration_executes_backend_once_and_audits_hit():
    backend=Backend(); records=[]
    wrapped=CachedInstrumentedTextExtractor(backend,cache=InMemoryOCRCache(),audit_sink=records.append)
    image=Image.new("L",(100,100),255)
    first=wrapped.extract_region(image,10,10,60,40)
    second=wrapped.extract_region(image,10,10,60,40)
    assert backend.calls == 1
    assert first == second
    assert [record.cache_hit for record in records] == [False,True]
    assert records[1].candidate_produced
