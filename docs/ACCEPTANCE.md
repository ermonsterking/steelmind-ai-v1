# V1 Acceptance Checklist

## Functional
- [x] Health endpoint and interactive API documentation.
- [x] Conservative prompt interpretation with missing-field questions.
- [x] Supported component schedule generation.
- [x] Rectangular packing candidate generation using two heuristics.
- [x] Four candidates separate packing heuristic from remnant-source policy.
- [x] Inventory eligibility checks grade, form, thickness, availability, traceability, condition and project allocation.
- [x] Candidate summaries separate inventory value, remnant book value and new procurement cost.
- [x] Human approval reserves inventory after transactional availability recheck.
- [x] Planned procurement must be reconciled to physically recorded inventory lots before completion.
- [x] Completion gate requires human engineering sign-off and procurement confirmation where applicable.
- [x] Actual remnant records and audit events can be recorded.
- [x] SVG and review-only 2D DXF layout plus review-only ZIP export.
- [x] Synthetic demo inventory is opt-in via environment configuration.

## Automated verification
Run `python -m pytest -q`. The current 11-test suite covers parsing, missing-field behaviour, placements, oversized components, order creation, plan generation, review export, workflow state, procurement receipt, demo-seed configuration, and cross-project remnant exclusion.

## Required before real production deployment
- [ ] Authentication, RBAC, SSO and secure secret management.
- [ ] PostgreSQL, migration tooling, backups and tested restore.
- [ ] Real Strumis/PLM integration and a signed data contract.
- [ ] Approved material-grade/condition catalog and validated traceability.
- [ ] CAD-kernel geometry, actual cutting constraints, machine validation, and validated CNC/postprocessor path if eventually needed.
- [ ] Engineer-approved product templates and structural design checks.
- [ ] Baseline, controlled trial, uncertainty reporting, and verified cash-benefit methodology.
- [ ] Security, privacy, performance, monitoring and operational acceptance review.
