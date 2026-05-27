# Cloud Mixins 缺失方法修复记录

## 问题

平台管理后台 (`/admin`) 加载后所有 API 端点返回 500 错误。

## 根因

`service.py` 拆分为 7 个 mixin 文件时（commit `e9f5892ce`），4 个方法完全丢失，且 `_admin_mixin.py` 缺少大量 import。

## 修复内容

### 1. `_billing_mixin.py` — 恢复 4 个丢失方法

| 方法 | 原始位置 | 说明 |
|------|---------|------|
| `_build_billing_mismatch` | service.py:7073 | 计算账单快照与账本之间的差异 |
| `_upsert_current_period_billing_snapshot_in_session` | service.py:7790 | 创建/更新当前计费周期快照 |
| `_build_subscription_billing_snapshot_status` | service.py:7826 | 构建订阅账单快照状态（fresh/stale/missing） |
| `_refresh_subscription_billing_snapshots_in_session` | service.py:7912 | 刷新订阅覆盖站点的所有计费快照 |

### 2. `_admin_mixin.py` — 补充缺失 import

| 来源 | 新增内容 |
|------|---------|
| `collections` | `Counter`, `defaultdict` |
| `datetime` | `UTC`, `datetime`, `timedelta` |
| `urllib.parse` | `quote`（已随 Cloud 强收缩移除） |
| `uuid` | `uuid4` |
| `app.core.models` | `AccountSubscription`, `PlatformImpersonationSession`, `Site`, `ACCOUNT_MEMBERSHIP_STATUS_ACTIVE`, `PLATFORM_IMPERSONATION_STATUS_*`, `SITE_*_STATUS_*`, `SUBSCRIPTION_STATUS_*` |
| `app.domain.commercial.errors` | `CommercialNotFoundError`, `CommercialPermissionError` |
| `app.domain.commercial.mixins._audit_mixin` | `IDENTITY_TYPE_USER_ADMIN` |
| `app.domain.commercial.mixins._billing_mixin` | `SHADOW_PRICING_TARIFF_REGISTRY`, `SHADOW_PRICING_TARIFF_VERSION` |

### 3. `docker-compose.dev.yml` — 修复前端容器启动

| 变更 | 原因 |
|------|------|
| 命令改为 `node node_modules/next/dist/bin/next dev` | 跳过 pnpm deps check（容器内无法访问 npm registry） |
| 挂载 `./node_modules/.pnpm:/node_modules/.pnpm` | 让 pnpm symlink 能解析到 workspace root store |
| 移除 `/app/node_modules` 匿名卷 | 避免空卷覆盖镜像中的 node_modules |

## 验证

当时所有端点 200 OK。Cloud 强收缩后，impersonation 和 top-up pack
catalog 已退役，不再作为现行验证入口：
- `/api/admin/overview`
- `/api/admin/subscriptions`
- admin impersonation API（retired）
- admin top-up pack catalog API（retired）
- `/admin` 页面 0 errors
