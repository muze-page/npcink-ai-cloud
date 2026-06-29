# Hosted Model Runtime V1

> Status: canonical

> 状态：active
> 更新时间：2026-04-13
> 适用范围：`cloud/*`、插件侧 hosted runtime 集成面、相关打包/测试/部署脚本
> 历史来源：更早的私有云端规划草稿仅保留背景讨论价值；当前真源以本文为准。
> 上位边界：若本文与 [cloud-responsibility-boundary-v1.md](cloud-responsibility-boundary-v1.md) 冲突，以上位责任边界为准。
> 阅读顺序：先读 [cloud-responsibility-boundary-v1.md](cloud-responsibility-boundary-v1.md)；若当前问题是“Hosted Runtime / Task Backend / Telemetry 哪些应优先云化”，再读 [cloud-service-layering-matrix-v1.md](cloud-service-layering-matrix-v1.md)；若还涉及本地 `WP-Cron single event`、OpenClaw automation、hook owner freeze 或 async closeout，再读 [async-execution-and-cloud-offload-v1.md](async-execution-and-cloud-offload-v1.md) 与 [async-hook-ownership-matrix-v1.md](async-hook-ownership-matrix-v1.md)。本文只定义 `Hosted Runtime / Cloud Core` 局部合同，不承担云端总边界入口。

## 1. 目标与阶段边界

- 当前总定义固定为：`Magick AI Cloud = 本地插件的运行增强层，不是第二控制台，不是第二真源，不是 SaaS 替身。`
- 本文只收 `Hosted Model Runtime` 这条局部主线；Cloud 总责任边界、接手入口与取信顺序仍以上位责任边界为准。
- 当前产品主路径固定为：
  - Hosted Runtime 是普通用户的默认执行路径
  - 普通用户不应被要求先导入本地模型才能获得基础 AI 能力
  - 本地运行时保留为可选高级路径，而不是默认 onboarding 主路径
- 一期只做一个子系统：`Hosted Model Runtime`。
- 一期范围固定为四类能力：
  - 平台托管模型目录
  - 托管实例与能力标签
  - 托管路由与执行
  - 托管统计与健康检查
- 一期明确不做：
  - 云端 `Skills` 平台
  - 云端 `MCP` 平台
  - 云端 `Agent Gateway` 平台
  - 云端完整 `Workflow` 编排平台
  - 第二套 `abilities/workflows/projections` 真源

### 1.1 Hosted-First Product Rule

- `hosted` 是当前冻结的 mainstream execution path。
- 当 addon 已安装、兼容检查通过、Cloud service healthy 时：
  - `execution_mode` 可默认推荐或默认落到 `hosted`
  - router / model-center 可优先呈现 hosted profile
  - 但本地 fallback 不得消失
- 本地运行时固定只承担以下补位角色：
  - 离线
  - 隐私敏感
  - 本地调试 / smoke test
  - hosted 不可用时的 fail-closed 降级
- Hosted-first 不是 cloud-only：
  - 不得要求所有 AI 功能都只能走 Cloud
  - 不得删掉本地 runtime seam、canonical run/status/result 或最终本地控制面

## 2. 核心判定

- 本项目判定结果固定为：`core runtime seam + standalone cloud addon`。
- 判定依据：
  - 命中“可被 `Abilities/MCP/Labs/Third-party` 统一复用”
  - 命中“必须纳入审批/限额/审计/观测治理闭环”
  - 命中“本质属于 AI 执行、路由与工具调用协议能力”
- 因此 runtime canonical seam 继续留在 core，但插件侧 hosted credentials / transport 可以拆成独立薄插件，不得扩展成新的产品域。

## 3. 控制面与运行面分层

### 3.1 WordPress 本地继续负责

- `abilities` registry 与 frozen contract 真源
- Gateway 主入口与 canonical run/proposal/approval 链
- 用户策略配置与后台控制台
- 本地权限闸门与写操作确认
- 最终 WordPress 对象落地
- model-center / router 的最终启用真值，包括 `execution_mode` 与 `hosted_profile_id`

### 3.1A Standalone Cloud Addon 负责

- hosted runtime access settings 的唯一插件侧配置面
- hosted transport client
- Cloud service entry / status 链接
- 一次性导入并清理 legacy core `cloud_runtime_*`

冻结约束：

- core `settings/local` 不再显示或保存 `cloud_runtime_*`
- core 不再保留 `cloud_runtime_*` option fallback 或双写链
- addon 对 legacy core `cloud_runtime_*` 只允许做一次性导入并清理；smoke/fixtures 不得再把 core legacy option 当成长期配置路径
- addon 不能复制 model-center / router / approval / write path
- addon 本地设置面只允许暴露 `base_url + Cloud API Key + save-and-verify`
- addon 未验证时只显示 Settings；保存并验证通过后才显示 `Cloud Overview / Expiry & Entitlement / Settings`
- addon 验证成功后的 TAB 顺序固定为 `Cloud Overview / Expiry & Entitlement / Settings`
- addon 可以把 customer-facing `Cloud API Key` 解析成内部 `site_id / key_id / secret` 供签名请求使用，但不得把这些 split credentials 暴露成 UI 字段、admin save payload 或 developer/debug tab
- addon 不得注册本地 Developer diagnostics route，例如 `/admin/cloud-addon/developer-readonly`
- provider release evidence、hosted reconcile detail、callback delivery detail 与 runtime repair workflow 默认归属 Cloud/service-plane support 或隐藏运行链路，不得作为 WordPress addon 页面功能

### 3.2 云端子项目负责

- `model catalog`
  - 对外语义固定为 `Platform Models`
- `model instance registry`
- `provider adapter`
- `routing / fallback`
- `hosted routing profile catalog`
- `hosted execution`
- `provider-call telemetry`
- `usage / health / quota`
- 上游 provider/gateway 接入矩阵、显式启用规则与 namespaced `model_id`
  约束固定见 [cloud-provider-integration-matrix-v1.md](cloud-provider-integration-matrix-v1.md)。

### 3.2F Platform Models vs Recognition Bundle

- public `/v1/catalog/models` 与 `/v1/catalog/platform-models` 固定属于 `Platform Models` surface。
- 这层只表示平台实际托管、实际准备提供给用户的模型 API 与公开元数据。
- `Recognition Bundle` 固定独立于 `Platform Models`，它服务于模型情报汇聚、识别审查，以及插件本地下发参考。
- 任何插件或用户侧若需要“平台实际可用/可售卖的模型”，应消费 `Platform Models`，而不是 `Recognition Bundle`。

### 3.2A 托管路由 Profile 固定边界

- 云端可以维护 `Managed Router / Hosted Routing Profiles` 的目录、推荐权重、provider fallback、健康状态和官方策略包。
- 本地必须继续持有：
  - 最终启用的 `routing_profile`
  - adopted snapshot
  - 本地 prompt/preset/router 真值
  - 最终审批与 WordPress 写入
- 云端 profile 只能作为“本地可采纳的托管增强”，不得成为第二 router truth。
- 任何 hosted profile 失效时，本地必须可退回：
  - `fixed_instance`
  - `local_first`
  - 默认 preset / default profile

### 3.2B Site Provisioning & Activation Contract

- public runtime surface 只接受“已 provision 且 `active`”的 `site_id`。
- `POST /v1/runtime/resolve`、`POST /v1/runtime/execute`、`GET /v1/runs/*`、`GET /v1/stats/*`
  都不得在请求路径里隐式 upsert `sites` 或 `site_api_keys`。
- 当前最小 site lifecycle 固定为：
  - `provisioning`
  - `active`
  - `inactive`
  - `suspended`
  - `archived`
- `inactive` 表示用户在 Portal 中停用 Cloud 服务后保留的站点记录：
  - public runtime 不接受 `inactive` site；
  - `inactive` 不占用订阅的可用站点额度；
  - 用户可通过 Portal 或 WordPress addon 重连重新启用；
  - 站点密钥、用量、审计和历史记录继续保留。
- `suspended` 表示服务面/运营面暂停，不能由用户自助绕过，也继续占用站点额度。
- `archived` 表示隐藏在默认 Portal 工作区之外的历史站点记录；恢复时必须继续满足同账号单 active site 规则。
- 当前阶段允许的 provisioning owner 只有：
  - dev/test seed
  - 未来 Cloud `Service Plane / Internal Service Operations`
- Hosted Runtime 当前不提供“请求即建站”语义；未 provision 的 site 应在 auth/runtime guard 被拒绝，而不是被自动创建。
- `site_api_keys` 继续只服务已 provision 的 site；当前最小 key lifecycle 固定为：
  - `active`
  - `revoked`
  - `expired`
- customer-facing `Cloud API Key` wrapper format 固定见 [cloud-customer-api-key-format-v1.md](cloud-customer-api-key-format-v1.md)；
  它只负责交付体验，不改变底层 `site_id + key_id + secret` auth truth。
- 若未来上线 customer-facing Portal / self-serve key 管理，对外签发/轮换 contract 固定见 [cloud-portal-api-key-issue-v1.md](cloud-portal-api-key-issue-v1.md)；
  但 canonical key lifecycle owner 继续是 Cloud service-plane internal ops。
- public runtime auth 只接受未过期且未撤销的 `active` key；revoked 或 expired key 统一返回 `401 auth.invalid_key`。
- `create / rotate / revoke / expire / audit` owner 固定在 Cloud `Service Plane / Internal Service Operations`；
  public runtime surface 不得隐式补发、续期、轮换或审计 key。
- 当前 internal inspect surface 已包括 `/internal/service/audit-events`；该面只服务 internal/admin operations，不构成 customer-facing portal。
- 当前 request-guard reject 还会落到 `runtime_guard_events`；该面只服务 runtime/internal operator diagnostics，不构成 customer-facing risk console。

### 3.2C Site API Key Lifecycle Contract

- `site_api_keys` 当前最小字段固定为：
  - `key_id`
  - `site_id`
  - `secret_hash`
  - `status`
  - `expires_at`
  - `revoked_at`
  - `last_used_at`
  - `created_at`
- 当前 key lifecycle matrix 固定为：
  - `active`: 可用于 public runtime HMAC；要求 `revoked_at` 为空，且 `expires_at` 为空或晚于当前时间
  - `revoked`: 一旦进入该态，public runtime 立即拒绝；`revoked_at` 应记录服务面撤销时刻
  - `expired`: public runtime 立即拒绝；可由 `status=expired` 物化，也可由 `expires_at <= now` 推导
- `last_used_at` 只表示最近一次成功鉴权的运行证据，不是 key lifecycle 真源，也不能反向恢复 revoked/expired key。
- 当前 request-path contract 固定为：
  - `POST /v1/runtime/resolve`
  - `POST /v1/runtime/execute`
  - `GET /v1/runs/*`
  - `GET /v1/stats/*`
  都只能消费已签发 key 状态，不得在鉴权阶段隐式 extend、rotate 或 re-issue key。

### 3.2D Public Runtime Policy Ingress Contract

- public runtime `policy` 只允许携带 Cloud runtime plane 真正需要的最小字段。
- 当前冻结允许集合为：
  - `allow_fallback`
- `timeout_seconds / retry_max / retention_ttl / callback_url / task_backend` 必须走显式顶层 runtime request 字段，不得再通过开放字典侧载进入 Cloud。
- 以下字段固定属于本地控制面治理真相，public runtime `policy` 不得接收：
  - `requires_confirm`
  - `required_scope`
  - `required_scopes`
  - `tool_policy`
  - `approval_policy`
  - `apply_policy`
  - `final_write_policy`
  - `final_write_target`
  - `wordpress_write_policy`
  - `wordpress_write_target`
  - `write_control`
  - `write_controls`
- Cloud 内部仍可在 merged runtime policy 中附加运行面派生字段，例如 routing snapshot、commercial overrides 与 task backend snapshot；但这不改变 public ingress allowlist。

### 3.2D.1 Execution Contract Gate

- public hosted runtime 现在固定先经过 `execution contract gate`，再进入 routing / provider execution。
- Cloud 不生成第二套 ability contract truth；它只消费插件/WP 已经下发的运行合同字段，并在本地做 fail-closed 校验。
- execution contract artifact owner 固定在 `WP/plugin side`；hosted client 只消费该 artifact，不能再把 request-time scattered defaults 当成唯一 contract truth。
- feature-level runtime templates 同样固定在 `WP/plugin side`；至少 `comment_moderation`、`content_summary_seo_completion`、`article long-run content` 的 runtime/storage/baseline budget/concurrency 默认值必须先在本地模板冻结，再投影进 execution contract artifact。
- 当前冻结必须进入 execution contract 的字段为：
  - `ability_name`
  - `contract_version`
  - `profile_id`
  - `execution_pattern`
  - `timeout_seconds`
  - `retry_max`
  - `retention_ttl`
  - `callback_mode`
  - `data_classification`
  - `storage_mode`
- `callback_url` 不属于 execution contract artifact truth；它只能留在 bounded transport / callback registration seam。
- execution contract artifact 对 customer-facing intake 只表达 `inline / whole_run_offload`；`step_offload` 只能留在本地/internal seam，不得重新长成 public artifact 语义。
- commercial policy override 继续允许收紧执行面，例如 downgrade / disable queue / disable fallback；但不得扩大合同允许范围。

### 3.2D.2 Runtime Callback Registration Contract

- public runtime terminal callback 不再把 request-level `callback_url` 当长期真源。
- 当前固定语义是：callback endpoint 必须来自 site 预登记 metadata，Cloud callback dispatch 按注册信息做签名投递。
- signed runtime callback 至少固定带：
  - `X-Magick-Cloud-Event`
  - `X-Magick-Run-Id`
  - `X-Magick-Trace-Id`
  - `X-Magick-Timestamp`
  - `X-Magick-Callback-Id`
  - `X-Magick-Signature`
- canonical pull truth 继续固定为：
  - `GET /v1/runs/{run_id}`
  - `GET /v1/runs/{run_id}/result`
- callback failure / retry / stale reclaim 仍然只属于 bounded delivery semantics，不构成第二 scheduler 或第二 run truth。

### 3.2D.3 Storage Policy Contract

- `data_classification` 继续描述商业/治理语义；它不再单独承担 DB storage 行为。
- 当前 hosted runtime 额外冻结 `storage_mode`：
  - `no_store`
  - `result_only`
  - `full_store_with_ttl`
- 当前兼容默认值固定为 `result_only`。
- `full_store_with_ttl` 必须伴随正向 `retention_ttl`；不得把 full input/result storage 作为默认兼容路径。

### 3.2E Runtime Operator Diagnostics Contract

- 当前 internal operator diagnostics surface 固定包括：
  - `GET /internal/service/runtime/diagnostics/summary`
  - `GET /internal/service/runtime/diagnostics/backlog`
  - `GET /internal/service/runtime/diagnostics/runs`
  - `GET /internal/service/runtime/diagnostics/abuse-guard`
  - `GET /internal/service/runtime/diagnostics/guard-events`
- `summary` 固定服务 coarse runtime pressure explainability，只允许暴露：
  - queue/cancel/callback pressure state
  - oldest age / threshold / reason code
  - callback `recoverable_dispatching`
  - bounded callback reclaim action label
- `backlog` 固定服务 queued/running queue-worker observability，只允许暴露：
  - `site_id / ability_family / execution_pattern` 聚合
  - queued vs running split
  - oldest/p95 age
  - `fresh / aging / stale` buckets
  - `bottleneck_state / pressure_state / pressure_reasons / spread_state`
  - `lease_recovery_inputs`
- `abuse-guard` 固定服务 request-guard explainability，只允许暴露 bounded per-scope severity、reason code、event-code breakdown 与 watchlist。
- 以上 surface 只服务 operator 判定与后续 lease recovery 设计输入，不构成 broader queued/running lease recovery、第二 worker control plane 或 durable orchestration。

### 3.2F Runtime Intake Mode Freeze

- 当前 customer-facing hosted runtime intake mode 只冻结两类：
  - `inline`
  - `whole_run_offload`
- `step_offload` 仍可保留为本地/internal runtime seam，但不再允许作为 public `resolve / execute` 的 customer-facing intake 值。
- public `resolve / execute` 对 `step_offload` 现在固定 fail-closed；不得再恢复 deprecated/canonicalization 双轨公开语义。

### 3.3 绝对不得迁走

- `ability` 真源
- `workflow` 对外交付契约
- 本地权限与审批闸门
- WordPress 写入落地

一句话固定为：`WP 是控制面，cloud 是模型运行面。`

### 3.4 云端承接高级 Skills 的固定边界

- 云端后续可以承接高级 Skill 的重型分析/生成/异步执行，但这仍然属于 `runtime plane`，不是新的 `Skills` 控制面。
- 对外继续固定为本地 `skill-as-ability`；稳定面仍然是本地 canonical `run / status / result / cancel`。
- 本地必须继续持有：
  - `skill_id`
  - `ability_name / ability_id`
  - input/output schema
  - `contract_version`
  - `risk_level / requires_confirm / allowed_channels`
  - projection flags
  - 最终审批、apply 与 WordPress 写入
- 云端只允许消费运行事实，例如：
  - `skill_id`
  - `ability_name`
  - `ability_family`
  - `contract_version`
  - `execution_tier`
  - `execution_pattern`
  - `trace_id`
  - `idempotency_key`
  - `data_classification`
- 允许的模式只包括：
  - `step_offload`
  - `whole_run_offload`
- 若后续要继续扩 callback dispatch、lease recovery、durable orchestration 或新的 Cloud Intelligence services，必须先更新 [cloud-responsibility-boundary-v1.md](cloud-responsibility-boundary-v1.md)，再回到本文或 [cloud-skill-execution-v1.md](cloud-skill-execution-v1.md) 补局部合同。
- 当前样板状态（2026-03-14 02:09）：
  - `content_summary_seo_completion` 已作为首个 `step_offload` pilot 落地
  - 该 pilot 继续由本地 workflow 持有 canonical `run / status / result`，云端只承接 `generate_excerpt + generate_seo_meta` 的运行面语义
  - `media_alt_completion` 已作为第二个 `whole_run_offload` batch pilot 落地
  - 该 pilot 继续由本地 `skill-as-ability` 持有 canonical `run / status / result`，云端只承接 `items[] -> foreach -> magick-ai/generate-alt` 的批量执行语义
  - `media_nightly_image_optimize` 已作为第三个 `TaskBackend`/长任务基座 pilot 落地
  - 该 pilot 继续由本地 `workflow/media_nightly_image_optimize` 持有 canonical `run / status / result`；云端当前已承接 `queued run -> worker claim/drain -> result polling -> terminal callback delivery -> public cancel` 的最小 queue-backed orchestration，但 `run_records` 仍是 canonical truth，Redis 只作 wake-up signal
  - broader queued/running stale repair 现已作为 bounded operator action 落地，固定见 [cloud-batch-repair-v1.md](cloud-batch-repair-v1.md)；它不是第二控制台
  - heavy batch chunking 的 `media_nightly_image_optimize` v1 主链现已落地；它继续严格冻结在 `local parent manifest / checkpoint resume / failed chunk retry` 模型，固定见 [cloud-batch-chunking-v1.md](cloud-batch-chunking-v1.md)；它不是 durable workflow engine
  - `media_alt_completion` 的 proposal/review/apply v1 当前也已固定为本地 canonical proposal + local apply audit 闭环，详见 [cloud-batch-apply-boundary-v1.md](cloud-batch-apply-boundary-v1.md)；cloud 继续只提供 suggestion 与 evidence
  - 当前仍未进入 lease recovery 或完整 Workflow engine
- 明确禁止：
  - 云端 `skill registry / publish / marketplace` 真源
  - 云端 `MCP / Agent Gateway` projection 真源
  - 云端取代本地 Gateway、审批与写入
- 详细合同固定见 [cloud-skill-execution-v1.md](cloud-skill-execution-v1.md)。

### 3.4 商业底座与 entitlement gate

- Cloud 商业对象、ledger truth 与 `/internal/service/*` owner 固定见 [cloud-commercial-core-v1.md](cloud-commercial-core-v1.md)。
- public runtime commercial gate 顺序、`ability_family` seam 与商业错误码固定见 [cloud-entitlement-gate-v1.md](cloud-entitlement-gate-v1.md)。
- Hosted runtime request 现在必须能携带 `ability_family`；这是套餐/权益判断的最小商业分类，不是第二 ability registry。
- 当前已落地的是 admin-only commercial core、runtime entitlement gate，以及最小 subscription grace / budget soft-limit / runtime downgrade policy。
- 当前仍未落地的是 portal/session auth、自助用户中心、payment/invoice/reconciliation 与 finance loop；不得把最小商业策略误写成完整 front-office。

## 4. 仓库与打包边界

- `cloud/` 必须是独立 Python 子项目，不得并入插件现有 `pnpm/composer` 主构建链。
- 插件侧 hosted runtime integration 允许拆成独立薄插件；当前工作区冻结布局为并列插件目录 `magick-ai-cloud-addon/`。
- 该 addon 只承接 credentials / transport / service entry，不得长成第二控制面，core 继续通过稳定 hook/filter seam 消费它。
- 当前冻结实现为：
  - addon option + `magick_ai_cloud_runtime_settings` filter 是 hosted credentials 的唯一插件侧真值
  - core local settings payload / save / panel 不再持有 hosted credentials
  - addon UI 只接受 `base_url + Cloud API Key`；split signing fields 只是 API Key 解析后的内部存储
  - addon 未验证时只显示 Settings；保存并验证成功后才显示 `Cloud Overview / Expiry & Entitlement / Settings`
- 推荐目录骨架固定为：

```text
cloud/
  README.md
  pyproject.toml
  .env.example
  docker-compose.dev.yml
  docker-compose.prod.yml
  Dockerfile
  Makefile
  app/
    api/
      main.py
      routes/
        health.py
        catalog.py
        runtime.py
        runs.py
        internal.py
    core/
      config.py
      logging.py
      security.py
      tracing.py
      db.py
    domain/
      catalog/
      routing/
      runtime/
      usage/
      health/
    adapters/
      providers/
        base.py
        openaiible.py
        anthropic.py
        google.py
        ollama.py
      repositories/
      queue/
    workers/
      catalog_refresh.py
      provider_healthcheck.py
      usage_rollup.py
  migrations/
  tests/
    contract/
    api/
    domain/
  deploy/
    bundle-images.sh
    remote-load-and-up.sh
    remote-migrate.sh
```

- `../dist/magick-ai-install.zip` 必须排除 `cloud/`、Docker 文件、云端部署脚本与云端依赖。
- `../dist/magick-ai-source.zip` 作为内部源码归档时，可包含 `cloud/`；但它不是用户安装包。
- 若仓库内暂存独立 `Cloud addon` 源码，同样只能进入内部源码归档，不得并入 `../dist/magick-ai-install.zip`。
- 根仓的 `package.json` 可以暴露代理命令，但不得让 `cloud/` 变成插件发布包或插件构建前置。

## 5. 技术基线

### 5.1 一期技术栈

- API：FastAPI
- 配置：`pydantic-settings`
- 数据库：PostgreSQL
- 缓存/幂等/短队列：Redis
- ORM / migration：SQLAlchemy + Alembic
- 追踪：OpenTelemetry
- 部署：Docker Compose
- 反向代理：Caddy 或 Nginx

### 5.2 二期不提前引入

- 一期不引入 `Temporal`。
- 若未来需要 durable execution，只允许在代码边界预留 `JobBackend` 或 `RunOrchestrator` 抽象，不得在一期直接上完整 Workflow 引擎。

## 6. 一期里程碑与 DoD

## M0：仓库与容器骨架

- 交付：
  - `cloud/` 子项目骨架
  - `pyproject.toml`
  - `docker-compose.dev.yml`
  - `docker-compose.prod.yml`
  - `Dockerfile`
  - `README.md`
  - `.env.example`
  - `Makefile`
  - Alembic 初始化
  - `health` route
  - logging / tracing 基线
- DoD：
  - `docker compose up --build` 可启动
  - `/health/live` 返回 `200`
  - `/health/ready` 在携带 `X-Magick-Internal-Token` 时可检查 Postgres / Redis
  - `pytest`、`ruff`、`mypy` 均可执行

## M1：模型目录云端化

- 交付：
  - `provider catalog`
  - `catalog_models`
  - `catalog revision`
  - provider refresh worker
  - provider healthcheck worker
  - catalog query API
- API：
  - public runtime catalog：
    - `GET /v1/catalog/revision`
    - `GET /v1/catalog/models`
    - `GET /v1/catalog/models/{model_id}`
  - internal operations：
    - `POST /internal/catalog/refresh`
    - `POST /internal/health/providers/scan`
- DoD：
  - 云端可独立维护 catalog revision
  - 支持按 `feature/provider/status/filter` 查询
  - 支持推荐模型集合与 `recommended_for=<profile_id>` 过滤
  - 支持 `deprecated / unavailable / fallback_candidate` 标记

## M2：托管路由与执行

- 交付：
  - `profile -> candidate pool -> final selection`
  - hosted text execute
  - hosted embedding execute
  - 可选 hosted vision execute
  - `run_records`
  - `provider_call_records`
  - `runtime_guard_events`
  - retry / timeout / fallback
  - idempotency
- API：
  - `POST /v1/runtime/resolve`
  - `POST /v1/runtime/execute`
  - `GET /v1/runs/{run_id}`
  - `POST /v1/runs/{run_id}/cancel`
  - `GET /v1/runs/{run_id}/result`
- DoD：
  - 同一 `idempotency_key` 不重复执行
  - 返回 canonical `run_id`
  - 记录最终命中的 provider / model / instance
  - 记录 fallback 是否发生
  - request-guard reject 会保留 durable `runtime_guard_events` 证据；短 TTL replay receipt 只负责近实时拦截
  - 错误码统一
  - execute 失败时返回具体 `error_code`，并显式带出 `error_stage / retryable / retry_exhausted / provider_call_count`
  - 当前实现补记（2026-03-14 02:09）：
    - runtime 现已接受并透传 `timeout_seconds / retry_max / retention_ttl / callback_url / task_backend`
    - `resolve / execute / runs / result` 现已统一返回 `task_backend` metadata
    - `whole_run_offload + task_backend.enabled` 现会创建 hosted `queued` run，并显式回传 `canonical_run_id` backlink；`task_backend.status=queued` 只表达 hosted runtime 面状态
    - `app.workers.runtime_queue` 会通过 Redis wake-up queue + DB fallback claim queued runs，并在单个 poll cycle 内 drain 一批 queued runs 与 pending callbacks；`runs/result` 继续作为 hosted polling surface，本地仍保留 canonical polling surface
    - Redis queue 不是第二套 task truth source；`run_records` 只是真正的 hosted 状态真源，不能取代本地 canonical run/status/result
    - `runs` / `result` 现额外统一返回 `run_lifecycle`：把 `requested -> queued|processing -> terminal -> retention` 固定成单一视图
    - `POST /v1/runs/{run_id}/cancel` 已上线；当前只对 queue-backed runs 开放，queued run 可立即取消，`running` cancel 仍是 worker attempt boundary 上的 best-effort
    - `run_lifecycle.cancel` 现固定表达 `supported / state / requested_at / canceled_at`
    - `run_lifecycle.callback` 现固定表达 `requested / mode / dispatch_status / attempt_count / last_attempt_at / delivered_at / next_attempt_at / last_error_code`
    - `run_lifecycle.retention` 当前固定表达 `ttl_seconds / expires_at / state / result_purged_at`；保留窗口结束后，`GET /v1/runs/{run_id}/result` 必须返回 `410 runtime.result_expired`
    - 当前 callback delivery 已进入 worker-driven terminal dispatch；stale `dispatching` callback 现允许 bounded reclaim 回到 `pending`，并留下 `runtime.callback_dispatch_recovered` service audit 证据
    - 当前 runtime/operator diagnostics 现已补上 `summary + backlog + runs + abuse-guard + guard-events` 的 bounded explainability；其中 `backlog` 只作为 queued/running lease recovery 的前置观察面，不是 recovery 本身
    - broader queued/running lease recovery、delivery guarantee 与更复杂的 stage orchestration 仍未落地
    - 后续若补这些能力，先改上位责任边界，再改本文；不得让 Hosted Runtime 局部合同变成新的云端总边界入口

## M3：统计与健康

- 交付：
  - instance/profile 级 usage 聚合
  - provider / instance health snapshot
  - `today / rolling_24h` 指标
- API：
  - `GET /v1/stats/instances/{instance_id}`
  - `GET /v1/stats/profiles/{profile_id}`
  - `GET /v1/usage/summary`
- DoD：
  - 支持 `today / rolling_24h`
  - 支持按 `instance / profile` 聚合
  - 输出 `success_rate / avg_latency_ms / fallback_rate / last_seen_at`

## 7. 数据模型基线

- 一期最小表集合固定为：
  - `sites`
  - `site_api_keys`
  - `catalog_models`
  - `catalog_instances`
  - `routing_profiles`
  - `routing_bindings`
  - `run_records`
  - `provider_call_records`
  - `health_snapshots`

### 7.1 关键字段

- `sites`：
  - `site_id`
  - `name`
  - `status`
  - `created_at`
- `site_api_keys`：
  - `key_id`
  - `site_id`
  - `secret_hash`
  - `status`
  - `expires_at`
  - `revoked_at`
  - `last_used_at`
- `catalog_models`：
  - `model_id`
  - `provider_id`
  - `family`
  - `feature`
  - `status`
  - `context_window`
  - `price_input`
  - `price_output`
  - `is_deprecated`
  - `revision`
- `catalog_instances`：
  - `instance_id`
  - `model_id`
  - `provider_id`
  - `endpoint_variant`
  - `region`
  - `capability_tags`
  - `health_status`
  - `is_default`
  - `weight`
- `routing_profiles`：
  - `profile_id`
  - `execution_kind`
  - `default_policy_json`
- `routing_bindings`：
  - `profile_id`
  - `candidate_instance_ids`
  - `selection_policy_json`
  - `revision`
- `run_records`：
  - `run_id`
  - `site_id`
  - `ability_name`
  - `skill_id`
  - `workflow_id`
  - `contract_version`
  - `channel`
  - `profile_id`
  - `execution_tier`
  - `execution_pattern`
  - `data_classification`
  - `status`
  - `trace_id`
  - `started_at`
  - `processing_started_at`
  - `finished_at`
  - `retention_expires_at`
  - `result_purged_at`
  - `result_ref`
  - `error_code`
- `provider_call_records`：
  - `id`
  - `run_id`
  - `provider_id`
  - `model_id`
  - `instance_id`
  - `region`
  - `latency_ms`
  - `tokens_in`
  - `tokens_out`
  - `cost`
  - `retry_count`
  - `fallback_used`
  - `created_at`
- `health_snapshots`：
  - `provider_id`
  - `instance_id`
  - `status`
  - `reason`
  - `measured_at`

## 8. API 与契约规范

### 8.1 不得发明第二套能力模型

- 云端只接受上游运行时事实：
  - `ability_name`
  - `ability_family`
  - `channel`
  - `profile_id`
  - `policy`
  - `trace_id`
  - `run_id`
  - 若命中 cloud-capable skill，还允许附带：
    - `skill_id`
    - `workflow_id`
    - `contract_version`
    - `execution_tier`
    - `execution_pattern`
    - `data_classification`
    - `idempotency_key`
- 云端不得重新定义：
  - `abilities`
  - `workflows`
  - `projections`
  - `public exposure matrix`

- 当前阶段还固定两条边界：
  - `callback_url` 已进入 worker-driven terminal delivery；stale `dispatching` callback 允许 bounded reclaim 回到 `pending`，但 polling 仍是 canonical read surface，且当前没有 broader queued/running lease recovery / delivery guarantee
  - public cancel surface 已开放到 queue-backed runs；但 inline run 仍不支持，`running` cancel 也仍不是 provider-level hard abort

### 8.2 公共 API 必须版本化

- 当前统一为 `/v1/...`
- 破坏性变更必须显式升级到 `/v2/...`

### 8.3 JSON 固定使用 snake_case

- 云端不得切换到 `camelCase`
- 与插件现有 REST/settings contract 保持一致

### 8.4 响应 envelope 固定

```json
{
  "status": "ok",
  "error_code": "",
  "message": "",
  "data": {},
  "meta": {
    "trace_id": "...",
    "revision": "..."
  }
}
```

### 8.5 所有写请求必须支持以下头

- `Idempotency-Key`
- `traceparent`
- `X-Magick-Site-Id`
- `X-Magick-Key-Id`
- `X-Magick-Timestamp`
- `X-Magick-Signature`

### 8.6 执行失败 taxonomy 固定

- `/v1/runtime/execute` 失败时，response envelope `error_code` 必须返回具体失败码，不得统一退化成 `runtime.execute_failed`
- `runtime execute` response data 至少固定包含：
  - `error_code`
  - `error_message`
  - `error_stage`
  - `retryable`
  - `retry_exhausted`
  - `provider_call_count`
- `GET /v1/runs/{run_id}` 必须同步暴露 `error_code / error_message / error_stage / retryable / retry_exhausted`
- `GET /v1/runs/{run_id}/result` 内的 `provider_calls[*]` 必须保留：
  - `retry_count`
  - `error_code`
  - `error_stage`
  - `retryable`
- 当前一期固定的 provider 级 canonical 错误码至少包括：
  - `provider.invalid_request`
  - `provider.auth_invalid`
  - `provider.access_denied`
  - `provider.endpoint_not_found`
  - `provider.rate_limited`
  - `provider.timeout`
  - `provider.network_error`
  - `provider.upstream_unavailable`
  - `provider.upstream_error`

## 9. 鉴权规范

- 站点到云端一律使用 `site_id + key_id + secret`
- 签名算法固定为 `HMAC-SHA256`
- 请求体摘要必须参与签名
- public signed POST 必须带时间戳与 `X-Magick-Nonce`，防重放；app-side generic replay receipt 已覆盖 public signed POST 与 `/internal/*` POST，但 `/v1/runtime/execute -> run_records(site_id, idempotency_key)` 仍是 canonical idempotent replay truth
- 服务端只保存 `secret_hash`
- 规则：
  - secret 只展示一次，不回显
  - 支持 key rotation
  - 每个 key 绑定 scope
  - 每个 site 至少两把 key：`default`、`rollover`

### 9.1 当前安全现状

- 云端一期没有独立业务控制台；控制面仍在 WordPress。云端当前只暴露 Hosted Model Runtime API，不得把它误写成“已有云端后台平台”。
- 当前运行面已落地的安全边界固定为：
  - public runtime surface 固定为 `runtime / runs / stats / catalog`，走 `HMAC-SHA256` 站点鉴权 + scope 收口
  - public signed POST 额外固定要求 `X-Magick-Nonce`
  - `/v1/catalog/*` 继续公开为 public runtime catalog，但仍必须要求 `catalog:read`
  - `/internal/*` 固定为 internal operations surface，走独立 `X-Magick-Internal-Token`；当前两个 POST 入口都要求 `Idempotency-Key`
  - public runtime 的 `site_id/key_id/signature` 不再授权 `/internal/*`
  - write 请求强制 `Idempotency-Key`
  - `traceparent` 固定透传
  - 认证后的 `site_id` 必须用于 `runs / stats` 查询收口
  - `site_api_keys` 只保存 `secret_hash`，不保存明文 key
  - public runtime 只接受 `status=active` 且未过期、未撤销的 key；其它状态统一记为 `auth.invalid_key`
  - provider 密钥只允许通过 env / secret file 注入，不得写进仓库、普通业务表或后台明文回显
- 当前 app-side responsibility 固定为：
  - `GET /health/live` 只返回最小 liveness 语义，不暴露 provider、DB、Redis、queue、site 或 scope 细节
  - `GET /health/ready` 与 `/internal/*` 继续属于 internal operations surface，要求 `X-Magick-Internal-Token`
  - focused health tests 已固定 `GET /health/live = public minimal envelope` 与 `GET /health/ready = internal token required`；后续若要改边界，必须先回写本合同与上位云边界
  - public write path 当前最小持久化 replay contract 已落在 `/v1/runtime/execute`：`run_records(site_id, idempotency_key)` 继续作为 canonical 唯一键；同 key 同 payload 返回 `idempotent_replay=true`，冲突复用返回 `runtime.idempotency_conflict`
  - public signed POST 当前还固定要求 `X-Magick-Nonce`，并通过 `replay_receipts(scope_kind=public_post, scope_id=site_id, replay_key=nonce)` 阻断 nonce reuse
  - `/internal/*` POST 当前通过 `replay_receipts(scope_kind=internal_post, scope_id=internal, replay_key=idempotency_key)` 阻断 replay marker reuse
  - public signed POST 当前还会做最小 site-scoped short-window rate limit；`/internal/*` POST 也会做最小 internal-token-scoped short-window rate limit；超限统一返回 `429 auth.rate_limit_exceeded`
  - `Idempotency-Key` 继续是 write/internal POST 的最低要求；当前 app-side 还额外固定 `Idempotency-Key` hygiene：只接受受限字符集与有限长度，避免把 replay marker 退化成任意用户输入
  - public payload 当前固定还要经过 app-side `payload size cap`；超限请求必须 fail-closed，不把 body abuse 继续留给业务层兜底
- 当前实现层的显式保留项固定为：
  - `GET /health/live` 仍是最小 liveness probe；最终暴露策略由宿主/反代决定，默认推荐只走 allowlist/private probe。只有外部 LB/uptime probe 明确需要时，才允许经 TLS 反代公开最小 liveness；FastAPI app 自身不承诺“默认公网开放”
  - `GET /health/ready` 已改成 internal probe，要求 `X-Magick-Internal-Token`
  - 仓库当前提供的 `docker-compose.prod.yml` 已内置最小 perimeter proxy：对外只发布 proxy 入口，raw `api` 端口不再直接映射给宿主；`/internal/*` 与 `GET /health/ready` 只通过 private/allowlisted path 进入 app
  - production-style deploy helper 当前要求 `MAGICK_CLOUD_INTERNAL_AUTH_TOKEN` 非空；`remote-smoke.sh` 还会额外验证 `/docs`、`/redoc` 与 internal POST 在无 token 时 fail-closed
  - 合同中的 generic replay receipt 当前已落到 public signed POST 与 `/internal/*` POST；public GET 仍主要依赖时间窗、签名和 scope，不引入第二套 GET replay truth
  - public HMAC 拒绝事件当前至少要统一记录 `auth.invalid_timestamp`、`auth.stale_timestamp`、`auth.invalid_site`、`auth.invalid_key`、`auth.scope_denied`、`auth.invalid_signature`、`auth.nonce_required`、`auth.invalid_nonce`、`auth.invalid_idempotency_key`、`auth.payload_too_large`、`auth.replay_blocked`
  - generic replay reject 现在统一使用 `auth.replay_blocked`；`/v1/runtime/execute` 的 payload 不一致持久化 replay 冲突继续保留 `runtime.idempotency_conflict`
  - runtime commercial gate 的 allow/deny 决策现已写入 `commercial_decision_events`；internal mutating service ops 现已写入 `service_audit_events`
  - public/internal request-guard reject 现已写入 `runtime_guard_events`；public `site/key/ip` 与 internal `token/ip` 现在同时有 short-window guard 与 minimal cooldown
  - 云端当前没有独立的人类登录、后台会话或 RBAC/IAM
  - public runtime surface 必须先经反向代理做 HTTPS 终止后再对外开放
  - `/internal/*` 与 `GET /health/ready` 必须放在 allowlist / private ingress 后，不得直接暴露在原始 app 端口上
  - 当前 repo 提供的 perimeter proxy 已补最小 route split 与基础 rate limiting；HTTPS、来源限制、IP allowlist 与更强 edge/WAF 仍依赖外层反向代理/宿主，不由 FastAPI app 自身兜底
- 当前 host/proxy responsibility 固定为：
  - 先负责 HTTPS 终止与 private ingress / allowlist，把 `GET /health/ready` 与 `/internal/*` 固定在 internal 面
  - 再决定 `GET /health/live` 是“经 TLS 反代公开的最小公网探针”还是“仅 allowlist/private probe”；默认推荐后者，不能保持裸端口默认公开
  - 对任何公开入口负责来源限制/IP allowlist 与基础 rate limit
  - 保证 `GET /health/ready` 与 `/internal/*` 只出现在 private ingress / allowlist 后，而不是原始 app 端口

### 9.2 `CLOUD-SEC-2` 当前 follow-up owner 与顺序

- 剩余云安全 follow-up 只认 `CLOUD-SEC-2`，不得再把这组事项混挂到 `CLOUD-SEC-1` 或 `CLOUD-RUNTIME-2`。
- `CLOUD-SEC-2` 当前最终口径已固定为：
  - `P0 / host-proxy`：
    - 已完成：`/v1/catalog/*` 保持 public runtime catalog，对外继续走 `HMAC + catalog:read`
    - 已完成：`/internal/*` 已改为 `X-Magick-Internal-Token + POST Idempotency-Key`，不再复用 public runtime HMAC + scope
    - 已完成：`GET /health/ready` 已改成 internal probe，要求 `X-Magick-Internal-Token`
    - 已完成：`docker-compose.prod.yml` 现在通过 bundled perimeter proxy 对外暴露 Hosted Runtime；raw `api` 端口不再直接映射给宿主，`/internal/*` 与 `GET /health/ready` 默认走 private/allowlisted path
    - 已完成：production bundle 内的 smoke/load helper 已改成 `health/live` 作为公开 liveness，`health/ready` 只在提供 internal token 时验证；deploy helper 当前也拒绝在 `MAGICK_CLOUD_INTERNAL_AUTH_TOKEN` 为空时继续启动/重启 perimeter
    - 已完成：perimeter smoke 现在显式验证 `/docs`、`/redoc` 与 internal POST 无 token 时 fail-closed
    - 最终结论：宿主/反代必须先落实 TLS 终止与 private ingress / allowlist，把 `GET /health/ready` 与 `/internal/*` 固定在 internal 面，且 production 继续关闭 `/docs` 与 `/redoc`
    - 最终结论：`GET /health/live` 的暴露策略由宿主/反代 owner 定稿。默认推荐 allowlist/private probe；只有外部 LB/uptime probe 明确需要时，才允许经 TLS 反代公开最小 liveness
  - `P1 / app`：
    - 最终结论：当前 canonical replay truth 固定保留在 `/v1/runtime/execute -> run_records(site_id, idempotency_key)`，不把 truth 从 DB 唯一键漂移到 Redis
    - 最终结论：generic replay receipt 已在当前 tranche 落到 public signed POST 与 `/internal/*` POST；它以短 TTL DB receipt 追加 auth 层阻断，但不替换现有 `run_records` contract
    - 当前 canonical auth rejection log 固定为 `auth.invalid_timestamp / auth.stale_timestamp / auth.invalid_site / auth.invalid_key / auth.scope_denied / auth.invalid_signature / auth.nonce_required / auth.invalid_nonce / auth.invalid_idempotency_key / auth.payload_too_large / auth.replay_blocked`
    - `/v1/runtime/execute` 的冲突复用继续保留 `runtime.idempotency_conflict`，不要把它收敛到 auth 层第二套临时码
  - `P1 / host-proxy`：
    - 已完成：bundled perimeter proxy 已对 `GET /health/live` 与 `/v1/*` 补最小基础 rate limiting / abuse protection
    - 最终结论：保留 HTTPS、来源限制和 allowlist 的部署真源，不把它倒写成 FastAPI app 内建能力
  - `P2 / separate workstream`：
    - 若未来真的需要云端 ops/admin、IAM 或 RBAC，必须另开 workstream；不得直接扩当前 runtime API
    - 若未来需要 generic replay store、WAF、secret manager rotation automation、审计报表等更强宿主/安全能力，也必须作为新的 follow-up workstream，而不是回挂 `CLOUD-SEC-1` 或 `CLOUD-RUNTIME-2`
- `CLOUD-SEC-2` 当前 closeout 结论：本节继续是云端安全尾项的唯一真源；当前 tranche 已完成 app-side replay guard 与 bundled host/proxy perimeter。后续若要补 callback dispatch、generic replay store、真正的 edge TLS/allowlist/WAF 或新的 focused tests，应继续沿本合同和上位 `cloud-responsibility-boundary-v1` 新开 follow-up，不得回写到 `CLOUD-SEC-1` 或 `CLOUD-RUNTIME-2`。

## 10. 日志与追踪规范

- 云端从第一天起必须统一记录：
  - `trace_id`
  - `run_id`
  - `site_id`
  - `ability_name`
  - `channel`
  - `profile_id`
  - `provider_id`
  - `model_id`
  - `instance_id`
  - `latency_ms`
  - `tokens_in`
  - `tokens_out`
  - `cost`
  - `fallback_used`
  - `error_code`
- 传播规则：
  - WordPress 发 `traceparent`
  - 云端接入 OTel
  - `API -> service -> provider adapter` 全链路透传
  - 所有日志必须带 `trace_id`
- auth/security rejection 最小口径固定为：
  - public auth rejection 至少记录 `error_code / trace_id / site_id / key_id / method / path / required_scope`
  - 当前固定 rejection code 包括 `auth.invalid_timestamp`、`auth.stale_timestamp`、`auth.invalid_site`、`auth.invalid_key`、`auth.scope_denied`、`auth.invalid_signature`、`auth.nonce_required`、`auth.invalid_nonce`、`auth.invalid_idempotency_key`、`auth.payload_too_large`、`auth.replay_blocked`
  - `/v1/runtime/execute` 的持久化 replay 冲突继续记录 `runtime.idempotency_conflict`

## 11. 插件侧同步契约

### 11.1 执行模式

- 插件侧模型执行模式固定新增：
  - `local`
  - `hosted`

### 11.2 用户暴露面

- 普通用户不得再被暴露到底层 `raw model_instance_id`
- hosted 模式只允许暴露 profile：
  - `text.economy`
  - `text.balanced`
  - `text.quality`
  - `vision.default`
  - `embed.default`

### 11.3 本地云端客户端

- 插件侧必须新增 `CloudModelRuntimeClient`
- 它负责：
  - request signing
  - request sending
  - `traceparent` 透传
  - error normalization
  - hosted result 映射回本地 run

### 11.4 设置页契约

- `settings-instances-mvp-v1` 不在一期直接废弃
- 当 `execution_mode=hosted` 时：
  - `GET /admin/settings/instances` 读取云端镜像
  - `GET /instances/stats` 读取云端聚合
  - `save` 改为保存 `hosted profile / hosted routing policy`

## 12. 测试与门禁

### 12.1 最小测试集合

- contract：
  - catalog response shape
  - runtime execute response shape
  - run status shape
  - auth header contract
  - error code contract
- api：
  - health
  - execute sync
  - execute async
  - idempotency
  - invalid signature
  - timeout / retry / fallback
- domain：
  - routing selection
  - profile binding resolution
  - health scoring
  - usage rollup
- e2e：
  - docker compose 启动
  - `WP -> cloud execute -> result -> stats`

### 12.2 根仓代理脚本建议

```json
{
  "scripts": {
    "cloud:dev": "docker compose -f cloud/docker-compose.dev.yml up --build",
    "cloud:test": "docker compose -f cloud/docker-compose.dev.yml run --rm api pytest",
    "cloud:lint": "docker compose -f cloud/docker-compose.dev.yml run --rm api ruff check . && docker compose -f cloud/docker-compose.dev.yml run --rm api mypy app",
    "cloud:build": "docker compose -f cloud/docker-compose.prod.yml build",
    "cloud:bundle": "bash cloud/deploy/bundle-images.sh"
  }
}
```

## 13. 部署基线

### 13.1 本地开发

```bash
cd cloud
docker compose -f docker-compose.dev.yml up --build
```

### 13.2 一期发布方式

- 一期允许手工上传部署
- 优先上传镜像 tar 包，不上传源码目录

```bash
docker compose -f docker-compose.prod.yml build
docker save magick-ai-cloud-api:prod | gzip > dist/api.tar.gz
docker save magick-ai-cloud-worker:prod | gzip > dist/worker.tar.gz
tar czf dist/deploy-bundle.tgz \
  docker-compose.prod.yml \
  deploy/common.sh \
  deploy/deploy-to-ssh-host.sh \
  deploy/remote-load-and-up.sh \
  deploy/remote-migrate.sh \
  deploy/remote-baseline-status.sh \
  deploy/remote-seed-runtime.sh \
  deploy/remote-smoke.sh \
  dist/api.tar.gz \
  dist/worker.tar.gz
```

```bash
tar xzf deploy-bundle.tgz
bash deploy/remote-load-and-up.sh
bash deploy/remote-migrate.sh
bash deploy/remote-baseline-status.sh
bash deploy/remote-seed-runtime.sh --site-id site_smoke --key-id key_default --secret magick-cloud-test-secret
bash deploy/remote-smoke.sh --base-url http://127.0.0.1:8010
```

### 13.3 deploy bundle 验证

- Hosted Runtime 的验证顺序固定为三层：
  - `L1` 本地源码/合同/README 修改
  - `L2` 本地 Docker exact-bundle replay、focused tests、`check:cloud:perimeter`
  - `L3` 真实外部宿主的 `scp -> load/up -> migrate -> seed -> smoke`
- `L3` 只负责发布验证、provider readiness、宿主 env 与持久化状态兼容性验证；它不是日常 authoring surface，也不替代 `L1/L2`
- 一期至少要有一条“打包产物 -> 解包产物 -> prod compose 自举 -> seed -> signed smoke”的 exact-bundle replay
- 当前仓库固定验证入口：

```bash
pnpm --dir .. run check:e2e:cloud-deploy-bundle:smoke
```

- 这条 smoke 必须基于 `cloud/dist/deploy-bundle.tgz` 解包后的产物执行，而不是直接在源码目录里跑 prod compose
- 若要产出“真实外部宿主”证据，必须经 `deploy-to-ssh-host.sh` 或等价 SSH 路径完成 `scp -> ssh load/up -> migrate -> baseline-status -> seed -> smoke`，不能只提交本机 exact-bundle replay
- `remote-smoke.sh` 当前必须按 public auth contract 访问 catalog/runtime/runs/stats/usage；其中 `/v1/catalog/models` 不是匿名读入口，而是 signed public read
- smoke seed key 的默认 scopes 现在固定至少包含：`catalog:read,runtime:resolve,runtime:execute,runtime:read,stats:read`
- 若手工覆盖 `--scopes` 或 `MAGICK_CLOUD_SCOPES`，不得丢掉 `catalog:read`，否则 remote smoke 会在 catalog 阶段以 `auth.scope_denied` fail closed
- `deploy-to-ssh-host.sh` 现已支持按远端 `uname -m` 自动选择 `linux/amd64` 或 `linux/arm64` bundle；若本机是 Apple Silicon、远端是 `x86_64`，不得继续上传本机默认 `arm64` 镜像
- 若未显式传 `--env-file`，`deploy-to-ssh-host.sh` 必须优先复用远端当前 release 的 `.env.deploy`；`common.sh` / compose 也应默认允许从 release 根目录 `.env.deploy` 读取 env，避免升级时丢生产 secret
- 若远端构建受 pip 解析或跨境网络抖动影响，可显式注入：
  - `MAGICK_CLOUD_PIP_INDEX_URL`
  - `MAGICK_CLOUD_PIP_EXTRA_INDEX_URL`
  - `MAGICK_CLOUD_PIP_TRUSTED_HOST`
- 若要安全更新真实宿主的 provider env，而不是重新整份上传 `.env.deploy`，优先使用：
  - `bash deploy/env-to-ssh-host.sh --ssh-host <host> --ssh-user <user> --remote-dir /opt/magick-ai-cloud --set MAGICK_CLOUD_ANTHROPIC_BASE_URL=https://api.anthropic.com --set MAGICK_CLOUD_ANTHROPIC_VERSION=2023-06-01 --from-env MAGICK_CLOUD_ANTHROPIC_API_KEY`
- `env-to-ssh-host.sh` 必须只打印被修改的键名、目标文件和重启结果，不得回显明文值；默认应同步更新当前 release `.env.deploy` 与共享 `/opt/magick-ai-cloud/.env.deploy`，并重启 `api,worker`
- 远端升级完成后，应优先运行：
  - `bash deploy/remote-baseline-status.sh`
  - `bash deploy/remote-provider-status.sh`
  - 或在 `cloud/` 下执行 `make provider-status`
- `remote-baseline-status.sh` 当前固定校验：
  - 远端 DB `alembic_version` 与当前 release head 对齐
  - `sites / site_api_keys / run_records / usage_meter_events / billing_snapshots / service_audit_events / commercial_decision_events / runtime_guard_events` 的关键列存在
  - `MAGICK_CLOUD_INTERNAL_AUTH_TOKEN` 已实际注入运行中的 `api` 容器
- 若 `remote-baseline-status.sh` 失败，先把问题归为远端 env/schema drift，并将修复回写仓库 migration 或 deploy helper；不要把一次性线上手修当成新的常规流程
- `remote-provider-status.sh` 只允许输出 provider `configured / registered / base_url / timeout / catalog` 等 readiness 信息，不得回显明文 secret
- 若真实外部宿主 smoke 失败而 `L1/L2` 仍通过，优先检查 `.env.deploy` carry-forward、migration/schema drift、seed scopes、provider reachability 与宿主防火墙/安全组；不要先把问题归因到本地源码主线
- 真实宿主 smoke 成功但本机直连 `http://host:port` 仍失败时，先检查云厂商安全组/防火墙/反向代理，不要把公网入口问题误判为 bundle 或 runtime 故障
- 当前已有一条 Debian 12 `x86_64` 真实宿主的 off-machine deploy + signed smoke + 真实 provider HTTP path 证据：公网 `<public-cloud-base-url>` 已从本机直连通过 `/health/live` 与 signed smoke，真实 OpenAI-compatible execute 也已成功命中 fallback 链
- 当前还已有一条“保留旧 `.env.deploy` 的远端升级”证据：同一宿主 `<deploy-ssh-host>` 在不重新上传 env 文件的前提下完成 `scp -> load/up -> migrate -> smoke`，并通过 `remote-provider-status.sh` 确认 provider readiness
- 当前还已有一条“通过 env-to-ssh-host 更新远端 provider env”证据：同一宿主 `<deploy-ssh-host>` 已通过 `env-to-ssh-host.sh` 安全写入 provider 默认配置，自动重启 `api,worker` 后 `remote-provider-status.sh` 仍确认变更生效，且公网 smoke 未受影响
- 若宿主已有旧失败记录污染 health/bootstrap，先执行：
  - `bash deploy/remote-seed-runtime.sh --site-id site_smoke --key-id key_default --secret <secret> --skip-health-scan`
- 若需要 fresh signed smoke，优先使用：
  - `bash deploy/remote-smoke.sh --base-url http://<host>:8010 --site-id <site_id> --key-id <key_id> --secret <secret> --idempotency-suffix "$(date +%s)"`
- 若需要把 smoke 从“执行成功”升级为“明确命中目标 provider/model”，优先使用：
  - `bash deploy/remote-smoke.sh --base-url http://<host>:8010 --site-id <site_id> --key-id <key_id> --secret <secret> --expected-provider-id <provider_id> [--expected-model-id <model_id>] [--expected-instance-id <instance_id>] [--prompt-text "<prompt>"]`

### 13.4 真实 provider 实现补记

- provider refresh 在重建 routing 之前，必须先清理同 provider 下已经失效的 `catalog_models / catalog_instances`，避免旧 sample candidate 残留污染选择池
- hosted routing 的默认 `timeout_ms` 基线当前固定为 `30000`，不得继续沿用早期 `200ms` 级开发占位值
- 第二条 provider 扩展当前已验证到 `anthropic` text-only adapter：仅支持 `GET /v1/models` 与 `POST /v1/messages`，并复用既有 `error taxonomy / routing / run/provider-call telemetry`；在未配置 `MAGICK_CLOUD_ANTHROPIC_API_KEY` 时，不得把 Anthropic sample adapter 静默加入默认 provider registry 污染 routing
- health scoring 当前固定规则为：
  - 无近期 provider call 样本：`healthy`
  - 少量（`<3`）近期失败样本：`degraded`
  - 持续失败或更差分数窗口：`unhealthy`

## 14. 明确禁止事项

- 禁止把云端做成第二套 `abilities/workflows` 平台
- 禁止把 `Skills / MCP / Agent Gateway / 完整 Workflow orchestration` 一期一起搬上云
- 禁止把 `cloud/` 混入插件安装包
- 禁止在 route handler 里直接拼 provider 请求
- 禁止在 provider adapter 里写站点业务逻辑
- 禁止在插件侧继续把普通用户暴露给 raw `model_instance_id`
- 禁止把“public runtime surface 与 `/internal/*` 都已有鉴权”误表述成“所有云端入口都已生产级加固”；`health` 公开探针、`nonce` 持久化、防重放与外层 TLS/allowlist/rate limit 仍必须以当前合同与代码为准
