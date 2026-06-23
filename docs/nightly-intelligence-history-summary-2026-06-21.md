# Nightly Intelligence 历史归纳总结 - 2026-06-21

Status: phase closed

## 这份文档的用途

这份文档归纳本阶段围绕“晚间执行计划 / Nightly Inspection / Nightly
Intelligence”的历史讨论、架构边界、已完成工作、验证结果和下一阶段建议。

它不是新的产品需求文档，而是阶段收口记录，方便后续继续由 Cloud、Toolbox、
Core 或其他 AI/工程协作者接手。

## 最终定位

当前功能定位已经收敛为：

```text
Nightly Intelligence =
夜间站点巡检 + 早晨写作准备 + 内容质量评分
```

对外可以解释为：

```text
off-hours site inspection and morning editorial readiness
```

它不是“晚上自动写文章”，也不是“无人自动发布系统”。

允许做：

- 文章质量分析；
- 数据完整性检查；
- SEO/AEO/GEO 缺口发现；
- 图片 ALT 缺失扫描；
- 内容过旧提醒；
- 站点健康和内容机会 Morning Brief；
- review items、blocked items、retry guidance、Core handoff suggestion。

明确不做：

- 批量改图片；
- 批量改标签；
- 批量更新文章；
- 自动发布；
- 自动写 SEO/meta；
- Cloud 直接写 WordPress；
- Cloud 自动创建、批准或执行 Core proposal。

## 历史演进

### 1. 最初的问题

讨论起点是：基础版是否用 `WP-Cron`，高级版是否用 Cloud 编排。

最终判断是：

- 基础版可以保留 WordPress 本地轻量巡检；
- Pro 版应该使用 Cloud 执行重分析任务；
- 但 Cloud 只做 runtime/detail，不成为第二控制面。

### 2. Action Scheduler 的取舍

曾讨论是否在插件里引入 Action Scheduler 做批处理。

结论：当前阶段不引入。

原因不是 Action Scheduler 技术上不能用，而是它会在 WordPress 插件侧增加第二套
queue、claim、retry、表结构、恢复面和调试面。对于 Pro 用户，可靠性应该放在
Cloud Batch Runtime；对于本地无人值守/批量自动化，未来 owner 是
`npcink-local-automation-runtime`，不是 Toolbox 也不是 Cloud。

### 3. 商业化分层的收敛

曾考虑“基础版 WP-Cron，高级版 Cloud 编排”。

后来策略调整为：整体能力走 Pro 化，不同等级用户通过次数、批量大小、额度、观测
能力、站点数量等限制区分。

当前技术上仍保留本地兜底/预览能力，但产品重心不再是把基础版做成完整独立运行面。

### 4. 过重风险的收敛

过程中多次检查“是不是做太重了”。

最终收敛点是：

- 本阶段只做闭环，不做完整生产级编排平台；
- 不新增 Temporal、Celery、RabbitMQ、Kafka、NATS 等系统；
- 不在 Cloud 做 scheduler truth；
- 不在插件做 Action Scheduler；
- 不把 Morning Brief 变成自动写作或自动发布；
- 只保留 reviewable、approveable、auditable 的最小闭环。

## 已确立的边界

### Cloud

Cloud 负责：

- hosted runtime；
- queue-backed worker execution；
- run evidence；
- usage、quota、billing、entitlement evidence；
- provider-call evidence；
- polling 或 terminal result delivery；
- read-only diagnostics。

Cloud 不负责：

- WordPress schedule truth；
- 本地 batch fan-out policy；
- Ability registry truth；
- Core proposal truth；
- approval state；
- commit preflight；
- final WordPress writes；
- 第二 scheduler truth；
- 第二 workflow engine。

### Toolbox / WordPress 本地插件

Toolbox 负责：

- 用户可见的 operator/review surface；
- 本地设置、启停、手动运行入口；
- Morning Brief 展示；
- review item 选择；
- Cloud run 状态、结果、重试入口；
- 把用户选中的 review item handoff 给 Core。

Toolbox 不负责：

- 绕过 Core 直接写内容；
- 自动批准 proposal；
- 成为无人批量写入 owner；
- 在当前阶段引入 Action Scheduler。

### Core

Core 负责：

- proposal intake；
- approval state；
- preflight；
- audit；
- 最终受控写入路径。

Core 必须保持治理内核定位，不变成产品工作台。

### npcink-local-automation-runtime

`npcink-local-automation-runtime` 被明确为未来无人值守/批量本地自动化 owner。

它的存在不会和当前 Nightly Intelligence 冲突，前提是：

- 当前 Nightly Intelligence 只输出 review/handoff；
- 当前阶段不做自动写入；
- 将来真正无人值守、本地批量执行才进入该 runtime owner。

## 已完成的主要内容

### Cloud 侧

已完成：

- Cloud Batch Runtime 能执行 Nightly Inspection 类型的 hosted runtime 任务；
- `POST /v1/runtime/execute` 可接入对应 runtime；
- run result 支持 Morning Brief 结构；
- result 内包含 review items、blocked items、retry guidance；
- result 内可带 Core review-plan candidate；
- Cloud entitlement/quota/usage/provider-call evidence 接入；
- retry、recent run、run status/result 等 operator 所需信息已能支撑 Toolbox；
- PR #11 已合并，记录 `npcink.local` live-site runtime trial closeout。

关键文档：

- `docs/nightly-site-inspection-morning-brief-v1.md`
- `docs/nightly-inspection-cloud-core-handoff-v1.md`
- `docs/nightly-inspection-stage-closeout-2026-06-16.md`
- `docs/live-site-trial-closeout-npcink-local-2026-06-21.md`

### Toolbox 侧

已完成或已验证：

- 本地 WP-Cron fallback preview；
- Nightly Inspection snapshot collector；
- deterministic scoring / preview builder；
- Pro Cloud Runtime controls；
- Cloud quota refresh；
- Cloud inspection submit/status/result；
- Cloud recent runs；
- partial run retry；
- merged Morning Brief preview；
- review item 选择；
- Core handoff panel；
- handoff 后创建 Core pending proposal 的闭环验证。

重要结论：

- 用户可以在 Morning Brief 里选择 review item；
- 选择后可以 handoff 到 Core proposal；
- 但不会自动批准、自动执行或直接写 WordPress。

### Core 侧

已完成或已验证：

- 接收 Nightly Inspection review plan；
- 生成受控 pending proposal；
- proposal 保留 Cloud evidence；
- 需要人工补充 title/content；
- fail-closed 拒绝 ready-to-write、evidence-free、direct-write、non-dry-run、
  publish/commit 类型计划；
- Core 仍是 proposal、approval、preflight、audit owner。

## 真实站点和 trial 结果

本阶段做过多轮 trial 和交叉验证，包括：

- `npcink.local`；
- `dbd.local`；
- `wp.local`；
- `npcink.local`；
- `npcink-trial` clone；
- 以及可配合 `npcink-eval-lab` 做样本扩展和交叉验证的方向。

关键结果：

- Nightly/Morning Brief 的基础闭环可用；
- Cloud hosted runtime 能被真实本地站点 addon 连接、verify、resolve、execute；
- `npcink.local` live-site Cloud trial 已完成；
- trial 明确未做 Site Knowledge sync/search、WordPress 内容写入、monitoring、proposal/apply；
- `npcink-trial` clone 证明 Site Knowledge suggestion-only 路径、usage/billing/run evidence
  和边界守护可工作。

## 当前最新状态

截至 2026-06-21：

- PR #11 已合并；
- merge commit: `2fc277824ed206291b8d6984bb9b193d7b91f06b`；
- Cloud `master` 已同步到 `origin/master`；
- 本地 Cloud 工作区干净；
- 本阶段正式结束。

为修复 PR #11 backend CI，已完成一个窄修复：

- 文件：`app/domain/runtime/service.py`
- 问题：`RunRecord` 动态属性 `_transient_result_json` 被 mypy 拒绝；
- 修复：封装 transient result helper，保持 `no_store` 运行时语义不变；
- 本地验证：
  - `.venv/bin/mypy app`
  - `.venv/bin/ruff check .`
  - `.venv/bin/python -m pytest tests/api tests/contract tests/domain -q`
  - 结果：`478 passed, 5 skipped`
- GitHub CI：backend/frontend 均通过。

## 用户现在能看到什么效果

在 Toolbox operator surface 中，用户预期可以看到或操作：

- Cloud quota；
- recent Cloud runs；
- run status；
- worker phase；
- result/retry guidance；
- Morning Brief review queue；
- review items；
- blocked items；
- Core handoff suggestion；
- 选择 review item 后 handoff 到 Core pending proposal。

这已经构成基础闭环：

```text
Cloud inspection run
  -> Morning Brief
  -> user selects review item
  -> Core proposal handoff
  -> Core pending proposal
  -> human review/approval path
```

闭环中仍然刻意缺失自动写入，这是设计目标，不是未完成缺口。

## 刻意没有做的内容

以下内容没有做，原因是边界和阶段控制：

- 没有 Cloud scheduler truth；
- 没有 Cloud workflow engine；
- 没有插件内 Action Scheduler；
- 没有 Cloud ability registry；
- 没有 Cloud proposal truth；
- 没有自动批准 proposal；
- 没有自动执行 proposal；
- 没有直接写 WordPress；
- 没有自动发布；
- 没有把 Morning Brief 变成自动文章生成器。

这些都不是“遗漏”，而是本阶段有意避免的复杂度和边界漂移。

## 到此为止了吗

对“基础功能闭环”来说：到此为止。

本阶段目标已经完成：

- 夜间/Cloud 检查能产生 reviewable 输出；
- Morning Brief 能组织 review items；
- 用户能选择 item；
- Core handoff 能创建受控 proposal；
- 写入仍停留在 Core 审核、批准、执行链路内；
- Cloud 和 Toolbox 没有越界成为写入 owner。

对“生产级平台能力”来说：还没有全部完成，但那是下一阶段。

## 下一阶段建议

如果继续推进，建议不要再扩 Nightly 本体，而是做生产级运行保障：

1. 生产级编排与可观测性

   - run lifecycle 更清晰；
   - retry/failure reason 更可诊断；
   - operator runbook 更完整；
   - Cloud/Admin/Toolbox 能定位失败原因。

2. Core proposal 审核、批准、执行体验

   - Morning Brief 到 proposal 的 receipt 更清晰；
   - Core proposal 页面更适合审核 Cloud evidence；
   - approval/preflight/execute 后能回到 Toolbox/Morning Brief 显示结果。

3. 真实站点小规模灰度

   - 只使用 clone/staging 或明确授权的 live site；
   - 每次 trial 有审批、回滚、只读/写入边界；
   - 不直接做全量站点自动执行。

## 后续 AI 接手提示

后续任何 AI 或工程协作者接手时，应先读：

1. `docs/nightly-site-inspection-morning-brief-v1.md`
2. `docs/nightly-inspection-cloud-core-handoff-v1.md`
3. `docs/nightly-inspection-stage-closeout-2026-06-16.md`
4. `docs/live-site-trial-closeout-npcink-local-2026-06-21.md`
5. `docs/real-site-trial-go-no-go-npcink-trial-2026-06-20.md`

接手原则：

- 不要把 Cloud 做成第二控制面；
- 不要绕过 Core proposal；
- 不要在插件里新增重型队列系统；
- 不要把 Nightly Intelligence 改成自动写作/自动发布；
- 下一步如果要做，优先做观测、重试、receipt、Core proposal 体验闭环。
