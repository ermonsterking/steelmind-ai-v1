# Architecture and Decision Notes

## Request lifecycle

1. An operator enters a customer prompt.
2. The interpreter extracts fields to a draft. It uses deterministic rules by default; a configured OpenAI-compatible text model can be enabled, but its JSON remains untrusted draft data.
3. The operator confirms the supported template, dimensions, quantity, grade, thickness, kerf, trim, stock assumptions and project code.
4. The design service generates a component schedule for the selected starter template or user-provided rectangular components.
5. The planner generates four candidate plans to keep heuristic choice and source policy separately visible.
6. Each candidate is evaluated against the available inventory snapshot. Only same-project, traceable, available, released-condition remnants are eligible.
7. A human selects a candidate. Approval runs inside a write transaction, rechecks availability, and reserves source lots.
8. Completion requires an engineering-signoff assertion and procurement confirmation if new sheets are needed. Actual remnants are added as operator-reported inventory with traceability/condition fields.
9. Order and plan actions are written to an audit-event table.

## Main modules

- `app/services/interpreter.py`: draft field extraction; optional OpenAI-compatible adapter, deterministic fallback.
- `app/services/design.py`: bounded template-to-component decomposition.
- `app/services/nesting.py`: single-sheet rectangular shelf packing.
- `app/services/dxf_export.py`: minimal 2D rectangular DXF export for review, not CNC output.
- `app/services/planner.py`: eligibility rules, source policies, candidate comparison and cost categories.
- `app/main.py`: API endpoints, workflow transitions, approval, audit, and review-package exports (SVG/DXF/ZIP).
- `app/ui/streamlit_app.py`: local human-review interface.

## Why not a free-form agent?

The LLM does not receive authority to choose unvalidated dimensions, create arbitrary CAD, make structural calculations, mutate inventory autonomously, or release manufacturing outputs. Exact operations are deterministic services with explicit input/output contracts. This reduces the risk that plausible language output is treated as valid engineering data.

## Data ownership

SQLite stores orders, specifications, design drafts, inventory, candidate plans and audit events. The database is appropriate for a single-instance local pilot. A multi-user deployment should move to a managed relational database and adopt migrations, backups, recovery objectives, access controls and concurrency testing.

## Cost semantics

- `estimated_existing_stock_value`: assigned value of existing purchased stock consumed by a plan.
- `estimated_remnant_book_value`: assigned book value for remnants used.
- `estimated_new_procurement_cost`: additional sheets the plan proposes to buy if stock inventory is insufficient.

These values must not be added or interpreted as realized savings without the client's costing policy. A remnant is not “free” merely because it avoids a new purchase; handling cost, book value, allocation and physical reuse matter.

## Non-goals

V1 does not produce solid CAD assemblies, arbitrary 2D profiles, bend flat patterns, validated weld/joint geometry, load calculations, CNC postprocessor files or shop-release documentation. SVG and the minimal rectangular DXF are review artifacts only. These require a CAD kernel, engineering constraints, actual machine definitions, geometry validation and separate release approval.
