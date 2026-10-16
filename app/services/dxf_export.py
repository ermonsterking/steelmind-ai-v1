from __future__ import annotations
from typing import Any


def _fmt(value: float) -> str:
    return f"{float(value):.4f}".rstrip("0").rstrip(".") or "0"


def _line(layer: str, x1: float, y1: float, x2: float, y2: float) -> list[str]:
    return [
        "0", "LINE", "8", layer,
        "10", _fmt(x1), "20", _fmt(y1), "30", "0",
        "11", _fmt(x2), "21", _fmt(y2), "31", "0",
    ]


def _rectangle(layer: str, x: float, y: float, width: float, height: float) -> list[str]:
    return (
        _line(layer, x, y, x + width, y)
        + _line(layer, x + width, y, x + width, y + height)
        + _line(layer, x + width, y + height, x, y + height)
        + _line(layer, x, y + height, x, y)
    )


def build_review_dxf(sheet: dict[str, Any]) -> bytes:
    """Return minimal ASCII DXF R12 for review of rectangular placements only.

    This export intentionally contains outlines only. It is not a toolpath,
    CNC program, cut sequence, or production release file.
    """
    width = float(sheet["width_mm"])
    length = float(sheet["length_mm"])
    lines = [
        "999", "STEELMIND REVIEW-ONLY: NOT CNC-READY; no cut sequence, kerf compensation, lead-ins, clamps or machine postprocessing.",
        "0", "SECTION", "2", "HEADER",
        "9", "$ACADVER", "1", "AC1009",
        "9", "$INSUNITS", "70", "4",
        "0", "ENDSEC",
        "0", "SECTION", "2", "TABLES",
        "0", "TABLE", "2", "LTYPE", "70", "1",
        "0", "LTYPE", "2", "CONTINUOUS", "70", "0", "3", "Solid line", "72", "65", "73", "0", "40", "0",
        "0", "ENDTAB",
        "0", "TABLE", "2", "LAYER", "70", "3",
        "0", "LAYER", "2", "0", "70", "0", "62", "7", "6", "CONTINUOUS",
        "0", "LAYER", "2", "STOCK_BOUNDARY", "70", "0", "62", "7", "6", "CONTINUOUS",
        "0", "LAYER", "2", "PART_OUTLINE", "70", "0", "62", "3", "6", "CONTINUOUS",
        "0", "LAYER", "2", "PART_ID", "70", "0", "62", "2", "6", "CONTINUOUS",
        "0", "ENDTAB",
        "0", "ENDSEC",
        "0", "SECTION", "2", "ENTITIES",
    ]
    lines += _rectangle("STOCK_BOUNDARY", 0, 0, width, length)
    # Labels are simple ASCII identifiers created by the app (P0001, etc.).
    for part in sheet.get("placements", []):
        x = float(part["x_mm"])
        y = float(part["y_mm"])
        w = float(part["width_mm"])
        h = float(part["height_mm"])
        lines += _rectangle("PART_OUTLINE", x, y, w, h)
        label_height = min(20.0, max(4.0, min(w, h) * 0.12))
        lines += [
            "0", "TEXT", "8", "PART_ID",
            "10", _fmt(x + w / 2), "20", _fmt(y + h / 2), "30", "0",
            "40", _fmt(label_height), "1", str(part["part_id"]),
            "50", "0", "72", "1", "73", "2",
        ]
    lines += ["0", "ENDSEC", "0", "EOF", ""]
    return "\n".join(lines).encode("ascii", errors="replace")
