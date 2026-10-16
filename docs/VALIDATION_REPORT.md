# V1 Validation Report

## Checks performed

- `python -m compileall -q app tests` — passed.
- `python -m pytest -q` — 11 tests passed.
- FastAPI `TestClient` smoke check for `GET /health` — HTTP 200, `status=ok`.
- FastAPI OpenAPI document endpoint — HTTP 200.
- Sample JSON files are synthetic and shipped in `data/`.

## Scope of verification

Automated tests cover deterministic prompt extraction, supported order creation, rectangular packing behavior, plan generation, candidate approval/reservation, procurement reconciliation, completion gates, audit events, review exports, demo-seed opt-in, and cross-project remnant exclusion.

The tests do not establish production CAD validity, optimal nesting, structural safety, CNC readiness, actual material savings, or readiness for internet exposure.

## Environment limitations during package preparation

The packaging environment could not reach the Python package index to install missing third-party packages, so the Streamlit interface could not be launched interactively in this environment. The Streamlit source was syntax-compiled, and the backend/API was tested. Docker was not available in this environment, so Docker Compose build/start was not executed here. The README contains the commands to perform these checks on the target Ubuntu machine after dependencies are installed.

## Required before a real factory pilot

Run the setup instructions on the target machine; start API and UI; perform the complete demo walkthrough; validate product templates and measurements with a qualified engineer; and obtain security, production, and IT approval before connecting real client data or machinery.
