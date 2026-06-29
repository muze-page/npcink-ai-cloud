# Model Reference Metadata v1

Status: active internal operator metadata.

Date: 2026-06-29

## Context

Cloud provider operators need model capability and reference price context while
configuring provider channels. External catalogs such as `models.dev` are useful
because they expose model modality, context limits, output limits, capability
flags, release metadata, and reference token prices.

The same data is not reliable enough to become Cloud routing truth or billing
truth. External catalogs can lag provider changes, omit provider-specific price
variants, or carry incomplete capability details.

## Decision

Use `model_reference_*` storage as a Cloud-owned reference metadata layer.

The first source is `models.dev`. The internal admin sync endpoint imports its
provider/model metadata into:

- `model_reference_sources`
- `model_reference_models`
- `model_reference_overrides`

The data is exposed to internal Admin through:

- `GET /internal/service/admin/model-references`
- `POST /internal/service/admin/model-references/sync`

The Admin provider-channel form may display reference capability and price
metadata beside the provider-visible model catalog. Operators may use the data
to decide which model IDs to expose on a provider channel.

## Boundaries

This layer is allowed to be:

- hosted metadata
- operator reference detail
- provider-channel configuration aid
- price estimation input
- model capability inspection input

This layer is not:

- billing truth
- usage meter truth
- router truth
- provider credential truth
- ability registry truth
- workflow registry truth
- prompt or preset truth
- WordPress write truth

Real usage cost remains owned by provider-call telemetry and usage ledger
records. Runtime model selection remains owned by the existing hosted runtime
and local WordPress control-plane contracts.

## Source Handling

External source payloads are treated as untrusted input:

- the sync service validates payload shape before using it;
- all values are normalized into bounded fields;
- raw source JSON is retained only as reference metadata;
- sync failures are recorded on `model_reference_sources`;
- manual overrides are stored separately from source records.

Reference prices use:

```text
usd_per_1m_tokens
```

This price unit is explicit display metadata only.

## Current Non-Goals

- no model batch testing;
- no automatic cheapest-model routing;
- no automatic plan or billing mutation;
- no customer-facing price guarantee;
- no replacement of platform `catalog_models`;
- no replacement of provider connection model visibility.

## Verification

Use focused checks:

```bash
.venv/bin/python -m pytest tests/api/test_service_routes.py::test_admin_model_references_syncs_models_dev_payload_as_reference_only
node frontend/tests/unit/admin-ai-resources-contract.mjs
pnpm run frontend:type-check
```
