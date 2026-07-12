# AI task runtime contract v1

## Decision

Cloud consumes the additive `ai_task_contract.v1` projection inside the existing
`wp_ai_connector_runtime.v1` request. It does not register or edit WordPress
Abilities and does not add another endpoint.

The projection provides only:

- the registered local Ability name and task identifier;
- one fixed text task family;
- allowlisted context requirements and output constraints;
- the Ability-owned output JSON Schema;
- the mandatory `suggestion_only` write posture.

Cloud validates the projection, applies family-level runtime instructions and
constraints, selects hosted provider policy, and returns a suggestion. Unknown
task identifiers can therefore use an existing family without a Cloud code
change. Legacy task identifiers remain supported when no projection is sent.

## Ownership boundary

WordPress owns Ability discovery, permission callbacks, input/output schemas,
instructions, user interaction, approval, and writes. Cloud owns hosted model
execution, context retrieval detail, provider routing, budgets, observability,
and result normalization.

This contract must not become a second Ability registry, prompt registry,
workflow registry, WordPress control plane, or arbitrary chat proxy. Messages,
tools, credentials, streams, and direct WordPress writes remain rejected by the
existing connector perimeter.

## Compatibility and rollback

The projection is additive. Omitting `task_contract` preserves the current
allowlisted task behavior. Removing the projection consumer does not require a
database migration, endpoint rollback, or WordPress data cleanup.
