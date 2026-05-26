from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import jwt
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from jwt import InvalidTokenError

from app.adapters.notifications.base import PortalEmailDeliveryError
from app.api.admin_catalog import (
    save_admin_model_annotation,
    save_admin_recognition_annotation,
)
from app.api.admin_mutations import (
    disable_admin_account_member,
    enable_admin_account_member,
    invite_admin_account_member,
    resend_admin_account_member_invite,
    sync_admin_provider_connection_catalog,
    test_admin_provider_connection,
    upsert_admin_provider_connection,
)
from app.api.admin_ops import (
    ResolvedAdminSession,
    end_platform_impersonation,
    resolve_admin_login_identity,
    start_platform_impersonation_session,
)
from app.api.auth import (
    PortalBearerTokenError,
    get_cloud_services,
)
from app.api.browser_security import enforce_browser_same_origin, enforce_json_request
from app.api.envelope import build_envelope
from app.api.portal_locale import resolve_portal_email_locale
from app.api.portal_session import (
    build_new_portal_session_metadata,
    portal_cookie_secure,
)
from app.api.portal_session import (
    clear_portal_impersonation_cookies as _clear_portal_impersonation_cookies,
)
from app.api.portal_session import (
    clear_portal_session_cookies as _clear_browser_session_cookies,
)
from app.api.portal_session import (
    current_portal_impersonation_session as _current_portal_impersonation,
)
from app.api.portal_session import (
    portal_auth_mode as _portal_auth_mode,
)
from app.api.portal_session import (
    portal_json_error as _json_error,
)
from app.api.portal_session import (
    serialize_portal_session as _serialize_portal_session,
)
from app.api.portal_session import (
    set_portal_impersonation_cookies as _set_portal_impersonation_cookies,
)
from app.api.portal_session import (
    set_portal_session_cookies as _set_browser_session_cookies,
)
from app.api.routes.service import (
    CatalogModelAnnotationPayload,
    PlanPayload,
    PlanVersionPayload,
    ProviderConnectionPayload,
    RecognitionModelAnnotationPayload,
    SubscriptionPayload,
    SubscriptionTopUpPayload,
    _build_audit_context,
    _get_catalog_service,
    _get_commercial_service,
)
from app.core.models import ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN, PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN
from app.core.security import extract_trace_id
from app.domain.commercial.errors import CommercialServiceError
from app.domain.commercial.service import (
    IDENTITY_TYPE_PLATFORM_ADMIN,
    _platform_capability_flags,
    assert_platform_admin_capability,
)

DEFAULT_PORTAL_SCOPES = [
    "runtime:execute",
    "runtime:read",
    "runtime:resolve",
    "stats:read",
]
COOKIE_ADMIN_TOKEN = "magick_admin_session_token"
COOKIE_LOCALE = "magick_locale"
SUPPORTED_LOCALES = ("en", "zh-CN", "zh-TW")
DEFAULT_LOCALE = "en"
ADMIN_SESSION_ALGORITHM = "HS256"

WEB_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "nav.home": "Home",
        "nav.features": "Features",
        "nav.getting_started": "Getting Started",
        "nav.portal": "Portal",
        "base.brand_tagline": "Hosted runtime, service-plane, member portal",
        "base.footer_blurb": "Keep WordPress as the control plane. Push heavier runtime, stats, and service operations into Cloud.",
        "base.portal": "Portal",
        "common.language": "Language",
        "common.logout": "Logout",
        "common.refresh": "Refresh",
        "common.overview": "Overview",
        "common.connected_sites": "Connected sites",
        "common.change_member": "Change member",
        "common.change_login": "Change login",
        "common.key_manager": "Key manager",
        "common.site": "Site",
        "common.status": "Status",
        "common.account": "Account",
        "common.role": "Role",
        "common.action": "Action",
        "common.label": "Label",
        "common.actions": "Actions",
        "common.scope": "Scopes",
        "common.boundary": "Boundary",
        "common.pages": "Pages",
        "common.login": "Login",
        "common.active": "Active",
        "common.inactive": "Inactive",
        "common.not_selected": "No site selected.",
        "template.portal": "Portal",
        "template.internal_admin": "Internal Admin",
        "template.portal_home.session_summary": "Session summary",
        "template.portal_home.session_desc": "Portal state is bound to server-issued cookies, not browser-side copied headers.",
        "template.portal_home.open_overview": "Open overview",
        "template.portal_home.connected_sites": "Connected Sites",
        "template.portal_home.choose_site": "Choose the site you want to manage",
        "template.portal_home.login_to_load": "Login to load connected sites.",
        "template.portal_home.selection_rule": "Selection rule",
        "template.portal_home.selection_title": "Choose from real membership",
        "template.portal_home.selection_desc": "Login only establishes the member. Site selection happens here, based on real account membership.",
        "template.portal_home.selection_note": "That keeps the customer flow aligned with a future My Sites portal instead of forcing raw site_id input.",
        "template.portal_login.eyebrow": "Portal",
        "template.portal_login.what_this_is": "What this is",
        "template.portal_login.what_this_is_desc": "This surface provides member portal login on top of the existing portal routes.",
        "template.portal_login.preferred_path": "Portal access is invite-only. Enter your approved email to request a one-time verification code.",
        "template.portal_login.smtp_enabled": "Verification codes are currently delivered through configured SMTP email.",
        "template.portal_login.smtp_disabled": "SMTP is not configured yet, so the current environment returns the verification code in-app.",
        "template.portal_login.preferred_login": "Preferred login",
        "template.portal_login.preferred_login_desc": "Cloud maps the approved email back to one internal <code>member_ref</code> and reuses the existing membership and site access rules.",
        "template.portal_login.continue_with_provider": "Request verification code",
        "template.portal_login.read_onboarding": "Read onboarding",
        "template.portal_login.email_verification_code": "Email verification code",
        "template.portal_login.email_label": "Email",
        "template.portal_login.email_placeholder": "admin@example.com",
        "template.portal_login.send_verification_code": "Send verification code",
        "template.portal_login.open_portal_shell": "Open portal",
        "template.portal_login.auth_mode": "Portal auth mode",
        "template.home.eyebrow": "Magick AI Cloud",
        "template.home.see_onboarding": "See onboarding",
        "template.home.open_portal": "Open portal",
        "template.home.hosted_runtime": "Hosted Runtime",
        "template.home.hosted_runtime_desc": "Queued execution, replay-safe runs, profile stats",
        "template.home.service_plane": "Service Plane",
        "template.home.service_plane_desc": "Accounts, sites, keys, plans, commercial inspect",
        "template.home.why_exists": "Why it exists",
        "template.home.why_exists_title": "Cloud is the runtime layer for heavy work, not a second WordPress admin.",
        "template.home.why_exists_desc_1": "Use Cloud when you need hosted routing, queued runs, callback delivery, usage evidence, and commercial operations without moving product truth out of the plugin.",
        "template.home.why_exists_desc_2": "The buyer-facing surface can explain the product, guide onboarding, and show key lifecycle. The canonical key and service truth still stays in the existing service-plane.",
        "template.home.buyers_see": "What buyers see",
        "template.home.buyers_see_title": "One clear journey instead of scattered operator endpoints.",
        "template.home.offer_title": "Understand the offer",
        "template.home.offer_desc": "Public pages explain hosted runtime, who it is for, and how Cloud relates to the local plugin.",
        "template.home.onboarding_title": "Portal onboarding",
        "template.home.onboarding_desc": "The portal shows login, site context, and one-time API key delivery flow.",
        "template.home.operate_title": "Operate safely",
        "template.home.operate_desc": "Cloud keeps service-plane lifecycle, diagnostics, and request auth contracts intact underneath the UI.",
        "template.home.next_step": "Next step",
        "template.home.next_step_title": "Start with the portal, then harden auth and operations as usage grows.",
        "template.home.portal_login": "Portal login",
        "template.features.eyebrow": "Feature Surface",
        "template.features.runtime_title": "Hosted runtime execution",
        "template.features.runtime_desc": "Resolve and execute against hosted profiles, keep fallback metadata, and surface run lifecycle through canonical runtime routes.",
        "template.features.queued_title": "Queued long-running work",
        "template.features.queued_desc": "Move whole-run offload and callback delivery into the worker loop without creating a second result truth outside `run_records`.",
        "template.features.commercial_title": "Commercial service-plane",
        "template.features.commercial_desc": "Operate accounts, sites, keys, plans, subscriptions, entitlements, usage meter, and billing snapshot inspect from internal routes.",
        "template.features.portal_surface_title": "Portal seam",
        "template.features.portal_surface_desc": "Reuse existing `/portal/v1/*` key issue, rotate, revoke, and list routes to support authenticated member flows.",
        "template.features.not_shipped": "Not shipped as front-office",
        "template.features.not_shipped_title": "Keep the claims honest.",
        "template.features.not_shipped_desc_1": "Cloud already ships hosted runtime, service-plane, diagnostics, and key lifecycle scaffolding.",
        "template.features.not_shipped_desc_2": "It does not yet ship customer registration, formal session auth, checkout, invoice, payment recovery, or a complete billing portal.",
        "template.getting_started.eyebrow": "Getting Started",
        "template.getting_started.step_1": "Step 1",
        "template.getting_started.step_1_title": "Provision a site and key",
        "template.getting_started.step_1_desc": "Use internal service-plane or seeded data to create an active site and runtime key. The portal then wraps the same lifecycle.",
        "template.getting_started.step_2": "Step 2",
        "template.getting_started.step_2_title": "Configure the Cloud addon",
        "template.getting_started.step_2_desc": "Point the WordPress addon at Cloud with `base_url`, `site_id`, `key_id`, `secret`, and timeout. Core stays the control plane.",
        "template.getting_started.step_3": "Step 3",
        "template.getting_started.step_3_title": "Call the hosted runtime",
        "template.getting_started.step_3_desc": "Use the canonical HMAC contract for catalog, runtime, runs, and stats. The buyer-facing page should explain this contract in plain language.",
        "template.getting_started.step_4": "Step 4",
        "template.getting_started.step_4_title": "Complete the member flow",
        "template.getting_started.step_4_desc": "Open the portal, verify the invited email, select a site, then issue or rotate a `Cloud API Key` without inventing a second auth model.",
        "template.getting_started.remote_endpoint": "Current remote endpoint",
        "template.getting_started.remote_endpoint_title": "Verified public health endpoint",
        "route.home_title": "Managed execution for teams that have already outgrown localhost.",
        "route.home_lead": "Magick AI Cloud adds hosted runtime, durable runs, usage evidence, and key-based onboarding without replacing the WordPress control plane.",
        "route.features_title": "A buyer-facing surface for what Cloud actually ships today.",
        "route.features_lead": "Hosted runtime, queued execution, operational diagnostics, and commercial service-plane primitives are already here. Full front-office is not.",
        "route.getting_started_title": "Go from provisioned site to signed runtime call in a short, reproducible path.",
        "route.getting_started_lead": "Use the Cloud addon for credentials, issue or manage keys through portal routes, then call the hosted runtime with the canonical HMAC contract.",
        "template.portal_overview.workspace": "Workspace",
        "template.portal_overview.snapshot": "Selected site snapshot",
        "template.portal_overview.select_site": "Select a site to load summary data.",
        "template.portal_overview.usage": "Usage",
        "template.portal_overview.usage_summary": "Usage summary",
        "template.portal_overview.waiting": "Waiting for selected site…",
        "template.portal_overview.entitlements": "Entitlements",
        "template.portal_overview.commercial_state": "Commercial state",
        "template.portal_overview.billing": "Billing",
        "template.portal_overview.latest_snapshot": "Latest snapshot",
        "template.portal_overview.verification_boundary": "Verification boundary",
        "template.portal_overview.verification_desc": "This overview is a bounded fallback workspace for release verification, not the final customer portal UI.",
        "template.portal_overview.verification_note": "The canonical data still comes from /portal/v1/*; this page only makes it visible quickly in local Docker and remote smoke runs.",
        "template.portal_keys.keys": "Keys",
        "template.portal_keys.current_site_keys": "Current site keys",
        "template.portal_keys.start_session": "Start a portal session to load key data.",
        "template.portal_keys.last_four": "Last four",
        "template.portal_keys.one_time_delivery": "One-time delivery",
        "template.portal_keys.latest_result": "Latest issue / rotate result",
        "template.portal_keys.no_key_issued": "No key has been issued in this browser session yet.",
        "template.portal_keys.issue_key": "Issue key",
        "template.portal_keys.rotate_key": "Rotate key",
        "template.portal_keys.expires_at": "Expires at",
        "template.portal_keys.existing_key": "Existing key",
        "template.portal_keys.new_label": "New label",
        "template.portal_keys.scopes_override": "Scopes override",
        "template.portal_keys.revoke_key": "Revoke key",
        "template.portal_keys.key_to_revoke": "Key to revoke",
        "template.portal_keys.production_key": "Production Key",
        "template.portal_keys.production_key_rotated": "Production Key Rotated",
        "template.portal_keys.keep_scopes": "Leave empty to keep current scopes",
        "template.portal_keys.select_key": "Select a key",
        "route.portal_login_title": "Portal login",
        "route.portal_login_lead": "Use the bounded portal session seam to reach the sites this member can actually access. Invited members sign in with a one-time email verification code.",
        "route.portal_home_title": "Connected sites",
        "route.portal_home_lead": "Start from the sites this member can actually reach, then open the key manager for one selected site.",
        "route.portal_overview_title": "Portal overview",
        "route.portal_overview_lead": "See the selected site's current summary, usage, entitlement state, and latest billing snapshot in one bounded verification workspace.",
        "route.portal_keys_title": "Portal key manager",
        "route.portal_keys_lead": "List, issue, rotate, and revoke site keys without exposing raw operator headers in the browser.",
    },
    "zh-CN": {
        "nav.home": "首页",
        "nav.features": "功能特性",
        "nav.getting_started": "入门指南",
        "nav.portal": "控制台",
        "base.brand_tagline": "托管运行时、服务平面与 Portal",
        "base.footer_blurb": "保留 WordPress 作为控制平面，把更重的运行时、统计和服务运维放到 Cloud。",
        "base.portal": "Portal",
        "common.language": "语言",
        "common.logout": "退出登录",
        "common.refresh": "刷新",
        "common.overview": "概览",
        "common.connected_sites": "已连接站点",
        "common.change_member": "切换成员",
        "common.change_login": "切换登录",
        "common.key_manager": "密钥管理",
        "common.site": "站点",
        "common.status": "状态",
        "common.account": "账户",
        "common.role": "角色",
        "common.action": "操作",
        "common.label": "标签",
        "common.actions": "操作",
        "common.scope": "权限范围",
        "common.boundary": "边界",
        "common.pages": "页面",
        "common.login": "登录",
        "common.active": "启用",
        "common.inactive": "停用",
        "common.not_selected": "尚未选择站点。",
        "template.portal": "Portal",
        "template.internal_admin": "内部后台",
        "template.portal_home.session_summary": "会话摘要",
        "template.portal_home.session_desc": "Portal 会话状态绑定在服务端签发的 Cookie 上，而不是浏览器侧复制的请求头。",
        "template.portal_home.open_overview": "打开概览",
        "template.portal_home.connected_sites": "已连接站点",
        "template.portal_home.choose_site": "选择你要管理的站点",
        "template.portal_home.login_to_load": "登录后即可加载已连接站点。",
        "template.portal_home.selection_rule": "选择规则",
        "template.portal_home.selection_title": "基于真实成员关系选择",
        "template.portal_home.selection_desc": "登录只确认成员身份，站点选择在这里根据真实账户成员关系进行。",
        "template.portal_home.selection_note": "这样可以让客户流程贴近未来的“我的站点”Portal，而不是强迫输入原始 site_id。",
        "template.portal_login.eyebrow": "控制台",
        "template.portal_login.what_this_is": "这是什么",
        "template.portal_login.what_this_is_desc": "这个界面用于在现有 portal 路由之上验证买家可见的登录流程。",
        "template.portal_login.preferred_path": "Portal 采用邀请制登录。输入已批准邮箱后，系统会发送一次性验证码。",
        "template.portal_login.smtp_enabled": "当前验证码会通过已配置的 SMTP 邮件送达。",
        "template.portal_login.smtp_disabled": "当前还没有配置 SMTP，因此开发环境会直接在页面内返回验证码。",
        "template.portal_login.preferred_login": "首选登录方式",
        "template.portal_login.preferred_login_desc": "Cloud 会把已批准邮箱映射回一个内部 <code>member_ref</code>，并复用现有成员关系与站点访问规则。",
        "template.portal_login.continue_with_provider": "申请验证码",
        "template.portal_login.read_onboarding": "查看接入说明",
        "template.portal_login.email_verification_code": "邮箱验证码",
        "template.portal_login.email_label": "邮箱",
        "template.portal_login.email_placeholder": "admin@example.com",
        "template.portal_login.send_verification_code": "发送验证码",
        "template.portal_login.open_portal_shell": "打开 Portal",
        "template.portal_login.auth_mode": "Portal 认证模式",
        "template.home.eyebrow": "Magick AI Cloud",
        "template.home.see_onboarding": "查看接入流程",
        "template.home.open_portal": "打开 Portal",
        "template.home.hosted_runtime": "托管运行时",
        "template.home.hosted_runtime_desc": "排队执行、可重放安全运行、Profile 统计",
        "template.home.service_plane": "服务平面",
        "template.home.service_plane_desc": "账户、站点、密钥、套餐与商业检查",
        "template.home.why_exists": "为什么存在",
        "template.home.why_exists_title": "Cloud 是承接重型运行工作的 runtime 层，不是第二个 WordPress 后台。",
        "template.home.why_exists_desc_1": "当你需要托管路由、排队运行、回调投递、用量证据和商业运维，同时又不想把产品真相移出插件时，就该用 Cloud。",
        "template.home.why_exists_desc_2": "面向买家的界面可以解释产品、引导接入并说明密钥生命周期，而规范性的密钥与服务真相仍然留在现有服务平面。",
        "template.home.buyers_see": "买家看到什么",
        "template.home.buyers_see_title": "一条清晰旅程，而不是零散的运维端点。",
        "template.home.offer_title": "理解产品能力",
        "template.home.offer_desc": "公开页面解释托管运行时、适用对象，以及 Cloud 与本地插件的关系。",
        "template.home.onboarding_title": "接入流程",
        "template.home.onboarding_desc": "Portal 展示目标登录方式、站点上下文和一次性 API 密钥交付流程。",
        "template.home.operate_title": "安全运营",
        "template.home.operate_desc": "Cloud 在 UI 下方保持服务平面生命周期、诊断信息和请求认证契约不被破坏。",
        "template.home.next_step": "下一步",
        "template.home.next_step_title": "先从 Portal 开始，等使用量上来后再继续加固认证和运营。",
        "template.home.portal_login": "Portal 登录",
        "template.features.eyebrow": "功能表层",
        "template.features.runtime_title": "托管运行时执行",
        "template.features.runtime_desc": "对托管 profile 进行解析与执行，保留回退元数据，并通过规范 runtime 路由暴露运行生命周期。",
        "template.features.queued_title": "排队的长耗时工作",
        "template.features.queued_desc": "将整次运行的 offload 与回调投递放进 worker 循环中，而不在 `run_records` 之外制造第二份结果真相。",
        "template.features.commercial_title": "商业服务平面",
        "template.features.commercial_desc": "通过内部路由管理账户、站点、密钥、套餐、订阅、权益、用量计量和账单快照检查。",
        "template.features.portal_surface_title": "Portal 接缝",
        "template.features.portal_surface_desc": "复用现有 `/portal/v1/*` 的签发、轮换、撤销和列出密钥路由，支持已认证成员流程。",
        "template.features.not_shipped": "尚未作为前台完整交付",
        "template.features.not_shipped_title": "保持对外表述诚实。",
        "template.features.not_shipped_desc_1": "Cloud 已经提供托管运行时、服务平面、诊断能力和密钥生命周期脚手架。",
        "template.features.not_shipped_desc_2": "它还没有交付客户注册、正式会话认证、结账、发票、支付追缴或完整账单门户。",
        "template.getting_started.eyebrow": "快速开始",
        "template.getting_started.step_1": "步骤 1",
        "template.getting_started.step_1_title": "准备站点和密钥",
        "template.getting_started.step_1_desc": "使用内部服务平面或 seed 的开发数据创建一个活跃站点和 runtime key，然后再用 Portal 承接同一条生命周期。",
        "template.getting_started.step_2": "步骤 2",
        "template.getting_started.step_2_title": "配置 Cloud addon",
        "template.getting_started.step_2_desc": "把 WordPress addon 指向 Cloud，并配置 `base_url`、`site_id`、`key_id`、`secret` 和 timeout。Core 仍是控制平面。",
        "template.getting_started.step_3": "步骤 3",
        "template.getting_started.step_3_title": "调用托管运行时",
        "template.getting_started.step_3_desc": "按照规范 HMAC 契约调用 catalog、runtime、runs 和 stats。面向买家的页面应该用通俗语言解释这套契约。",
        "template.getting_started.step_4": "步骤 4",
        "template.getting_started.step_4_title": "走通成员流程",
        "template.getting_started.step_4_desc": "打开 Portal，使用受邀邮箱验证码登录，选择站点，然后在不发明第二套认证模型的前提下签发或轮换 `Cloud API Key`。",
        "template.getting_started.remote_endpoint": "当前远端环境",
        "template.getting_started.remote_endpoint_title": "已验证的公开健康检查端点",
        "route.home_title": "为已经超出 localhost 阶段的团队提供托管执行。",
        "route.home_lead": "Magick AI Cloud 在不替换 WordPress 控制平面的前提下，增加托管运行时、持久运行、用量证据与基于密钥的接入流程。",
        "route.features_title": "面向买家的表层，用来说明 Cloud 今天真正交付了什么。",
        "route.features_lead": "托管运行时、排队执行、运维诊断和商业服务平面原语已经具备，完整前台仍未交付。",
        "route.getting_started_title": "用一条简短、可复现的路径，从已开通站点走到已签名的 runtime 调用。",
        "route.getting_started_lead": "先用 Cloud addon 配置凭据，通过 portal 路由签发或管理密钥，再按规范 HMAC 契约调用托管运行时。",
        "template.portal_overview.workspace": "工作区",
        "template.portal_overview.snapshot": "当前选中站点快照",
        "template.portal_overview.select_site": "选择一个站点以加载摘要数据。",
        "template.portal_overview.usage": "用量",
        "template.portal_overview.usage_summary": "用量摘要",
        "template.portal_overview.waiting": "等待选择站点…",
        "template.portal_overview.entitlements": "权益",
        "template.portal_overview.commercial_state": "商业状态",
        "template.portal_overview.billing": "账单",
        "template.portal_overview.latest_snapshot": "最新快照",
        "template.portal_overview.verification_boundary": "验证边界",
        "template.portal_overview.verification_desc": "这个概览是用于发布验证的受限回退工作区，不是最终客户 Portal UI。",
        "template.portal_overview.verification_note": "规范数据仍来自 /portal/v1/*；这个页面只是让它能在本地 Docker 和远端 smoke 中更快可见。",
        "template.portal_keys.keys": "密钥",
        "template.portal_keys.current_site_keys": "当前站点密钥",
        "template.portal_keys.start_session": "先启动 Portal 会话以加载密钥数据。",
        "template.portal_keys.last_four": "后四位",
        "template.portal_keys.one_time_delivery": "一次性交付",
        "template.portal_keys.latest_result": "最近一次签发 / 轮换结果",
        "template.portal_keys.no_key_issued": "当前浏览器会话中还没有签发过密钥。",
        "template.portal_keys.issue_key": "签发密钥",
        "template.portal_keys.rotate_key": "轮换密钥",
        "template.portal_keys.expires_at": "过期时间",
        "template.portal_keys.existing_key": "现有密钥",
        "template.portal_keys.new_label": "新标签",
        "template.portal_keys.scopes_override": "覆盖权限范围",
        "template.portal_keys.revoke_key": "撤销密钥",
        "template.portal_keys.key_to_revoke": "要撤销的密钥",
        "template.portal_keys.production_key": "生产密钥",
        "template.portal_keys.production_key_rotated": "生产密钥（已轮换）",
        "template.portal_keys.keep_scopes": "留空则保持当前 scopes",
        "template.portal_keys.select_key": "选择一个密钥",
        "route.portal_login_title": "Portal 登录",
        "route.portal_login_lead": "通过受限的 Portal 会话边界进入该成员实际可访问的站点。受邀成员通过邮箱一次性验证码登录。",
        "route.portal_home_title": "已连接站点",
        "route.portal_home_lead": "从该成员实际可访问的站点开始，然后为一个选中站点打开密钥管理。",
        "route.portal_overview_title": "Portal 概览",
        "route.portal_overview_lead": "在一个受限的验证工作区中查看选中站点的当前摘要、用量、权益状态和最新账单快照。",
        "route.portal_keys_title": "Portal 密钥管理",
        "route.portal_keys_lead": "列出、签发、轮换并撤销站点密钥，而不在浏览器中暴露原始运维请求头。",
    },
    "zh-TW": {
        "nav.home": "首頁",
        "nav.features": "功能特色",
        "nav.getting_started": "快速開始",
        "nav.portal": "入口網站",
        "base.brand_tagline": "託管執行環境、服務平面與 Portal",
        "base.footer_blurb": "保留 WordPress 作為控制平面，把更重的執行環境、統計與服務營運放到 Cloud。",
        "base.portal": "Portal",
        "common.language": "語言",
        "common.logout": "登出",
        "common.refresh": "重新整理",
        "common.overview": "總覽",
        "common.connected_sites": "已連線網站",
        "common.change_member": "切換成員",
        "common.change_login": "切換登入",
        "common.key_manager": "金鑰管理",
        "common.site": "網站",
        "common.status": "狀態",
        "common.account": "帳戶",
        "common.role": "角色",
        "common.action": "操作",
        "common.label": "標籤",
        "common.actions": "操作",
        "common.scope": "權限範圍",
        "common.boundary": "邊界",
        "common.pages": "頁面",
        "common.login": "登入",
        "common.active": "啟用",
        "common.inactive": "停用",
        "common.not_selected": "尚未選取網站。",
        "template.portal": "Portal",
        "template.internal_admin": "內部後台",
        "template.portal_home.session_summary": "工作階段摘要",
        "template.portal_home.session_desc": "Portal 工作階段狀態綁定在伺服器簽發的 Cookie，而不是瀏覽器端複製的標頭。",
        "template.portal_home.open_overview": "開啟總覽",
        "template.portal_home.connected_sites": "已連線網站",
        "template.portal_home.choose_site": "選擇你要管理的網站",
        "template.portal_home.login_to_load": "登入後即可載入已連線網站。",
        "template.portal_home.selection_rule": "選擇規則",
        "template.portal_home.selection_title": "依真實成員關係選取",
        "template.portal_home.selection_desc": "登入只會確認成員身份，網站選取會依真實帳戶成員關係在這裡完成。",
        "template.portal_home.selection_note": "這能讓客戶流程更貼近未來的「我的網站」Portal，而不是強迫輸入原始 site_id。",
        "template.portal_login.eyebrow": "控制台",
        "template.portal_login.what_this_is": "這是什麼",
        "template.portal_login.what_this_is_desc": "這個介面用來在現有 portal 路由之上驗證面向買家的登入流程。",
        "template.portal_login.preferred_path": "Portal 採用邀請制登入。輸入已批准電子郵件後，系統會傳送一次性驗證碼。",
        "template.portal_login.smtp_enabled": "目前驗證碼會透過已設定的 SMTP 郵件寄送。",
        "template.portal_login.smtp_disabled": "目前尚未設定 SMTP，因此開發環境會直接在頁面內回傳驗證碼。",
        "template.portal_login.preferred_login": "首選登入方式",
        "template.portal_login.preferred_login_desc": "Cloud 會將已批准電子郵件映射回單一內部 <code>member_ref</code>，並沿用現有成員關係與網站存取規則。",
        "template.portal_login.continue_with_provider": "申請驗證碼",
        "template.portal_login.read_onboarding": "閱讀導覽",
        "template.portal_login.email_verification_code": "電子郵件驗證碼",
        "template.portal_login.email_label": "電子郵件",
        "template.portal_login.email_placeholder": "admin@example.com",
        "template.portal_login.send_verification_code": "發送驗證碼",
        "template.portal_login.open_portal_shell": "開啟 Portal",
        "template.portal_login.auth_mode": "Portal 驗證模式",
        "template.home.eyebrow": "Magick AI Cloud",
        "template.home.see_onboarding": "查看導覽流程",
        "template.home.open_portal": "開啟 Portal",
        "template.home.hosted_runtime": "託管執行環境",
        "template.home.hosted_runtime_desc": "排隊執行、可安全重播的 run、Profile 統計",
        "template.home.service_plane": "服務平面",
        "template.home.service_plane_desc": "帳戶、網站、金鑰、方案與商業檢視",
        "template.home.why_exists": "為何存在",
        "template.home.why_exists_title": "Cloud 是承接重型執行工作的 runtime 層，不是第二個 WordPress 後台。",
        "template.home.why_exists_desc_1": "當你需要託管路由、排隊執行、回呼投遞、用量證據與商業營運，同時又不想把產品真相搬離外掛時，就該使用 Cloud。",
        "template.home.why_exists_desc_2": "面向買家的介面可以解釋產品、引導導入並說明金鑰生命週期，而規範性的金鑰與服務真相仍留在既有服務平面。",
        "template.home.buyers_see": "買家會看到什麼",
        "template.home.buyers_see_title": "一條清楚旅程，而不是零散的營運端點。",
        "template.home.offer_title": "理解產品能力",
        "template.home.offer_desc": "公開頁面說明託管執行環境、適用對象，以及 Cloud 與本地外掛之間的關係。",
        "template.home.onboarding_title": "導入流程",
        "template.home.onboarding_desc": "Portal 展示預期登入方式、網站上下文與一次性 API 金鑰交付流程。",
        "template.home.operate_title": "安全營運",
        "template.home.operate_desc": "Cloud 在 UI 下方維持服務平面生命週期、診斷資訊與請求驗證契約的完整性。",
        "template.home.next_step": "下一步",
        "template.home.next_step_title": "先從 Portal 開始，等使用量上來後再繼續強化驗證與營運。",
        "template.home.portal_login": "Portal 登入",
        "template.features.eyebrow": "功能表層",
        "template.features.runtime_title": "託管執行環境執行",
        "template.features.runtime_desc": "對託管 profile 進行解析與執行，保留回退中繼資料，並透過標準 runtime 路由呈現執行生命週期。",
        "template.features.queued_title": "排隊的長時間工作",
        "template.features.queued_desc": "將整次 run 的 offload 與回呼投遞放入 worker 迴圈，而不在 `run_records` 之外建立第二份結果真相。",
        "template.features.commercial_title": "商業服務平面",
        "template.features.commercial_desc": "透過內部路由操作帳戶、網站、金鑰、方案、訂閱、權益、用量計量與帳務快照檢視。",
        "template.features.portal_surface_title": "Portal 接縫",
        "template.features.portal_surface_desc": "重用既有 `/portal/v1/*` 的簽發、輪換、撤銷與列出金鑰路由，支援已驗證成員流程。",
        "template.features.not_shipped": "尚未作為前台完整交付",
        "template.features.not_shipped_title": "保持對外說法誠實。",
        "template.features.not_shipped_desc_1": "Cloud 已提供託管執行環境、服務平面、診斷能力與金鑰生命週期腳手架。",
        "template.features.not_shipped_desc_2": "它尚未交付客戶註冊、正式工作階段驗證、結帳、發票、付款補救或完整帳單入口網站。",
        "template.getting_started.eyebrow": "快速開始",
        "template.getting_started.step_1": "步驟 1",
        "template.getting_started.step_1_title": "準備網站與金鑰",
        "template.getting_started.step_1_desc": "使用內部服務平面或 seed 的開發資料建立一個啟用中的網站與 runtime key，然後再用 Portal 承接同一條生命週期。",
        "template.getting_started.step_2": "步驟 2",
        "template.getting_started.step_2_title": "設定 Cloud addon",
        "template.getting_started.step_2_desc": "將 WordPress addon 指向 Cloud，並設定 `base_url`、`site_id`、`key_id`、`secret` 與 timeout。Core 仍是控制平面。",
        "template.getting_started.step_3": "步驟 3",
        "template.getting_started.step_3_title": "呼叫託管執行環境",
        "template.getting_started.step_3_desc": "依標準 HMAC 契約呼叫 catalog、runtime、runs 與 stats。面向買家的頁面應以易懂語言解釋這份契約。",
        "template.getting_started.step_4": "步驟 4",
        "template.getting_started.step_4_title": "走通成員流程",
        "template.getting_started.step_4_desc": "打開 Portal，使用受邀電子郵件驗證碼登入，選擇站點，然後在不發明第二套驗證模型的前提下簽發或輪換 `Cloud API Key`。",
        "template.getting_started.remote_endpoint": "目前遠端環境",
        "template.getting_started.remote_endpoint_title": "已驗證的公開健康檢查端點",
        "route.home_title": "為已經超出 localhost 階段的團隊提供託管執行。",
        "route.home_lead": "Magick AI Cloud 在不取代 WordPress 控制平面的前提下，加入託管執行環境、持久 runs、用量證據與基於金鑰的導入流程。",
        "route.features_title": "面向買家的表層，用來說明 Cloud 今天真正交付了什麼。",
        "route.features_lead": "託管執行環境、排隊執行、營運診斷與商業服務平面基元已經就緒，完整前台仍未交付。",
        "route.getting_started_title": "用一條簡短且可重現的路徑，從已佈署網站走到已簽名的 runtime 呼叫。",
        "route.getting_started_lead": "先用 Cloud addon 設定憑證，透過 portal 路由簽發或管理金鑰，再依標準 HMAC 契約呼叫託管執行環境。",
        "template.portal_overview.workspace": "工作區",
        "template.portal_overview.snapshot": "目前選取網站快照",
        "template.portal_overview.select_site": "選擇一個網站以載入摘要資料。",
        "template.portal_overview.usage": "用量",
        "template.portal_overview.usage_summary": "用量摘要",
        "template.portal_overview.waiting": "等待選取網站…",
        "template.portal_overview.entitlements": "權益",
        "template.portal_overview.commercial_state": "商業狀態",
        "template.portal_overview.billing": "帳務",
        "template.portal_overview.latest_snapshot": "最新快照",
        "template.portal_overview.verification_boundary": "驗證邊界",
        "template.portal_overview.verification_desc": "這個總覽是用於發佈驗證的受限回退工作區，不是最終客戶 Portal UI。",
        "template.portal_overview.verification_note": "標準資料仍來自 /portal/v1/*；這個頁面只是讓它能在本地 Docker 與遠端 smoke 中更快可見。",
        "template.portal_keys.keys": "金鑰",
        "template.portal_keys.current_site_keys": "目前網站金鑰",
        "template.portal_keys.start_session": "先啟動 Portal 工作階段以載入金鑰資料。",
        "template.portal_keys.last_four": "末四碼",
        "template.portal_keys.one_time_delivery": "一次性交付",
        "template.portal_keys.latest_result": "最近一次簽發 / 輪換結果",
        "template.portal_keys.no_key_issued": "目前瀏覽器工作階段中尚未簽發過金鑰。",
        "template.portal_keys.issue_key": "簽發金鑰",
        "template.portal_keys.rotate_key": "輪換金鑰",
        "template.portal_keys.expires_at": "到期時間",
        "template.portal_keys.existing_key": "現有金鑰",
        "template.portal_keys.new_label": "新標籤",
        "template.portal_keys.scopes_override": "覆寫權限範圍",
        "template.portal_keys.revoke_key": "撤銷金鑰",
        "template.portal_keys.key_to_revoke": "要撤銷的金鑰",
        "template.portal_keys.production_key": "正式環境金鑰",
        "template.portal_keys.production_key_rotated": "正式環境金鑰（已輪換）",
        "template.portal_keys.keep_scopes": "留空則保留目前 scopes",
        "template.portal_keys.select_key": "選擇一個金鑰",
        "route.portal_login_title": "Portal 登入",
        "route.portal_login_lead": "透過受限的 Portal 工作階段邊界進入該成員實際可存取的網站。受邀成員使用電子郵件一次性驗證碼登入。",
        "route.portal_home_title": "已連線網站",
        "route.portal_home_lead": "從該成員實際可存取的網站開始，然後為其中一個選取網站開啟金鑰管理。",
        "route.portal_overview_title": "Portal 總覽",
        "route.portal_overview_lead": "在一個受限的驗證工作區中查看所選網站的目前摘要、用量、權益狀態與最新帳務快照。",
        "route.portal_keys_title": "Portal 金鑰管理",
        "route.portal_keys_lead": "列出、簽發、輪換與撤銷網站金鑰，而不在瀏覽器中暴露原始營運標頭。",
    },
}

router = APIRouter(include_in_schema=False)


def _resolve_locale(request: Request) -> str:
    explicit = str(request.query_params.get("lang") or "").strip()
    if explicit in SUPPORTED_LOCALES:
        return explicit
    cookie_locale = str(request.cookies.get(COOKIE_LOCALE) or "").strip()
    if cookie_locale in SUPPORTED_LOCALES:
        return cookie_locale
    accepted = str(request.headers.get("accept-language") or "")
    lowered = accepted.lower()
    if "zh-tw" in lowered or "zh-hk" in lowered:
        return "zh-TW"
    if "zh" in lowered:
        return "zh-CN"
    return DEFAULT_LOCALE


def _translate(locale: str, key: str, **values: object) -> str:
    table = WEB_TRANSLATIONS.get(locale) or WEB_TRANSLATIONS[DEFAULT_LOCALE]
    text = table.get(key) or WEB_TRANSLATIONS[DEFAULT_LOCALE].get(key) or key
    for name, value in values.items():
        text = text.replace(f"{{{{{name}}}}}", str(value))
    return text


def _js_translations(locale: str) -> str:
    messages = {
        "common.not_selected": _translate(locale, "common.not_selected"),
        "common.site": _translate(locale, "common.site"),
        "common.account": _translate(locale, "common.account"),
        "common.role": _translate(locale, "common.role"),
        "common.status": _translate(locale, "common.status"),
        "common.action": _translate(locale, "common.action"),
        "common.label": _translate(locale, "common.label"),
        "common.actions": _translate(locale, "common.actions"),
        "common.scope": _translate(locale, "common.scope"),
        "common.active": _translate(locale, "common.active"),
        "common.inactive": _translate(locale, "common.inactive"),
        "template.portal_home.session_summary": _translate(locale, "template.portal_home.session_summary"),
        "template.portal_home.login_to_load": _translate(locale, "template.portal_home.login_to_load"),
        "template.portal_overview.select_site": _translate(locale, "template.portal_overview.select_site"),
        "template.portal_overview.waiting": _translate(locale, "template.portal_overview.waiting"),
        "template.portal_keys.start_session": _translate(locale, "template.portal_keys.start_session"),
        "template.portal_keys.no_key_issued": _translate(locale, "template.portal_keys.no_key_issued"),
        "template.portal_keys.select_key": _translate(locale, "template.portal_keys.select_key"),
        "js.portal.selected_site": _translate(locale, "common.site") + ": {{value}}",
        "js.portal.member": "Member: {{value}}" if locale == "en" else ("成员：{{value}}" if locale == "zh-CN" else "成員：{{value}}"),
        "js.portal.auth_mode": "Portal auth mode: {{value}}." if locale == "en" else ("Portal 认证模式：{{value}}。" if locale == "zh-CN" else "Portal 驗證模式：{{value}}。"),
        "js.portal.no_session": "No portal session is active in this browser." if locale == "en" else ("当前浏览器没有激活的 Portal 会话。" if locale == "zh-CN" else "目前瀏覽器沒有啟用中的 Portal 工作階段。"),
        "js.portal.issuing_verification_code": "Issuing verification code..." if locale == "en" else ("正在签发验证码..." if locale == "zh-CN" else "正在簽發驗證碼..."),
        "js.portal.verification_code_sent": "Verification code sent. Check your inbox." if locale == "en" else ("验证码已发送，请检查收件箱。" if locale == "zh-CN" else "驗證碼已寄出，請檢查收件匣。"),
        "js.portal.verification_code_redirecting": "Verification code issued. Redirecting..." if locale == "en" else ("验证码已签发，正在跳转..." if locale == "zh-CN" else "驗證碼已簽發，正在跳轉..."),
        "js.portal.email_required": "Email is required." if locale == "en" else ("必须填写邮箱。" if locale == "zh-CN" else "必須填寫電子郵件。"),
        "js.portal.login_failed": "Portal login failed." if locale == "en" else ("Portal 登录失败。" if locale == "zh-CN" else "Portal 登入失敗。"),
        "js.portal.loading_overview": "Loading site overview..." if locale == "en" else ("正在加载站点概览..." if locale == "zh-CN" else "正在載入網站總覽..."),
        "js.portal.select_site_first": "Select a site first." if locale == "en" else ("请先选择站点。" if locale == "zh-CN" else "請先選取網站。"),
        "js.portal.loaded_overview": "Loaded site overview." if locale == "en" else ("站点概览已加载。" if locale == "zh-CN" else "網站總覽已載入。"),
        "js.portal.failed_overview": "Failed to load overview." if locale == "en" else ("加载概览失败。" if locale == "zh-CN" else "載入總覽失敗。"),
        "js.portal.no_connected_sites": "No connected sites found for this member." if locale == "en" else ("没有找到该成员可访问的站点。" if locale == "zh-CN" else "找不到這位成員可存取的網站。"),
        "js.portal.open_keys": "Open keys" if locale == "en" else ("打开密钥" if locale == "zh-CN" else "開啟金鑰"),
        "js.portal.selecting_site": "Selecting site..." if locale == "en" else ("正在选择站点..." if locale == "zh-CN" else "正在選取網站..."),
        "js.portal.site_selection_failed": "Site selection failed." if locale == "en" else ("站点选择失败。" if locale == "zh-CN" else "網站選取失敗。"),
        "js.portal.request_failed": "Request failed: {{status}}" if locale == "en" else ("请求失败：{{status}}" if locale == "zh-CN" else "請求失敗：{{status}}"),
        "js.portal.loading_keys": "Loading keys..." if locale == "en" else ("正在加载密钥..." if locale == "zh-CN" else "正在載入金鑰..."),
        "js.portal.loaded_keys": "Loaded {{count}} key{{suffix}}." if locale == "en" else ("已加载 {{count}} 个密钥。" if locale == "zh-CN" else "已載入 {{count}} 個金鑰。"),
        "js.portal.failed_keys": "Failed to load keys." if locale == "en" else ("加载密钥失败。" if locale == "zh-CN" else "載入金鑰失敗。"),
        "js.portal.issuing_key": "Issuing key..." if locale == "en" else ("正在签发密钥..." if locale == "zh-CN" else "正在簽發金鑰..."),
        "js.portal.key_issued": "Key issued." if locale == "en" else ("密钥已签发。" if locale == "zh-CN" else "金鑰已簽發。"),
        "js.portal.issue_failed": "Issue failed." if locale == "en" else ("签发失败。" if locale == "zh-CN" else "簽發失敗。"),
        "js.portal.choose_key_to_rotate": "Choose a key to rotate." if locale == "en" else ("请选择要轮换的密钥。" if locale == "zh-CN" else "請選擇要輪換的金鑰。"),
        "js.portal.rotating_key": "Rotating key..." if locale == "en" else ("正在轮换密钥..." if locale == "zh-CN" else "正在輪換金鑰..."),
        "js.portal.key_rotated": "Key rotated." if locale == "en" else ("密钥已轮换。" if locale == "zh-CN" else "金鑰已輪換。"),
        "js.portal.rotate_failed": "Rotate failed." if locale == "en" else ("轮换失败。" if locale == "zh-CN" else "輪換失敗。"),
        "js.portal.choose_key_to_revoke": "Choose a key to revoke." if locale == "en" else ("请选择要撤销的密钥。" if locale == "zh-CN" else "請選擇要撤銷的金鑰。"),
        "js.portal.revoking_key": "Revoking key..." if locale == "en" else ("正在撤销密钥..." if locale == "zh-CN" else "正在撤銷金鑰..."),
        "js.portal.key_revoked": "Key revoked." if locale == "en" else ("密钥已撤销。" if locale == "zh-CN" else "金鑰已撤銷。"),
        "js.portal.revoke_failed": "Revoke failed." if locale == "en" else ("撤销失败。" if locale == "zh-CN" else "撤銷失敗。"),
        "js.portal.loading_sites": "Loading connected sites..." if locale == "en" else ("正在加载已连接站点..." if locale == "zh-CN" else "正在載入已連線網站..."),
        "js.portal.loaded_sites": "Loaded {{count}} connected site{{suffix}}." if locale == "en" else ("已加载 {{count}} 个已连接站点。" if locale == "zh-CN" else "已載入 {{count}} 個已連線網站。"),
        "js.portal.failed_sites": "Failed to load connected sites." if locale == "en" else ("加载已连接站点失败。" if locale == "zh-CN" else "載入已連線網站失敗。"),
        "js.portal.auth_not_configured": "Portal auth is not configured. Set Portal JWT or fallback static auth first." if locale == "en" else ("尚未配置 Portal 认证。请先设置 Portal JWT 或静态回退认证。" if locale == "zh-CN" else "尚未設定 Portal 驗證。請先設定 Portal JWT 或靜態備援驗證。"),
    }
    return json.dumps(messages, ensure_ascii=False)

def _base_context(request: Request, *, page_id: str, title: str, lead: str) -> dict[str, Any]:
    settings = get_cloud_services(request).settings
    locale = _resolve_locale(request)
    locale_links = []
    for item in SUPPORTED_LOCALES:
        params = dict(request.query_params)
        params["lang"] = item
        query = urlencode(params)
        locale_links.append(
            {
                "code": item,
                "label": item,
                "href": f"{request.url.path}?{query}" if query else request.url.path,
                "current": item == locale,
            }
        )
    return {
        "request": request,
        "page_id": page_id,
        "locale": locale,
        "page_title": title,
        "page_lead": lead,
        "project_name": settings.project_name,
        "t": lambda key, **values: _translate(locale, key, **values),
        "locale_links": locale_links,
        "site_js_translations": _js_translations(locale),
        "portal_enabled": _portal_auth_mode(request) != "disabled",
        "portal_auth_mode": _portal_auth_mode(request),
        "portal_email_delivery_mode": (
            "smtp" if get_cloud_services(request).portal_email_sender is not None else "stub"
        ),
        "nav_items": [
            {"href": "/", "label": _translate(locale, "nav.home")},
            {"href": "/features", "label": _translate(locale, "nav.features")},
            {"href": "/getting-started", "label": _translate(locale, "nav.getting_started")},
            {"href": "/portal/login", "label": _translate(locale, "nav.portal")},
        ],
    }


def _admin_has_session(request: Request) -> bool:
    try:
        _current_admin_session(request)
    except PortalBearerTokenError:
        return False
    return True


def _resolve_admin_session_secret(request: Request) -> str:
    settings = get_cloud_services(request).settings
    secret = str(settings.admin_session_secret or "").strip()
    if not secret:
        environment = str(settings.environment or "").strip().lower()
        if environment == "test":
            secret = str(settings.internal_auth_token or "").strip()
        elif environment == "development" and settings.allow_dev_admin_internal_token_fallback:
            secret = str(settings.internal_auth_token or "").strip()
    if not secret:
        raise PortalBearerTokenError(
            503,
            "auth.admin_not_configured",
            "admin session secret is not configured",
        )
    return secret


def _build_admin_session_token(
    request: Request,
    *,
    platform_admin_ref: str,
    role: str,
    auth_mode: str,
) -> str:
    settings = get_cloud_services(request).settings
    now = datetime.now(UTC)
    expires_at = now.timestamp() + max(60, int(settings.admin_session_ttl_seconds or 0))
    payload = {
        "sub": platform_admin_ref,
        "role": role,
        "auth_mode": auth_mode,
        "iat": int(now.timestamp()),
        "exp": int(expires_at),
    }
    return jwt.encode(
        payload,
        _resolve_admin_session_secret(request),
        algorithm=ADMIN_SESSION_ALGORITHM,
    )


def _resolve_admin_session_cookie_candidates(request: Request) -> list[str]:
    candidates: list[str] = []
    parsed_cookie = str(request.cookies.get(COOKIE_ADMIN_TOKEN, "") or "").strip()
    if parsed_cookie:
        candidates.append(parsed_cookie)

    raw_cookie_header = str(request.headers.get("cookie") or "").strip()
    if not raw_cookie_header:
        return candidates

    for chunk in raw_cookie_header.split(";"):
        name, separator, value = chunk.partition("=")
        if separator != "=":
            continue
        if name.strip() != COOKIE_ADMIN_TOKEN:
            continue
        token = value.strip()
        if token and token not in candidates:
            candidates.append(token)
    return candidates


def _current_admin_session(request: Request) -> dict[str, Any]:
    tokens = _resolve_admin_session_cookie_candidates(request)
    if not tokens:
        raise PortalBearerTokenError(
            401,
            "auth.admin_session_required",
            "admin session is required",
        )

    claims: dict[str, Any] | None = None
    decode_error: InvalidTokenError | None = None
    for token in tokens:
        try:
            claims = jwt.decode(
                token,
                _resolve_admin_session_secret(request),
                algorithms=[ADMIN_SESSION_ALGORITHM],
            )
            break
        except InvalidTokenError as error:
            decode_error = error
            continue

    if claims is None:
        raise PortalBearerTokenError(
            401,
            "auth.admin_session_invalid",
            "admin session is invalid",
        ) from decode_error

    platform_admin_ref = str(claims.get("sub") or "").strip()
    auth_mode = str(claims.get("auth_mode") or "admin_bootstrap_token").strip()
    bootstrap_admin_ref = str(
        get_cloud_services(request).settings.admin_bootstrap_admin_ref or "platform:internal_root"
    ).strip()
    allow_bootstrap = auth_mode in {"admin_bootstrap_token", "dev_internal_autologin"} and (
        platform_admin_ref in {bootstrap_admin_ref, "platform:internal_root"}
    )
    try:
        identity = _get_commercial_service(request).resolve_platform_admin_identity(
            admin_ref=platform_admin_ref,
            bootstrap_role=PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
            allow_bootstrap=allow_bootstrap,
        )
    except CommercialServiceError as error:
        raise PortalBearerTokenError(
            401,
            "auth.admin_session_revoked",
            "admin session is no longer valid",
        ) from error
    identity_metadata = identity.get("metadata")
    revocable = not bool(identity_metadata.get("bootstrap")) if isinstance(
        identity_metadata, dict
    ) else True

    issued_at = ""
    expires_at = ""
    if claims.get("iat"):
        issued_at = (
            datetime.fromtimestamp(int(claims["iat"]), tz=UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
    if claims.get("exp"):
        expires_at = (
            datetime.fromtimestamp(int(claims["exp"]), tz=UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
    return {
        "platform_admin_ref": str(identity.get("admin_ref") or platform_admin_ref),
        "identity_type": IDENTITY_TYPE_PLATFORM_ADMIN,
        "role": str(identity.get("role") or claims.get("role") or "").strip(),
        "capabilities": dict(
            identity.get("capabilities")
            if isinstance(identity.get("capabilities"), dict)
            else _platform_capability_flags(
                str(identity.get("role") or claims.get("role") or "").strip()
            )
        ),
        "auth_mode": auth_mode,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "transport": "cookie",
        "revocable": revocable,
    }


def _require_admin_session(request: Request) -> RedirectResponse | None:
    if _admin_has_session(request):
        return None
    locale = _resolve_locale(request)
    params: dict[str, str] = {}
    if locale:
        params["lang"] = locale
    params["redirect"] = _sanitize_console_return_to(
        str(request.url.path) + (f"?{request.url.query}" if request.url.query else ""),
        fallback="/admin",
    )
    query = urlencode(params) if params else ""
    target = f"/admin/login?{query}" if query else "/admin/login"
    return RedirectResponse(url=target, status_code=303)


def _set_admin_session_cookie(response: Response, request: Request, token: str) -> None:
    secure = portal_cookie_secure(request)
    ttl_seconds = max(60, int(get_cloud_services(request).settings.admin_session_ttl_seconds or 0))
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    # Clear any legacy admin-path cookie so browsers stop sending duplicate
    # admin session cookies with different paths after a fresh login.
    response.delete_cookie(COOKIE_ADMIN_TOKEN, path="/admin")
    response.set_cookie(
        COOKIE_ADMIN_TOKEN,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=ttl_seconds,
        expires=expires_at,
    )


def _clear_admin_session_cookie(response: RedirectResponse) -> None:
    response.delete_cookie(COOKIE_ADMIN_TOKEN, path="/")
    response.delete_cookie(COOKIE_ADMIN_TOKEN, path="/admin")


def _admin_session_json_error(
    request: Request,
    *,
    status_code: int,
    error_code: str,
    message: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=build_envelope(
            status="error",
            error_code=error_code,
            message=message,
            revision="m6",
        ),
    )


def _require_admin_session_json(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        return _current_admin_session(request)
    except PortalBearerTokenError as error:
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )


def _require_admin_capability_json(
    request: Request,
    *,
    capability: str,
) -> dict[str, Any] | JSONResponse:
    session = _require_admin_session_json(request)
    if isinstance(session, JSONResponse):
        return session
    try:
        assert_platform_admin_capability(
            role=str(session.get("role") or ""),
            capability=capability,
            error_code="auth.admin_role_forbidden",
            message="admin session is not allowed for this action",
        )
    except CommercialServiceError as error:
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    return session


def _require_same_origin_json_write(request: Request) -> JSONResponse | None:
    try:
        enforce_browser_same_origin(request)
        enforce_json_request(request)
    except PortalBearerTokenError as error:
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    return None


def _parse_optional_datetime(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _build_platform_admin_audit_context(request: Request, platform_admin_ref: str):
    audit_context = _build_audit_context(request)
    audit_context.actor_kind = "platform_admin"
    audit_context.actor_ref = platform_admin_ref
    return audit_context


def _normalize_admin_email(value: object) -> str:
    return str(value or "").strip().lower()


def _admin_email_is_valid(email: str) -> bool:
    local_part, separator, domain = email.partition("@")
    return bool(separator and local_part and domain and "." in domain and " " not in email)


def _issue_admin_portal_invite_notice(
    request: Request,
    *,
    member_ref: str = "",
    email: str,
    locale: str = "",
) -> dict[str, object]:
    services = get_cloud_services(request)
    email_sender = services.portal_email_sender
    if email_sender is None:
        raise PortalBearerTokenError(
            503,
            "portal.email_delivery_unavailable",
            "portal email delivery is not configured",
        )

    login_member_ref = member_ref.strip()
    resolved_email = email
    if not login_member_ref:
        login = _get_commercial_service(request).resolve_portal_member_login(email=email)
        login_member_ref = str(login.get("member_ref") or "")
        resolved_email = str(login.get("email") or email)
    portal_url = _build_frontend_public_url(request, "/portal/login")
    delivery = "email"
    try:
        email_sender.send_invite_notice(
            recipient_email=resolved_email,
            member_ref=login_member_ref,
            portal_url=portal_url,
            project_name=services.settings.project_name,
            locale=locale,
        )
    except PortalEmailDeliveryError as error:
        raise PortalBearerTokenError(
            502,
            "portal.email_delivery_failed",
            str(error),
        ) from error
    return {
        "delivery": delivery,
        "member_ref": login_member_ref,
        "email": resolved_email,
        "portal_url": portal_url,
    }


async def _json_body(request: Request) -> dict[str, Any]:
    payload = await request.json()
    return payload if isinstance(payload, dict) else {}


async def _request_payload(request: Request) -> dict[str, Any]:
    content_type = str(request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        return await _json_body(request)
    if "application/x-www-form-urlencoded" in content_type:
        body = (await request.body()).decode("utf-8", errors="ignore")
        return {key: value for key, value in parse_qsl(body, keep_blank_values=True)}
    if "multipart/form-data" in content_type:
        form = await request.form()
        return {str(key): value for key, value in form.items()}
    return {}


def _request_wants_html_redirect(request: Request) -> bool:
    content_type = str(request.headers.get("content-type") or "").lower()
    return (
        "application/x-www-form-urlencoded" in content_type
        or "multipart/form-data" in content_type
    )


def _sanitize_admin_return_to(value: object, *, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        return fallback
    if not parsed.path.startswith("/admin"):
        return fallback
    return urlunsplit(("", "", parsed.path, parsed.query, ""))


def _sanitize_console_return_to(value: object, *, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        return fallback
    if not parsed.path.startswith("/admin"):
        return fallback
    return urlunsplit(("", "", parsed.path, parsed.query, ""))


def _append_query_params(url: str, **params: object) -> str:
    parsed = urlsplit(url)
    items = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)]
    for key, value in params.items():
        if value is None:
            continue
        raw = str(value).strip()
        if not raw:
            continue
        items.append((key, raw))
    return urlunsplit(("", "", parsed.path, urlencode(items), ""))


def _build_admin_login_url(
    request: Request,
    *,
    error_code: str | None = None,
    redirect_to: str | None = None,
) -> str:
    params: dict[str, str] = {}
    locale = _resolve_locale(request)
    if locale:
        params["lang"] = locale
    if error_code:
        params["error"] = error_code
    target = _sanitize_console_return_to(redirect_to, fallback="/admin")
    if target:
        params["redirect"] = target
    query = urlencode(params) if params else ""
    return f"/admin/login?{query}" if query else "/admin/login"


def _build_console_redirect_response(
    request: Request,
    *,
    fallback: str,
    redirect_to: object = None,
) -> RedirectResponse:
    target = _sanitize_console_return_to(redirect_to, fallback=fallback)
    return RedirectResponse(url=target, status_code=303)


def _build_frontend_public_url(request: Request, target_path: str) -> str:
    settings = get_cloud_services(request).settings
    base_url = str(settings.portal_public_base_url or "").strip().rstrip("/")
    if not base_url:
        base_url = str(request.base_url).rstrip("/")
    query = str(request.url.query or "").strip()
    path = target_path if target_path.startswith("/") else f"/{target_path}"
    return f"{base_url}{path}{f'?{query}' if query else ''}"


def _redirect_frontend_public(request: Request, target_path: str) -> RedirectResponse:
    return RedirectResponse(url=_build_frontend_public_url(request, target_path), status_code=307)


def _parse_scopes(value: object) -> list[str]:
    raw = str(value or "")
    values = [item.strip() for item in raw.replace("\n", ",").split(",")]
    scopes = [item for item in values if item]
    return scopes or list(DEFAULT_PORTAL_SCOPES)


@router.get("/")
async def web_home(request: Request) -> Any:
    return _redirect_frontend_public(request, "/")


@router.get("/features")
async def web_features(request: Request) -> Any:
    return _redirect_frontend_public(request, "/features")


@router.get("/getting-started")
async def web_getting_started(request: Request) -> Any:
    return _redirect_frontend_public(request, "/getting-started")


@router.post("/admin/auth/bootstrap")
async def web_admin_auth_bootstrap(request: Request) -> Any:
    payload = await _request_payload(request)
    wants_redirect = _request_wants_html_redirect(request)
    try:
        enforce_browser_same_origin(request)
    except PortalBearerTokenError as error:
        redirect_to = payload.get("redirect") or request.query_params.get("redirect")
        if wants_redirect:
            return RedirectResponse(
                url=_build_admin_login_url(
                    request,
                    error_code=error.error_code,
                    redirect_to=redirect_to,
                ),
                status_code=303,
            )
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    token = str(payload.get("token") or "").strip()
    admin_ref = str(payload.get("admin_ref") or "").strip()
    redirect_to = payload.get("redirect") or request.query_params.get("redirect")
    if not token:
        if wants_redirect:
            return RedirectResponse(
                url=_build_admin_login_url(
                    request,
                    error_code="auth.admin_bootstrap_token_required",
                    redirect_to=redirect_to,
                ),
                status_code=303,
            )
        return _admin_session_json_error(
            request,
            status_code=400,
            error_code="auth.admin_bootstrap_token_required",
            message="missing admin bootstrap token",
        )
    try:
        identity = resolve_admin_login_identity(
            request,
            token=token,
            admin_ref=admin_ref,
        )
        session = ResolvedAdminSession.from_identity(
            identity,
            auth_mode="admin_bootstrap_token",
            fallback_admin_ref=admin_ref
            or str(
                get_cloud_services(request).settings.admin_bootstrap_admin_ref
                or "platform:internal_root"
            ),
        )
    except PortalBearerTokenError as error:
        if wants_redirect:
            return RedirectResponse(
                url=_build_admin_login_url(
                    request,
                    error_code=error.error_code,
                    redirect_to=redirect_to,
                ),
                status_code=303,
            )
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    except CommercialServiceError as error:
        if wants_redirect:
            return RedirectResponse(
                url=_build_admin_login_url(
                    request,
                    error_code=error.error_code,
                    redirect_to=redirect_to,
                ),
                status_code=303,
            )
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    try:
        response = _build_console_redirect_response(
            request,
            fallback="/admin",
            redirect_to=redirect_to,
        )
        _issue_admin_session_cookie(request, response, session=session)
        return response
    except PortalBearerTokenError as error:
        if wants_redirect:
            return RedirectResponse(
                url=_build_admin_login_url(
                    request,
                    error_code=error.error_code,
                    redirect_to=redirect_to,
                ),
                status_code=303,
            )
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )


@router.get("/admin")
async def web_admin_overview(request: Request) -> Any:
    redirect = _require_admin_session(request)
    if redirect is not None:
        return redirect
    return _redirect_frontend_public(request, "/admin")


@router.get("/admin/accounts")
async def web_admin_accounts_page(request: Request) -> Any:
    redirect = _require_admin_session(request)
    if redirect is not None:
        return redirect
    return _redirect_frontend_public(request, "/admin/accounts")


@router.get("/admin/accounts/{account_id}")
async def web_admin_account_page(request: Request, account_id: str) -> Any:
    redirect = _require_admin_session(request)
    if redirect is not None:
        return redirect
    return _redirect_frontend_public(request, f"/admin/accounts/{account_id}")


@router.get("/admin/sites")
async def web_admin_sites_page(request: Request) -> Any:
    redirect = _require_admin_session(request)
    if redirect is not None:
        return redirect
    return _redirect_frontend_public(request, "/admin/sites")


@router.get("/admin/sites/{site_id}")
async def web_admin_site_page(request: Request, site_id: str) -> Any:
    redirect = _require_admin_session(request)
    if redirect is not None:
        return redirect
    return _redirect_frontend_public(request, f"/admin/sites/{site_id}")


@router.get("/admin/subscriptions")
async def web_admin_subscriptions_page(request: Request) -> Any:
    redirect = _require_admin_session(request)
    if redirect is not None:
        return redirect
    return _redirect_frontend_public(request, "/admin/subscriptions")


@router.get("/admin/subscriptions/{subscription_id}")
async def web_admin_subscription_page(request: Request, subscription_id: str) -> Any:
    redirect = _require_admin_session(request)
    if redirect is not None:
        return redirect
    return _redirect_frontend_public(request, f"/admin/subscriptions/{subscription_id}")


@router.get("/admin/impersonations")
async def web_admin_impersonations_page(request: Request) -> Any:
    redirect = _require_admin_session(request)
    if redirect is not None:
        return redirect
    return _redirect_frontend_public(request, "/admin/impersonations")


@router.get("/admin/plans")
async def web_admin_plans_page(request: Request) -> Any:
    redirect = _require_admin_session(request)
    if redirect is not None:
        return redirect
    return _redirect_frontend_public(request, "/admin/plans")


def _issue_admin_session_cookie(
    request: Request,
    response: Response,
    *,
    session: ResolvedAdminSession,
) -> None:
    _set_admin_session_cookie(
        response,
        request,
        _build_admin_session_token(
            request,
            platform_admin_ref=session.platform_admin_ref,
            role=session.role,
            auth_mode=session.auth_mode,
        ),
    )


@router.get("/admin/session")
async def web_admin_session(request: Request) -> Any:
    session = _require_admin_session_json(request)
    if isinstance(session, JSONResponse):
        return session
    return build_envelope(
        status="ok",
        message="admin session loaded",
        data={
            **session,
            "impersonation": _current_portal_impersonation(request),
        },
        revision="m6",
    )


async def web_admin_start_impersonation(request: Request) -> Any:
    session = _require_admin_session_json(request)
    if isinstance(session, JSONResponse):
        return session
    payload = await _request_payload(request)
    wants_redirect = _request_wants_html_redirect(request)
    try:
        enforce_browser_same_origin(request)
    except PortalBearerTokenError as error:
        return_to = _sanitize_admin_return_to(payload.get("return_to"), fallback="/admin/impersonations")
        if wants_redirect:
            return RedirectResponse(
                url=_append_query_params(return_to, admin_error=error.message),
                status_code=303,
            )
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    member_ref = str(payload.get("member_ref") or "").strip()
    site_id = str(payload.get("site_id") or "").strip()
    reason_code = str(payload.get("reason_code") or "").strip() or "support_debug"
    reason_text = str(payload.get("reason_text") or "").strip()
    return_to = _sanitize_admin_return_to(payload.get("return_to"), fallback="/admin/impersonations")
    if not member_ref or not site_id:
        if wants_redirect:
            return RedirectResponse(
                url=_append_query_params(
                    return_to,
                    admin_error="member_ref and site_id are required",
                    member_ref=member_ref,
                    site_id=site_id,
                    reason_code=reason_code,
                    reason_text=reason_text,
                ),
                status_code=303,
            )
        return _admin_session_json_error(
            request,
            status_code=400,
            error_code="auth.admin_impersonation_target_required",
            message="member_ref and site_id are required",
        )
    try:
        impersonation_session = start_platform_impersonation_session(
            request,
            platform_admin_ref=str(session.get("platform_admin_ref") or ""),
            platform_role=str(session.get("role") or ""),
            member_ref=member_ref,
            site_id=site_id,
            reason_code=reason_code,
            reason_text=reason_text,
            audit_context=_build_platform_admin_audit_context(
                request,
                str(session.get("platform_admin_ref") or ""),
            ),
        )
    except CommercialServiceError as error:
        if wants_redirect:
            return RedirectResponse(
                url=_append_query_params(
                    return_to,
                    admin_error=error.message,
                    member_ref=member_ref,
                    site_id=site_id,
                    reason_code=reason_code,
                    reason_text=reason_text,
                ),
                status_code=303,
            )
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    if wants_redirect:
        response: JSONResponse | RedirectResponse = RedirectResponse(
            url=_append_query_params(
                return_to,
                admin_notice=f"Impersonation started for {member_ref} on {site_id}",
            ),
            status_code=303,
        )
    else:
        response = JSONResponse(
            status_code=200,
            content=build_envelope(
                status="ok",
                message="platform impersonation started",
                data={
                    "impersonation": impersonation_session.impersonation,
                    "portal_session": impersonation_session.portal_session,
                },
                revision="m6",
            ),
        )
    _set_browser_session_cookies(
        request,
        response,
        member_ref=impersonation_session.member_ref,
        site_id=impersonation_session.site_id,
    )
    _set_portal_impersonation_cookies(
        request,
        response,
        impersonation_id=str(impersonation_session.impersonation.get("impersonation_id") or ""),
        platform_admin_ref=str(impersonation_session.impersonation.get("platform_admin_ref") or ""),
        platform_role=str(impersonation_session.impersonation.get("platform_role") or ""),
        read_only=bool(impersonation_session.impersonation.get("read_only", True)),
        expires_at=impersonation_session.expires_at,
        max_age=impersonation_session.max_age,
    )
    return response


@router.post("/admin/impersonations")
async def web_admin_start_impersonation(request: Request) -> Any:
    return await web_admin_start_impersonation(request)


async def web_admin_end_impersonation(request: Request, impersonation_id: str) -> Any:
    session = _require_admin_session_json(request)
    if isinstance(session, JSONResponse):
        return session
    payload = await _request_payload(request)
    wants_redirect = _request_wants_html_redirect(request)
    try:
        enforce_browser_same_origin(request)
    except PortalBearerTokenError as error:
        return_to = _sanitize_admin_return_to(payload.get("return_to"), fallback="/admin")
        if wants_redirect:
            return RedirectResponse(
                url=_append_query_params(return_to, admin_error=error.message),
                status_code=303,
            )
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    ended_reason = str(payload.get("ended_reason") or "").strip()
    return_to = _sanitize_admin_return_to(payload.get("return_to"), fallback="/admin")
    try:
        result = end_platform_impersonation(
            request,
            impersonation_id=impersonation_id,
            platform_admin_ref=str(session.get("platform_admin_ref") or ""),
            ended_reason=ended_reason,
            audit_context=_build_platform_admin_audit_context(
                request,
                str(session.get("platform_admin_ref") or ""),
            ),
        )
    except CommercialServiceError as error:
        if wants_redirect:
            return RedirectResponse(
                url=_append_query_params(return_to, admin_error=error.message),
                status_code=303,
            )
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    if wants_redirect:
        response = RedirectResponse(
            url=_append_query_params(
                return_to,
                admin_notice=f"Impersonation ended: {impersonation_id}",
            ),
            status_code=303,
        )
    else:
        response = JSONResponse(
            status_code=200,
            content=build_envelope(
                status="ok",
                message="platform impersonation ended",
                data=result,
                revision="m6",
            ),
        )
    _clear_portal_impersonation_cookies(response)
    _clear_browser_session_cookies(response)
    return response


@router.post("/admin/impersonations/{impersonation_id}/end")
async def web_admin_end_impersonation(request: Request, impersonation_id: str) -> Any:
    return await web_admin_end_impersonation(request, impersonation_id)


@router.get("/admin/logout")
async def web_admin_logout() -> RedirectResponse:
    response = RedirectResponse(url="/admin/login", status_code=303)
    _clear_admin_session_cookie(response)
    _clear_portal_impersonation_cookies(response)
    _clear_browser_session_cookies(response)
    return response


@router.post("/admin/accounts/{account_id}/invite-member")
async def web_admin_invite_member(request: Request, account_id: str) -> Any:
    write_guard = _require_same_origin_json_write(request)
    if write_guard is not None:
        return write_guard
    session = _require_admin_capability_json(
        request,
        capability="can_manage_accounts",
    )
    if isinstance(session, JSONResponse):
        return session

    payload = await _request_payload(request)
    email = _normalize_admin_email(payload.get("email"))
    locale = resolve_portal_email_locale(request, str(payload.get("locale") or ""))
    if not email:
        return _admin_session_json_error(
            request,
            status_code=400,
            error_code="validation.email_required",
            message="email is required",
        )
    if not _admin_email_is_valid(email):
        return _admin_session_json_error(
            request,
            status_code=400,
            error_code="validation.invalid_email",
            message="invalid email format",
        )

    return invite_admin_account_member(
        request=request,
        json_error=lambda current_request, status_code, error_code, message: _admin_session_json_error(
            current_request,
            status_code=status_code,
            error_code=error_code,
            message=message,
        ),
        commercial_service=_get_commercial_service(request),
        audit_context=_build_platform_admin_audit_context(
            request,
            str(session.get("platform_admin_ref") or ""),
        ),
        account_id=account_id,
        email=email,
        role=ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN,
        locale=locale,
        platform_role=str(session.get("role") or ""),
        send_invite=lambda invite_member_ref, invite_email, invite_locale: _issue_admin_portal_invite_notice(
            request,
            member_ref=invite_member_ref,
            email=invite_email,
            locale=invite_locale,
        ),
    )


@router.post("/admin/sites/{site_id}/activate")
async def web_admin_activate_site(
    request: Request,
    site_id: str,
) -> Any:
    write_guard = _require_same_origin_json_write(request)
    if write_guard is not None:
        return write_guard
    session = _require_admin_capability_json(
        request,
        capability="can_manage_accounts",
    )
    if isinstance(session, JSONResponse):
        return session

    try:
        result = _get_commercial_service(request).activate_site(
            site_id,
            audit_context=_build_platform_admin_audit_context(
                request,
                str(session.get("platform_admin_ref") or ""),
            ),
        )
    except CommercialServiceError as error:
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    return build_envelope(
        status="ok",
        message="site activated",
        data=result,
        revision="m6",
    )


@router.post("/admin/plans")
async def web_admin_upsert_plan(
    request: Request,
    payload: PlanPayload,
) -> Any:
    write_guard = _require_same_origin_json_write(request)
    if write_guard is not None:
        return write_guard
    session = _require_admin_capability_json(
        request,
        capability="can_manage_accounts",
    )
    if isinstance(session, JSONResponse):
        return session

    try:
        result = _get_commercial_service(request).upsert_plan(
            plan_id=payload.plan_id,
            name=payload.name,
            status=payload.status,
            description=payload.description,
            metadata_json=payload.metadata,
            audit_context=_build_platform_admin_audit_context(
                request,
                str(session.get("platform_admin_ref") or ""),
            ),
        )
    except CommercialServiceError as error:
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    return build_envelope(status="ok", message="plan saved", data=result, revision="m6")


@router.post("/admin/plans/{plan_id}/versions")
async def web_admin_publish_plan_version(
    request: Request,
    plan_id: str,
    payload: PlanVersionPayload,
) -> Any:
    write_guard = _require_same_origin_json_write(request)
    if write_guard is not None:
        return write_guard
    session = _require_admin_capability_json(
        request,
        capability="can_manage_accounts",
    )
    if isinstance(session, JSONResponse):
        return session

    try:
        result = _get_commercial_service(request).publish_plan_version(
            plan_id=plan_id,
            plan_version_id=payload.plan_version_id,
            version_label=payload.version_label,
            status=payload.status,
            currency=payload.currency,
            entitlements_json=payload.entitlements,
            budgets_json=payload.budgets,
            concurrency_json=payload.concurrency,
            policy_json=payload.policy,
            metadata_json=payload.metadata,
            audit_context=_build_platform_admin_audit_context(
                request,
                str(session.get("platform_admin_ref") or ""),
            ),
        )
    except CommercialServiceError as error:
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    return build_envelope(
        status="ok",
        message="plan version published",
        data=result,
        revision="m6",
    )


@router.post("/admin/topup-packs/{pack_id}")
async def web_admin_update_topup_pack(
    request: Request,
    pack_id: str,
    payload: TopUpPackPayload,
) -> Any:
    write_guard = _require_same_origin_json_write(request)
    if write_guard is not None:
        return write_guard
    session = _require_admin_capability_json(
        request,
        capability="can_manage_accounts",
    )
    if isinstance(session, JSONResponse):
        return session

    try:
        result = _get_commercial_service(request).update_operator_managed_points_pack(
            pack_id=pack_id,
            label=payload.label,
            points_label=payload.points_label,
            runs_increment=payload.runs_increment,
            tokens_increment=payload.tokens_increment,
            cost_increment=payload.cost_increment,
            operator_note=payload.operator_note,
            recommended_for_tiers=payload.recommended_for_tiers,
            display_order=payload.display_order,
            active=payload.active,
            audit_context=_build_platform_admin_audit_context(
                request,
                str(session.get("platform_admin_ref") or ""),
            ),
        )
    except CommercialServiceError as error:
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    return build_envelope(
        status="ok",
        message="top-up pack updated",
        data=result,
        revision="m6",
    )


@router.post("/admin/subscriptions/{subscription_id}/topup")
async def web_admin_subscription_topup(
    request: Request,
    subscription_id: str,
    payload: SubscriptionTopUpPayload,
) -> Any:
    write_guard = _require_same_origin_json_write(request)
    if write_guard is not None:
        return write_guard
    session = _require_admin_capability_json(
        request,
        capability="can_manage_accounts",
    )
    if isinstance(session, JSONResponse):
        return session

    try:
        result = _get_commercial_service(request).apply_operator_managed_subscription_topup(
            subscription_id=subscription_id,
            pack_id=payload.pack_id,
            runs_increment=payload.runs_increment,
            tokens_increment=payload.tokens_increment,
            cost_increment=payload.cost_increment,
            reason=payload.reason,
            note=payload.note,
            target_period_start_at=payload.target_period_start_at,
            target_period_end_at=payload.target_period_end_at,
            audit_context=_build_platform_admin_audit_context(
                request,
                str(session.get("platform_admin_ref") or ""),
            ),
        )
    except CommercialServiceError as error:
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    return build_envelope(
        status="ok",
        message="subscription top-up applied",
        data=result,
        revision="m6",
    )


@router.post("/admin/subscriptions/{subscription_id}/billing-snapshots/rebuild")
async def web_admin_subscription_billing_snapshot_rebuild(
    request: Request,
    subscription_id: str,
) -> Any:
    write_guard = _require_same_origin_json_write(request)
    if write_guard is not None:
        return write_guard
    session = _require_admin_capability_json(
        request,
        capability="can_manage_accounts",
    )
    if isinstance(session, JSONResponse):
        return session

    try:
        result = _get_commercial_service(request).rebuild_subscription_billing_snapshots(
            subscription_id,
            audit_context=_build_platform_admin_audit_context(
                request,
                str(session.get("platform_admin_ref") or ""),
            ),
        )
    except CommercialServiceError as error:
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    return build_envelope(
        status="ok",
        message="subscription billing snapshots rebuilt",
        data=result,
        revision="m6",
    )


@router.post("/admin/accounts/{account_id}/members/{member_ref:path}/resend-invite")
async def web_admin_resend_member_invite(
    request: Request,
    account_id: str,
    member_ref: str,
) -> Any:
    write_guard = _require_same_origin_json_write(request)
    if write_guard is not None:
        return write_guard
    session = _require_admin_capability_json(
        request,
        capability="can_manage_accounts",
    )
    if isinstance(session, JSONResponse):
        return session

    return resend_admin_account_member_invite(
        request=request,
        json_error=lambda current_request, status_code, error_code, message: _admin_session_json_error(
            current_request,
            status_code=status_code,
            error_code=error_code,
            message=message,
        ),
        commercial_service=_get_commercial_service(request),
        audit_context=_build_platform_admin_audit_context(
            request,
            str(session.get("platform_admin_ref") or ""),
        ),
        account_id=account_id,
        member_ref=member_ref,
        locale=resolve_portal_email_locale(request, ""),
        platform_role=str(session.get("role") or ""),
        send_invite=lambda invite_member_ref, invite_email, invite_locale: _issue_admin_portal_invite_notice(
            request,
            member_ref=invite_member_ref,
            email=invite_email,
            locale=invite_locale,
        ),
    )


@router.post("/admin/accounts/{account_id}/members/{member_ref:path}/disable")
async def web_admin_disable_member(
    request: Request,
    account_id: str,
    member_ref: str,
) -> Any:
    write_guard = _require_same_origin_json_write(request)
    if write_guard is not None:
        return write_guard
    session = _require_admin_capability_json(
        request,
        capability="can_manage_accounts",
    )
    if isinstance(session, JSONResponse):
        return session

    return disable_admin_account_member(
        request=request,
        json_error=lambda current_request, status_code, error_code, message: _admin_session_json_error(
            current_request,
            status_code=status_code,
            error_code=error_code,
            message=message,
        ),
        commercial_service=_get_commercial_service(request),
        audit_context=_build_platform_admin_audit_context(
            request,
            str(session.get("platform_admin_ref") or ""),
        ),
        account_id=account_id,
        member_ref=member_ref,
        platform_role=str(session.get("role") or ""),
    )


@router.post("/admin/accounts/{account_id}/members/{member_ref:path}/enable")
async def web_admin_enable_member(
    request: Request,
    account_id: str,
    member_ref: str,
) -> Any:
    write_guard = _require_same_origin_json_write(request)
    if write_guard is not None:
        return write_guard
    session = _require_admin_capability_json(
        request,
        capability="can_manage_accounts",
    )
    if isinstance(session, JSONResponse):
        return session

    return enable_admin_account_member(
        request=request,
        json_error=lambda current_request, status_code, error_code, message: _admin_session_json_error(
            current_request,
            status_code=status_code,
            error_code=error_code,
            message=message,
        ),
        commercial_service=_get_commercial_service(request),
        audit_context=_build_platform_admin_audit_context(
            request,
            str(session.get("platform_admin_ref") or ""),
        ),
        account_id=account_id,
        member_ref=member_ref,
        platform_role=str(session.get("role") or ""),
    )


@router.post("/admin/providers/{connection_id}")
async def web_admin_provider_connection_upsert(
    request: Request,
    connection_id: str,
) -> Any:
    write_guard = _require_same_origin_json_write(request)
    if write_guard is not None:
        return write_guard
    session = _require_admin_capability_json(
        request,
        capability="can_manage_catalog",
    )
    if isinstance(session, JSONResponse):
        return session

    payload = ProviderConnectionPayload.model_validate(await _request_payload(request))
    if connection_id != payload.connection_id:
        return _admin_session_json_error(
            request,
            status_code=400,
            error_code="admin.provider_connection_invalid",
            message="connection_id path and payload must match",
        )

    return upsert_admin_provider_connection(
        request=request,
        json_error=lambda current_request, status_code, error_code, message: _admin_session_json_error(
            current_request,
            status_code=status_code,
            error_code=error_code,
            message=message,
        ),
        catalog_service=_get_catalog_service(request),
        commercial_service=_get_commercial_service(request),
        audit_context=_build_platform_admin_audit_context(
            request,
            str(session.get("platform_admin_ref") or ""),
        ),
        connection_id=payload.connection_id,
        provider_type=payload.provider_type,
        source_role=payload.source_role,
        display_name=payload.display_name,
        enabled=payload.enabled,
        base_url=payload.base_url,
        config=payload.config,
        api_key=payload.api_key,
    )


@router.post("/admin/providers/{connection_id}/test")
async def web_admin_provider_connection_test(
    request: Request,
    connection_id: str,
) -> Any:
    write_guard = _require_same_origin_json_write(request)
    if write_guard is not None:
        return write_guard
    session = _require_admin_capability_json(
        request,
        capability="can_manage_catalog",
    )
    if isinstance(session, JSONResponse):
        return session

    return test_admin_provider_connection(
        request=request,
        json_error=lambda current_request, status_code, error_code, message: _admin_session_json_error(
            current_request,
            status_code=status_code,
            error_code=error_code,
            message=message,
        ),
        catalog_service=_get_catalog_service(request),
        commercial_service=_get_commercial_service(request),
        audit_context=_build_platform_admin_audit_context(
            request,
            str(session.get("platform_admin_ref") or ""),
        ),
        connection_id=connection_id,
    )


@router.post("/admin/providers/{connection_id}/sync")
async def web_admin_provider_connection_sync(
    request: Request,
    connection_id: str,
) -> Any:
    write_guard = _require_same_origin_json_write(request)
    if write_guard is not None:
        return write_guard
    session = _require_admin_capability_json(
        request,
        capability="can_manage_catalog",
    )
    if isinstance(session, JSONResponse):
        return session

    return sync_admin_provider_connection_catalog(
        request=request,
        json_error=lambda current_request, status_code, error_code, message: _admin_session_json_error(
            current_request,
            status_code=status_code,
            error_code=error_code,
            message=message,
        ),
        catalog_service=_get_catalog_service(request),
        commercial_service=_get_commercial_service(request),
        audit_context=_build_platform_admin_audit_context(
            request,
            str(session.get("platform_admin_ref") or ""),
        ),
        connection_id=connection_id,
    )


@router.post("/admin/models/{model_id:path}/annotation")
async def web_admin_model_annotation(
    request: Request,
    model_id: str,
) -> Any:
    write_guard = _require_same_origin_json_write(request)
    if write_guard is not None:
        return write_guard
    session = _require_admin_capability_json(
        request,
        capability="can_manage_catalog",
    )
    if isinstance(session, JSONResponse):
        return session

    payload = CatalogModelAnnotationPayload.model_validate(await _request_payload(request))
    return save_admin_model_annotation(
        catalog_service=_get_catalog_service(request),
        commercial_service=_get_commercial_service(request),
        audit_context=_build_platform_admin_audit_context(
            request,
            str(session.get("platform_admin_ref") or ""),
        ),
        model_id=model_id,
        recommended=payload.recommended,
        cost_tier=payload.cost_tier,
        visibility=payload.visibility,
        badges=payload.badges,
        operator_notes=payload.operator_notes,
    )


@router.post("/admin/recognition/{provider_id}/{model_id:path}/annotation")
async def web_admin_recognition_annotation(
    request: Request,
    provider_id: str,
    model_id: str,
) -> Any:
    write_guard = _require_same_origin_json_write(request)
    if write_guard is not None:
        return write_guard
    session = _require_admin_capability_json(
        request,
        capability="can_manage_catalog",
    )
    if isinstance(session, JSONResponse):
        return session

    payload = RecognitionModelAnnotationPayload.model_validate(await _request_payload(request))
    return save_admin_recognition_annotation(
        catalog_service=_get_catalog_service(request),
        commercial_service=_get_commercial_service(request),
        audit_context=_build_platform_admin_audit_context(
            request,
            str(session.get("platform_admin_ref") or ""),
        ),
        provider_id=provider_id,
        model_id=model_id,
        review_status=payload.review_status,
        manual_tags=payload.manual_tags,
        operator_notes=payload.operator_notes,
        recommended=payload.recommended,
        cost_tier_override=payload.cost_tier_override,
        visibility=payload.visibility,
        badges=payload.badges,
    )


@router.get("/portal/login")
async def web_portal_login(request: Request) -> Any:
    return _redirect_frontend_public(request, "/portal/login")


@router.get("/portal")
async def web_portal_home(request: Request) -> Any:
    return _redirect_frontend_public(request, "/portal")


@router.get("/portal/overview")
async def web_portal_overview(request: Request) -> Any:
    return _redirect_frontend_public(request, "/portal/overview")


@router.get("/portal/keys")
async def web_portal_keys(request: Request) -> Any:
    return _redirect_frontend_public(request, "/portal/keys")


@router.get("/portal/logout")
async def web_portal_logout() -> RedirectResponse:
    response = RedirectResponse(url="/portal/login", status_code=303)
    _clear_browser_session_cookies(response)
    return response
