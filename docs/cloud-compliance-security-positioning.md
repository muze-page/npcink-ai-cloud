# Cloud Compliance And Security Positioning

Status: contracted to minimum service-plane scope.

Cloud keeps compliance and security as operator evidence, audit, retention,
export, policy posture, and diagnostics. It does not expose a customer-facing
compliance portal, compliance request queue, or legal automation workflow.

Removed surfaces include:

- `/portal/compliance`
- `/admin/compliance`
- portal compliance posture/request APIs
- customer-submitted compliance request flows

Allowed scope:

- service audit events
- billing and entitlement evidence
- runtime guard events
- operator diagnostics
- policy posture stored as internal metadata or audit evidence

Any future regional or enterprise compliance work must remain service-plane
evidence unless a new boundary document explicitly approves a broader surface.
