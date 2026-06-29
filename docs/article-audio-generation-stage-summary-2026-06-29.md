# Article Audio Generation Stage Summary - 2026-06-29

Status: project history and implementation summary.

This document records the product and engineering decisions made while shaping
Cloud-assisted article audio generation across Cloud, Toolbox, Adapter, Core,
and the Abilities Toolkit. It is a history document, not a new runtime API or a
new WordPress control plane.

## Product Direction

Article audio is useful only when it reaches the reader near the article. The
operator-facing Cloud/Admin surfaces are for provider setup, diagnostics, and
candidate verification; the product outcome is an adopted playback entry on the
WordPress article after the local governed path accepts it.

The first useful scope is deliberately narrow:

- article narration: generate a spoken version of the current article for
  readers who prefer listening;
- long-form audio summary: generate a shorter audio overview for readers who
  want to decide whether to read the full article;
- editor-side review: show one audio candidate, allow playback, and let the
  operator adopt it through the governed local path.

The fixed posture is:

- Cloud may execute hosted audio/text runtime work and retain candidate
  artifacts according to storage policy.
- Toolbox may expose fixed editor controls, preview candidates, and prepare
  adoption plans.
- Core remains the approval, preflight, execution, and audit truth.
- Abilities Toolkit owns the final reusable WordPress write ability.
- Adapter remains the channel that submits local proposals.
- No Cloud page or Toolbox button may directly mutate WordPress content,
  publish posts, import media, or bypass Core governance.

## Problems Solved

### Article Narration

Article narration solves a reader-access problem: long text is not always the
best consumption mode. It helps readers who are commuting, multitasking, using
accessibility tools, or reviewing a post by ear.

The WordPress-side user experience should eventually be simple:

1. An approved audio packet is attached to one article.
2. The public article renders a small playback entry near the article content.
3. The reader clicks the speaker/play control and listens.

The generation and adoption workflow behind that button remains governed and
auditable.

### Long-Form Audio Summary

Long-form audio summary solves a different problem: time and attention. It is
not a replacement for the article. It gives a reader a short spoken overview so
they can understand the article's point, decide whether to continue, or catch up
without reading the full body immediately.

This is especially useful for:

- documentation or product updates with many details;
- long editorial posts;
- release notes and implementation reports;
- readers who want a quick review before deeper reading.

The summary output should be labeled as a summary candidate, not confused with a
full narration.

## Provider And Configuration Decisions

The first audio provider is MiniMax. This choice was accepted for the first
version because the immediate goal was to prove hosted text-to-speech through
one concrete provider before generalizing provider behavior.

The early MiniMax-specific admin surface was treated as a bootstrap step. The
current direction is centralized AI resource management:

- operators configure provider connections through the Cloud AI resources
  center;
- provider secrets are encrypted at rest and masked in browsers;
- MiniMax audio, OpenAI-compatible text models, Anthropic, OpenRouter,
  SiliconFlow, LiteLLM, vLLM, embedding, rerank, image-source, and vector-store
  channels should all use the same provider-connection pattern;
- old environment-key paths and narrow provider pages are treated as historical
  baggage and should not be revived.

Do not record real API keys, group IDs, provider tokens, or secrets in docs,
fixtures, proposal payloads, browser responses, or logs.

## Cross-Repo Responsibilities

| Repo | Responsibility |
| --- | --- |
| `npcink-ai-cloud` | Hosted runtime execution, MiniMax provider call, text provider call, runtime diagnostics, provider readiness, candidate artifact storage, authorized artifact delivery, usage and audit evidence. |
| `npcink-toolbox` | WordPress editor UI, article-audio fixed flow, local narration preferences, candidate preview, Core adoption-plan preparation, source freshness evidence. |
| `npcink-governance-core` | Proposal records, policy decision, auto-approval where allowed, preflight, execution orchestration, and audit truth. |
| `npcink-abilities-toolkit` | `adopt-article-audio` style reusable ability that writes approved audio metadata or imports media when policy allows. |
| `npcink-ai-client-adapter` | Thin channel layer that submits the reviewed Toolbox plan to Core and reports governed results. |
| `npcink-cloud-addon` | Local connector for signed Cloud runtime calls and service status projection. |

The intended governed flow is:

```text
Toolbox fixed flow
-> Cloud hosted runtime candidate
-> Toolbox article_audio_adoption_plan.v1
-> Adapter submits Core proposal
-> Core policy may auto-approve safe article-audio adoption
-> Core preflight
-> Abilities Toolkit executes the write ability
-> Core audit records the outcome
-> Toolbox frontend playback reads adopted WordPress metadata
```

## Governance Classification

Article audio adoption is suitable for a narrow auto-approval policy only when
all of these are true:

- a currently logged-in administrator triggered the action;
- the scope is one article;
- the audio candidate came from a Cloud generation record;
- the candidate has `audio_url`, duration, provider/model, and trace evidence;
- the action writes only the protected article-audio metadata family;
- it does not edit the article body;
- it does not publish a post;
- it does not batch across posts;
- preflight passes;
- Core audit records proposal, decision, preflight, execution, and result.

More sensitive variants remain stronger-confirmation actions, especially media
library import. Publishing, replacing article body content, bulk edits,
creating new taxonomy terms, deleting media, or broad media replacement must not
be auto-approved by this article-audio policy.

## Storage And Playback Decisions

Provider audio URLs can be temporary, browser-hostile, or protected by provider
response rules. During verification, browser playback failures made it clear
that relying directly on provider preview URLs is fragile.

The preferred first-version storage posture is:

- Cloud downloads or persists the provider audio result into a Cloud-owned
  candidate artifact store;
- Cloud returns an authorized playback URL for review;
- WordPress stores only the adopted playback projection after Core/Abilities
  approval;
- optional local WordPress media import remains a governed action, not the
  default first-version path;
- if a customer requires local storage, the same adoption plan can request a
  media-library import through the stronger governed path.

This keeps the first version stable while leaving a clear path for customers who
need local media ownership.

## Source Freshness

When an article changes after audio generation, automatic regeneration is not
the first-version default. It would add complexity, cost, and confusing
background behavior.

The adopted audio metadata should instead carry lightweight source evidence:

- source content hash;
- source word count;
- generation timestamp;
- provider/model/trace;
- audio duration and format.

The local playback/editor surface can then show a freshness status such as:

- `current`;
- `minor_drift`;
- `review_recommended`;
- `stale`;
- `unknown`.

The operator can decide whether to regenerate. This avoids unnecessary spend
while still making drift visible.

## Editor UX Decisions

The editor surface should not look like a raw Cloud operation page. It should
look like a reviewable article-audio candidate.

Important UX decisions already made:

- hide full article body/script text in the audio result card;
- show the candidate title, compact metadata, player, open-audio link, and
  adoption action;
- label the action as adoption, not direct use;
- hide irrelevant "why no AI text" diagnostics for audio results;
- keep technical run details collapsed or lower-priority;
- improve failure copy so upstream GPT/script-generation failures do not show
  only technical messages such as "script empty";
- provide retry/regenerate behavior for transient upstream failures;
- avoid brittle local-dev bootstrap popups and prefer seeded local accounts and
  real login paths for Admin/Portal debugging.

The latest Toolbox direction for narration preferences is:

- fixed local options for tone, pace, content handling, and focus;
- optional extra request text;
- browser-local persistence with `localStorage`;
- send a normalized `audio_preferences` snapshot to the existing request;
- use cleaned `content_audio_text` for narration source text so skipped code or
  table handling can affect the generated audio;
- keep these preferences local to Toolbox for now, not as Cloud account-level
  configuration.

Cloud may later map these preferences to provider-specific voice, speed, and
style parameters, but the first useful version can carry them as reviewable
metadata and bounded instruction text.

## Current Implementation State From The Session

The session progressed through these milestones:

1. Chose article narration and long-form audio summary as the first two audio
   use cases.
2. Chose MiniMax as the first audio provider.
3. Added Cloud/Admin provider configuration and test concepts, then moved the
   long-term direction to centralized AI resource/provider connections.
4. Clarified that OpenAI-compatible text-provider settings should be replaced by
   the centralized provider connection model rather than kept as historical env
   keys.
5. Added local developer login guidance and removed the unstable platform-admin
   bootstrap-popup expectation in favor of seeded local accounts and real login.
6. Identified MiniMax provider preview URLs as unreliable for browser playback
   and moved toward Cloud-hosted candidate artifact storage with authorized
   reads.
7. Defined the governed adoption path through Toolbox, Adapter, Core, and
   Abilities Toolkit.
8. Tightened editor audio result layout so the operator reviews an audio
   candidate rather than seeing raw text/debug output.
9. Added local fixed narration preferences in Toolbox and preserved the Cloud
   boundary by not making Cloud a prompt/preset/config control plane for those
   preferences.

## Operational Notes

- MiniMax provider credentials should be configured through Cloud provider
  connections and tested from Admin.
- A successful provider test is not enough; the candidate must also be playable
  through the Cloud-hosted artifact URL.
- If generated audio does not play, check whether the provider URL expired,
  whether Cloud persisted the artifact, whether the authorized delivery route is
  returning the expected MIME type, and whether browser CORS/range requests are
  supported.
- Do not treat Cloud Admin playback as the final product experience. The final
  experience is public article playback after local governed adoption.
- Do not log provider secrets, raw authorization headers, or full provider
  responses.
- Keep result storage mode and retention explicit for audio artifacts because
  audio can contain customer article content.

## Next Useful Work

The next useful stage should stay narrow:

1. Verify Cloud-hosted audio artifact storage and authorized playback for MiniMax
   output, including MIME type, range support, and expiry behavior.
2. Wire the Toolbox adoption action through Adapter/Core to the Toolkit audio
   adoption ability for one article.
3. Prove the auto-approval policy only for the narrow metadata-write case.
4. Add one local smoke that generates or uses a fixture audio candidate, adopts
   it through Core, and verifies frontend playback metadata without mutating the
   article body.
5. After that path is stable, consider provider-specific mapping for tone, pace,
   voice, and summary length.

Do not expand into batch regeneration, background refresh jobs, direct Cloud
publishing, or broad media import until the single-article governed path is
boring and auditable.
