"""Resolution-independent, explainable page-structure evidence for Router V4."""

from __future__ import annotations

from dataclasses import dataclass, asdict

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class StructuralDescriptors:
    horizontal_line_histogram: tuple[float, ...]
    vertical_line_histogram: tuple[float, ...]
    grid_density_map: tuple[float, ...]
    box_density_map: tuple[float, ...]
    region_occupancy: tuple[float, ...]
    service_table_repetition: float
    connected_component_distribution: tuple[float, ...]
    edge_projection: tuple[float, ...]

    def model_dump(self) -> dict:
        return asdict(self)


def _bins(values: np.ndarray, count: int) -> tuple[float, ...]:
    chunks=np.array_split(values.astype(float),count)
    maximum=max(float(values.max(initial=0)),1.0)
    return tuple(round(float(chunk.mean())/maximum,6) if chunk.size else 0.0 for chunk in chunks)


def describe_structure(image: Image.Image, *, bins: int = 12) -> StructuralDescriptors:
    """Describe relative layout; all outputs are normalized and contain no page text."""
    gray=np.asarray(image.convert("L"))
    scale=1000/max(gray.shape)
    if scale < 1:
        gray=cv2.resize(gray,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
    ink=cv2.threshold(gray,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)[1]
    h=cv2.morphologyEx(ink,cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT,(max(12,gray.shape[1]//30),1)))
    v=cv2.morphologyEx(ink,cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT,(1,max(12,gray.shape[0]//40))))
    rows=np.count_nonzero(h,axis=1); cols=np.count_nonzero(v,axis=0)
    grid=cv2.bitwise_or(h,v)
    density=[]; occupancy=[]
    for ys in np.array_split(np.arange(gray.shape[0]),4):
        for xs in np.array_split(np.arange(gray.shape[1]),3):
            region=grid[np.ix_(ys,xs)]; raw=ink[np.ix_(ys,xs)]
            density.append(float(np.count_nonzero(region))/max(region.size,1))
            occupancy.append(float(np.count_nonzero(raw))/max(raw.size,1))
    contours,_=cv2.findContours(grid,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    page=float(gray.size)
    boxes=[cv2.contourArea(c)/page for c in contours if cv2.contourArea(c)>page*.00005]
    box_hist=np.histogram(boxes,bins=6,range=(0,.08))[0]
    count,_,stats,_=cv2.connectedComponentsWithStats(ink,8)
    areas=stats[1:count,cv2.CC_STAT_AREA]/page if count>1 else np.array([])
    component_hist=np.histogram(areas,bins=6,range=(0,.01))[0]
    middle=rows[int(len(rows)*.18):int(len(rows)*.80)]
    line_rows=(middle > gray.shape[1]*.20).astype(np.uint8)
    transitions=np.diff(np.pad(line_rows,(1,1)))
    repetition=min(1.0,float(np.count_nonzero(transitions==1))/12.0)
    edges=cv2.Canny(gray,80,180)
    edge_projection=_bins(np.count_nonzero(edges,axis=1),bins//2)+_bins(np.count_nonzero(edges,axis=0),bins//2)
    return StructuralDescriptors(_bins(rows,bins),_bins(cols,bins),tuple(round(x,6) for x in density),
        tuple(float(x) for x in box_hist/max(int(box_hist.sum()),1)),tuple(round(x,6) for x in occupancy),
        repetition,tuple(float(x) for x in component_hist/max(int(component_hist.sum()),1)),edge_projection)

