from __future__ import annotations
from typing import Any
from app.schemas import OrderCreateRequest


def build_design(request: OrderCreateRequest) -> dict[str, Any]:
    """Create a small, reviewable component schedule. Not a structural design engine."""
    definitions: list[dict[str, Any]] = []
    if request.parts:
        definitions = [part.model_dump() for part in request.parts]
    elif request.product_type == "workbench_panel_kit":
        definitions = [
            {"name": "tabletop_panel", "width_mm": request.length_mm, "height_mm": request.width_mm,
             "quantity_per_unit": 1, "allow_rotation": True, "material_grade": request.material_grade,
             "thickness_mm": request.thickness_mm},
            {"name": "mounting_plate", "width_mm": 80.0, "height_mm": 60.0,
             "quantity_per_unit": 4, "allow_rotation": True, "material_grade": request.material_grade,
             "thickness_mm": request.thickness_mm},
        ]
    elif request.product_type == "flat_panel_kit":
        definitions = [
            {"name": "main_panel", "width_mm": request.length_mm, "height_mm": request.width_mm,
             "quantity_per_unit": 1, "allow_rotation": True, "material_grade": request.material_grade,
             "thickness_mm": request.thickness_mm},
        ]
    else:
        raise ValueError("custom_plate_kit requires at least one component definition.")

    projected_count = sum(int(definition.get("quantity_per_unit", 1)) for definition in definitions) * request.quantity
    if projected_count > 2500:
        raise ValueError("V1 limits an order to 2,500 physical rectangular components. Split larger orders or use a batch-capable implementation.")

    components: list[dict[str, Any]] = []
    component_counter = 0
    for definition in definitions:
        qty = int(definition.get("quantity_per_unit", 1)) * request.quantity
        grade = definition.get("material_grade") or request.material_grade
        thickness = float(definition.get("thickness_mm") or request.thickness_mm)
        for i in range(qty):
            component_counter += 1
            components.append({
                "part_id": f"P{component_counter:04d}",
                "component_name": str(definition["name"]),
                "width_mm": float(definition["width_mm"]),
                "height_mm": float(definition["height_mm"]),
                "allow_rotation": bool(definition.get("allow_rotation", True)),
                "material_grade": str(grade),
                "thickness_mm": thickness,
            })
    return {
        "design_type": request.product_type,
        "design_state": "DRAFT_REQUIRES_ENGINEERING_REVIEW",
        "overall_dimensions_mm": {"length": request.length_mm, "width": request.width_mm, "height": request.height_mm},
        "quantity": request.quantity,
        "components": components,
        "assembly_notes": [
            "Component schedule is an initial parametric template, not a complete CAD assembly or certified engineering design.",
            "For workbench panel kits, tabletop and rectangular mounting plates are included; legs, profiles, joints, welds, load validation, stability and fastener selection are not designed by V1.",
            "An engineer must validate specifications, component geometry, revision status, manufacturing constraints and assembly before production.",
        ],
        "excluded_from_v1": [
            "structural/load calculations", "profile/beam cutting plans", "bend allowances and flat-pattern validation",
            "weld/joint design", "freeform CAD generation", "CNC-ready export", "automatic production release"
        ],
    }
