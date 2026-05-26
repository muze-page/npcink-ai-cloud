# Cloud Compliance & Security Premium Layer — Positioning Document

> **Version:** 1.0  
> **Scope:** Enterprise / Regional premium capability planning and minimum surface  
> **Boundary:** This is NOT a complete legal-automation platform. We do NOT promise automatic legal compliance. We provide posture visibility, audit infrastructure, and region-readiness signals.

---

## 1. Positioning

Magick AI Cloud treats compliance, security, and audit as **Enterprise-tier differentiators** and **regional-market enablers**, not as a full GRC (Governance, Risk, Compliance) product.

| What we do | What we do NOT do |
|---|---|
| Read-only compliance posture in Portal/Admin | Auto-legal-compliance promises |
| Audit log retention, query, and export | Full risk console or SOAR |
| Data-residency disclosure and BYOM/hybrid guidance | Cross-border data-transfer automation |
| Region-readiness checklists (ICP, GDPR, EU AI Act) | Legal advice or DPO substitution |
| SLA/support-tier documentation | Automatic regulatory filing |

The local WordPress plugin remains a **runtime client**, not a compliance enforcement surface.

---

## 2. Architecture Principles

1. **Cloud-as-service-detail, plugin-as-local-control-plane** — Compliance posture, audit retention, and residency detail live in Cloud because they describe hosted service behavior. The local plugin remains the product control plane and the only owner of local approval and final WordPress writes.
2. **Read-only by default** — All compliance UI in Portal is read-only posture. Any data-subject request (DSR) or compliance action flows into a **human-reviewed ticket/request**, not an automated execution.
3. **Audit as source of truth** — `service_audit_events`, `commercial_decision_events`, and `runtime_guard_events` are the single audit backbone. Retention and export are infrastructure capabilities, not UI features alone.
4. **Explicit scope limitation** — We document what we cover (infrastructure security, access audit, data-at-rest encryption) and what is customer-shared responsibility (WordPress site content, end-user PII inside prompts, model-provider terms).

---

## 3. Minimum Portal / Admin Surface

### 3.1 Portal — `/portal/compliance` (read-only posture)

A single page, linked from the **More** menu in PortalNavbar, showing:

| Section | Content | Interaction |
|---|---|---|
| **Data Residency** | Current deployment region, storage region, inference region (if BYOM, show "Customer-managed endpoint") | Read-only badge |
| **Audit Posture** | Retention period (e.g., 90 days / 1 year / Enterprise), last export timestamp, event count in current window | Read-only; link to `/portal/audit` |
| **Security Controls** | Encryption-at-rest (Fernet), request signing (HMAC-SHA256), replay protection, secret rotation cadence | Read-only list |
| **Compliance Requests** | "Request data export", "Request deletion review", "Request compliance report" — each opens a modal that creates a `PortalActionRequest` (ticket) for operator review | Form → ticket; NOT auto-execution |
| **Model & Provider Posture** | List of active providers, model hosting mode (Cloud-hosted / BYOM / Hybrid), data classification levels used | Read-only |

**Design constraint:** No real-time risk scoring. No "compliance score". No green checkmarks that imply legal certification.

### 3.2 Admin — `/admin/compliance` (operator view)

A single page in the Admin **More** menu:

| Section | Content |
|---|---|
| **Tenant Compliance Overview** | Per-account: residency region, retention tier, DSR open tickets, last audit export |
| **DSR Request Queue** | List of compliance-related `PortalActionRequest` items (export, deletion, report) with status and assignee |
| **Audit Infrastructure Health** | Aggregate audit event volume, retention cleanup last run, storage trend |
| **Region Readiness Signals** | China-market checklist progress, EU readiness flags (for operator awareness) |

The current P0 implementation keeps operator execution inside the existing
`/admin/requests` queue. `/admin/compliance` is a read-only queue and posture
summary that points operators back to the bounded request workflow.

### 3.3 API Surface (minimum)

Add a read-only `GET /portal/v1/sites/{site_id}/compliance/posture` endpoint returning:

```json
{
  "site_id": "...",
  "data_residency": {
    "storage_region": "ap-east-1",
    "inference_region": "ap-east-1",
    "byom_enabled": false
  },
  "audit": {
    "retention_days": 90,
    "events_in_retention": 12480,
    "last_export_at": null
  },
  "security_controls": [
    { "control": "encryption_at_rest", "status": "active", "detail": "Fernet AES-128" },
    { "control": "request_signing", "status": "active", "detail": "HMAC-SHA256" },
    { "control": "replay_protection", "status": "active", "detail": "ReplayReceipt + nonce" }
  ],
  "compliance_requests_allowed": ["data_export", "deletion_review", "compliance_report"]
}
```

Add `POST /portal/v1/sites/{site_id}/compliance/requests` to create a compliance ticket (creates a `PortalActionRequest` with `request_type = compliance_*`).

---

## 4. Audit Retention, Export, BYOM/Hybrid, Data Residency

### 4.1 Audit Retention

| Tier | Retention | Target Customer |
|---|---|---|
| Starter (Free) | 30 days | Self-serve |
| Pro | 90 days | SMB |
| Agency / Enterprise | 1 year + export | Enterprise |

**Implementation:**
- The existing `service_audit_events` table already captures `event_kind`, `outcome`, `actor_ref`, `trace_id`, `idempotency_key`.
- The `deploy/OPS_PLAYBOOK.md` documents a manual retention cleanup endpoint (`/internal/service/runtime/retention/cleanup`).
- **Premium layer addition:** Scheduled retention job (operator-triggered or cron) with tier-aware cutoff.
- **Export:** `GET /portal/v1/audit/export?format=csv|json` streaming export for Enterprise tier, scoped to the site/account.

### 4.2 BYOM / Hybrid

| Mode | Data Flow | Residency Implication |
|---|---|---|
| **Cloud-hosted** (default) | Prompts go to Cloud-managed provider endpoints | Cloud controls provider selection and region |
| **BYOM** | Customer provides their own API key / endpoint; Cloud proxies with guard logging | Inference data leaves Cloud to customer-specified endpoint; Cloud logs metadata only |
| **Hybrid** | Some abilities use Cloud-hosted, others use BYOM | Per-ability residency determined by provider routing |

**Posture rule:** In `/portal/compliance`, always disclose whether the current site is using BYOM and, if so, remind the user that their model provider's terms and residency apply.

### 4.3 Data Residency

- **Storage:** Customer data (site records, API keys, audit events) resides in the Cloud database region tied to the deployment.
- **Inference:** Prompt/response payloads transit through the Cloud runtime. If BYOM is enabled, payloads also transit to the customer-managed endpoint.
- **Cross-border:** We do NOT automate cross-border transfer agreements. Enterprise customers may request a deployment in a specific region via `PortalActionRequest`.

---

## 5. China Market Readiness

### 5.1 ICP 备案 Status

- **Current posture:** Magick AI Cloud is a hosted platform; customer WordPress sites remain on customer-owned domains.
- **Responsibility split:** The customer is responsible for ICP filing of their own public-facing domain. Cloud does not host the public WordPress site.
- **Premium signal:** In `/portal/compliance`, show a note: "Your WordPress site domain is managed by you; ensure ICP compliance if serving visitors in mainland China."
- **Future:** If Cloud introduces a mainland China SaaS landing page or CDN edge, that property requires separate ICP filing.

### 5.2 Domestic Model Priority

- Catalog should surface **domestic models** (e.g., Qwen, Baichuan, Zhipu) with clear region labels.
- For China-focused Enterprise tiers, offer a "domestic-first" routing policy where eligible abilities prefer domestic endpoints.
- This is a **catalog/policy** feature, not a compliance automation.

### 5.3 Data Localization Posture

- Short-term: Deployable to any region; no hard region lock.
- Medium-term: Offer a **mainland China deployment option** (Aliyun / Tencent Cloud) as an Enterprise add-on.
- UI signal: `/portal/compliance` shows current storage region; if not mainland China, show "Data is stored outside mainland China."

### 5.4 WeChat Pay / Alipay Readiness

- Billing system currency is already CNY-default for `zh-CN` locale.
- **Preparation:**
  - Add `wechat_pay` and `alipay` as `payment_provider` enums in plan/billing metadata.
  - Ensure `PortalActionRequest` can capture "request alternative payment method".
  - Do NOT build full payment gateway integration in this layer; only surface readiness and capture requests.

### 5.5 Domestic CDN & Chinese Language Support

- **CDN:** Document that Cloud runtime API is served from the deployment region; customers may place their own CDN in front of their WordPress origin.
- **Language:** `zh-CN` and `zh-TW` are already supported in `PortalMemberPreference` and i18n.
- **Premium signal:** Enterprise SLA includes Simplified Chinese support channel.

---

## 6. International Market Readiness

### 6.1 GDPR Posture

| Aspect | Posture |
|---|---|
| **Lawful basis** | Contractual necessity (service delivery) + legitimate interest (security audit). Explicit consent is NOT relied upon for runtime processing. |
| **Data minimization** | Runtime payloads are processed transiently; only metadata, audit events, and encrypted secrets are retained. |
| **Retention** | Tier-based (30/90/365 days). No indefinite retention. |
| **DSR** | Via `PortalActionRequest` ticket → operator review. NOT automatic deletion because WordPress site data and model-provider logs are outside Cloud control. |
| **Sub-processors** | Documented in compliance page: model providers (OpenAI, Anthropic, etc.), hosting provider, email/SMS delivery. |
| **DPO** | No DPO UI or auto-legal-advice. Enterprise customers contact support for DPO inquiries. |

**UI rule:** `/portal/compliance` shows a short GDPR posture card: "We process data for service delivery and security. For data-subject requests, submit a ticket."

### 6.2 EU AI Act Auxiliary Audit

- We do NOT classify Magick AI Cloud as a high-risk AI system provider under EU AI Act; we are a **general-purpose AI hosting platform**.
- **Auxiliary capability:** For Enterprise customers who need to demonstrate auditability, we provide:
  - Audit log export with model/version identifiers.
  - `data_classification` tag usage report.
  - Human-in-the-loop evidence (impersonation sessions are read-only and audited).
- **Scope limit:** We do NOT provide automatic conformity assessments, CE marking, or risk-classification logic.

### 6.3 Audit Log Retention (International)

- Same tier-based retention as Section 4.1.
- Enterprise customers may request extended retention (custom SOW) via `PortalActionRequest`.
- Export formats: CSV (for Excel/Splunk ingestion), JSON (for SIEM).

### 6.4 BYOM / Hybrid (International)

- GDPR relevance: If a customer uses BYOM with an EU-based endpoint, they may establish their own Article 28 processing agreement with that endpoint provider.
- Cloud's role: We remain a processor for Cloud-hosted inference; for BYOM, we are a sub-processor or infrastructure proxy depending on contract terms.
- `/portal/compliance` discloses this distinction.

### 6.5 SLA / Support Tier

| Tier | SLA | Support |
|---|---|---|
| Starter | Best effort | Community |
| Pro | 99.5% uptime | Email, business hours |
| Enterprise | 99.9% uptime | Email + dedicated channel, 24×7 critical |

**Premium positioning:** Compliance and security features (extended audit, export, DSR handling, region deployment) are gated behind Enterprise tier or sold as add-ons.

---

## 7. Red Lines (Forbidden)

1. **No automatic legal compliance** — We never claim the platform makes a customer GDPR-compliant, ICP-compliant, or EU AI Act-compliant. We provide tools and visibility; compliance is a shared responsibility.
2. **No full risk console** — No SIEM replacement, no real-time threat intelligence dashboard, no automated risk scoring.
3. **No plugin compliance enforcement** — The WordPress plugin does not implement consent banners, DSR handlers, or legal checks. It sends `data_classification` and respects runtime guards; all compliance UI lives in Cloud Portal/Admin.
4. **No indefinite data retention** — Retention tiers must be enforced and documented.
5. **No cross-border transfer automation** — We document residency; we do not auto-generate SCCs or BCRs.

---

## 8. Implementation Roadmap (Minimum -> Mature)

| Phase | Deliverable | Surface |
|---|---|---|
| **P0 — Minimum** | Positioning doc (this doc) + `/portal/compliance` read-only page + `/admin/compliance` request summary + site-scoped compliance posture/request API | Portal/Admin nav, posture cards, DSR request form, existing Admin requests queue |
| **P1 — Export** | Audit export endpoint (`GET /portal/v1/audit/export`) + UI download button | Portal audit page |
| **P2 — Retention Tiers** | Tier-aware retention job + retention display in compliance page | Admin automation, Portal badge |
| **P3 — Region Signals** | China checklist (operator-only), EU AI Act export template | Admin checklist, Portal disclosure |
| **P4 — Enterprise Add-ons** | Custom region deployment, extended retention SLA, dedicated support channel | Sales/operator workflow |

---

## 9. Glossary

- **BYOM** — Bring Your Own Model (customer-managed endpoint)
- **DSR** — Data Subject Request (access, deletion, portability)
- **GRC** — Governance, Risk, Compliance
- **ICP** — Internet Content Provider (China regulation)
- **SCC** — Standard Contractual Clauses (GDPR transfer mechanism)
- **SIEM** — Security Information and Event Management

---

## 10. Related Documents

- `deploy/OPS_PLAYBOOK.md` — Operational security procedures
- `deploy/RELEASE_CHECKLIST.md` — Security gates
- `config/cloud-anti-drift-high-risk-surfaces-v1.json` — High-risk surface governance
- `docs/cloud-task-pack-boundary-v1.md` — Cloud-hosted task pack boundaries
- `app/core/security.py` — Request signing and replay protection
- `app/core/secrets.py` — Encryption at rest
- `app/domain/commercial/mixins/_audit_mixin.py` — Audit event infrastructure
