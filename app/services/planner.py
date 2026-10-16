from __future__ import annotations
import sqlite3
import uuid
from collections import Counter, defaultdict
from typing import Any

from app.database import dump_json, load_json, utc_now
from app.services.nesting import pack_one_sheet


def _lot_is_eligible(lot: sqlite3.Row, project_code: str, grade: str, thickness: float,
                     allow_cross_project: bool = False) -> tuple[bool, str | None]:
    if lot["status"] != "available" or int(lot["quantity_available"]) < 1:
        return False, "not_available"
    if lot["material_grade"].strip().upper() != grade.strip().upper():
        return False, "material_grade_mismatch"
    if abs(float(lot["thickness_mm"]) - thickness) > 1e-6:
        return False, "thickness_mismatch"
    if lot["form"] != "plate":
        return False, "form_mismatch"
    if not bool(lot["traceability_verified"]):
        return False, "traceability_not_verified"
    if str(lot["material_condition"]).lower() not in {"verified", "good", "inspected", "released"}:
        return False, "condition_not_released"
    allocation = lot["project_code"]
    if lot["source_kind"] == "remnant" and not allocation:
        return False, "project_allocation_missing"
    if allocation and allocation != project_code and not allow_cross_project:
        return False, "cross_project_transfer_not_authorised"
    return True, None


def _unroll_components(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(component) for component in components]


def create_candidate(conn: sqlite3.Connection, order: sqlite3.Row, candidate_name: str,
                     strategy: str, source_policy: str) -> dict[str, Any]:
    spec = load_json(order["spec_json"])
    design = load_json(order["design_json"])
    components = _unroll_components(design["components"])
    inventory_rows = conn.execute(
        "SELECT * FROM inventory_lots WHERE quantity_available > 0 AND status = 'available' ORDER BY created_at, id"
    ).fetchall()

    groups: dict[tuple[str, float], list[dict[str, Any]]] = defaultdict(list)
    for p in components:
        groups[(str(p["material_grade"]).upper(), round(float(p["thickness_mm"]), 4))].append(p)

    all_sheets: list[dict[str, Any]] = []
    all_unplaced: list[str] = []
    rejection_counts: Counter[str] = Counter()
    new_procurement_cost = 0.0
    existing_stock_value = 0.0
    remnant_book_value = 0.0
    net_part_area = 0.0
    material_group_summaries = []
    sheet_index = 0

    for (grade, thickness), group_parts in groups.items():
        remaining = list(group_parts)
        candidate_lots = []
        for lot in inventory_rows:
            # Do not allow duplicate allocation beyond quantity available. Each candidate is an independent scenario.
            eligible, reason = _lot_is_eligible(lot, order["project_code"], grade, thickness, allow_cross_project=False)
            if not eligible:
                if reason:
                    rejection_counts[reason] += 1
                continue
            if source_policy == "new_stock_only" and lot["source_kind"] != "new_stock":
                continue
            candidate_lots.append(lot)

        def lot_sort_key(lot: sqlite3.Row):
            area = float(lot["width_mm"]) * float(lot["length_mm"])
            if source_policy == "remnant_first":
                rank = 0 if lot["source_kind"] == "remnant" else 1
            else:
                rank = 0
            return (rank, area, float(lot["unit_value"]), lot["id"])

        candidate_lots.sort(key=lot_sort_key)
        assignments: list[dict[str, Any]] = []

        for lot in candidate_lots:
            for unit_index in range(int(lot["quantity_available"])):
                if not remaining:
                    break
                packed = pack_one_sheet(remaining, float(lot["width_mm"]), float(lot["length_mm"]),
                                        float(spec["kerf_mm"]), float(spec["edge_trim_mm"]), strategy)
                if not packed["placements"]:
                    continue
                sheet_index += 1
                placed_ids = {p["part_id"] for p in packed["placements"]}
                remaining = [p for p in remaining if p["part_id"] not in placed_ids]
                source_kind = lot["source_kind"]
                assigned = {
                    "sheet_id": f"S{sheet_index:03d}", "inventory_lot_id": lot["id"],
                    "source_kind": source_kind, "source_reference": lot["id"],
                    "project_code": lot["project_code"], "material_grade": grade,
                    "thickness_mm": thickness, "width_mm": float(lot["width_mm"]),
                    "length_mm": float(lot["length_mm"]), "unit_value": float(lot["unit_value"]),
                    "placements": packed["placements"], "placed_count": packed["placed_count"],
                    "net_part_area_mm2": packed["net_part_area_mm2"],
                    "gross_stock_area_mm2": packed["gross_stock_area_mm2"],
                    "net_area_yield_pct": packed["net_area_yield_pct"],
                    "inventory_consumption_pending_approval": True,
                }
                all_sheets.append(assigned)
                assignments.append(assigned)
                net_part_area += float(packed["net_part_area_mm2"])
                if source_kind == "new_stock":
                    existing_stock_value += float(lot["unit_value"])
                else:
                    remnant_book_value += float(lot["unit_value"])
            if not remaining:
                break

        # If stock inventory cannot satisfy all parts, generate explicit planned-purchase candidates.
        procurement_sheets = 0
        max_purchase_sheets = max(1, min(1000, len(remaining) * 2))
        while remaining and procurement_sheets < max_purchase_sheets:
            packed = pack_one_sheet(remaining, float(spec["stock_width_mm"]), float(spec["stock_length_mm"]),
                                    float(spec["kerf_mm"]), float(spec["edge_trim_mm"]), strategy)
            if not packed["placements"]:
                impossible = list(remaining)
                all_unplaced.extend(p["part_id"] for p in impossible)
                break
            sheet_index += 1
            procurement_sheets += 1
            placed_ids = {p["part_id"] for p in packed["placements"]}
            remaining = [p for p in remaining if p["part_id"] not in placed_ids]
            all_sheets.append({
                "sheet_id": f"S{sheet_index:03d}", "inventory_lot_id": None,
                "source_kind": "planned_purchase", "source_reference": "PROCUREMENT_REQUIRED",
                "project_code": order["project_code"], "material_grade": grade,
                "thickness_mm": thickness, "width_mm": float(spec["stock_width_mm"]),
                "length_mm": float(spec["stock_length_mm"]), "unit_value": float(spec["raw_stock_unit_cost"]),
                "placements": packed["placements"], "placed_count": packed["placed_count"],
                "net_part_area_mm2": packed["net_part_area_mm2"],
                "gross_stock_area_mm2": packed["gross_stock_area_mm2"],
                "net_area_yield_pct": packed["net_area_yield_pct"],
                "inventory_consumption_pending_approval": False,
                "procurement_required": True,
            })
            net_part_area += float(packed["net_part_area_mm2"])
            new_procurement_cost += float(spec["raw_stock_unit_cost"])

        material_group_summaries.append({
            "material_grade": grade, "thickness_mm": thickness,
            "required_parts": len(group_parts), "unplaced_parts": len(remaining),
            "inventory_sheets_used": sum(1 for s in assignments), "procurement_sheets_required": procurement_sheets,
        })

    gross_area = sum(float(s["width_mm"]) * float(s["length_mm"]) for s in all_sheets)
    used_sheet_count = len(all_sheets)
    placed_count = sum(int(s["placed_count"]) for s in all_sheets)
    required_count = len(components)
    feasible = not all_unplaced and placed_count == required_count
    summary = {
        "candidate_name": candidate_name,
        "packing_strategy": strategy,
        "source_policy": source_policy,
        "feasible_for_all_parts": feasible,
        "required_part_count": required_count,
        "placed_part_count": placed_count,
        "unplaced_part_ids": all_unplaced,
        "sheet_count": used_sheet_count,
        "remnant_sheets_used": sum(1 for s in all_sheets if s["source_kind"] == "remnant"),
        "existing_new_stock_sheets_used": sum(1 for s in all_sheets if s["source_kind"] == "new_stock"),
        "new_procurement_sheets_required": sum(1 for s in all_sheets if s["source_kind"] == "planned_purchase"),
        "net_part_area_mm2": round(net_part_area, 3),
        "gross_stock_area_mm2": round(gross_area, 3),
        "net_area_yield_pct": round(100 * net_part_area / gross_area, 2) if gross_area else 0.0,
        "estimated_existing_stock_value": round(existing_stock_value, 2),
        "estimated_remnant_book_value": round(remnant_book_value, 2),
        "estimated_new_procurement_cost": round(new_procurement_cost, 2),
        "estimated_material_value_total": round(existing_stock_value + remnant_book_value + new_procurement_cost, 2),
        "material_groups": material_group_summaries,
        "eligibility_rejection_counts": dict(rejection_counts),
        "assumptions": [
            "Synthetic/prototype geometry: rectangular parts only; layouts are not CNC-ready.",
            "Net area yield is not an audited scrap rate and does not account for all industrial cutting constraints.",
            "The baseline is a deterministic next-fit/new-stock-only reference, not an assertion about the client's actual manual performance.",
            "Existing inventory value, remnant book value, and new procurement cost are reported separately; remnant reuse is not automatically a cash saving.",
        ],
    }
    return {"summary": summary, "sheets": all_sheets, "created_at": utc_now()}


def make_candidate_plans(conn: sqlite3.Connection, order: sqlite3.Row) -> list[dict[str, Any]]:
    candidates = [
        ("reference_baseline", "next_fit", "new_stock_only"),
        ("heuristic_only_comparison", "best_fit_decreasing", "new_stock_only"),
        ("remnant_policy_comparison", "next_fit", "remnant_first"),
        ("recommended_candidate", "best_fit_decreasing", "remnant_first"),
    ]
    output = []
    for name, strategy, policy in candidates:
        result = create_candidate(conn, order, name, strategy, policy)
        plan_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO plans(id, order_id, candidate_name, strategy, source_policy, status, result_json, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (plan_id, order["id"], name, strategy, policy, "draft", dump_json(result), utc_now()),
        )
        output.append({"plan_id": plan_id, **result})
    return output
