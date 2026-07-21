# Python 3.14.6 Controlled Production Validation Risk Decision — 2026-07-21

> Status: Accepted for controlled production validation only
>
> Owner: Muze
>
> Decision date: 2026-07-21
>
> Exception expiry: 2026-08-05
>
> GA is not authorized.

## Decision

The exact Linux/AMD64 release bundle may be used for operator-controlled
production validation while its API image still contains the three temporary
Python 3.14.6 allowlist entries below, but only when every gate in this document
is satisfied:

- `CVE-2026-11940`
- `CVE-2026-11972`
- `CVE-2026-15308`

This decision does not authorize GA, customer rollout, marketing claims,
general production reuse, or a conclusion that the image is vulnerability
free. It is a short-lived exception for one exact artifact and one controlled
validation scope.

## Current evidence and uncertainty

The authoritative vulnerability records are:

- [NVD — CVE-2026-11940](https://nvd.nist.gov/vuln/detail/CVE-2026-11940)
- [NVD — CVE-2026-11972](https://nvd.nist.gov/vuln/detail/CVE-2026-11972)
- [NVD — CVE-2026-15308](https://nvd.nist.gov/vuln/detail/CVE-2026-15308)

On 2026-07-21 those NVD records displayed CISA Vulnrichment SSVC
`exploitation: none` for all three entries. That value is current threat
intelligence, not proof that exploitation is impossible, and it must be
rechecked immediately before the operator signs an acceptance.

The earlier engineering reachability review is recorded in
[P5-B7 Python API Image CVE Exception](p5-b7-python-api-image-cve-exception-2026-07-19.md).
That review found no direct `tarfile` call path for
`CVE-2026-11940` or `CVE-2026-11972`, and no direct
`html.parser.HTMLParser` call path for `CVE-2026-15308`. Bundled archive tools
also avoid `extractall` and the affected tarfile streaming read mode (`r|`);
the repository's `w|` streaming write does not support the vulnerable read
path. These findings reduce known direct reachability; they do not prove that
indirect dependency, provider input, or future-code reachability is absent.

[PEP 745](https://peps.python.org/pep-0745/) schedules Python 3.14.7 for
2026-08-04. A schedule is not evidence that a release exists or contains every
relevant fix. The exception must be removed as soon as the first supported
stable 3.14 image containing the relevant fixes can be pinned, rebuilt, scanned,
and replayed; do not wait for the expiry date.

## Required artifact gate

Before any production-host image, database, Edge, or release mutation:

1. Build the exact bundle from the final merged commit for `linux/amd64`.
2. Verify the archive and checksum.
3. Run a fresh release image scan. Its index must report `status=passed`, the
   API image's `blocking_finding_count=3`, and
   `unallowlisted_blocking_finding_count=0`. The API receipt must separately
   report `status=passed`, the exact three allowlisted High findings, and zero
   unallowlisted blocking findings.
4. Run the repository's single-command same-bundle double replay successfully.
5. Recheck the three NVD records and this decision's expiry and stop conditions.
6. Manually create the bundle-external operator acceptance below and compare it
   to the bundle manifest, outer checksum, scan index, API scan receipt, and
   embedded allowlist.

The acceptance contract is
`npcink.controlled_production_cve_risk_acceptance.v1`. It records a human risk
decision; it is not a scanner receipt and must use
`status=accepted_by_operator`, never `passed`.

```json
{
  "contract": "npcink.controlled_production_cve_risk_acceptance.v1",
  "status": "accepted_by_operator",
  "scope": "controlled_production_validation_only",
  "decision_document": "docs/python-3-14-6-controlled-production-validation-risk-decision-2026-07-21.md",
  "source_revision": "<40-lowercase-hex>",
  "source_tree": "<40-lowercase-hex>",
  "bundle_sha256": "<64-lowercase-hex>",
  "scan_index_sha256": "<64-lowercase-hex>",
  "api_scan_receipt_sha256": "<64-lowercase-hex>",
  "allowlist_sha256": "<64-lowercase-hex>",
  "scan_index_status": "passed",
  "api_scan_status": "passed",
  "image_platform": "linux/amd64",
  "api_image_reference": "npcink-ai-cloud-api:prod",
  "blocking_finding_count": 3,
  "allowlisted_blocking_finding_count": 3,
  "unallowlisted_blocking_finding_count": 0,
  "allowlisted_findings": [
    {
      "vulnerability_id": "CVE-2026-11940",
      "package": "python",
      "package_version": "3.14.6",
      "severity": "high",
      "fix_state": "unknown"
    },
    {
      "vulnerability_id": "CVE-2026-11972",
      "package": "python",
      "package_version": "3.14.6",
      "severity": "high",
      "fix_state": "unknown"
    },
    {
      "vulnerability_id": "CVE-2026-15308",
      "package": "python",
      "package_version": "3.14.6",
      "severity": "high",
      "fix_state": "fixed"
    }
  ],
  "cisa_ssvc_exploitation": {
    "CVE-2026-11940": "none",
    "CVE-2026-11972": "none",
    "CVE-2026-15308": "none"
  },
  "cisa_ssvc_checked_at_utc": "<RFC3339-UTC>",
  "exception_expires_on": "2026-08-05",
  "ga_authorized": false,
  "authorized_by": "Muze",
  "authorized_at_utc": "<RFC3339-UTC>"
}
```

The final scan must match every fixed value in this template. If a finding,
fix state, package version, count, platform, or status differs, stop and review
the new evidence rather than editing the acceptance to make it fit.

The acceptance stays outside Git, the deploy bundle, and every release tree. It
must be an owner-only mode-`0600` file in the trusted operator evidence store.
After creation, record its SHA-256 separately.
The receipt cannot contain a self-digest because that would create a circular
value. The release operator
manually compares all bound values before continuing.
The deployment, image-scan, and P1-E06 tooling do not consume this acceptance.

This contract is distinct from `p1_e06_off_host_backup_receipt.v1`. The latter
is machine-consumed proof of an independently copied database backup; neither
receipt substitutes for the other.

## Immediate stop conditions

Controlled validation stops if any of the following is true:

- the current date is after 2026-08-05;
- NVD/CISA intelligence no longer reports `exploitation: none` for all three;
- a vulnerability, package version, severity, fix state, finding count, scan
  status, platform, commit, tree, bundle digest, scan digest, or allowlist digest
  differs from the signed acceptance;
- direct or indirect reachability changes or cannot be bounded;
- the bundle verifier, fresh scan, or either same-bundle replay fails;
- the acceptance is absent, malformed, not mode `0600`, or not independently
  hash-recorded;
- a supported fixed Python image is available.

After any stop condition, do not stage or mutate production. Reassess the
decision, or upgrade, repin, rebuild, rescan, and replay before continuing.

## Boundary consequence

This decision changes no Cloud product ownership. Cloud remains the hosted
runtime and evidence layer; WordPress remains the local control, approval, and
write owner. No new registry, workflow truth, scheduler, public API, deployment
input, or production-host code path is introduced.
