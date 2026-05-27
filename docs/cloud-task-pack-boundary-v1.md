# Cloud Task Pack Boundary v1

Status: retired.

Cloud no longer exposes public task-pack APIs or task-pack product surfaces.
Removed examples include WooCommerce Growth, GEO Visibility, and Managed Model
Routing task-pack endpoints.

Current Cloud scope is limited to hosted runtime, catalog, routing
recommendation, usage, entitlement, billing snapshots, audit, and operator
diagnostics. WordPress/plugin side remains the control plane and final write
truth.

Do not reintroduce `/v1/task-packs/*` without first replacing this retired
contract and passing the Cloud boundary review.
