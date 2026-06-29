# Cloud Site Connection Closeout History - 2026-06-29

Status: historical closeout record.

Purpose: summarize the 2026-06-29 site connection, activation, removal, and
Cloud Addon credential-flow discussion across `npcink-ai-cloud` and
`npcink-cloud-addon`.

## Background

The original customer-facing flow exposed too much key-management detail:

- Portal had a visible key-management entry point.
- Users could see API-key oriented concepts while the real product task was
  connecting, enabling, disabling, or removing WordPress sites.
- WordPress Addon settings could still feel like a manual credential form.
- A disabled site still blocked adding the same URL again because site quota and
  uniqueness behavior were not aligned with the intended lifecycle.

The product decision was to separate user-facing site management from runtime
credentials:

- usage, quota, and entitlement follow the account/subscription;
- usage history keeps `site_id` as attribution evidence;
- keys remain bottom-layer runtime connection credentials;
- users manage sites, not signing keys;
- the WordPress addon receives and stores connection credentials automatically
  through the Cloud authorization flow.

## Decisions

### Site lifecycle

The intended site lifecycle is:

- `active`: the only site state accepted by public runtime services.
- `inactive`: user-disabled site; it keeps history but does not consume active
  site quota and cannot call runtime services.
- `suspended`: service-plane/operator pause; users cannot bypass it by
  self-service.
- `archived`: user removed the site from Portal; history remains readable by
  `site_id`, but the site does not consume active quota.

At a given time, an account/subscription should have only the allowed number of
active sites. Disabled or removed sites should not block reconnecting the same
WordPress URL during development-stage operation.

### Site removal

Users may remove a site because quota and billing are account/subscription
scoped, not key scoped. Removal should:

- archive the site record instead of deleting historical evidence;
- revoke active runtime keys for that site;
- preserve usage, billing, audit, and attribution history by `site_id`;
- free the active-site capacity for a new or reconnected site.

### Key ownership

Portal should not present key management as a normal customer workflow.

The key rule is:

```text
Portal exposes site connection management.
Cloud service plane owns key issuance and revocation.
Addon stores runtime credentials internally for signed requests.
```

Manual key entry is only an advanced recovery path in the WordPress addon, and
it accepts only Cloud-issued `mak1_` wrappers. Split JSON signing credentials
must not be accepted through the normal admin save path and must not be exposed
in the UI.

## Implemented Cloud-side behavior

The Cloud repository landed the Portal/key-management side in:

- `d6a5fd7 Hide portal key management behind site connection`

Important Cloud-side outcomes:

- `/portal/keys` redirects to `/portal/sites`.
- Addon connection and reconnection issue a new customer-facing Cloud API Key
  wrapper automatically.
- Old active runtime keys for the same site are revoked when a new connection is
  issued.
- Portal site management is the main user surface.
- Runtime acceptance still depends on an active site and an active key.

## Implemented Addon-side behavior

The WordPress addon repository landed the connection-flow side in:

- `de7c2e0 Finalize Cloud authorization connection flow`
- `6db15f1 Document Cloud site connection flow closeout`

Important addon outcomes:

- The addon authorization callback exchanges `code` and `state` through Cloud.
- The addon saves the Cloud-returned wrapper-derived credentials internally.
- The existing signed verify flow runs immediately after exchange.
- The default settings page no longer displays Site ID, Key ID, copied key
  values, `mak1_` values, or `Bearer` values.
- Advanced manual recovery accepts only Cloud-issued `mak1_` wrappers.
- Admin notices and verification errors redact `mak1_...` and `Bearer ...`
  values.

The detailed addon-side historical summary is in the addon repository:

```text
/Users/muze/gitee/npcink-cloud-addon/docs/cloud-site-connection-flow-history.md
```

## End-to-end verification

The local end-to-end verification used:

- Cloud: `http://127.0.0.1:8010`
- WordPress site: `https://magick-ai.local`
- Cloud site id: `site_magick-ai-local`

The verified chain was:

1. Portal created an addon connection.
2. Cloud returned a connection code and issued a new runtime credential.
3. The WordPress addon callback exchanged `code/state`.
4. The addon saved the returned Cloud API Key wrapper-derived connection
   details.
5. The addon immediately verified the saved connection.
6. The addon used the saved connection to make a signed runtime entitlement
   request.

Observed results:

- Cloud live health returned `ok`.
- Cloud addon connection returned `ok`.
- Saved addon `key_id` matched the Cloud-issued `key_id`.
- The old active key was returned in `revoked_key_ids`.
- WordPress option had `has_secret=true` and `verified=true`.
- Signed runtime entitlement request returned `ok`.

No secret, full Cloud API Key wrapper, or authorization token was printed in the
final report.

## UI smoke verification

Portal UI:

- `/portal/sites` opened successfully.
- The main site action was `添加站点`.
- The normal Portal surface did not expose key management as the primary flow.
- The add-site modal showed WordPress site URL and display-name fields.
- The add-site modal did not show `Cloud API Key`, `Site ID`, or `Key ID`.

WordPress addon UI:

- `Npcink > Cloud Addon` loaded on `magick-ai.local`.
- The page showed a verified connection state.
- The page exposed a Cloud-side change/reconnect action.
- The default page did not show `Cloud API Key`, `Site ID`, `Key ID`,
  `mak1_...`, or `Bearer ...` values.

## Verification gates

Addon verification:

```bash
composer run test:all
composer run check:wporg
git diff --check
rg "/v1/runtime/workflows/runs|wp_insert_post|wp_update_post" --glob '*.php' --glob '!build/**' .
composer run ai:i18n:audit
```

Results:

- `composer run test:all`: passed.
- `composer run check:wporg`: passed.
- `git diff --check`: passed.
- forbidden endpoint/write search: no hits.
- `composer run ai:i18n:audit`: exit code 0, with the existing external
  WordPress AI plugin translation candidate report still printed.

Cloud verification:

```bash
curl -sS http://127.0.0.1:8010/health/live
```

Result: `status=ok`.

## Boundary conclusions

The final shape keeps the intended ownership split:

- Cloud owns service-plane connection issuance, key lifecycle, runtime
  authentication, usage, entitlement, audit, and detail evidence.
- Portal exposes site management, not a self-serve runtime-key console.
- WordPress addon remains a thin connector for Cloud URL, credential storage,
  signing, verify, runtime calls, and read-only status.
- WordPress/local Core remains the control plane for approval, preflight, and
  final WordPress writes.
- No second ability registry, workflow registry, scheduler truth, prompt/preset
  owner, or WordPress write owner was introduced.

## Follow-up guardrails

Future changes should preserve these constraints:

- Do not restore customer-facing Portal key management without a fresh boundary
  review.
- Do not display split signing credentials in the addon UI.
- Do not accept raw split JSON credential payloads in the addon admin save path.
- Keep account/subscription quota separate from runtime keys.
- Keep historical usage and audit attributed by `site_id`.
- Revoking/reissuing keys remains a Cloud service-plane operation.
- Portal and addon can help users connect, reconnect, disable, or remove sites,
  but they must not become a second WordPress control plane.
