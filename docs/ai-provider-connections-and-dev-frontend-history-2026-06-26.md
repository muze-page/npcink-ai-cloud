# AI Provider Connections 与本地前端依赖稳定性历史总结

日期：2026-06-26

状态：阶段记录，供后续开发、排障和产品边界复查使用。

## 背景

本轮讨论从一个实际问题开始：Cloud 里各种 AI 凭据接入比较散，`.env.local`
里配置项越来越多，用户难以判断“哪个功能用了哪里的哪个模型”。因此提出两个后台界面方向：

- AI 凭据管理：管理各 AI provider 的连接信息、API key、基础 URL、启用状态等。
- 功能使用模型配置：展示 Cloud 每个能力调用的 provider、connection、profile、model。

讨论后确认，这个方向有价值，但必须遵守 Cloud 边界：

- Cloud 可以拥有 hosted runtime、provider adapter、usage、entitlement、health、diagnostics、runtime metadata/detail。
- Cloud 不应该成为第二套 WordPress 控制面。
- Cloud 不应该成为第二 ability registry、workflow registry、approval/preflight/audit truth。
- Cloud 不应该拥有 prompt/router/preset 的本地真相。
- WordPress 写入、审批、最终应用仍然回到本地 Core/Adapter 路径。

## 主要决策

### 1. AI provider 信息从 `.env.local` 逐步迁移到后台表单

目标不是一次性迁移所有配置，而是先建立一个窄而安全的 provider connection 管理面：

- 后台可以新增、更新、删除 provider connection。
- credential 通过表单写入后端。
- 后端加密存储 credential。
- API 和前端只返回 masked 状态，例如 `configured` 或 `missing`。
- AI Resources 页面把 DB-managed connections 合并到现有 capability/profile/model 投影里。

这解决的是“Cloud runtime provider 连接管理”问题，不解决 WordPress 侧能力、工作流、审批和 prompt/router 真相。

### 2. AI Resources 页面承担可视化入口

`/admin/ai-resources` 被定位为 operator 视角的 runtime resource 页面：

- 展示 provider connections。
- 展示 capabilities。
- 展示 capability matrix。
- 展示 runtime profiles 和最近运行证据。
- 提供 provider connection 表单入口。

页面文案明确说明：

- provider connections 属于 Cloud runtime storage。
- WordPress writes、approvals、abilities、workflows、prompts、router truth 不属于该页面。

### 3. 本地 8010 入口报 500 的根因

访问 `http://127.0.0.1:8010/` 曾经返回 nginx 500。排查结果：

- `http://127.0.0.1:8010/health/live` 返回 200，API 正常。
- `/admin/ai-resources` 能到前端并重定向登录，说明 proxy 基本可用。
- frontend 日志显示：
  - `Cannot find module '@swc/helpers/package.json'`
  - `Module not found: Can't resolve 'next-flight-client-entry-loader'`
  - `Module not found: Can't resolve 'next-app-loader'`
  - `Module not found: Can't resolve 'next-middleware-loader'`

直接根因是 frontend 容器内的依赖视图坏了。原 dev compose 把主机
`./node_modules/.pnpm` bind mount 到容器 `/node_modules/.pnpm`，而本机 pnpm
检查/安装过程改变了主机依赖目录状态，导致容器内 symlink 指向不可用目标。

临时修复是重建 `frontend` 和 `proxy` 容器；后续做了结构性修复，见下文。

## 已落实的改动

### AI provider connection 管理

新增或修改的关键文件：

- `app/core/models.py`
  - 新增 `ProviderConnection` SQLAlchemy model。
- `migrations/versions/20260626_0047_provider_connections_runtime_admin.py`
  - 重建窄语义的 `provider_connections` 表。
  - 注意：历史上旧 `provider_connections` 曾随 model-ops 控制台删除；本迁移不是恢复旧控制台，而是为 runtime credential 管理重建窄表。
- `app/core/secrets.py`
  - 新增 provider connection secret 加密/解密 helper。
- `app/domain/provider_connections/service.py`
  - 新增 admin service，负责校验、加密、masked projection、CRUD。
- `app/api/routes/service.py`
  - 新增：
    - `GET /internal/service/admin/provider-connections`
    - `POST /internal/service/admin/provider-connections`
    - `PATCH /internal/service/admin/provider-connections/{connection_id}`
    - `DELETE /internal/service/admin/provider-connections/{connection_id}`
- `app/domain/provider_resources.py`
  - AI Resources 投影合并 DB-managed provider connections。
- `frontend/src/app/admin/ai-resources/page.tsx`
  - Connections 视图增加 provider connection 表单。
  - credential 是写入型字段，不回显。
- `frontend/src/app/api/admin/[...path]/route.ts`
  - admin proxy 支持 provider connection 写入路径。
- `tests/api/test_service_routes.py`
  - 覆盖 credential 加密存储、masked 响应、AI Resources 投影、删除。
- `frontend/tests/unit/admin-ai-resources-contract.mjs`
  - 覆盖页面边界和 provider connection endpoint 使用。

### 本地 frontend 依赖稳定性

新增或修改的关键文件：

- `docker-compose.dev.yml`
  - 删除 `./node_modules/.pnpm:/node_modules/.pnpm` 主机 pnpm store 挂载。
  - 改为：
    - `cloud-frontend-node-modules-dev:/app/node_modules`
    - `cloud-frontend-next-cache-dev:/app/.next`
  - API reload 收窄为：
    - `--reload-dir app`
    - `--reload-dir migrations`
  - 避免 `.git`、`node_modules`、frontend 依赖变化触发 API 反复 reload。
- `scripts/dev-frontend-doctor.sh`
  - 检查 frontend 容器依赖、Next loader、API health、首页和 admin 路由。
  - 失败时提示恢复命令。
- `scripts/dev-frontend-recover.sh`
  - 停止并删除 frontend/proxy 容器。
  - 删除 frontend node_modules 和 `.next` named volume。
  - 重建 frontend/proxy。
  - 自动运行 doctor。
  - 该脚本不依赖 pnpm，可在 pnpm 本身状态异常时使用。
- `package.json`
  - 新增：
    - `frontend:doctor`
    - `frontend:recover`
  - 前端 type-check/lint 改为直接调用本地二进制，减少 pnpm 自动 install 副作用。
- `Makefile`
  - 新增：
    - `frontend-doctor`
    - `frontend-recover`
- `README.md`
  - 在 quick entry 中记录 doctor/recover 命令。
- `tests/contract/test_dev_frontend_dependency_guard.py`
  - 防止 dev compose 重新退回主机 pnpm store 挂载。
  - 防止 doctor/recover 入口缺失。
  - 防止 API reload 范围重新扩散到 frontend/node_modules。

## 当前推荐操作

### 检查本地 frontend 是否健康

```bash
bash scripts/dev-frontend-doctor.sh
```

该命令会检查：

- frontend/proxy 容器是否运行。
- `/app/node_modules/.pnpm` 是否存在且不是空目录。
- `@swc/helpers/package.json` 是否能解析。
- Next 关键 loader 是否能解析。
- `http://127.0.0.1:8010/health/live` 是否可达。
- `http://127.0.0.1:8010/` 是否渲染 Cloud 首页。
- `http://127.0.0.1:8010/admin/ai-resources` 是否能进入前端路由或登录重定向。

### 恢复本地 frontend 依赖和容器

```bash
bash scripts/dev-frontend-recover.sh
```

该命令会清理 frontend 的依赖 volume 并重建容器。适用于：

- 首页 500。
- frontend 日志出现 `Cannot find module '@swc/helpers/package.json`。
- frontend 日志出现 Next loader 缺失。
- pnpm 本地状态异常但仍需要恢复 Docker dev 环境。

### 进入 AI Resources 页面

```text
http://127.0.0.1:8010/admin/ai-resources
```

未登录时会跳到：

```text
/admin/login?redirect=%2Fadmin%2Fai-resources
```

## 已执行过的验证

AI provider connection 相关：

```bash
uv run --extra dev pytest \
  tests/api/test_service_routes.py::test_admin_provider_connections_store_encrypted_credentials_and_project_to_ai_resources \
  tests/api/test_service_routes.py::test_admin_provider_connections_can_be_deleted \
  tests/api/test_service_routes.py::test_admin_ai_resources_projects_connections_capabilities_and_profiles \
  tests/api/test_service_routes.py::test_admin_ai_resources_saves_profile_preferences_without_secrets \
  -q
```

dev frontend guard 相关：

```bash
bash scripts/dev-frontend-doctor.sh
bash scripts/dev-frontend-recover.sh
docker compose -f docker-compose.dev.yml config -q
uv run --extra dev pytest tests/contract/test_dev_frontend_dependency_guard.py -q
cd frontend && ./node_modules/.bin/tsc --noEmit
node frontend/tests/unit/admin-ai-resources-contract.mjs
git diff --check
```

## 注意事项

- `pnpm run ...` 在当前 Codex runtime 下可能先触发 pnpm 11 的 install/build approval 检查，未执行目标脚本前就失败。
- 因此本地恢复路径优先使用：

```bash
bash scripts/dev-frontend-recover.sh
```

- provider connection 现在解决的是 admin storage/projection 问题；后续如果要让所有 runtime adapter 都完全 DB-first，需要继续逐项改 provider adapter/registry 的读取路径。
- `.env.local` 仍应保留 deployment/runtime 基础 secret，例如数据库 URL、internal token、session secret、加密根 secret 等；AI provider credential 可以逐步从表单迁移。

## 后续建议

1. 为 provider connection 增加单独 audit event，记录谁在何时新增、更新、删除连接，但不要记录明文 credential。
2. 为 provider connection 增加 provider-specific test endpoint，例如 OpenAI-compatible、MiniMax、web search provider。
3. 逐步让现有 web search、image source、audio provider admin config 改为 DB-first，并保留 env fallback。
4. 在 runtime adapter registry 中明确 DB-managed connection 的加载路径，避免“后台显示 ready，但 runtime 未使用”的认知差。
5. 保持 AI Resources 页面为 runtime/operator 视角，不扩展成 WordPress ability/workflow/prompt 控制面。
