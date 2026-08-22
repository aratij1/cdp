"""Minimal XLSX sheet reader for runtime batch reference providers."""

from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"m": MAIN}


def _column(reference: str) -> int:
    value = 0
    for char in (char for char in reference if char.isalpha()):
        value = value * 26 + ord(char.upper()) - 64
    return value - 1


def read_sheet(path: Path, sheet_name: str) -> list[dict[str, str]]:
    with ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.text or "" for node in item.iter(f"{{{MAIN}}}t")) for item in root.findall("m:si", NS)]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {item.attrib["Id"]: item.attrib["Target"] for item in relationships}
        target = next((targets[sheet.attrib[f"{{{REL}}}id"]].lstrip("/") for sheet in workbook.findall(".//m:sheets/m:sheet", NS) if sheet.attrib["name"] == sheet_name), None)
        if target is None:
            raise ValueError(f"Workbook does not contain sheet {sheet_name!r}")
        target = target if target.startswith("xl/") else f"xl/{target}"
        xml = ET.fromstring(archive.read(target))
        matrix: list[list[str]] = []
        for row in xml.findall(".//m:sheetData/m:row", NS):
            values: dict[int, str] = {}
            for cell in row.findall("m:c", NS):
                raw, inline = cell.find("m:v", NS), cell.find("m:is", NS)
                value = "".join(node.text or "" for node in inline.iter(f"{{{MAIN}}}t")) if inline is not None else (raw.text if raw is not None else "")
                if cell.attrib.get("t") == "s" and value:
                    value = shared[int(value)]
                values[_column(cell.attrib["r"])] = str(value or "").strip()
            matrix.append([values.get(index, "") for index in range(max(values, default=-1) + 1)])
    if not matrix:
        return []
    headers = matrix[0]
    return [{header: row[index] if index < len(row) else "" for index, header in enumerate(headers)} for row in matrix[1:] if any(row)]
