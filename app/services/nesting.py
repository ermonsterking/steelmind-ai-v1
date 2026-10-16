from __future__ import annotations
from typing import Any


def _orientations(part: dict[str, Any], kerf_mm: float) -> list[dict[str, Any]]:
    w, h = float(part["width_mm"]), float(part["height_mm"])
    out = [{"width": w + kerf_mm, "height": h + kerf_mm, "actual_width": w,
            "actual_height": h, "rotated": False}]
    if part.get("allow_rotation", True) and abs(w - h) > 1e-9:
        out.append({"width": h + kerf_mm, "height": w + kerf_mm, "actual_width": h,
                    "actual_height": w, "rotated": True})
    return out


def pack_one_sheet(parts: list[dict[str, Any]], stock_width_mm: float, stock_length_mm: float,
                   kerf_mm: float = 3.0, edge_trim_mm: float = 10.0,
                   strategy: str = "best_fit_decreasing") -> dict[str, Any]:
    """Pack rectangular parts on one sheet using simple shelf heuristics.

    Coordinates are illustrative and are not CNC-ready. Kerf is conservatively
    added to each part's shelf occupancy. Arbitrary polygons, common-line cuts,
    lead-ins, clamping zones and machine-specific constraints are not modelled.
    """
    if strategy not in {"next_fit", "best_fit_decreasing"}:
        raise ValueError("strategy must be 'next_fit' or 'best_fit_decreasing'")
    usable_w = float(stock_width_mm) - 2 * float(edge_trim_mm)
    usable_h = float(stock_length_mm) - 2 * float(edge_trim_mm)
    if usable_w <= 0 or usable_h <= 0:
        raise ValueError("Edge trim leaves no usable stock area")

    original = list(parts)
    if strategy == "best_fit_decreasing":
        working = sorted(original, key=lambda p: (
            max(float(p["width_mm"]), float(p["height_mm"])),
            float(p["width_mm"]) * float(p["height_mm"])
        ), reverse=True)
    else:
        working = original

    shelves: list[dict[str, float]] = []
    placements: list[dict[str, Any]] = []
    unplaced: list[str] = []

    def place_on_shelf(part: dict[str, Any], shelf: dict[str, float]):
        choices = []
        for orient in _orientations(part, kerf_mm):
            if orient["height"] <= shelf["height"] + 1e-9 and orient["width"] <= usable_w - shelf["x"] + 1e-9:
                rem = usable_w - shelf["x"] - orient["width"]
                choices.append((rem, orient))
        if not choices:
            return None
        return min(choices, key=lambda x: x[0])[1]

    for part in working:
        chosen_shelf = None
        chosen_orientation = None
        candidate_shelves = shelves if strategy == "best_fit_decreasing" else shelves[-1:]
        row_choices = []
        for shelf in candidate_shelves:
            orient = place_on_shelf(part, shelf)
            if orient:
                leftover = usable_w - shelf["x"] - orient["width"]
                # Best-fit uses least horizontal residual; next-fit has only the current shelf.
                row_choices.append((leftover, shelf, orient))
        if row_choices:
            _, chosen_shelf, chosen_orientation = min(row_choices, key=lambda item: item[0])
        else:
            current_bottom = max((s["y"] + s["height"] for s in shelves), default=0.0)
            options = [o for o in _orientations(part, kerf_mm)
                       if o["width"] <= usable_w + 1e-9 and current_bottom + o["height"] <= usable_h + 1e-9]
            if options:
                # Prefer the orientation that leaves the least vertical space after creating a new row.
                chosen_orientation = min(options, key=lambda o: (usable_h - current_bottom - o["height"],
                                                                  usable_w - o["width"]))
                chosen_shelf = {"x": 0.0, "y": current_bottom, "height": chosen_orientation["height"]}
                shelves.append(chosen_shelf)
            else:
                unplaced.append(str(part["part_id"]))
                continue

        x = chosen_shelf["x"]
        y = chosen_shelf["y"]
        placements.append({
            "part_id": str(part["part_id"]),
            "component_name": str(part.get("component_name", part.get("name", "part"))),
            "x_mm": round(edge_trim_mm + x, 3),
            "y_mm": round(edge_trim_mm + y, 3),
            "width_mm": round(chosen_orientation["actual_width"], 3),
            "height_mm": round(chosen_orientation["actual_height"], 3),
            "rotated": bool(chosen_orientation["rotated"]),
            "material_grade": part.get("material_grade"),
            "thickness_mm": part.get("thickness_mm"),
        })
        chosen_shelf["x"] += chosen_orientation["width"]

    net_area = sum(p["width_mm"] * p["height_mm"] for p in placements)
    gross_area = float(stock_width_mm) * float(stock_length_mm)
    return {
        "stock_width_mm": float(stock_width_mm),
        "stock_length_mm": float(stock_length_mm),
        "usable_width_mm": usable_w,
        "usable_length_mm": usable_h,
        "strategy": strategy,
        "placements": placements,
        "unplaced_part_ids": unplaced,
        "placed_count": len(placements),
        "net_part_area_mm2": round(net_area, 3),
        "gross_stock_area_mm2": round(gross_area, 3),
        "net_area_yield_pct": round(100 * net_area / gross_area, 2) if gross_area else 0.0,
        "synthetic_or_candidate_layout": True,
        "cnc_ready": False,
    }
