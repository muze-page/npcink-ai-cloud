# P5-B4 Runtime Load/Soak Closeout — 2026-07-19

Status: **P5-B4 engineering acceptance complete** on exact Cloud revision
`dff31baf942542d12860b82f6a65a47dd2129d91`. Global P5 and P5-B5 release
closure remain incomplete.

## Outcome

P5-B4 now has three independent, fresh, deterministic formal baselines for the
external Gunicorn runtime, Redis queue, PostgreSQL persistence, and real runtime
worker path. All three formal baselines passed the same 29 checks on the same
clean revision, environment, dataset, and proof topology. The aggregate record
sets `formal_acceptance=true` and does not claim a production SLO.

The accepted topology uses two proof-only runtime workers. That is a measured
response to the retained single-worker capacity-edge result, not a change to
the production deployment contract. Production defaults remain unchanged and
single-worker. Media multiworker and heartbeat safety have not been proved, so
this batch does not authorize production worker scaling.

The current revision also passed the formal high-cardinality query proof and a
serial replay of the bounded media performance and representative-corpus
proofs. These results close P5-B4 engineering evidence only; they are not a
production release, production validation, or global P5 completion claim.

## Boundary And Non-goals

- Cloud remains the hosted runtime, queue/worker, usage, health, and diagnostic
  evidence owner only.
- WordPress/Core remains the permission, review, approval, final audit, and CMS
  write owner. The proof performs no WordPress write and creates no new local
  control-plane truth.
- The formal runtime proof uses a deterministic local provider with a fixed
  delay. It excludes upstream provider latency, quality, availability, and
  credential behavior.
- Measurements are local engineering results from a warm, disposable proof
  environment. They do not define a production SLO or prove production
  capacity, cold-start behavior, regional latency, or external network
  behavior.
- The dual-worker Compose file is isolated proof infrastructure. It does not
  replace or modify `docker-compose.prod.yml` or
  `docker-compose.runtime.yml`.
- No production configuration, database, secret, service, deployment, paid
  provider, or WordPress installation was changed.
- This batch does not close authentication-claim hardening, global sensitive-log
  redaction, deterministic image supply chain, container CVE scanning, restore
  rehearsal, exact release-bundle replay, or the final clean cross-repository
  matrix. Those remain P5-B5 work.

## Exact Evidence Inventory

| Evidence | Result | Integrity |
| --- | --- | --- |
| Formal runtime v5 | passed; `formal_acceptance=true` | `/tmp/p5-b4-runtime-formal-v5-dff31baf.json`; mode `0600`; `84,247` bytes; SHA-256 `3ec494de645d8c12cea5429b14fbd46f7be4dccc2bd54ad9ca5b187893d5475d` |
| Retained formal runtime v4 | failed; `formal_acceptance=false` | `/tmp/p5-b4-runtime-formal-20260719-8b2eb392.json`; mode `0600`; `67,379` bytes; SHA-256 `ef86cec2900adaf91ae9c38db7d34a960e4754274efad41af733045d90e3e542` |
| Formal hot-query proof | passed | `/tmp/p5-b4-hot-query-formal-dff31baf.json`; mode `0600`; `11,824` bytes; SHA-256 `3f325e09c3d15b4f7681561998dee45fd82e15e202b6dd873a376e59192e4766` |
| Media performance full replay | passed | normalized report SHA-256 `a3b714882c38a2244019d73ff5f255a455b4eb4ce26cde6c0e57514481282863` |
| Media representative-corpus replay | passed | normalized report SHA-256 `1e643446c2d514a7d67ab0c7544e3b19c7b83ac3708d148236ab4b116998b563` |

The two media hashes are normalized-report digests, not hashes of the temporary
runtime and hot-query files. All `/tmp` paths are local evidence locations, not
durable release storage. A later source, configuration, dataset, container, or
proof-tool change requires new evidence rather than inheriting these hashes.

## Formal Runtime Proof

### Frozen input

The accepted record uses contract
`p5_b4_external_runtime_load_soak_proof.v5` and dataset
`p5_b4_runtime_8_sites_v5` with:

- exact clean revision
  `dff31baf942542d12860b82f6a65a47dd2129d91` and `git_dirty=false`;
- three independent fresh baselines;
- eight sites, `30` seconds of warm-up, and `600` seconds of measured soak per
  baseline;
- request rate `8/s`, concurrency cap `8`, and a `64`-request queue burst;
- deterministic provider delay `150 ms`;
- two proof workers, worker batch size `8`, and worker poll interval `5 s`;
- an external Gunicorn API plus disposable PostgreSQL and Redis services;
- source, harness, wrapper, Compose, migrations, dataset, image, and environment
  fingerprints captured in the aggregate record.

The aggregate gate verified that the three records had matching contracts,
configuration, revision, environment, and dataset; that their topologies and
diagnostics were valid; that each baseline was independent; and that later
provider-excluded latency did not regress against the locked first record.

### Formal results

| Baseline | Observed / database / succeeded | Provider calls | Checks | Queue-wait p95 | Provider-excluded API p95 / p99 | Transport / HTTP 5xx | Queue/runtime residue |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `5,113 / 5,113 / 5,113` | `5,113` | `29/29` | `4.6318 s` | `89.467 / 117.303 ms` | `0 / 0` | `0` |
| 2 | `5,113 / 5,113 / 5,113` | `5,113` | `29/29` | `5.0296 s` | `89.397 / 117.202 ms` | `0 / 0` | `0` |
| 3 | `5,113 / 5,113 / 5,113` | `5,113` | `29/29` | `4.7298 s` | `86.209 / 97.130 ms` | `0 / 0` | `0` |

All three queue-wait p95 values stayed below the frozen two-poll-interval
threshold of `10 s`. The database, observed-result, succeeded-run, and provider
call sets were exact. No queued, running, dispatching, provider-active, Redis
queue, or artifact residue remained.

The 29 checks cover:

- zero unexpected HTTP 5xx and zero HTTP transport failures;
- accepted/completed rates and provider-excluded p95/p99 latency;
- complete persistent provider timing and exact request/run/provider identity
  sets;
- exact queue requested/accepted/completed counts, complete queue timing,
  queue-wait bound, and zero queue/runtime residue;
- provider usage and meter integrity, proof-fixture rejection discipline, and
  cross-site/result-read isolation;
- artifact return to the initial manifest;
- bounded RSS growth, stable API/worker process cohorts, resource sample
  completeness, and no sustained API FD, worker FD, or PostgreSQL connection
  growth;
- service survival, zero restarts, clean-revision enforcement, achieved request
  rate, scheduler drift, and observed real concurrency.

Each formal baseline used a fresh disposable Compose project. Final cleanup
verified the absence of the proof containers, volumes, and networks before the
aggregate evidence was published with mode `0600`.

## Retained v4 Failure And Capacity Decision

The earlier v4 formal run is retained as failure evidence rather than being
replaced by a more favorable rerun. It executed on clean revision
`8b2eb3923e1a6c1c82aa0513240cff7178883933` with one runtime worker.

Its three queue-wait p95 results were `9.9631 s`, `9.9538 s`, and `10.0267 s`.
Baseline 3 exceeded the frozen `10 s` threshold by `26.7 ms`, so the
`queue_wait` check failed and the aggregate correctly recorded
`formal_acceptance=false`. This is treated as evidence that one worker was on
the capacity edge under the frozen P5-B4 workload. The threshold was not
lowered, and the result was not rerun until timing happened to pass.

The v4 receipts also recorded transport failures of `0`, `1`, and `2` across
the three baselines even though v4 did not enforce a dedicated zero-transport
check. Version 5 therefore did more than add the second proof worker: it made
transport failures an explicit gate, tightened phase/error diagnostics and
cross-field integrity, and aggregated resource evidence across both workers.
The accepted v5 run then produced zero transport failures in all three
baselines. This hardening prevents the topology change from hiding an
observation or sampling defect.

The resulting decision is deliberately narrow: retain single-worker production
defaults, use two workers only in the P5-B4 proof topology, and defer any
production scaling decision until worker ownership, heartbeat, and media
multiworker safety are independently proved.

## Harness Diagnostics And Quick-Mode Posture

Quick mode is only a harness observation tool. It uses one reduced baseline and
is contractually unable to claim formal acceptance. The final v5 quick record
was used to verify the corrected harness before the three-baseline formal run;
it was not used as P5-B4 acceptance evidence.

Two pre-formal failures were investigated rather than suppressed:

1. The first quick attempt stopped during image build, before any load
   measurement. The Dockerfile resolves broad Python dependency ranges live
   instead of consuming the committed `uv.lock`; a transient resolver/index
   response reported no compatible ARM64 `uvloop`, while a later build of the
   same base resolved `uvloop 0.22.1`. No performance record was emitted. This
   is a supply-chain reproducibility defect, not runtime capacity evidence. It
   is explicitly transferred to P5-B5 for locked installation, image identity,
   and container scanning work.
2. A later quick attempt reached load but the Bash 3.2 sampler shutdown check
   misclassified an already-completed, unreaped background job as active.
   Focused reproduction showed that `jobs -p` inside command substitution can
   retain that `Done` entry. The wrapper now probes running/stopped jobs with
   `jobs -pr` and `jobs -ps`, waits for the sampler, and preserves fail-closed
   nonzero-exit handling. Dedicated Done/running/stopped/success/nonzero cases
   passed before the formal proof.

Neither diagnosis relaxed an acceptance threshold or converted failed evidence
into a pass.

## Formal Hot-query Proof

The current revision passed
`p5_b4_hot_query_proof.v1` on PostgreSQL 16 with a deterministic metadata-only
fixture containing `100,000` run records and `20,000` provider-call records.
Each of six canonical queries had `3` warm-ups and `30` measured iterations.

| Canonical query | p95 | Threshold result |
| --- | ---: | --- |
| Runtime queue claim candidates | `0.014 ms` | `< 50 ms` |
| Stale-running diagnostics | `2.23675 ms` | `< 50 ms` |
| Due-callback diagnostics | `0.02165 ms` | `< 50 ms` |
| Stale callback-dispatch recovery | `0.020 ms` | `< 50 ms` |
| Recent nightly runs for one site | `0.43195 ms` | `< 50 ms` |
| Image-source provider metrics | `4.4282 ms` | `< 50 ms` |

The highest p95 was `4.4282 ms`. Expected indexes were present and observed
where required, representative hit-cardinality checks passed, and the gate
reported no unexplained or unknown-cardinality sequential scan. The proof did
not execute a provider, store prompt/result payloads, or perform a WordPress
write.

## Current-revision Media Replay

The media proofs were replayed serially against the current Cloud source. The
serial posture is intentional: it confirms that the previously accepted
bounded byte path still holds at the P5-B4 revision without claiming
multiworker safety.

### Full performance proof

- status: passed;
- normalized report SHA-256:
  `a3b714882c38a2244019d73ff5f255a455b4eb4ce26cde6c0e57514481282863`;
- maximum-pixel image RSS delta: `340,189,184` bytes, below the
  `402,653,184`-byte budget;
- all four over-limit probes were rejected: upload byte limit, image-axis
  limit, pixel-count limit, and deliverable-output byte limit.

### Representative corpus

- status: passed;
- normalized report SHA-256:
  `1e643446c2d514a7d67ab0c7544e3b19c7b83ac3708d148236ab4b116998b563`;
- five representative conversion cases passed;
- two expected format/animation rejection cases failed closed;
- no network was used, no CMS write occurred, and no source or derivative
  bytes were persisted by the proof.

These media results preserve the P3 bounded-media gate on the current revision.
They do not authorize concurrent media workers, automatic media application,
or Cloud-side CMS mutation.

## Implementation Verification

| Gate | Result |
| --- | --- |
| Focused P5-B4 contract suite | `103 passed` |
| Complete Python test suite | `1,855 passed, 6 skipped`; one pre-existing Starlette/httpx deprecation warning |
| Ruff | passed |
| mypy | passed for `231` source files |
| Shell syntax, diff check, anti-drift, and provider-retirement checks | passed |
| Reduced v5 quick proof | passed as observation only; not acceptance evidence |
| Formal runtime v5 | three independent baselines passed; `formal_acceptance=true` |
| Formal hot-query proof | six canonical queries passed |
| Current-revision media replays | performance full and representative corpus passed |

`pnpm run check:perimeter` was not claimed in this isolated worktree because it
does not contain the required `.env`. No secret was copied from another
worktree to manufacture that environment. P5-B5 remains responsible for the
complete release gates and strict clean matrix in an appropriately configured
environment.

## Completion Decision And P5-B5 Handoff

P5-B4 is complete for local engineering acceptance on exactly revision
`dff31baf942542d12860b82f6a65a47dd2129d91`, contract v5, dataset v5, the
recorded proof images/environment, and the evidence hashes above. It proves
that the existing external runtime and queue/worker stack can meet the frozen
P5-B4 workload with two proof workers, that the current high-cardinality query
set stays within its engineering threshold, and that the serial bounded-media
proofs still pass.

Global P5 remains incomplete. P5-B5 still owns, at minimum:

- deterministic lock-based container builds, pinned image/dependency identity,
  and a container-image vulnerability scan;
- strict Portal/Admin JWT required-claim enforcement and missing-claim tests;
- a central sensitive-log redaction contract and regression gate;
- exact release-bundle replay, production-config verification, and
  release-policy proof;
- backup/restore rehearsal and rollback evidence;
- current text/media release acceptance as required by the exact bundle;
- the strict clean central cross-repository matrix, independent review, and
  final requirement-to-evidence audit.

P5-B4 must not be cited as production deployment approval, a production SLO,
production two-worker approval, concurrent-media proof, upstream-provider
quality evidence, a penetration test, or final refactor completion.
