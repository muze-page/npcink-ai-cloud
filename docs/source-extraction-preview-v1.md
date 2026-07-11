# Source Extraction Preview v1

Status: bounded Cloud runtime contract.

## Purpose

`source_extraction_preview.v1` proves what the Cloud-managed Reader extracted
from one explicit public article URL before Toolbox asks Site Knowledge or a
hosted model to prepare an adaptation review.

## Ownership

- Cloud owns public-URL validation, fixed Reader execution, bounded extraction
  evidence, usage evidence, and runtime diagnostics.
- Toolbox owns the WordPress operator steps and review UI.
- WordPress authors own any later article text and native save action.
- Core and Toolkit continue to govern media import and other non-editor writes.

This contract does not create a new route, ability registry, workflow runtime,
queue, provider selector, WordPress write path, or publishing surface.

## Input

The existing `npcink-cloud/web-search` / `web_search.v1` runtime receives:

```json
{
  "contract_version": "web_search.v1",
  "intent": "source_extraction_preview",
  "query": "https://example.com/article",
  "source_url": "https://example.com/article",
  "max_results": 1,
  "write_posture": "suggestion_only"
}
```

Only public HTTP/HTTPS URLs without credentials are accepted. Localhost,
`.local`, `.test`, private, loopback, link-local, multicast, unspecified, and
reserved IP literals fail closed.

## Output

The result includes:

- requested and Reader-resolved URL;
- exact host/article-path match status;
- title, language, and publication time when the Reader supplies them;
- content hash, word count, character count, bounded start/end preview, and a
  bounded Reader excerpt for the next review step;
- `coverage.level=partial`, `reader_bounded=true`, and
  `complete_capture_claimed=false` unless a future provider-independent
  completeness contract is proven;
- `suggestion_only` and `direct_wordpress_write=false`.
- `content_trust=untrusted_external_source` and
  `prompt_injection_review_required=true`, so downstream hosted models treat
  Reader text as evidence rather than instructions.

Missing, mismatched, or non-public Reader-resolved URLs return a blocked
artifact without readable content or source metadata.

## Non-goals

- no HTML fetch from WordPress;
- no provider settings in Toolbox;
- no full-article translation or article-body generation;
- no media import, editor insertion, proposal creation, or publish action;
- no claim that a Reader response is a complete legal copy of the source.
