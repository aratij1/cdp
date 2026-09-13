"""Rebuild the extraction coordinate frame without intensity filtering.

A secondary identity observation must preserve thin printed labels while using
exactly the orientation and deskew recorded for its own prepared page.
"""
from PIL import Image

from workers.document_preparation.preprocessing import apply_orientation, deskew


def source_routing_image(original: Image.Image, transforms: list[dict],
                         expected_size: tuple[int, int]) -> Image.Image:
    image = original.copy()
    for transform in transforms:
        step = transform['step']
        parameters = transform['parameters']
        if step == 'orientation_correction':
            image = apply_orientation(image, parameters['rotation_degrees'])
        elif step == 'deskew':
            image = deskew(image, parameters['angle_degrees'])
        elif step not in {'denoise', 'contrast_enhancement'}:
            raise ValueError('UNSUPPORTED_ROUTING_SOURCE_TRANSFORM')
    if image.size != expected_size:
        raise ValueError('ROUTING_SOURCE_COORDINATE_MISMATCH')
    return image
