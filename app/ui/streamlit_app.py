from __future__ import annotations
import json
import os
from typing import Any

import pandas as pd
import requests
import streamlit as st

API_URL = os.getenv("STEELMIND_API_URL", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(page_title="SteelMind AI · V1", page_icon="🧩", layout="wide")
st.markdown("""
<style>
.block-container {max-width: 1450px; padding-top: 1.3rem; padding-bottom: 3rem;}
.small-note {font-size: 0.88rem; color: #475569;}
[data-testid="stMetric"] {background: #f8fafc; border: 1px solid #e2e8f0; padding: 0.7rem; border-radius: 0.6rem;}
</style>
""", unsafe_allow_html=True)


def api(method: str, path: str, **kwargs):
    try:
        response = requests.request(method, f"{API_URL}{path}", timeout=20, **kwargs)
        if not response.ok:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            st.error(f"API returned {response.status_code}: {detail}")
            return None
        if response.status_code == 204:
            return {}
        return response.json()
    except requests.RequestException as exc:
        st.error(f"Cannot reach the SteelMind API at {API_URL}. Start the API server first. Details: {exc}")
        return None


def money(value: float) -> str:
    return f"₹{value:,.2f}"


def inventory_table():
    rows = api("GET", "/api/v1/inventory", params={"available_only": "false", "limit": 1000})
    if rows is not None:
        if rows:
            df = pd.DataFrame(rows)
            visible = [c for c in ["id", "material_grade", "thickness_mm", "width_mm", "length_mm", "source_kind",
                                   "project_code", "quantity_available", "quantity_reserved", "quantity_consumed",
                                   "unit_value", "traceability_verified", "material_condition", "status"] if c in df.columns]
            st.dataframe(df[visible], use_container_width=True, hide_index=True)
        else:
            st.info("Inventory is empty. Add verified material or load the synthetic demo fixture.")


def order_panel(order_id: str):
    order = api("GET", f"/api/v1/orders/{order_id}")
    if not order:
        return
    st.subheader(f"Order {order['order_number']}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Status", order["status"].replace("_", " ").title())
    m2.metric("Order quantity", order["quantity"])
    m3.metric("Design components", len(order["design"]["components"]))
    m4.metric("Project", order["project_code"])
    st.warning("The component schedule is a draft template. Engineering must confirm all dimensions, joints, material grades, and fabrication requirements. V1 is not load-rated and does not produce CNC-ready output.")
    with st.expander("Draft component schedule", expanded=True):
        comp_df = pd.DataFrame(order["design"]["components"])
        st.dataframe(comp_df, use_container_width=True, hide_index=True)
        st.write("**Assembly/design notes**")
        for note in order["design"]["assembly_notes"]:
            st.write(f"- {note}")

    if not order.get("plans") and order["status"] not in {"completed", "cancelled", "reserved_for_review"}:
        if st.button("Generate four candidate plans", key=f"plan_{order_id}", type="primary"):
            result = api("POST", f"/api/v1/orders/{order_id}/plans")
            if result:
                st.session_state[f"plans_{order_id}"] = result["plans"]
                st.success("Candidate plans generated. They are estimates based on current available inventory and synthetic packing heuristics.")
                st.rerun()
    elif not order.get("plans") and order["status"] == "reserved_for_review":
        st.info("This order has an approved/reserved candidate. Resolve or complete it before generating alternatives.")
    plans = st.session_state.get(f"plans_{order_id}")
    if plans is None:
        plans = order.get("plans", [])
        if plans:
            plans = [{**p, **p.get("result", {})} for p in plans]
    if plans:
        st.subheader("Candidate comparison")
        summary_rows = []
        for p in plans:
            res = p.get("result", p)
            summary = res["summary"]
            summary_rows.append({
                "Plan ID": p.get("plan_id", p.get("id")),
                "Candidate": summary["candidate_name"],
                "Packing": summary["packing_strategy"],
                "Source policy": summary["source_policy"],
                "Feasible": summary["feasible_for_all_parts"],
                "Plates/sheets": summary["sheet_count"],
                "Remnants used": summary["remnant_sheets_used"],
                "New purchase sheets": summary["new_procurement_sheets_required"],
                "Net area yield %": summary["net_area_yield_pct"],
                "New procurement cost": money(summary["estimated_new_procurement_cost"]),
                "Remnant book value": money(summary["estimated_remnant_book_value"]),
            })
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
        st.caption("These are modelled candidate comparisons, not the customer's actual manual/Strumis baseline. Remnant book value is not automatically cash savings. Layouts are not CNC-ready.")
        plan_options = {}
        for p in plans:
            pid = p.get("plan_id", p.get("id"))
            res = p.get("result", p)
            plan_options[f"{res['summary']['candidate_name']} · {pid[:8]}"] = (pid, p, res)
        selected_label = st.selectbox("Inspect a candidate", list(plan_options.keys()), key=f"selected_{order_id}")
        selected_id, selected_record, selected_result = plan_options[selected_label]
        summary = selected_result["summary"]
        st.markdown(f"#### {summary['candidate_name']}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Parts placed", f"{summary['placed_part_count']}/{summary['required_part_count']}")
        c2.metric("Sheets used", summary["sheet_count"])
        c3.metric("Net area yield", f"{summary['net_area_yield_pct']:.2f}%")
        c4.metric("Planned purchases", summary["new_procurement_sheets_required"])
        cost_cols = st.columns(4)
        cost_cols[0].metric("Existing stock value allocated", money(summary["estimated_existing_stock_value"]))
        cost_cols[1].metric("Remnant book value allocated", money(summary["estimated_remnant_book_value"]))
        cost_cols[2].metric("Pending procurement estimate", money(summary["estimated_new_procurement_cost"]))
        cost_cols[3].metric("Confirmed procurement value", money(summary.get("confirmed_procurement_value", 0.0)))
        if summary["eligibility_rejection_counts"]:
            with st.expander("Why some inventory was excluded"):
                st.json(summary["eligibility_rejection_counts"])
        for sheet in selected_result["sheets"]:
            with st.expander(f"{sheet['sheet_id']} · {sheet['source_kind']} · {sheet['width_mm']} × {sheet['length_mm']} mm"):
                st.write(f"Material: {sheet['material_grade']} · {sheet['thickness_mm']} mm")
                st.write(f"Parts placed: {sheet['placed_count']} · Net area yield: {sheet['net_area_yield_pct']}%")
                try:
                    raw = requests.get(f"{API_URL}/api/v1/plans/{selected_id}/sheets/{sheet['sheet_id']}.svg", timeout=10)
                    if raw.ok:
                        import streamlit.components.v1 as components
                        components.html(raw.text, height=460, scrolling=True)
                        st.download_button("Download SVG preview", raw.content, file_name=f"{sheet['sheet_id']}.svg", mime="image/svg+xml",
                                           key=f"svg_{order_id}_{selected_id}_{sheet['sheet_id']}")
                        dxf = requests.get(f"{API_URL}/api/v1/plans/{selected_id}/sheets/{sheet['sheet_id']}.dxf", timeout=10)
                        if dxf.ok:
                            st.download_button("Download 2D CAD review DXF (not CNC-ready)", dxf.content,
                                               file_name=f"{sheet['sheet_id']}-review-only.dxf", mime="application/dxf",
                                               key=f"dxf_{order_id}_{selected_id}_{sheet['sheet_id']}")
                    else:
                        st.info("SVG preview is currently unavailable.")
                except requests.RequestException:
                    st.info("SVG preview is currently unavailable.")
                st.dataframe(pd.DataFrame(sheet["placements"]), use_container_width=True, hide_index=True)
        st.download_button("Download selected plan JSON", json.dumps(selected_result, indent=2),
                           file_name=f"{summary['candidate_name']}.json", mime="application/json",
                           key=f"json_{order_id}_{selected_id}")
        try:
            review_response = requests.get(f"{API_URL}/api/v1/plans/{selected_id}/review-package.zip", timeout=20)
            if review_response.ok:
                st.download_button("Download review-only package (ZIP)", review_response.content,
                                   file_name=f"{summary['candidate_name']}-review-only.zip", mime="application/zip",
                                   key=f"review_zip_{order_id}_{selected_id}")
            else:
                st.caption("Review-package export is unavailable for this candidate.")
        except requests.RequestException:
            st.caption("Review-package export is currently unavailable.")
        approval_note = st.text_input("Engineer review note (record the reason for accepting this candidate)",
                                      value="Selected for controlled engineering/procurement review",
                                      key=f"approval_note_{order_id}_{selected_id}")
        if selected_record.get("status", "draft") == "draft" and st.button("Approve candidate for review / reserve inventory", key=f"approve_{order_id}_{selected_id}"):
            approved = api("POST", f"/api/v1/plans/{selected_id}/approve", json={"actor": "engineer", "note": approval_note})
            if approved:
                st.success(approved["next_step"])
                st.session_state.pop(f"plans_{order_id}", None)
                st.rerun()
        st.info("Approval reserves the selected existing inventory for controlled review. It does not release manufacturing or CNC instructions.")

        if selected_record.get("status") == "approved_pending_procurement":
            st.markdown("### Reconcile received procurement")
            purchase_sheets = [sheet for sheet in selected_result["sheets"] if sheet.get("source_kind") == "planned_purchase"]
            st.warning("The selected plan requires new plates. First receive them into Material inventory with the correct project allocation, dimensions, material grade, traceability and released condition. Then enter one inventory lot ID per planned sheet below.")
            st.dataframe(pd.DataFrame([{ "planned_sheet_id": s["sheet_id"], "material_grade": s["material_grade"],
                                         "thickness_mm": s["thickness_mm"], "width_mm": s["width_mm"],
                                         "length_mm": s["length_mm"], "expected_value": s["unit_value"] }
                                        for s in purchase_sheets]), use_container_width=True, hide_index=True)
            received_ids = st.text_input("Received inventory lot IDs, comma-separated; repeat an ID only if that lot contains multiple matching plates",
                                          key=f"received_lots_{order_id}_{selected_id}")
            if st.button("Validate and reserve received plates", key=f"receive_{order_id}_{selected_id}"):
                lot_ids = [v.strip() for v in received_ids.split(",") if v.strip()]
                response = api("POST", f"/api/v1/plans/{selected_id}/receive-procurement",
                               json={"inventory_lot_ids": lot_ids, "actor": "procurement",
                                     "note": "Physical receipt and allocation checked in the V1 workflow UI"})
                if response:
                    st.success(response["next_step"])
                    st.session_state.pop(f"plans_{order_id}", None)
                    st.rerun()
        if selected_record.get("status") == "reserved_pending_engineering_signoff":
            st.markdown("### Complete after engineering and procurement checks")
            st.caption("Use only after real-world checks in the project procedure are complete. This demo records completion and manually verified remnants; it does not certify a design or release CNC instructions.")
            with st.form(f"complete_{order_id}_{selected_id}"):
                engineering_signoff = st.checkbox("Engineering sign-off completed")
                procurement_confirmed = st.checkbox("Required new material has been procured/confirmed")
                add_remnant = st.checkbox("Record one measured remnant generated by this job")
                remnant_values = None
                if add_remnant:
                    rc1, rc2, rc3 = st.columns(3)
                    rem_w = rc1.number_input("Remnant width (mm)", min_value=1.0, value=400.0)
                    rem_l = rc2.number_input("Remnant length (mm)", min_value=1.0, value=600.0)
                    rem_t = rc3.number_input("Remnant thickness (mm)", min_value=0.1, value=float(order["spec"]["thickness_mm"]))
                    trace_ok = st.checkbox("Remnant identity and dimensions physically verified")
                    remnant_values = {"material_grade": order["spec"]["material_grade"], "thickness_mm": rem_t,
                                      "width_mm": rem_w, "length_mm": rem_l, "traceability_verified": trace_ok,
                                      "material_condition": "verified" if trace_ok else "inspection_required",
                                      "project_code": order["project_code"]}
                submit_complete = st.form_submit_button("Record controlled completion")
            if submit_complete:
                body = {"plan_id": selected_id, "engineering_signoff": engineering_signoff,
                        "procurement_confirmed": procurement_confirmed, "actor": "engineer",
                        "actual_remnants": [remnant_values] if remnant_values else []}
                completed = api("POST", f"/api/v1/orders/{order_id}/complete", json=body)
                if completed:
                    st.success("Completion recorded. Newly generated remnants are available only if their dimensions/traceability and condition pass later eligibility checks.")
                    st.session_state.pop(f"plans_{order_id}", None)
                    st.rerun()
        else:
            st.info("Select and approve a feasible candidate before the completion controls appear. No manufacturing release occurs in V1.")

    audit_rows = api("GET", f"/api/v1/orders/{order_id}/audit")
    if audit_rows:
        with st.expander("Audit trail"):
            st.dataframe(pd.DataFrame(audit_rows), use_container_width=True, hide_index=True)


st.title("🧩 SteelMind AI · V1")
st.caption("AI-assisted order interpretation · rectangular plate-packing · remnant eligibility · human-reviewed planning")
st.warning("Engineering prototype only. No trained ML model is included; prompt extraction is deterministic by default with an optional configured LLM adapter. Geometry is rectangular, layouts are not CNC-ready, and costs cover material allocation/procurement only—not labour, cutting, welding, coating, handling, or overhead. V1 has no authentication/RBAC: keep it on localhost or a trusted private environment.")

health = api("GET", "/health")
if health:
    st.sidebar.success(f"API connected · v{health['version']}")
else:
    st.sidebar.error("API unavailable")
st.sidebar.caption(f"API URL: {API_URL}")

order_tab, inventory_tab, previous_tab, help_tab = st.tabs(["1 · New order", "2 · Material inventory", "3 · Existing orders", "4 · Runbook & boundaries"])

with order_tab:
    st.subheader("Describe the order")
    default_prompt = "Build 4 workbenches, each 1200 x 600 x 850 mm, S275JR mild steel, 3 mm plate for the tabletop and mounting plates. Project DEMO-PROJECT."
    prompt = st.text_area("Customer order prompt", value=st.session_state.get("prompt_text", default_prompt), height=110, key="prompt_text")
    if st.button("Interpret prompt into a draft (not design approval)", type="secondary"):
        interpreted = api("POST", "/api/v1/orders/interpret", json={"prompt": prompt})
        if interpreted:
            st.session_state["interpreted"] = interpreted
    interpreted = st.session_state.get("interpreted")
    if interpreted:
        st.markdown("**Prompt interpretation (review before creating an order)**")
        st.json(interpreted)
        if interpreted["missing_questions"]:
            st.warning("The parser found missing fields. Resolve them before creating an order.")
    draft = interpreted or {}
    st.caption("The fields below are editable. Any prefilled value not extracted from the prompt is only a UI default—not a customer requirement—so verify every value before continuing.")
    with st.form("create_order_form"):
        a, b, c = st.columns(3)
        product_labels = {"Workbench panel kit": "workbench_panel_kit", "Flat panel kit": "flat_panel_kit", "Custom rectangular plate kit": "custom_plate_kit"}
        default_prod = draft.get("product_type") or "workbench_panel_kit"
        prod_label = st.selectbox("Supported template", list(product_labels.keys()), index=list(product_labels.values()).index(default_prod) if default_prod in product_labels.values() else 0)
        product_name = st.text_input("Order/product name", value=draft.get("product_name") or "Workbench panel kit")
        quantity = st.number_input("Order quantity", min_value=1, max_value=10000, value=int(draft.get("quantity") or 4))
        project_code = st.text_input("Project / allocation code", value="DEMO-PROJECT")
        length_mm = a.number_input("Product length (mm)", min_value=1.0, max_value=10000.0, value=float(draft.get("length_mm") or 1200))
        width_mm = b.number_input("Product width (mm)", min_value=1.0, max_value=10000.0, value=float(draft.get("width_mm") or 600))
        height_mm = c.number_input("Product height (mm)", min_value=1.0, max_value=10000.0, value=float(draft.get("height_mm") or 850))
        d, e, f = st.columns(3)
        material_grade = d.text_input("Material grade", value=draft.get("material_grade") or "S275JR")
        thickness_mm = e.number_input("Plate thickness (mm)", min_value=0.1, max_value=500.0, value=float(draft.get("thickness_mm") or 3.0), step=0.5)
        raw_cost = f.number_input("Assumed cost per new plate (₹; illustrative)", min_value=0.0, value=22000.0, step=500.0)
        g, h, i = st.columns(3)
        stock_length = g.number_input("New stock length (mm)", min_value=100.0, value=3000.0, step=100.0)
        stock_width = h.number_input("New stock width (mm)", min_value=100.0, value=1500.0, step=100.0)
        kerf_mm = i.number_input("Kerf allowance (mm)", min_value=0.0, value=3.0, step=0.5)
        edge_trim = st.number_input("Edge trim per side (mm)", min_value=0.0, value=10.0, step=1.0)
        use_custom_parts = st.checkbox("Override template with my own rectangular plate component list")
        custom_rows = []
        if use_custom_parts:
            base = pd.DataFrame([
                {"name": "panel_A", "width_mm": 400.0, "height_mm": 300.0, "quantity_per_unit": 2, "allow_rotation": True, "material_grade": None, "thickness_mm": None},
                {"name": "panel_B", "width_mm": 200.0, "height_mm": 150.0, "quantity_per_unit": 4, "allow_rotation": True, "material_grade": None, "thickness_mm": None},
            ])
            edit = st.data_editor(base, num_rows="dynamic", use_container_width=True, key="custom_parts_editor")
            custom_rows = edit.to_dict(orient="records")
            for row in custom_rows:
                for field, value in list(row.items()):
                    try:
                        missing_value = bool(pd.isna(value))
                    except (TypeError, ValueError):
                        missing_value = False
                    if missing_value:
                        row[field] = None
                    elif hasattr(value, "item"):
                        row[field] = value.item()
        confirm_spec = st.checkbox("I have reviewed and confirmed the order quantity, overall dimensions, material grade, thickness, project code and stock assumptions.")
        submitted = st.form_submit_button("Create draft order")
    if submitted and not confirm_spec:
        st.error("Please confirm the order fields before creating a draft.")
    if submitted and confirm_spec:
        payload = {
            "prompt": prompt, "product_type": product_labels[prod_label], "product_name": product_name,
            "quantity": int(quantity), "project_code": project_code, "length_mm": length_mm,
            "width_mm": width_mm, "height_mm": height_mm, "material_grade": material_grade,
            "thickness_mm": thickness_mm, "stock_length_mm": stock_length, "stock_width_mm": stock_width,
            "raw_stock_unit_cost": raw_cost, "kerf_mm": kerf_mm, "edge_trim_mm": edge_trim,
        }
        if use_custom_parts:
            payload["parts"] = custom_rows
        created = api("POST", "/api/v1/orders", json=payload)
        if created:
            st.session_state["active_order_id"] = created["id"]
            st.success(f"Draft order {created['order_number']} created. It has not been approved.")
            st.rerun()
    if st.session_state.get("active_order_id"):
        st.divider()
        order_panel(st.session_state["active_order_id"])

with inventory_tab:
    st.subheader("Material and remnant inventory")
    col_a, col_b = st.columns([1, 2])
    with col_a:
        if st.button("Load synthetic demo inventory"):
            seeded = api("POST", "/api/v1/demo/seed")
            if seeded:
                st.success(f"Demo inventory created: {seeded['created']}; existing demo records: {seeded['existing']}.")
    st.caption("Demo inventory is invented data. Real material should only be added after its identity, dimensions, condition, status, and allocation are verified.")
    with st.expander("Add a physical material lot/remnant"):
        with st.form("add_inventory_form"):
            inv_id = st.text_input("Inventory ID (optional; unique)")
            inv_grade = st.text_input("Material grade", value="S275JR")
            inv_thickness = st.number_input("Thickness (mm)", min_value=0.1, value=3.0, step=0.5)
            inv_width = st.number_input("Width (mm)", min_value=1.0, value=800.0, step=50.0)
            inv_length = st.number_input("Length (mm)", min_value=1.0, value=600.0, step=50.0)
            inv_kind_label = st.selectbox("Source kind", ["Remnant", "New stock"])
            inv_project = st.text_input("Project/allocation code (required for remnant)", value="DEMO-PROJECT")
            inv_qty = st.number_input("Quantity (remnant quantity must equal 1)", min_value=1, max_value=10000, value=1)
            inv_value = st.number_input("Book/purchase value per piece (₹; illustrative)", min_value=0.0, value=0.0, step=500.0)
            inv_trace = st.checkbox("Traceability verified against physical material record")
            inv_condition = st.selectbox("Material condition", ["verified", "inspection_required", "hold", "damaged", "unknown"])
            inv_submit = st.form_submit_button("Add inventory")
        if inv_submit:
            kind = "remnant" if inv_kind_label == "Remnant" else "new_stock"
            body = {"id": inv_id or None, "material_grade": inv_grade, "form": "plate", "thickness_mm": inv_thickness,
                    "width_mm": inv_width, "length_mm": inv_length, "source_kind": kind,
                    "project_code": inv_project if kind == "remnant" else (inv_project or None), "quantity": int(inv_qty),
                    "unit_value": inv_value, "traceability_verified": inv_trace, "material_condition": inv_condition}
            result = api("POST", "/api/v1/inventory", json=body)
            if result:
                st.success(f"Inventory record {result['id']} added.")
    inventory_table()

with previous_tab:
    st.subheader("Orders")
    orders = api("GET", "/api/v1/orders", params={"limit": 100})
    if orders:
        df = pd.DataFrame([{k: o[k] for k in ["id", "order_number", "product_name", "quantity", "project_code", "status", "created_at"]} for o in orders])
        st.dataframe(df, use_container_width=True, hide_index=True)
        choices = {f"{o['order_number']} · {o['product_name']} · {o['status']}": o["id"] for o in orders}
        chosen = st.selectbox("Open order", list(choices.keys()))
        if st.button("Open selected order"):
            st.session_state["active_order_id"] = choices[chosen]
            st.rerun()
        if st.session_state.get("active_order_id"):
            st.divider()
            order_panel(st.session_state["active_order_id"])
    else:
        st.info("No orders yet. Create a draft order in the first tab.")

with help_tab:
    st.subheader("V1 operating boundaries")
    st.markdown("""
- **Prompt interpretation:** deterministic regular-expression parsing by default; an optional configured LLM adapter can assist field extraction but output remains untrusted draft data.
- **Supported design:** parametric starter template for a limited workbench panel kit, flat-panel kit, or user-specified rectangular plate kit.
- **Geometry:** rectangular parts and simple shelf-packing heuristics; no arbitrary polygons, nesting kernels, profile cutting, bend development, weld design, or load calculations.
- **Remnants:** traceability, status, grade/thickness, condition, dimensions, and project allocation are eligibility gates. Cross-project remnant transfer is blocked in V1.
- **Costing:** estimated inventory value, remnant book value, and new procurement are separated. These are assumptions, not verified savings.
- **Human approval:** plans reserve inventory only after explicit review. Completion requires an engineering sign-off flag and procurement confirmation if new sheets are required. That records a pilot workflow; it does not constitute a legal/technical certification.
- **Deployment:** use on localhost or a trusted private network only. V1 has no authentication/RBAC, production secret management, or CNC release pipeline. A real deployment needs SSO/RBAC, TLS, backups, monitoring, change management, validated geometry, site-specific safety approval, and security review.
""")
    st.code("""# Terminal 1
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Terminal 2
source .venv/bin/activate
streamlit run app/ui/streamlit_app.py --server.address 127.0.0.1 --server.port 8501""", language="bash")
