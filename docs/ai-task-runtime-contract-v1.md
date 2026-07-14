# AI Task Runtime Contract v1

Status: active; aligned with the P1 connector reset.
Updated: 2026-07-14.

## Decision

Cloud consumes the active `ai_task_contract.v1` projection inside the
`request` of a `wordpress_operation.v1` operation. The WordPress operation is
carried by the neutral Cloud connector envelope:

- outer ability: `npcink-cloud/connector-runtime`;
- outer contract: `cloud_connector_runtime.v1`;
- channel: `editor`;
- required connector fields: `site_url`, `platform_kind=wordpress`,
  `connector_id=npcink-cloud-addon`, `connector_version`, and
  `suggestion_only=true`;
- operation contract: `wordpress_operation.v1` with a task and a bounded
  scene request.

There is one active connector envelope. The superseded WordPress-shaped
envelope, validator, aliases, and legacy compatibility path are not part of
the current contract.

## Projection Shape

The `task_contract` remains an optional field inside the WordPress operation's
scene request. When present, it projects only:

- the registered local Ability name and task identifier;
- one allowlisted task family;
- allowlisted context requirements and output constraints;
- the Ability-owned output JSON Schema;
- the mandatory `suggestion_only` write posture.

The projected task must match the enclosing WordPress operation task. Cloud
validates the bounded vocabulary and JSON Schema size, then uses those runtime
facts for hosted provider preparation and result normalization. A valid task
projection can describe a registered task without adding a Cloud-side Ability
registry.

The current fixed WordPress operation allowlist may omit `task_contract`.
That is a current `wordpress_operation.v1` mode, not an alias or fallback to a
superseded connector envelope.

## Ownership Boundary

WordPress owns Ability discovery, permission callbacks, input/output schemas,
instructions, user interaction, review, approval, audit, and final writes.
Cloud owns hosted execution, bounded context retrieval detail, provider
routing, usage and entitlement evidence, observability, and result
normalization.

This contract must not become a second Ability, prompt, workflow, or channel
registry. Public operation input rejects generic messages, tools, streams,
credentials, signed headers, connector control fields, and direct WordPress
write controls.

Cloud returns `cloud_connector_result.v1` suggestion evidence. It never treats
runtime success as approval or applies the result to WordPress.

## Change And Rollback Rule

Changing or removing `ai_task_contract.v1` requires one coordinated update to
the local producer, `wordpress_operation.v1` validation, Cloud runtime tests,
and the consuming addon. Rollback restores that coordinated version; it must
not restore the superseded connector envelope or introduce dual reads.
