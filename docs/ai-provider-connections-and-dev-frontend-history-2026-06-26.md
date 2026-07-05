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
  - API reload 增加 `--timeout-graceful-shutdown 5`，避免开发期
    FastAPI/uvicorn reload 因 in-process background task 长时间等待而拖住
    `/admin/*` 页面首屏接口。
  - API reload 排除 `app/workers/*`。worker-only 代码改动不应该触发 API
    reload；否则 `/api/admin/ability-models/runtime-projection`、
    `/api/admin/ai-resources`、`/api/admin/wordpress-ai-routing` 会一起等待，
    页面看起来像一直加载中。
  - runtime queue worker 每轮 poll 前重新解析 DB-managed execution providers，
    避免供应商页新增或更新 MiniMax 等 provider 后，长跑 worker 继续使用旧
    adapter 集合并把 queued run 标成 `runtime.provider_not_configured`。
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

### 前端新增依赖的强制规范

当修改 `frontend/package.json` 的 `dependencies` 或 `devDependencies` 时，
必须同时维护两个 lockfile：

- 根目录 `pnpm-lock.yaml`，用于仓库级工具和生产构建上下文。
- `frontend/pnpm-lock.yaml`，用于 `frontend/Dockerfile.dev` 的本地 Docker
  dev 构建上下文。

后续 AI 或开发者不得只在宿主机执行一次依赖安装后就认为 Docker 开发环境已同步。
Docker dev 的 `/app/node_modules` 是 named volume，可能继续保留旧依赖视图；
如果 `frontend/pnpm-lock.yaml` 没同步，重建容器也可能仍然缺包。

推荐流程：

```bash
pnpm install --lockfile-only --no-frozen-lockfile
pnpm --dir frontend install --lockfile-only --ignore-workspace --no-frozen-lockfile
pnpm run check:frontend-locks
bash scripts/dev-frontend-doctor.sh
```

如果 `frontend` 容器已经启动，并且浏览器或日志出现
`Module not found: Can't resolve '<package>'`，不要只在宿主机重复安装依赖。
先确认 lockfile 一致，再恢复 Docker 依赖卷：

```bash
pnpm run check:frontend-locks
bash scripts/dev-frontend-recover.sh
```

`pnpm run check:frontend-locks` 会检查 `frontend/package.json` 中声明的前端依赖
是否同时出现在根 `pnpm-lock.yaml` 的 `frontend` importer 和
`frontend/pnpm-lock.yaml` 的 `.` importer 中。该检查已接入
`scripts/dev-frontend-doctor.sh`，因此本地 Docker 诊断会先阻止 lockfile 不一致
的问题继续扩散。

给后续 AI 的执行规则：

- 新增前端依赖时，必须更新两个 lockfile，并运行 `pnpm run check:frontend-locks`。
- 如果错误只出现在 Docker 中，优先怀疑 Docker named volume 中的
  `/app/node_modules` 仍是旧视图。
- 不要删除无关本地状态；需要恢复前端依赖时使用 `bash scripts/dev-frontend-recover.sh`。
- 不要把 `frontend/.pnpm-store/`、`node_modules/`、`.next/` 等本地缓存加入提交。
- 如果新增依赖是为了一个轻量 UI 行为库，必须同时确认前端 type-check、lint、
  Docker doctor 通过。

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
pnpm run check:frontend-locks
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

## 2026-07-04 模型目录、路由候选和试听排障记录

本轮问题集中在一个认知差：供应商页没有启用的模型，为什么还能在
能力-模型路由里被选中，甚至试听时才报错。最终决定把 Cloud runtime
候选收紧到“供应商连接的 `model_ids` 必须包含该模型”。这更符合 operator
直觉：供应商页是 Cloud runtime 白名单入口，能力-模型路由只能从这个白名单里选。

### 模型目录同步规则

- 对支持官方模型列表接口的 provider，`同步模型和情报` 应先通过已保存凭据调用官方
  model list，拿到当前账号真实可调用的 `model_id`。
- 本地 metadata、`models.dev`、provider-specific 规则只负责补充能力、类型、价格、
  上下文、实例和端点信息，不再反向发明可调用模型。
- MiniMax 不能再保留误导性的手工 native list。文本模型以官方 `/v1/models`
  返回为准；语音、图片、视频模型如果官方模型列表漏报，则从官方 API schema 的
  `model` enum 提取候选作为官方文档证据，而不是从页面人工抄一份静态清单。
- `同步模型和情报` 合并目录同步与模型情报刷新，避免 operator 必须点两次；失败时应
  区分“模型目录已保存但情报刷新失败”和“目录同步失败”。
- 历史/废弃模型默认不作为新候选启用。它们只在已保存路由或调试需要时可见，用于解释
  旧配置，不应该鼓励新选择。

### 路由候选规则

- `/admin/ability-models` 的可选候选必须来自 enabled/configured provider
  connection，并且 provider connection 的 `model_ids` 必须包含候选 `model_id`。
- 如果供应商过滤器已经选中某个供应商，候选行标题只显示模型 ID，避免重复展示
  `供应商 / 模型`。未筛选时仍保留完整 `供应商 / 模型`，防止不同供应商同名模型
  产生歧义。
- 主模型和兜底模型摘要继续保留完整 provider/model 标签，因为那是已选路由结果，
  需要可审计来源。
- 英文运行时标签需要有中文落地，例如 `Text generation` -> `文本生成`，
  `Video generation` -> `视频生成`，`Image generation` -> `图片生成`。

### 供应商参考链接

- 官网、状态页、API 文档应由 Cloud 预置模板补全，不要求 operator 手填。
- UI 只展示已知链接；如果只查到官网，就只展示官网。不要显示空输入框或
  `example.com` 占位来暗示用户必须维护这些参考信息。
- 这些链接只是 operator 参考入口，不参与 provider credential、runtime routing
  或 WordPress 控制面决策。

### 试听和 worker 排障规则

- `provider adapter is not configured for minimax` 的根因不是模型本身，而是长跑
  runtime worker 没有刷新 DB-managed execution provider 集合。供应商页已经保存
  并测试通过，不代表旧 worker 进程已经看到新的 adapter。
- runtime queue worker 应在每轮 poll 前重新解析 execution providers；这样新增或
  更新 provider connection 后，queued run 不需要等 worker 重启才可用。
- 如果本地页面又出现无错误长时间加载，先看 dev API reload，而不是直接怀疑业务接口。
  `uvicorn --reload` 等待 background task 时会让多个 `/api/admin/*` 同时卡住。
  dev compose 已排除 `app/workers/*` reload，并设置 graceful shutdown 上限。

### 后续 AI 执行规则

- 修改 provider/model 逻辑前，先检查 `docs/cloud-ability-model-routing-v1.md` 的边界：
  Cloud 只拥有 runtime model binding，不拥有 plugin prompt、ability 开关、审批或
  WordPress 最终写入。
- 不要为了“看起来模型更多”添加静态 provider native list。没有官方模型列表或官方
  schema 证据的模型，只能作为文档情报，不应进入可调用候选。
- 新增 UI 文案时补齐中英文 key，并增加窄 contract test，避免后续页面再次漏出英文。
- 本地卡住问题先区分 browser/frontend/API/worker 四层：页面加载慢、API reload 卡住、
  worker adapter 过期、provider runtime 报错是四类问题，不应混为一谈。

## 后续建议

1. 为 provider connection 增加单独 audit event，记录谁在何时新增、更新、删除连接，但不要记录明文 credential。
2. 为 provider connection 增加 provider-specific test endpoint，例如 OpenAI-compatible、MiniMax、web search provider。
3. 逐步让现有 web search、image source、audio provider admin config 改为 DB-first，并保留 env fallback。
4. 在 runtime adapter registry 中明确 DB-managed connection 的加载路径，避免“后台显示 ready，但 runtime 未使用”的认知差。
5. 保持 AI Resources 页面为 runtime/operator 视角，不扩展成 WordPress ability/workflow/prompt 控制面。
