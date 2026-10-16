# Product Roadmap and Release Gates

## V1 — Controlled engineering MVP (this repository)

**Purpose:** demonstrate the whole data/decision loop for a tightly bounded rectangular plate use case. Run on localhost or a trusted evaluation environment only.

Included: draft prompt extraction, supported component schedule, rectangular shelf heuristics, inventory and remnant eligibility, four candidate comparisons, material value/procurement estimate, human approval/reservation, measured remnant entry, audit trail, SVG previews, review-only export, tests, local Docker Compose.

**V1 release gate:** unit/API tests pass; no cross-project remnant allocation; inventory availability is rechecked transactionally at approval; unverified/held stock is excluded; plan and completion are explicitly review-only.

## V1.1 — Controlled internal pilot hardening

- Replace SQLite with the company's approved relational database where concurrent users or uptime requirements demand it; introduce versioned schema migrations and backup/restore tests.
- Implement authentication, role-based permissions, SSO, TLS, secret storage, audit retention, observability, alerts, and an operational support plan.
- Add inventory import validation and a signed schema/data contract with the ERP/PLM owners.
- Add source-file references, row-level reconciliation, duplicate detection, and an import exception queue.
- Add approval roles for Engineering, Procurement, Cost Control and material transfer; don't implement transfer until governance is agreed.
- Agree on business definitions and an offline benchmark using representative historical jobs.

**V1.1 release gate:** security review, recovery test, traceability reconciliation, and operational sign-off completed by the client's named owners.

## V1.2 — CAD template integration

- Select one low-risk, repeatable product family with complete approved design rules.
- Use a parametric CAD engine and documented templates to create model geometry and drawings from validated parameters.
- Verify units, geometry, dimensions, assembly references, tolerances, materials and revision metadata.
- Add a CAD-kernel geometry validation step; don't infer undocumented joints, welds, thickness, bends or load ratings.
- Keep unsupported prompts in a clarification queue. Engineering signs off before using any generated design downstream.

**V1.2 release gate:** independent drawing/geometry review on a validation set, change-propagation tests, revision traceability and signed engineering acceptance.

## V2 — Industrial nesting and decision support

- Integrate the actual nesting/PLM/ERP systems through supported and permissioned interfaces.
- Evaluate production-grade 2D/1D nesting solvers appropriate to actual plate and profile geometries and CNC processes.
- Add machine constraints, cutting sequence/toolpath constraints, kerf/trim definitions, clamps, lead-ins, common-line cutting, heat/distortion rules where relevant, and machine-specific validation.
- Benchmark against the real manual baseline and Strumis output with matched jobs; run advisory/shadow trials before controlled production use.
- Add outcome capture: actual parts, scrap, measured residuals, handling effort, acceptance/rejection reasons and verified purchase avoidance.
- Use human corrections as governed data for analytics/ML only after permissions, label quality and a defined prediction target exist.

**V2 release gate:** machine-vendor validation where required, production/quality sign-off, no critical geometric violations in the approved test set, controlled rollout, monitoring and an agreed rollback procedure.

## Principle

Do not promote a software milestone to production merely because a demo looks good. Each phase must satisfy its data, engineering, safety, security and commercial acceptance gates independently.
