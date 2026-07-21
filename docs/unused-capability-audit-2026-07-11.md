# Unused Capability Audit - 2026-07-11

Status: accepted

## Scope

This audit separates removable runtime baggage from active Cloud capabilities.
It does not move WordPress approval, registry, routing, workflow, or write truth
into Cloud.

## Removed

### Environment-backed feature flags

The feature flag facade was removed because no runtime or commercial decision
called it. It only exposed static labels through the observability summary, and
the `portal.billing.readonly.enabled` label contradicted the active Portal
purchase flow.

Removed surfaces:

- `app/core/feature_flags.py`;
- `Settings.feature_flags_json`;
- `NPCINK_CLOUD_FEATURE_FLAGS_JSON`;
- the observability `feature_flags` projection and its dedicated tests.

## Kept After Consumer Audit

### Audio generation kept; audio assets superseded

The original audit kept both surfaces. P3-B4B2 supersedes its audio-asset
conclusion: `npcink-workflow-toolbox` and `npcink-cloud-addon` still use the
bounded `audio_generation_request.v1` hosted-runtime path, but Cloud no longer
provides permanent audio-asset promote/playback endpoints. Generated audio is a
short-lived `MediaArtifact` delivered through the unified signed pull; local
CMS review, import, playback ownership, and canonical audit remain local.

### Site Knowledge comments

Keep disabled by default. The Toolbox sends bounded approved comments and the
Cloud Addon has a comment change bridge. Cloud only admits public approved
comment fields, rejects private author and request metadata, and only includes
comments in search when callers request them explicitly. Production remains
opt-in through `NPCINK_CLOUD_SITE_KNOWLEDGE_COMMENTS_ENABLED=true`.

### Agent Feedback

Keep. The metadata-only feedback contract has active event and summary APIs,
an internal read-only detail page, and regression coverage. It remains quality
evidence and does not become approval or WordPress write truth.

### Model reference intelligence

Keep. Provider administration actively consumes the reference read model and
sync endpoint. Reference capability and price metadata stays explicitly
separate from billing, routing, and hosted catalog truth.

## Hidden From First-release Navigation

### Operations Advisor

The troubleshooting catalog no longer exposes Operations Advisor as a routine
entry. Its direct page and read-only diagnostic API remain available for
internal investigation and existing tests. This is a navigation reduction,
not an API retirement.

## Evidence That Must Remain

Do not delete the following as compatibility baggage:

- Alembic migration history, including migrations that remove retired tables;
- `docs/legacy-contracts` and current Cloud boundary contracts;
- tests that explicitly reject retired environment aliases, callback paths,
  request-level callback overrides, or old authorization behavior.

These files preserve upgrade, audit, and anti-regression evidence without
keeping the retired behavior executable.
