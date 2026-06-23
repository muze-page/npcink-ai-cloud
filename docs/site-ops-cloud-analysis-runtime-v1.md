# Site Ops Cloud Analysis Runtime v1

Status: active runtime/detail contract.

`site_ops_cloud_analysis_request.v1` is produced by Toolbox from bounded local
WordPress evidence. Cloud consumes that request through the hosted runtime and
returns `site_ops_cloud_analysis_result.v1`.

## Runtime Role

Cloud role is `runtime_detail`. The Cloud result may rank local findings,
produce an executive summary, explain aggregate drivers, build dimension-level
summaries, surface semantic ranking and trend explanations, and prepare
operator next actions. It must not become a second WordPress control plane.

The runtime result keeps:

- `write_posture=suggestion_only`;
- `direct_wordpress_write=false`;
- `core_proposal_created=false`;
- `cloud_scheduler_truth=false`;
- `operator_review_required=true`.

## Inputs

Allowed input is the Toolbox-prepared request:

- aggregate post/page, media, taxonomy, and approved-comment signal summaries;
- local `site_ops_insight_pack.v1` finding summaries;
- blocked items and requested analysis tasks;
- operator context flags such as Site Context readiness and Cloud readiness.

The request must not include raw private data such as full comment text, comment
author contact details, IP addresses, user agents, provider secrets, private
content, request logs, local scheduler instructions, or WordPress write actions.

## Outputs

The result can include:

- executive summary;
- priority queue;
- dimension summaries;
- semantic ranked findings;
- trend notes;
- trend explanations;
- confidence and limitations;
- blocked items;
- Core handoff candidates with `proposal_ready=false`;
- operator next actions.
- analysis closure state for whether the current loop is blocked, ready for
  operator prioritization, or has no priority findings.

Core handoff candidates are planning hints only. Toolbox, Adapter, Core, and
Abilities still own review, proposal creation, approval, preflight, audit, and
final WordPress writes.

Cloud-only detail is limited to explanation and prioritization:

- cross-run or heavier trend explanation;
- semantic ranking;
- higher-cost runtime/detail analysis.

The result must not claim that Cloud created proposals, scheduled work, or
changed WordPress data.

## Failure And Degraded Detail

Contract validation failures fail closed before a runtime run is created. Cloud
must not meter or persist a run when the request contains private comment
fields, provider secrets, local scheduler instructions, or WordPress write
actions.

Runtime analyzer failures are recorded as Cloud runtime failed detail with
`status=failed`, `error_code=site_ops_analysis.execution_failed`, provider id
`site_ops_analysis`, model id `deterministic-ops-analyzer-v1`, and
`fallback_used=false`. Failed detail still keeps Cloud in `runtime_detail`; it
does not create Core proposals, scheduler truth, local run tables in Toolbox, or
WordPress writes.

Low-signal aggregate requests may succeed with empty priority and trend arrays.
The result must stay reviewable: confidence should fall to `low`, blockers such
as incomplete Site Context should appear in `blocked_items`, and operator next
actions should point to clearing those blockers rather than inventing findings.
