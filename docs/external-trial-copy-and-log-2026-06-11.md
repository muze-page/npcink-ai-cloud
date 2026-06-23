# External Trial Copy And Log - 2026-06-11

Status: active controlled-trial template.

Purpose: keep first-batch trial messaging and evidence capture consistent while
Npcink AI Cloud remains pre-release and operator-managed.

## Approved Trial Copy

Use these phrases:

- reviewable suggestions
- writing preparation
- hosted runtime assistance
- Cloud-managed evidence
- local WordPress/Core review remains the final write owner
- feedback improves evaluation quality and does not change production behavior

Chinese copy:

```text
本次试用提供的是可审查的 AI 建议、写作准备辅助、站内证据整理和
Cloud 托管运行能力。AI 输出不会自动发布，也不会直接修改 WordPress。
最终是否采纳、如何编辑、是否写入和发布，仍由你的本地 WordPress/Core
审核链路决定。
```

English copy:

```text
This controlled trial provides reviewable AI suggestions, writing preparation,
site evidence, and hosted runtime assistance. Npcink AI Cloud does not publish
or directly modify WordPress content. Local WordPress/Core review remains the
final write owner.
```

## Do Not Say

Do not use copy that implies:

- automatic article generation
- direct publishing
- unrestricted content automation
- fake engagement generation
- bulk SEO article production
- no human review required
- bypassing AI disclosure, platform rules, or legal review

## Trial Log Template

Create one entry per site:

```markdown
## Trial Site

- Date:
- Operator:
- Environment:
- Cloud base URL:
- WordPress site URL:
- Site ID:
- Account ID:
- Contact:
- Declared use case:
- Site category:
- Category decision: approved / manual-review / rejected
- Cloud API key verified: yes/no
- Operational ready: yes/no

## Verification

- `pnpm run check:fast`:
- `pnpm run check:seam`:
- `pnpm run smoke:internal-alpha-onboarding`:
- `pnpm run smoke:site-knowledge`:
- Site Knowledge evidence JSON:
- `pnpm run smoke:local-alpha`:
- Local alpha evidence JSON:
- Toolbox `composer test:all`:
- Toolbox `composer smoke:site-knowledge-review-ui`:

## Runtime Evidence

- Run IDs:
- Error trace IDs:
- Provider health:
- Usage evidence:
- Audit evidence:
- Feedback summary:

## Abuse And Boundary Review

- Blocked prompts or abuse signals:
- Manual-review notes:
- WordPress direct write absent: yes/no
- Cloud article generation absent: yes/no
- Bulk article generation absent: yes/no
- Final write owner remains local/Core: yes/no

## Decision

- Go/no-go:
- Revocation/suspension action:
- Follow-up:
- Weekly review notes:
```

## Weekly Feedback Review

Before changing prompts, profiles, routing, or UX, review:

- whether users understood that outputs are suggestions
- whether any requests drifted toward prohibited content
- whether support could inspect run/error/usage evidence
- whether Site Knowledge answers were evidence-backed
- whether feedback labels identify a bounded product improvement

If the feedback suggests Cloud should own approval, publishing, prompt truth,
router truth, workflow truth, ability truth, or WordPress writes, stop and write
a separate boundary proposal.
