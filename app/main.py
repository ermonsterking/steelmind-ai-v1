from __future__ import annotations
import html
import json
import csv
import io
import zipfile
import sqlite3
import uuid
from contextlib import asynccontextmanager
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.config import APP_NAME, APP_VERSION, DEMO_SEED_ENABLED
from app.database import audit, dump_json, get_connection, init_db, load_json, seed_demo_inventory, utc_now
from app.schemas import (
    ApprovePlanRequest, CompleteOrderRequest, InterpretRequest, InventoryCreateRequest,
    OrderCreateRequest, ReceiveProcurementRequest,
)
from app.services.design import build_design
from app.services.dxf_export import build_review_dxf
from app.services.interpreter import interpret_prompt
from app.services.planner import make_candidate_plans

@asynccontextmanager
async def lifespan(application: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description=(
        "A controlled V1 proof of concept for order interpretation, rectangular plate packing, "
        "traceable remnant eligibility, costing scenarios, and human approval. Layouts are not CNC-ready."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def fetch_order(conn: sqlite3.Connection, order_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return row


def fetch_plan(conn: sqlite3.Connection, plan_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return row


def order_payload(row: sqlite3.Row, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    result = dict(row)
    result["spec"] = load_json(result.pop("spec_json"))
    result["design"] = load_json(result.pop("design_json"))
    if conn:
        result["plans"] = [plan_payload(p) for p in conn.execute(
            "SELECT * FROM plans WHERE order_id = ? ORDER BY created_at", (row["id"],)
        ).fetchall()]
    return result


def plan_payload(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["result"] = load_json(result.pop("result_json"))
    return result


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home() -> str:
    return f"""<!doctype html><html><head><title>{APP_NAME}</title></head><body style="font-family:system-ui;max-width:850px;margin:4rem auto;padding:0 1rem;">
    <h1>{APP_NAME} v{APP_VERSION}</h1><p>Order intake, rectangular plate-packing heuristics, remnant eligibility, cost estimates, and human review.</p>
    <p><a href='/docs'>Open API documentation</a> · <a href='/health'>Health check</a></p>
    <p><strong>Safety boundary:</strong> outputs are draft recommendations, not certified engineering designs or CNC-ready instructions. Engineering approval is mandatory.</p>
    </body></html>"""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": APP_NAME, "version": APP_VERSION}


@app.get("/api/v1/info")
def info() -> dict[str, Any]:
    return {
        "service": APP_NAME, "version": APP_VERSION,
        "scope": ["supported product templates", "rectangular plate components", "shelf-packing heuristics",
                  "traceability-gated remnant matching", "cost scenarios", "human approval and audit trail"],
        "not_in_v1": ["trained ML model", "arbitrary natural-language-to-CAD", "profile nesting", "load engineering",
                      "production CNC export", "identity and role management"],
        "demo_seed_enabled": DEMO_SEED_ENABLED,
        "deployment_warning": "V1 has no authentication/RBAC and is intended for local trusted evaluation only; do not expose publicly.",
    }


@app.post("/api/v1/demo/seed")
def seed_demo() -> dict[str, int]:
    if not DEMO_SEED_ENABLED:
        raise HTTPException(status_code=403, detail="Demo seeding is disabled by configuration")
    return seed_demo_inventory()


@app.post("/api/v1/orders/interpret")
def interpret_order(request: InterpretRequest) -> dict[str, Any]:
    return interpret_prompt(request.prompt).model_dump()


@app.post("/api/v1/orders", status_code=201)
def create_order(request: OrderCreateRequest) -> dict[str, Any]:
    try:
        design = build_design(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    spec = {
        "prompt": request.prompt,
        "product_type": request.product_type,
        "product_name": request.product_name,
        "quantity": request.quantity,
        "project_code": request.project_code,
        "length_mm": request.length_mm,
        "width_mm": request.width_mm,
        "height_mm": request.height_mm,
        "material_grade": request.material_grade,
        "thickness_mm": request.thickness_mm,
        "stock_length_mm": request.stock_length_mm,
        "stock_width_mm": request.stock_width_mm,
        "raw_stock_unit_cost": request.raw_stock_unit_cost,
        "kerf_mm": request.kerf_mm,
        "edge_trim_mm": request.edge_trim_mm,
        "parts_per_unit": [p.model_dump() for p in request.parts],
        "currency": "INR",
    }
    order_id = str(uuid.uuid4())
    order_number = f"SM-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{order_id[:6].upper()}"
    now = utc_now()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO orders(id, order_number, prompt, product_type, product_name, quantity, project_code, status, spec_json, design_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (order_id, order_number, request.prompt, request.product_type, request.product_name,
             request.quantity, request.project_code, "draft", dump_json(spec), dump_json(design), now, now),
        )
        audit(conn, "user", "order", order_id, "order_created", {
            "order_number": order_number, "product_type": request.product_type,
            "component_count": len(design["components"]), "human_review_required": True,
        })
        conn.commit()
        row = fetch_order(conn, order_id)
        return order_payload(row, conn)


@app.get("/api/v1/orders")
def list_orders(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [order_payload(row) for row in rows]


@app.get("/api/v1/orders/{order_id}")
def get_order(order_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        return order_payload(fetch_order(conn, order_id), conn)


@app.post("/api/v1/orders/{order_id}/plans", status_code=201)
def generate_plans(order_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        order = fetch_order(conn, order_id)
        if order["status"] in {"completed", "cancelled", "reserved_for_review"}:
            raise HTTPException(status_code=409, detail=f"Cannot generate plans for an order in status {order['status']}")
        plans = make_candidate_plans(conn, order)
        conn.execute("UPDATE orders SET status = 'planned', updated_at = ? WHERE id = ?", (utc_now(), order_id))
        audit(conn, "system", "order", order_id, "candidate_plans_generated", {
            "candidate_count": len(plans), "candidates": [p["summary"]["candidate_name"] for p in plans],
        })
        conn.commit()
        return {"order_id": order_id, "comparison_note": "Reference candidates are heuristic comparisons, not the client's actual manual/Strumis results.", "plans": plans}


@app.get("/api/v1/orders/{order_id}/plans")
def list_order_plans(order_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        fetch_order(conn, order_id)
        rows = conn.execute("SELECT * FROM plans WHERE order_id = ? ORDER BY created_at", (order_id,)).fetchall()
        return [plan_payload(row) for row in rows]


@app.get("/api/v1/plans/{plan_id}")
def get_plan(plan_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        return plan_payload(fetch_plan(conn, plan_id))


@app.post("/api/v1/plans/{plan_id}/approve")
def approve_plan(plan_id: str, request: ApprovePlanRequest) -> dict[str, Any]:
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        plan = fetch_plan(conn, plan_id)
        if plan["status"] != "draft":
            raise HTTPException(status_code=409, detail=f"Only a draft plan can be approved; current status is {plan['status']}")
        order = fetch_order(conn, plan["order_id"])
        existing = conn.execute(
            "SELECT id, status FROM plans WHERE order_id = ? AND id != ? AND status IN ('reserved_pending_engineering_signoff','approved_pending_procurement','completed')",
            (order["id"], plan_id),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Another candidate for this order is already approved/reserved. Release or resolve it before approving a second candidate.")
        result = load_json(plan["result_json"])
        summary = result["summary"]
        if not summary["feasible_for_all_parts"]:
            raise HTTPException(status_code=422, detail="This candidate does not place every required component and cannot be approved.")
        lot_counts = Counter(sheet["inventory_lot_id"] for sheet in result["sheets"] if sheet.get("inventory_lot_id"))
        for lot_id, qty in lot_counts.items():
            lot = conn.execute("SELECT * FROM inventory_lots WHERE id = ?", (lot_id,)).fetchone()
            if lot is None or lot["status"] != "available" or int(lot["quantity_available"]) < qty:
                raise HTTPException(status_code=409, detail=f"Inventory lot {lot_id} changed or is no longer available. Generate fresh candidate plans.")
            if lot["source_kind"] == "remnant" and lot["project_code"] != order["project_code"]:
                raise HTTPException(status_code=409, detail=f"Cross-project remnant reuse is not authorised for {lot_id}.")
            new_avail = int(lot["quantity_available"]) - qty
            new_reserved = int(lot["quantity_reserved"]) + qty
            next_status = "reserved" if new_avail == 0 and new_reserved > 0 else "available"
            conn.execute("UPDATE inventory_lots SET quantity_available = ?, quantity_reserved = ?, status = ? WHERE id = ?",
                         (new_avail, new_reserved, next_status, lot_id))
        has_procurement = int(summary["new_procurement_sheets_required"]) > 0
        new_status = "approved_pending_procurement" if has_procurement else "reserved_pending_engineering_signoff"
        conn.execute("UPDATE plans SET status = ?, approved_at = ? WHERE id = ?", (new_status, utc_now(), plan_id))
        conn.execute("UPDATE orders SET status = 'reserved_for_review', updated_at = ? WHERE id = ?", (utc_now(), order["id"]))
        audit(conn, request.actor, "plan", plan_id, "candidate_approved_for_review", {
            "note": request.note, "reserved_inventory_lots": dict(lot_counts),
            "procurement_sheets_required": summary["new_procurement_sheets_required"],
            "manufacturing_release": False,
        })
        conn.commit()
        fresh = fetch_plan(conn, plan_id)
        return {
            "plan": plan_payload(fresh),
            "reserved_inventory_lots": dict(lot_counts),
            "procurement_required": has_procurement,
            "next_step": "Engineering sign-off and procurement confirmation are required. This action does not release CNC instructions.",
        }


@app.post("/api/v1/plans/{plan_id}/receive-procurement")
def receive_procurement(plan_id: str, request: ReceiveProcurementRequest) -> dict[str, Any]:
    """Reconcile physically received, traceable stock against plan purchase requirements."""
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        plan = fetch_plan(conn, plan_id)
        if plan["status"] != "approved_pending_procurement":
            raise HTTPException(status_code=409, detail="This plan is not awaiting procurement receipt.")
        order = fetch_order(conn, plan["order_id"])
        result = load_json(plan["result_json"])
        planned = [sheet for sheet in result["sheets"] if sheet.get("source_kind") == "planned_purchase"]
        if len(request.inventory_lot_ids) != len(planned):
            raise HTTPException(status_code=422, detail=f"Expected exactly {len(planned)} received inventory lot ID entries, one per planned sheet.")

        lot_counts = Counter(request.inventory_lot_ids)
        loaded_lots: dict[str, sqlite3.Row] = {}
        for lot_id, qty in lot_counts.items():
            lot = conn.execute("SELECT * FROM inventory_lots WHERE id = ?", (lot_id,)).fetchone()
            if lot is None:
                raise HTTPException(status_code=404, detail=f"Received inventory lot {lot_id} does not exist.")
            if lot["source_kind"] != "new_stock" or lot["status"] != "available" or int(lot["quantity_available"]) < qty:
                raise HTTPException(status_code=409, detail=f"Lot {lot_id} is not available new-stock inventory in sufficient quantity.")
            if not bool(lot["traceability_verified"]) or str(lot["material_condition"]).lower() not in {"verified", "good", "inspected", "released"}:
                raise HTTPException(status_code=422, detail=f"Lot {lot_id} lacks verified traceability or released condition.")
            if lot["project_code"] != order["project_code"]:
                raise HTTPException(status_code=422, detail=f"Lot {lot_id} must be explicitly allocated to project {order['project_code']} before receipt reconciliation.")
            loaded_lots[lot_id] = lot

        # Match each expected purchase sheet to the lot ID supplied in order.
        receipt_value = 0.0
        for sheet, lot_id in zip(planned, request.inventory_lot_ids):
            lot = loaded_lots[lot_id]
            if (lot["material_grade"].upper() != sheet["material_grade"].upper()
                or abs(float(lot["thickness_mm"]) - float(sheet["thickness_mm"])) > 1e-6
                or abs(float(lot["width_mm"]) - float(sheet["width_mm"])) > 1.0
                or abs(float(lot["length_mm"]) - float(sheet["length_mm"])) > 1.0
                or lot["form"] != "plate"):
                raise HTTPException(status_code=422, detail=f"Received lot {lot_id} does not match the planned grade/thickness/form/dimensions for {sheet['sheet_id']}.")
            sheet["source_kind"] = "new_stock"
            sheet["source_reference"] = lot_id
            sheet["inventory_lot_id"] = lot_id
            sheet["unit_value"] = float(lot["unit_value"])
            sheet["procurement_received"] = True
            sheet["procurement_required"] = False
            sheet["inventory_consumption_pending_approval"] = True
            receipt_value += float(lot["unit_value"])

        # Reserve receipts only after every supplied lot has been validated.
        for lot_id, qty in lot_counts.items():
            lot = loaded_lots[lot_id]
            available = int(lot["quantity_available"]) - qty
            reserved = int(lot["quantity_reserved"]) + qty
            status = "reserved" if available == 0 and reserved > 0 else "available"
            conn.execute("UPDATE inventory_lots SET quantity_available = ?, quantity_reserved = ?, status = ? WHERE id = ?",
                         (available, reserved, status, lot_id))

        summary = result["summary"]
        summary["initial_estimated_procurement_cost"] = float(summary.get("initial_estimated_procurement_cost", summary["estimated_new_procurement_cost"]))
        summary["procurement_sheets_received"] = int(summary.get("procurement_sheets_received", 0)) + len(planned)
        summary["confirmed_procurement_value"] = round(float(summary.get("confirmed_procurement_value", 0.0)) + receipt_value, 2)
        summary["existing_new_stock_sheets_used"] = int(summary.get("existing_new_stock_sheets_used", 0)) + len(planned)
        summary["new_procurement_sheets_required"] = 0
        summary["estimated_new_procurement_cost"] = 0.0
        summary["estimated_material_value_total"] = round(
            float(summary["estimated_existing_stock_value"]) + float(summary["estimated_remnant_book_value"])
            + float(summary["confirmed_procurement_value"]), 2
        )
        result["summary"] = summary
        conn.execute("UPDATE plans SET result_json = ?, status = 'reserved_pending_engineering_signoff' WHERE id = ?",
                     (dump_json(result), plan_id))
        audit(conn, request.actor, "plan", plan_id, "procurement_received_and_reserved", {
            "note": request.note, "inventory_lot_ids": request.inventory_lot_ids,
            "received_sheet_count": len(planned), "confirmed_procurement_value": receipt_value,
        })
        conn.commit()
        return {
            "plan_id": plan_id, "status": "reserved_pending_engineering_signoff",
            "received_sheet_count": len(planned), "confirmed_procurement_value": round(receipt_value, 2),
            "next_step": "Engineering sign-off is still required; receipt reconciliation does not release manufacturing/CNC instructions.",
        }


@app.post("/api/v1/orders/{order_id}/complete")
def complete_order(order_id: str, request: CompleteOrderRequest) -> dict[str, Any]:
    if not request.engineering_signoff:
        raise HTTPException(status_code=422, detail="Engineering sign-off is required before completion.")
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        order = fetch_order(conn, order_id)
        plan = conn.execute("SELECT * FROM plans WHERE id = ? AND order_id = ?", (request.plan_id, order_id)).fetchone()
        if plan is None:
            raise HTTPException(status_code=404, detail="Plan does not belong to this order")
        if plan["status"] not in {"reserved_pending_engineering_signoff", "approved_pending_procurement"}:
            raise HTTPException(status_code=409, detail=f"Plan is not awaiting completion; status is {plan['status']}")
        result = load_json(plan["result_json"])
        if result["summary"]["new_procurement_sheets_required"]:
            raise HTTPException(status_code=409, detail="Record and reserve physically received procurement lots before completing this plan.")
        if int(result["summary"].get("procurement_sheets_received", 0)) > 0 and not request.procurement_confirmed:
            raise HTTPException(status_code=422, detail="Confirm the already reconciled procurement receipt before completion.")
        lot_counts = Counter(sheet["inventory_lot_id"] for sheet in result["sheets"] if sheet.get("inventory_lot_id"))
        for lot_id, qty in lot_counts.items():
            lot = conn.execute("SELECT * FROM inventory_lots WHERE id = ?", (lot_id,)).fetchone()
            if lot is None or int(lot["quantity_reserved"]) < qty:
                raise HTTPException(status_code=409, detail=f"Reservation is inconsistent for inventory lot {lot_id}.")
            new_available = int(lot["quantity_available"])
            new_reserved = int(lot["quantity_reserved"]) - qty
            new_consumed = int(lot["quantity_consumed"]) + qty
            status = "consumed" if new_available == 0 and new_reserved == 0 else ("reserved" if new_available == 0 else "available")
            conn.execute("UPDATE inventory_lots SET quantity_reserved = ?, quantity_consumed = ?, status = ? WHERE id = ?",
                         (new_reserved, new_consumed, status, lot_id))
        created_remnants = []
        for remnant in request.actual_remnants:
            project_code = remnant.project_code or order["project_code"]
            if project_code != order["project_code"]:
                raise HTTPException(status_code=422, detail="Cross-project remnant allocation is disabled in V1; record remnants against the completing order's project.")
            source_sheets = [sheet for sheet in result.get("sheets", [])
                             if str(sheet["material_grade"]).upper() == remnant.material_grade.upper()
                             and abs(float(sheet["thickness_mm"]) - remnant.thickness_mm) < 1e-6]
            remnant_fits_source = any(
                sorted([remnant.width_mm, remnant.length_mm]) <= sorted([float(sheet["width_mm"]), float(sheet["length_mm"])])
                for sheet in source_sheets
            )
            if not remnant_fits_source:
                raise HTTPException(status_code=422, detail="Reported remnant dimensions/material do not fit any source sheet in the selected plan. Verify the physical record and source material.")
            remnant_id = f"REM-{uuid.uuid4().hex[:10].upper()}"
            now = utc_now()
            conn.execute(
                """INSERT INTO inventory_lots(id, material_grade, form, thickness_mm, width_mm, length_mm,
                source_kind, project_code, quantity_available, quantity_reserved, quantity_consumed, unit_value,
                traceability_verified, material_condition, status, source_order_id, created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (remnant_id, remnant.material_grade, "plate", remnant.thickness_mm, remnant.width_mm, remnant.length_mm,
                 "remnant", project_code, 1, 0, 0, 0.0, int(remnant.traceability_verified), remnant.material_condition,
                 "available", order_id, now),
            )
            created_remnants.append(remnant_id)
        conn.execute("UPDATE plans SET status = 'completed', completed_at = ? WHERE id = ?", (utc_now(), request.plan_id))
        conn.execute("UPDATE orders SET status = 'completed', updated_at = ? WHERE id = ?", (utc_now(), order_id))
        audit(conn, request.actor, "order", order_id, "order_completed_with_human_signoff", {
            "plan_id": request.plan_id, "engineering_signoff": True,
            "procurement_confirmed": request.procurement_confirmed,
            "actual_remnants_created": created_remnants,
            "note": "Completion and remnants are human-reported; measurements require operational verification.",
        })
        conn.commit()
        return {"order_id": order_id, "status": "completed", "plan_id": request.plan_id,
                "consumed_inventory_lots": dict(lot_counts), "new_remnant_ids": created_remnants,
                "note": "This records a simulated/completed workflow. It does not release machine instructions or certify product safety."}


@app.get("/api/v1/inventory")
def list_inventory(available_only: bool = True, limit: int = Query(default=200, ge=1, le=1000)) -> list[dict[str, Any]]:
    with get_connection() as conn:
        where = "WHERE status = 'available'" if available_only else ""
        rows = conn.execute(f"SELECT * FROM inventory_lots {where} ORDER BY source_kind, created_at LIMIT ?", (limit,)).fetchall()
        return [dict(row) | {"traceability_verified": bool(row["traceability_verified"])} for row in rows]


@app.post("/api/v1/inventory", status_code=201)
def add_inventory(request: InventoryCreateRequest) -> dict[str, Any]:
    lot_id = request.id or f"INV-{uuid.uuid4().hex[:10].upper()}"
    now = utc_now()
    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM inventory_lots WHERE id = ?", (lot_id,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Inventory ID already exists")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT INTO inventory_lots(id, material_grade, form, thickness_mm, width_mm, length_mm,
            source_kind, project_code, quantity_available, quantity_reserved, quantity_consumed, unit_value,
            traceability_verified, material_condition, status, source_order_id, created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (lot_id, request.material_grade, request.form, request.thickness_mm, request.width_mm, request.length_mm,
             request.source_kind, request.project_code, request.quantity, 0, 0, request.unit_value,
             int(request.traceability_verified), request.material_condition, "available", None, now),
        )
        audit(conn, "user", "inventory", lot_id, "inventory_lot_added", {
            "source_kind": request.source_kind, "quantity": request.quantity,
            "traceability_verified": request.traceability_verified,
        })
        conn.commit()
        row = conn.execute("SELECT * FROM inventory_lots WHERE id = ?", (lot_id,)).fetchone()
        return dict(row) | {"traceability_verified": bool(row["traceability_verified"])}


@app.get("/api/v1/plans/{plan_id}/review-package.zip")
def download_review_package(plan_id: str) -> Response:
    """Export a review-only ZIP with plan JSON, BOM/part list, and illustrative SVGs."""
    with get_connection() as conn:
        plan = fetch_plan(conn, plan_id)
        order = fetch_order(conn, plan["order_id"])
        plan_data = load_json(plan["result_json"])
        design = load_json(order["design_json"])
        spec = load_json(order["spec_json"])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        manifest = {
            "package_type": "STEELMIND_REVIEW_ONLY",
            "order_number": order["order_number"],
            "order_id": order["id"],
            "plan_id": plan_id,
            "plan_status": plan["status"],
            "spec": spec,
            "design": design,
            "candidate": plan_data,
            "warning": "Review package only. Not a certified CAD assembly, not CNC-ready, and not approved manufacturing instructions.",
        }
        archive.writestr("review_manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        parts_buf = io.StringIO(newline="")
        writer = csv.DictWriter(parts_buf, fieldnames=["part_id", "component_name", "width_mm", "height_mm", "material_grade", "thickness_mm"])
        writer.writeheader()
        for part in design.get("components", []):
            writer.writerow({key: part.get(key) for key in writer.fieldnames})
        archive.writestr("component_schedule.csv", parts_buf.getvalue())
        for sheet in plan_data.get("sheets", []):
            stock_w = float(sheet["width_mm"])
            stock_h = float(sheet["length_mm"])
            scale = min(1000 / max(stock_w, 1), 700 / max(stock_h, 1))
            pad = 35
            svg_w, svg_h = stock_w * scale + 2 * pad, stock_h * scale + 2 * pad
            palette = ["#dceefe", "#d9f7e8", "#fce8c8", "#efdffc", "#f8d7da", "#d8f1f5"]
            shapes = []
            for item in sheet.get("placements", []):
                x = pad + float(item["x_mm"]) * scale
                y = pad + float(item["y_mm"]) * scale
                w = float(item["width_mm"]) * scale
                h = float(item["height_mm"]) * scale
                fill = palette[sum(ord(c) for c in item["part_id"]) % len(palette)]
                label = html.escape(str(item["part_id"]))
                shapes.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" fill="{fill}" stroke="#25415d" stroke-width="1.2"/>')
                if w > 35 and h > 15:
                    shapes.append(f'<text x="{x+w/2:.2f}" y="{y+h/2:.2f}" text-anchor="middle" dominant-baseline="middle" font-size="11">{label}</text>')
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w:.0f}" height="{svg_h:.0f}" viewBox="0 0 {svg_w:.0f} {svg_h:.0f}">'
                   f'<rect width="100%" height="100%" fill="#fff"/><text x="{pad}" y="20" font-size="14">{html.escape(sheet["sheet_id"])} · {html.escape(sheet["source_kind"])}</text>'
                   f'<rect x="{pad}" y="{pad}" width="{stock_w*scale:.2f}" height="{stock_h*scale:.2f}" fill="#f8fafc" stroke="#0f172a" stroke-width="2"/>'
                   + "".join(shapes) + f'<text x="{pad}" y="{svg_h-10}" font-size="11" fill="#b91c1c">Review only — not CNC-ready.</text></svg>')
            archive.writestr(f"layouts/{sheet['sheet_id']}.svg", svg)
            archive.writestr(f"layouts/{sheet['sheet_id']}-review-only.dxf", build_review_dxf(sheet))
        archive.writestr("IMPORTANT.txt", "This package is for design and algorithm review only. It is not a certified CAD assembly, structural calculation, machine/toolpath file, or CNC-ready instruction. Engineering and production validation are mandatory. Synthetic/prototype output must not be used to manufacture parts.\n")
    buffer.seek(0)
    filename = f"{order['order_number']}-{plan_id[:8]}-review-only.zip"
    return Response(content=buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/v1/orders/{order_id}/audit")
def get_order_audit(order_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        fetch_order(conn, order_id)
        rows = conn.execute(
            "SELECT * FROM audit_events WHERE (entity_type = 'order' AND entity_id = ?) OR (entity_type = 'plan' AND entity_id IN (SELECT id FROM plans WHERE order_id = ?)) ORDER BY created_at",
            (order_id, order_id),
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["details"] = load_json(item.pop("detail_json"))
            output.append(item)
        return output


@app.get("/api/v1/plans/{plan_id}/sheets/{sheet_id}.dxf")
def sheet_dxf(plan_id: str, sheet_id: str) -> Response:
    with get_connection() as conn:
        plan = fetch_plan(conn, plan_id)
        result = load_json(plan["result_json"])
    sheet = next((s for s in result["sheets"] if s["sheet_id"] == sheet_id), None)
    if sheet is None:
        raise HTTPException(status_code=404, detail="Sheet not found in plan")
    return Response(
        content=build_review_dxf(sheet),
        media_type="application/dxf",
        headers={"Content-Disposition": f'attachment; filename="{sheet_id}-review-only.dxf"'},
    )


@app.get("/api/v1/plans/{plan_id}/sheets/{sheet_id}.svg")
def sheet_svg(plan_id: str, sheet_id: str) -> Response:
    with get_connection() as conn:
        plan = fetch_plan(conn, plan_id)
        result = load_json(plan["result_json"])
    sheet = next((s for s in result["sheets"] if s["sheet_id"] == sheet_id), None)
    if sheet is None:
        raise HTTPException(status_code=404, detail="Sheet not found in plan")
    stock_w = float(sheet["width_mm"])
    stock_h = float(sheet["length_mm"])
    scale = min(1000 / max(stock_w, 1), 700 / max(stock_h, 1))
    pad = 35
    svg_w, svg_h = stock_w * scale + 2 * pad, stock_h * scale + 2 * pad
    parts = []
    palette = ["#dceefe", "#d9f7e8", "#fce8c8", "#efdffc", "#f8d7da", "#d8f1f5"]
    for item in sheet["placements"]:
        x = pad + float(item["x_mm"]) * scale
        y = pad + float(item["y_mm"]) * scale
        w = float(item["width_mm"]) * scale
        h = float(item["height_mm"]) * scale
        fill = palette[sum(ord(c) for c in item["part_id"]) % len(palette)]
        label = html.escape(item["part_id"])
        parts.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" fill="{fill}" stroke="#25415d" stroke-width="1.2"/>')
        if w > 35 and h > 15:
            parts.append(f'<text x="{x+w/2:.2f}" y="{y+h/2:.2f}" text-anchor="middle" dominant-baseline="middle" font-size="11">{label}</text>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w:.0f}" height="{svg_h:.0f}" viewBox="0 0 {svg_w:.0f} {svg_h:.0f}">'
           f'<rect width="100%" height="100%" fill="#ffffff"/><text x="{pad}" y="20" font-size="14" font-weight="bold">{html.escape(sheet_id)} · {html.escape(sheet["source_kind"])}</text>'
           f'<rect x="{pad}" y="{pad}" width="{stock_w*scale:.2f}" height="{stock_h*scale:.2f}" fill="#f8fafc" stroke="#0f172a" stroke-width="2"/>'
           + "".join(parts) + f'<text x="{pad}" y="{svg_h-10}" font-size="11" fill="#b91c1c">Illustrative layout only — not CNC-ready. Dimensions in mm.</text></svg>')
    return Response(content=svg, media_type="image/svg+xml", headers={"Content-Disposition": f'inline; filename="{sheet_id}.svg"'})


@app.exception_handler(sqlite3.IntegrityError)
def integrity_error_handler(request, exc: sqlite3.IntegrityError):
    return JSONResponse(status_code=409, content={"detail": "A database integrity constraint was violated. Check IDs, foreign keys, and state transitions."})
