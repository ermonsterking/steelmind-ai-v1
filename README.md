# SteelMind AI — V1 Engineering MVP

**Prompt-assisted order intake → supported component schedule → material/remnant screening → rectangular plate-packing candidates → cost comparison → human review and audit.**

SteelMind AI is a locally deployable proof of concept for a narrow, explicitly bounded manufacturing use case. It is designed to demonstrate the software architecture and operating controls needed before connecting to real fabrication systems.

> **Important boundary:** V1 is not a certified CAD system, structural design tool, industrial nesting solver, or CNC/postprocessor. Do not use its output directly to manufacture a product. Product templates and layouts require qualified engineering review. The app is bound to localhost by default when using Docker and has no authentication/RBAC; it is not ready to expose to the public internet.

## What V1 includes

- A web UI (Streamlit) and API (FastAPI).
- Natural-language order extraction using conservative deterministic rules by default. An optional OpenAI-compatible LLM adapter can be enabled; all results remain drafts and must be reviewed.
- Three limited input modes: workbench panel kit, flat panel kit, and user-defined rectangular plate kit.
- A draft component schedule. The starter workbench template includes a tabletop and rectangular mounting plates only; it does not design legs/profiles, welds, joints, fasteners, load-bearing members, or structural safety.
- Four candidate comparisons that separate two factors rather than mix them silently:
  1. next-fit packing with new stock only (reference heuristic),
  2. best-fit-decreasing with new stock only (packing heuristic comparison),
  3. next-fit with eligible remnants considered first (source policy comparison),
  4. best-fit-decreasing with eligible remnants considered first (recommended candidate).
- Simple rectangular shelf-packing heuristics with rotation control, edge-trim and conservative kerf allowance, explicit placements, SVG previews, review-only rectangular DXF exports, area-yield metric, and unplaced-part detection.
- Persistent inventory records with grade/form/thickness, dimensions, source, project allocation, traceability, condition, availability/reservation/consumption counts, and inventory value.
- Remnant eligibility gates. Cross-project remnant transfer is blocked in V1. Unverified or held/damaged/unknown-condition material is not recommended.
- Separate reporting for current new-stock inventory value, remnant book value, and newly planned procurement cost. This prevents an inventory remnant from being mistaken automatically for cash savings.
- An approval/reservation/completion state machine, mandatory engineering-signoff flag, procurement-confirmation guard when extra sheets are needed, recorded actual remnant dimensions, and an audit trail.
- Unit/API tests and Docker Compose configuration.

## What V1 deliberately does not claim

- No trained ML model is shipped. The optional LLM only extracts draft fields from a prompt; it does not create or validate engineering geometry.
- No arbitrary natural-language-to-CAD generation, general-purpose parametric assembly, profile/beam nesting, polygon nesting, bend/flat-pattern validation, weld/joint design, load calculations, machine clamping/lead-in/toolpath simulation, or CNC-ready outputs.
- No direct integration with Strumis, PLM, ERP, CNC, fleet, or yard systems.
- No guaranteed savings or global optimality. A 2D shelf heuristic is an illustrative candidate generator.
- No user authentication, RBAC, enterprise SSO, security certification, multi-tenant isolation, or production disaster-recovery design.

## Repository layout

```text
steelmind-ai-v1/
├── app/
│   ├── main.py                 # FastAPI routes, workflow transitions, review exports
│   ├── config.py               # Environment-driven configuration
│   ├── database.py             # SQLite schema, connection and audit helpers
│   ├── schemas.py              # Pydantic contracts and validation
│   ├── services/
│   │   ├── interpreter.py      # Rules + optional OpenAI-compatible extraction
│   │   ├── design.py           # Supported starter component schedule
│   │   ├── nesting.py          # Single-sheet rectangular shelf heuristics
│   │   ├── dxf_export.py       # Minimal review-only DXF rectangles; not CNC output
│   │   └── planner.py          # Inventory matching and candidate plan generation
│   └── ui/streamlit_app.py     # Human-in-the-loop UI
├── data/                       # Synthetic JSON examples; DB file is ignored
├── tests/                      # Automated tests
├── docs/                       # Architecture, acceptance, roadmap, validation report
├── scripts/run_checks.sh
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── pyproject.toml
├── Makefile
└── README.md
```

## Operating assumptions and control points

1. The prompt parser creates a **draft**, not an approved engineering specification. The operator confirms the fields before creating the order.
2. Component dimensions are rectangular in V1. A component must fit inside an available sheet after edge trim and the prototype's conservative kerf occupancy.
3. Only available, traceability-verified, released-condition stock of the matching grade and thickness is considered. Remnants are restricted to the same project code unless a future version implements and audits an explicit transfer-approval process.
4. A new plan is a recommendation. Selecting **Approve candidate for review / reserve inventory** atomically rechecks current availability and reserves the selected inventory records. It does not approve engineering design or release manufacturing instructions.
5. Completion requires an explicit engineering-signoff flag, and procurement confirmation when the plan needs new plates. This is a prototype workflow assertion, not a digital signature or safety certification.
6. Any remnant added after completion must be measured and physically verified by an operator before it can be treated as eligible inventory. The record starts in `inspection_required` unless verification is confirmed.
7. The area-yield denominator is gross sheet area used. Yield is not an audited scrap rate. Material value is not the same as avoided purchases; avoided purchases must be verified separately.
8. A newly generated plan is based on an inventory snapshot; an approval attempt fails closed if the selected inventory has changed. Review-package ZIPs include the component schedule and preview artifacts, with explicit non-CNC disclaimers.

## Local setup on Ubuntu / VS Code

### 0. Prerequisites

- Python 3.10 or newer (Python 3.12 recommended for the tested deployment image).
- `python3-venv`, Git, and VS Code if desired.
- Internet access only for the initial Python dependency installation, unless packages are already cached.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
```

### 1. Extract and open the project

If you downloaded a ZIP, extract it first. Then enter the project root (the folder containing this `README.md`):

```bash
cd ~/Projects/steelmind-ai-v1
code .
```

Do not run the commands from the ZIP preview folder or the Trash.

### 2. Create the virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Every new terminal session needs the environment activation command again:

```bash
cd ~/Projects/steelmind-ai-v1
source .venv/bin/activate
```

### 3. Run tests before launching

```bash
python -m pytest -q
# or
./scripts/run_checks.sh
```

### 4. Start the API (terminal 1)

Demo seeding is disabled by default. Enable it only for a local synthetic-data walkthrough, then run the API from the repository root while `.venv` is active:

```bash
export STEELMIND_ENABLE_DEMO_SEED=true
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Verify it:

```bash
curl http://127.0.0.1:8000/health
```

Open API documentation at <http://127.0.0.1:8000/docs>.

### 5. Start the UI (terminal 2)

Open a second VS Code terminal, then:

```bash
cd ~/Projects/steelmind-ai-v1
source .venv/bin/activate
streamlit run app/ui/streamlit_app.py --server.address 127.0.0.1 --server.port 8501
```

Open <http://127.0.0.1:8501>.

### 6. First-run walkthrough

1. Start the API with `STEELMIND_ENABLE_DEMO_SEED=true` set. In **Material inventory**, select **Load synthetic demo inventory**. The fixture inserts once and uses invented values only.
2. In **New order**, try the sample prompt: `Build 4 workbenches, each 1200 x 600 x 850 mm, S275JR mild steel, 3 mm plate for the tabletop and mounting plates. Project DEMO-PROJECT.`
3. Click **Interpret prompt**. Confirm the values and missing questions; this parser is deterministic unless the optional LLM is explicitly enabled.
4. Create the draft order. Review the component schedule and read the exclusions.
5. Click **Generate four candidate plans**. Inspect source policy, strategy, stock used, unplaced parts, yield, and the cost categories.
6. Compare the four options. The baseline is a software heuristic, not the client's actual manual plan or Strumis result.
7. Select a feasible plan and click **Approve candidate for review / reserve inventory**. This reserves available inventory; it does not approve the engineering design or release CNC instructions.
8. If the candidate needs new plates, receive them through the inventory tab with the exact grade, thickness, dimensions, traceability, released condition, and project allocation. Then use **Reconcile received procurement** and supply one lot ID per planned sheet. The API validates and reserves the received lots before the order can proceed.
9. Completion controls appear only after the required procurement is reconciled and the candidate is reserved for engineering sign-off. Use them only to demonstrate the state machine; real operations require the relevant engineer/procurement/operations process.
10. Add actual remnant dimensions only when measured. Unverified remnants remain ineligible for future plans.

### 7. Add a real inventory record (controlled test only)

A lot can be added in the UI or with the API. For example, this creates an available 3 mm S275JR new-stock plate only if you attest that traceability and condition are verified:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/inventory \
  -H 'Content-Type: application/json' \
  -d '{"id":"LOCAL-PLATE-001","material_grade":"S275JR","form":"plate","thickness_mm":3,"width_mm":1500,"length_mm":3000,"source_kind":"new_stock","quantity":2,"unit_value":22000,"traceability_verified":true,"material_condition":"verified"}'
```

Do not use synthetic test values as if they were actual factory records.

## Docker Compose deployment (local pilot)

Docker Compose keeps the API and UI in separate containers and persists the SQLite database in a named volume. Both published ports bind to `127.0.0.1` only.

```bash
cd ~/Projects/steelmind-ai-v1
STEELMIND_ENABLE_DEMO_SEED=true docker compose up --build
```

Omit the environment assignment for a local run without the synthetic demo-seeding endpoint enabled.

Open <http://127.0.0.1:8501>; API docs are at <http://127.0.0.1:8000/docs>.

Stop without deleting persistent data:

```bash
docker compose down
```

Stop and **delete** persistent application data only if you intentionally want a clean demo reset:

```bash
docker compose down -v
```

## Optional LLM order extraction

The default is `STEELMIND_LLM_ENABLED=false`; no paid LLM access is needed to run V1. To enable a compatible `/chat/completions` endpoint, configure environment variables **before starting the API**:

```bash
export STEELMIND_LLM_ENABLED=true
export STEELMIND_LLM_BASE_URL='https://api.openai.com/v1'
export STEELMIND_LLM_API_KEY='your-secret-key'
export STEELMIND_LLM_MODEL='your-available-model'
```

Keep keys in a private local `.env` or secret manager; never commit them. Do not send confidential engineering or client data to an external LLM without approval. If the configured provider fails or returns invalid JSON, the service falls back to deterministic rules. An LLM extraction remains untrusted input and must be reviewed.

## API route summary

| Route | Purpose |
|---|---|
| `GET /health` | Health probe |
| `GET /api/v1/info` | Capability and deployment boundary |
| `POST /api/v1/demo/seed` | Load synthetic inventory once when enabled |
| `POST /api/v1/orders/interpret` | Extract a draft from a natural-language prompt |
| `POST /api/v1/orders` | Create draft order and component schedule |
| `GET /api/v1/orders` / `GET /api/v1/orders/{id}` | List or inspect orders |
| `POST /api/v1/orders/{id}/plans` | Generate four candidates |
| `GET /api/v1/orders/{id}/plans` | List candidate plans |
| `GET /api/v1/plans/{id}` | Inspect one candidate |
| `GET /api/v1/plans/{id}/sheets/{sheet_id}.svg` | Get illustrative SVG placement |
| `GET /api/v1/plans/{id}/sheets/{sheet_id}.dxf` | Download review-only 2D DXF outlines (not CNC-ready) |
| `GET /api/v1/plans/{id}/review-package.zip` | Download review-only JSON, component schedule CSV, SVG layouts, and disclaimers |
| `POST /api/v1/plans/{id}/approve` | Recheck availability and reserve selected inventory for review |
| `POST /api/v1/plans/{id}/receive-procurement` | Match actual received sheet lots to planned purchases, then reserve them |
| `POST /api/v1/orders/{id}/complete` | Record engineer/procurement-gated simulated completion and measured remnants |
| `GET /api/v1/inventory` / `POST /api/v1/inventory` | Read or add inventory records |
| `GET /api/v1/orders/{id}/audit` | Inspect recorded actions |

See `docs/VALIDATION_REPORT.md` for checks executed while preparing this package and checks that still need to be run on the target machine.

## Industry hardening required before a real deployment

This version is a deployable local/pilot MVP, not an internet-exposed enterprise system. Before any real production use, add and test:

- Authentication, role-based permissions, SSO, TLS, CSRF/session protections where applicable, secret management, dependency/security scanning, and security review.
- PostgreSQL or the client's approved database, backup/restore tests, migration tooling, retention policy, monitoring, alerting, and operational support.
- Confirmed unit conventions, material-grade catalog, traceability and allocation policies, audit review, transaction/concurrency tests, and integration contracts with the actual ERP/PLM/nesting software.
- CAD kernel-based geometry validation, exact part outlines, bend allowances where applicable, machine constraints, cutting sequence/toolpath validation, operator sign-off, and CNC-vendor validation. SVG coordinates must never be treated as machine instructions.
- A measured, blinded or matched offline benchmark and a controlled trial to evaluate the system against the real manual and Strumis process.
- Qualified engineering validation for structural loads, joints, stability, tolerances, welds, and product safety.

## License / usage

Internal prototype for evaluation. Synthetic examples only. Add an explicit project license before redistributing the code publicly.
