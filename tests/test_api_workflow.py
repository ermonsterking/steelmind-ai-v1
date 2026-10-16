import pytest
import zipfile
import io
from fastapi.testclient import TestClient

import app.database as database
import app.main as main_module
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "steelmind-test.db"))
    monkeypatch.setattr(main_module, "DEMO_SEED_ENABLED", True)
    with TestClient(app) as test_client:
        yield test_client


def order_payload(quantity=2):
    return {
        "prompt": f"Build {quantity} workbenches, each 1200 x 600 x 850 mm, S275JR mild steel, 3 mm plate. Project DEMO-PROJECT.",
        "product_type": "workbench_panel_kit", "product_name": "Test workbench kit",
        "quantity": quantity, "project_code": "DEMO-PROJECT", "length_mm": 1200,
        "width_mm": 600, "height_mm": 850, "material_grade": "S275JR", "thickness_mm": 3,
        "stock_length_mm": 3000, "stock_width_mm": 1500, "raw_stock_unit_cost": 22000,
        "kerf_mm": 3, "edge_trim_mm": 10,
    }


def test_health_and_interpretation(client):
    assert client.get("/health").status_code == 200
    result = client.post("/api/v1/orders/interpret", json={"prompt": order_payload()["prompt"]})
    assert result.status_code == 200
    assert result.json()["quantity"] == 2
    assert result.json()["thickness_mm"] == 3.0


def test_create_plan_approve_complete_and_audit(client):
    seed = client.post("/api/v1/demo/seed")
    assert seed.status_code == 200
    created = client.post("/api/v1/orders", json=order_payload())
    assert created.status_code == 201, created.text
    order = created.json()
    assert order["status"] == "draft"
    assert len(order["design"]["components"]) == 10

    plans_resp = client.post(f"/api/v1/orders/{order['id']}/plans")
    assert plans_resp.status_code == 201, plans_resp.text
    plans = plans_resp.json()["plans"]
    assert len(plans) == 4
    assert all(p["summary"]["feasible_for_all_parts"] for p in plans)
    candidate = next(p for p in plans if p["summary"]["candidate_name"] == "recommended_candidate")
    svg_resp = client.get(f"/api/v1/plans/{candidate['plan_id']}/sheets/{candidate['sheets'][0]['sheet_id']}.svg")
    assert svg_resp.status_code == 200
    assert "not CNC-ready" in svg_resp.text
    dxf_resp = client.get(f"/api/v1/plans/{candidate['plan_id']}/sheets/{candidate['sheets'][0]['sheet_id']}.dxf")
    assert dxf_resp.status_code == 200
    assert b"$INSUNITS" in dxf_resp.content
    assert b"NOT CNC-READY" in dxf_resp.content
    package_resp = client.get(f"/api/v1/plans/{candidate['plan_id']}/review-package.zip")
    assert package_resp.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(package_resp.content))
    assert "review_manifest.json" in archive.namelist()
    assert "component_schedule.csv" in archive.namelist()
    assert any(name.startswith("layouts/") and name.endswith(".svg") for name in archive.namelist())
    assert any(name.startswith("layouts/") and name.endswith(".dxf") for name in archive.namelist())
    assert "IMPORTANT.txt" in archive.namelist()

    approved = client.post(f"/api/v1/plans/{candidate['plan_id']}/approve", json={"actor": "test-engineer"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["plan"]["status"] in {"reserved_pending_engineering_signoff", "approved_pending_procurement"}

    missing_signoff = client.post(f"/api/v1/orders/{order['id']}/complete", json={"plan_id": candidate["plan_id"], "engineering_signoff": False})
    assert missing_signoff.status_code == 422

    done = client.post(f"/api/v1/orders/{order['id']}/complete", json={
        "plan_id": candidate["plan_id"], "engineering_signoff": True,
        "procurement_confirmed": True,
        "actual_remnants": [{"material_grade": "S275JR", "thickness_mm": 3, "width_mm": 200,
                             "length_mm": 300, "traceability_verified": True,
                             "material_condition": "verified", "project_code": "DEMO-PROJECT"}],
        "actor": "test-engineer",
    })
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"
    audit = client.get(f"/api/v1/orders/{order['id']}/audit")
    assert audit.status_code == 200
    assert any(item["action"] == "order_completed_with_human_signoff" for item in audit.json())


def test_custom_plate_kit_requires_parts(client):
    payload = order_payload()
    payload["product_type"] = "custom_plate_kit"
    response = client.post("/api/v1/orders", json=payload)
    assert response.status_code == 422


def test_cross_project_remnant_is_not_used(client):
    client.post("/api/v1/demo/seed")
    created = client.post("/api/v1/orders", json=order_payload())
    plans = client.post(f"/api/v1/orders/{created.json()['id']}/plans").json()["plans"]
    recommended = next(p for p in plans if p["summary"]["candidate_name"] == "recommended_candidate")
    reject_counts = recommended["summary"]["eligibility_rejection_counts"]
    assert reject_counts.get("cross_project_transfer_not_authorised", 0) >= 1
    used_ids = {s["inventory_lot_id"] for s in recommended["sheets"] if s["inventory_lot_id"]}
    assert "DEMO-REMNANT-002" not in used_ids


def test_order_component_limit_fails_safely(client):
    payload = order_payload(quantity=1000)
    payload["product_type"] = "custom_plate_kit"
    payload["parts"] = [{"name": "panel", "width_mm": 100, "height_mm": 100, "quantity_per_unit": 3}]
    response = client.post("/api/v1/orders", json=payload)
    assert response.status_code == 422
    assert "2,500 physical rectangular components" in response.json()["detail"]


def test_purchase_requirement_must_be_received_and_reserved_before_completion(client):
    payload = order_payload(quantity=1)
    payload["project_code"] = "PROJECT-X"
    payload["material_grade"] = "A36"
    payload["thickness_mm"] = 4.0
    payload["prompt"] = "Build 1 workbench 1200 x 600 x 850 mm, A36, 4 mm plate, project PROJECT-X"
    created = client.post("/api/v1/orders", json=payload)
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]
    plans = client.post(f"/api/v1/orders/{order_id}/plans").json()["plans"]
    candidate = next(p for p in plans if p["summary"]["candidate_name"] == "recommended_candidate")
    assert candidate["summary"]["new_procurement_sheets_required"] >= 1
    approved = client.post(f"/api/v1/plans/{candidate['plan_id']}/approve", json={"actor": "test-procurement"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["plan"]["status"] == "approved_pending_procurement"

    blocked = client.post(f"/api/v1/orders/{order_id}/complete", json={
        "plan_id": candidate["plan_id"], "engineering_signoff": True, "procurement_confirmed": True,
    })
    assert blocked.status_code == 409

    receipt = client.post("/api/v1/inventory", json={
        "id": "PROC-RECEIPT-001", "material_grade": "A36", "form": "plate", "thickness_mm": 4,
        "width_mm": 1500, "length_mm": 3000, "source_kind": "new_stock", "project_code": "PROJECT-X",
        "quantity": candidate["summary"]["new_procurement_sheets_required"], "unit_value": 21500,
        "traceability_verified": True, "material_condition": "verified",
    })
    assert receipt.status_code == 201, receipt.text
    ids = ["PROC-RECEIPT-001"] * candidate["summary"]["new_procurement_sheets_required"]
    reconciled = client.post(f"/api/v1/plans/{candidate['plan_id']}/receive-procurement", json={
        "inventory_lot_ids": ids, "actor": "test-procurement",
    })
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["status"] == "reserved_pending_engineering_signoff"

    completed = client.post(f"/api/v1/orders/{order_id}/complete", json={
        "plan_id": candidate["plan_id"], "engineering_signoff": True, "procurement_confirmed": True,
    })
    assert completed.status_code == 200, completed.text
    inventory = client.get("/api/v1/inventory", params={"available_only": "false"}).json()
    received_lot = next(r for r in inventory if r["id"] == "PROC-RECEIPT-001")
    assert received_lot["quantity_consumed"] == len(ids)


def test_demo_seed_endpoint_is_closed_when_disabled(client, monkeypatch):
    monkeypatch.setattr(main_module, "DEMO_SEED_ENABLED", False)
    response = client.post("/api/v1/demo/seed")
    assert response.status_code == 403
