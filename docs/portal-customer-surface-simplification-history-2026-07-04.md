# Portal Customer Surface Simplification History

Date: 2026-07-04

## Purpose

The Portal is a customer-facing service center for ordinary users and site
owners. Its default experience should be simple, direct, and plain:

- show what the customer can understand and act on;
- keep site information, account package information, usage records, and contact
  information clearly separated;
- avoid exposing internal identities, permission records, runtime diagnostics,
  provider details, token/cost counters, or operator-only workflow language;
- keep Cloud as a hosted runtime and service evidence layer, not a second
  WordPress control plane.

## Main Decisions

### Account Package vs Site Record

Package ownership follows the customer account, not an individual site.

Portal pages now follow this split:

- Package page: current account package, included rights, current period,
  upgrade entry, credit packs, and support-level package records.
- Site pages: connected site name, address, service status, connection time, and
  simple status follow-up.
- Usage page: usage records and point-consumption details, focused on what was
  used during the current period.

Site lists, site detail cards, and site drawers should not show account package
as if it were a site-owned field.

### Package vs Usage

Package and usage were separated into two customer mental models:

- Package answers: "What does my account include?"
- Usage answers: "What did I use?"

The usage page no longer repeats package entitlement cards. Package rights stay
on the package page, while usage focuses on usage detail, records, trends, and
point consumption.

### Site Connection Flow

New sites are initiated from the WordPress `npcink-cloud-addon` connector.

Portal no longer treats "add site" as a primary customer action. The site list
shows a plain hint explaining that new connections start from the WordPress
addon and appear in Portal after binding.

### Technical Information

Customer-facing Portal screens were simplified to remove or hide professional
and internal material:

- internal principal/account IDs;
- action-scope and permission records;
- token/request/cost terminology in default views;
- audit-log style filters;
- plugin/vector observability details;
- AI insight/diagnostic advisor surfaces that were too vague or too technical;
- repeated quick links that duplicated global navigation.

Support-only records remain behind explicit detail disclosures where needed.

## Changes Applied

### Navigation And Layout

- Portal navigation was simplified to: Overview, Package, Usage, Sites, Contact.
- Repeated page headers, duplicated local navigation, and card-heavy sections
  were reduced.
- Global navigation is hidden from the unauthenticated login view.
- Login and registration were separated more clearly so users can understand
  whether they are signing in or creating a Free account.

### Overview

- Overview now starts from "My service" and shows a compact summary.
- Normal-state issue panels are hidden instead of showing "no action needed"
  cards.
- The connected-site preview no longer shows the current package per site.
- Site attention is based on site status and site address, not package coverage.

### Package

- Current package is resolved from the account subscription, not from
  `selectedSite.plan_name`.
- Current package rights are shown through a shared entitlement summary.
- Package records are kept behind an explicit support detail disclosure.
- The site-record shortcut was removed from the package rights section to avoid
  implying that package data belongs to a site.
- Package copy now uses account-level wording.

### Usage

- Usage focuses on point records and customer-readable usage details.
- English provider labels and vague "AI service" copy were rewritten into
  clearer customer-facing terms where backend evidence allows it.
- Redundant quantity columns and duplicated package entitlement blocks were
  removed or reduced.
- Period information is shown so "current usage" has a clear time window.

### Sites

- Site list filters, export controls, bulk operations, and direct add-site
  buttons were removed from the customer default view.
- Site cards no longer display package information.
- Site detail and inspector drawer focus on site address, status, and connection
  context.
- New-site guidance points users back to the WordPress addon connection flow.

### Monitoring, Audit, And AI Insight

- `/portal/ai-insights` was removed as a standalone customer page.
- Monitoring was simplified into a plain service-status page.
- Audit was simplified into recent customer-readable activity rather than an
  audit console.
- Plugin monitoring details remain behind support-style disclosures.

### Login And Session

- Login view no longer exposes the full authenticated Portal menu before login.
- Theme toggle hydration mismatch was addressed earlier by stabilizing the
  rendered button state.
- Development entry and session handling were adjusted so local Portal testing
  has a clearer path.
- "principal is not active" errors were treated as session/account activation
  state issues instead of customer-facing copy.

## Verification Used

The following checks were used during the Portal simplification work:

- `pnpm run frontend:type-check`
- `pnpm run frontend:lint`
- `node frontend/tests/unit/portal-home-layout-contract.mjs`
- `node frontend/tests/unit/portal-package-contract.mjs`
- `node frontend/tests/unit/portal-professional-info-simplification-contract.mjs`
- `node frontend/tests/unit/portal-usage-simplification-contract.mjs`
- `node frontend/tests/unit/portal-navigation-simplification-contract.mjs`
- targeted `git diff --check`

Earlier readiness review also ran `pnpm run check:fast`; at that time the Portal
direction was acceptable for a controlled trial, but the whole project was not
declared generally customer-ready because unrelated provider-domain tests still
needed follow-up.

## Current Product Rule

For future Portal work:

- keep the first screen understandable to a normal site owner;
- put status before explanation;
- put one job in one section;
- keep account-level package information out of site-level cards;
- keep usage details separate from package rights;
- show technical records only behind an explicit support/detail entry;
- prefer plain Chinese copy over platform, provider, or internal-system wording.

