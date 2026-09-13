import pytest
from PIL import Image

from workers.page_detection.source_representation import source_routing_image


def test_source_routing_preserves_thin_ink_and_replays_only_geometry():
    image=Image.new('L',(3,5),255);image.putpixel((1,1),0)
    transforms=[{'step':'orientation_correction','parameters':{'rotation_degrees':90}},
                {'step':'deskew','parameters':{'angle_degrees':0}},
                {'step':'denoise','parameters':{}},
                {'step':'contrast_enhancement','parameters':{}}]
    result=source_routing_image(image,transforms,(5,3))
    assert result.tobytes()==image.rotate(-90,expand=True).tobytes()
    assert image.size==(3,5) and image.getpixel((1,1))==0


def test_source_routing_rejects_unknown_transform_and_wrong_frame_size():
    with pytest.raises(ValueError,match='UNSUPPORTED_ROUTING_SOURCE_TRANSFORM'):
        source_routing_image(Image.new('L',(3,5)),[{'step':'crop','parameters':{}}],(3,5))
    with pytest.raises(ValueError,match='ROUTING_SOURCE_COORDINATE_MISMATCH'):
        source_routing_image(Image.new('L',(3,5)),[],(5,3))
