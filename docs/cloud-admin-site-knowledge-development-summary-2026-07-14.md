# Cloud 后台与 Site Knowledge 向量能力开发总结

状态：阶段完成，等待真实站点闭环验证。

日期：2026-07-14。

## 1. 文档目的

本文归纳本轮 Cloud 后台界面、供应商配置、Site Knowledge 向量配置和
自动索引维护的开发历史与设计理由，供后续产品、开发、测试和 AI Agent
继续工作时使用。

本文不是新的运行合同。发生冲突时，以下现有合同优先：

- [Cloud Admin Information Architecture v2](cloud-admin-information-architecture-v2.md)
- [ADR-002: Use Task-Oriented Page Models For Cloud Admin](decisions/002-cloud-admin-task-oriented-information-architecture.md)
- [Site Knowledge Runtime Contract v1](site-knowledge-runtime-contract-v1.md)
- [Cloud Content Generation Boundary v1](cloud-content-generation-boundary-v1.md)
- Addon 仓库中的 `docs/site-knowledge-vector-operations.md`

## 2. 一句话结论

本轮工作的核心不是给后台换一套视觉皮肤，而是把后台从“解释系统结构的
页面集合”重构为“按运营任务组织的 PC 工作台”，同时把 Site Knowledge
向量能力收敛为管理员只填写必要密钥、系统固定技术参数、Cloud 统一管理
生命周期、Addon 自动投递站点公开内容的低心智负担闭环。

## 3. 最初暴露的问题

### 3.1 登录页和后台页面解释过多

早期登录页展示了内部路由、命名空间和后台架构说明。运营人员真正需要的
只有环境范围、启动令牌、错误反馈和登录动作。大量技术说明拉长页面，也让
登录入口看起来像接口文档。

### 3.2 页面以卡片数量组织，而不是以任务组织

供应商、客户、订阅、诊断和配置页面虽然视觉相似，但操作目标完全不同。
统一套用大卡片布局后，出现了以下问题：

- 工作列表和主要动作被说明面板推到首屏以下；
- 同一页面同时暴露过多编辑入口；
- 筛选、表格、状态、诊断证据缺少稳定层级；
- 页面文件同时承担请求、归一化、交互和展示，难以系统维护；
- 操作完成后的大块成功信息占据主工作区，破坏页面位置和阅读节奏。

### 3.3 瞬时反馈与持久证据混在一起

供应商保存成功后，页面曾在统计卡和列表之间插入整块绿色提示与审计回执。
这类信息有价值，但位置和尺寸不合理：一次性的“已保存”结果不应永久挤压
主任务，审计详情也不应默认抢占列表上方的高价值空间。

最终采用的反馈层级是：

1. 瞬时成功使用 Toast 或紧邻操作的简短状态；
2. 异步任务使用行状态或任务状态，不能提前显示为成功；
3. 当前 readiness、阻断原因和下一步保留在页面稳定摘要中；
4. 审计回执继续保存，但进入对象详情、检查器或审计入口；
5. 只有主要页面任务失败时才使用页面级错误。

### 3.4 “供应商”概念承载了过多不同配置

模型 Provider、图片服务、搜索服务和向量服务被放在相近的供应商工作区，
还暴露优先级、通道备注和通用添加按钮。对于当前没有历史兼容负担的开发期
产品，这些自由度没有产生相应价值，反而增加了概念、验证分支和错误配置。

## 4. 后台重构的设计路线

### 4.1 先定义页面任务，再调整视觉

后台采用六类页面模型：

- `overview`：判断平台整体状态和首要工作；
- `queue`：查找、筛选、排序和打开运营对象；
- `detail`：理解一个对象并执行受限后续动作；
- `configuration`：查看 readiness、编辑一组配置、检测并保存；
- `diagnostic`：先看健康结论，再逐层打开异常和证据；
- `authentication`：完成单一登录任务。

这样做的理由是：一致性应该来自任务结构、状态模型和动作风险，而不是让
所有页面都变成同一种仪表盘。

### 4.2 PC 优先，但不删除响应式边界

当前阶段主要优化 PC 运营效率，优先保证首屏层级、列表比较、筛选、详情和
配置操作。响应式与可访问性合同继续保留，后续必须补齐窄屏和键盘验收；本轮
不为了兼顾所有终端而牺牲 PC 主工作台结构，也不把现阶段的 PC 优先解释为
永久放弃其他终端。

### 4.3 导航按业务域组织

后台导航收敛为概览、客户运营、运行运营和系统四个域。详情页和次级诊断页
继承父工作区，不再把每条路由都升级为一级产品。

供应商相关入口最终拆分为：

- 模型供应商：管理模型 Provider 连接和可见性；
- 搜索与图片：固定服务类型的配置页；
- 向量设置：Site Knowledge 专用配置与生命周期状态；
- 模型路由：能力到模型的运行配置；
- 运行诊断：统一进入证据和异常视图。

### 4.4 删除当前没有产品价值的自由度

能力供应商不再让管理员创建任意类型，也不再展示优先级和通道备注。搜索与
图片按提前选择的固定类型配置，向量设置因涉及 embedding space、数据库
schema 和重建生命周期而保持独立。

此处采用直接修改而不是兼容层迁移，原因是项目仍在开发期、没有用户数据和
历史配置包袱。未来只有在出现真实的多通道调度需求、可解释的优先级规则和
相应运维证据后，才应重新引入这些字段。

## 5. Site Knowledge 向量配置的产品决策

### 5.1 管理员只配置秘密和连接信息

当前固定档案为：

```text
profile_id: site-knowledge.zh.v1
provider: SiliconFlow
model: BAAI/bge-m3
dimensions: 1024
metric: COSINE
production_backend: Zilliz Cloud
collection: site_knowledge_zh_v1
local_test_backend: PostgreSQL JSON
```

管理员只需要填写：

- SiliconFlow API Key；
- Zilliz Cloud 公共 Endpoint；
- Zilliz Cloud Token。

管理员不能修改模型、维度、距离算法、Collection、生产后端、计量分类或
embedding space。这样可以把“管理员需要理解向量技术”改成“管理员只完成
两个连接”，并从源头消除模型、维度和 Collection 漂移。

### 5.2 单一配置真源

固定档案和已验证连接由 Cloud 侧 DB-managed Provider Connections 管理。
环境变量只保留超时、批次上限和功能保护等运行 guardrail，不再作为另一套
模型或 Provider 选择真源。调用方 payload 也不能覆盖固定事实。

建索引和查询必须读取同一个活动档案。通用 Provider Connection 写入不能
伪造 Site Knowledge 的探测标记，能力模型绑定也不能覆盖该档案。

### 5.3 保存动作必须先真实探测

Embedding 连接保存前执行真实请求，并验证：

- 请求成功；
- 返回非空数值数组；
- 所有元素都是有限数值；
- 长度严格等于 1024；
- 连接具备 embedding 能力。

Zilliz 保存前会先建立生产后端并检测固定 Collection：

- 支持 Zilliz 国际、国内 Dedicated 和国内 Serverless 公共 Endpoint；
- 拒绝控制台地址、任意 HTTPS 地址、带路径或查询参数的地址；
- Collection 不存在时按固定合同创建；
- Collection 已存在时验证字段、1024 维和 COSINE；
- schema 不兼容时 fail closed，不猜测、不自动修改旧结构；
- 新连接检测失败时不覆盖当前已验证秘密。

### 5.4 连接成功不等于检索有效

后台将证据拆成三个层次：

1. `connection`：Embedding 和 Zilliz 的实时连接探测通过；
2. `index`：Cloud chunk 已写入固定 Collection，并完成同向量回查；
3. `retrieval`：一次正常计量的 Site Knowledge 搜索在最近重建后命中。

因此“Zilliz 已保存”只能证明连接和 schema 可用，不能宣称站点内容已经可搜。

## 6. Embedding space 与生命周期

### 6.1 当前空间标识

当前实现使用 `provider_id:model_id`，即固定档案下的
`siliconflow:BAAI/bge-m3`。文档和 chunk 都记录所属空间，查询只允许读取与
当前查询空间完全一致的索引。

在当前 Provider、模型、维度和 metric 全部固定的前提下，这个标识足以阻止
最常见的跨模型混写。如果未来开放 Provider、模型 revision、预处理 revision
或 metric 选择，必须先把这些事实或稳定配置哈希纳入空间标识，并让旧索引
进入 `reindex_required`；不能仅靠相同模型名称推断兼容。

### 6.2 生命周期状态

后台向管理员展示的主要状态包括：

- `empty` / `awaiting_site_sync`：尚无可用索引，等待站点内容；
- `reindex_required`：固定档案或连接事实变化，需要重建；
- `rebuilding`：正在重建或发布；
- `ready`：索引验证通过；
- `failed`：连接、schema、投递或发布失败。

发生 embedding space 不一致时：

- 不把新向量写入旧空间；
- 不用新查询向量搜索旧空间；
- 不静默 fallback；
- 明确进入重建或等待站点同步状态。

## 7. 为什么改成管理端触发、站点端自动执行

要求站点管理员手动执行一次全量 Site Knowledge 同步，会把 Cloud 内部的
索引迁移责任转嫁给普通用户。用户还必须理解“连接成功”“全量同步”“索引
重建”和“向量空间”之间的区别，心智负担过高。

最终采用以下闭环：

1. Cloud 管理端检测到旧空间并生成不可伪造的维护 request id；
2. `site_knowledge_status.v1` 向已认证站点投影最小维护请求；
3. Addon 只在本地 Site Knowledge 投递许可开启时领取请求；
4. Addon 读取 WordPress 的公开 `post` 和 `page`，保存有界投递游标；
5. 自动全量同步每批最多 200 篇，第一批使用 `rebuild`，后续批次使用
   `refresh`；
6. 每批通过现有 Cloud runtime worker 提交，Addon 等待该 run 成功后才推进
   下一批；
7. 最终批次成功后，Cloud 将当前站点的固定空间 chunk 发布到 Zilliz，并在
   没有旧空间时关闭生命周期；
8. 单批失败最多重试 3 次，游标不会因一次失败丢失；平台管理员可以从 Cloud
   后台重试或加速，但普通站点管理员不需要理解或启动全量同步。

现有 WordPress 小变更投递仍使用独立的 25 条有界批次。自动重建的 200 篇
批次是全量维护路径，不应与日常增量缓冲上限混淆。

## 8. 为什么这不是第二控制面

自动维护虽然跨越 Cloud 和 Addon，但所有权没有改变：

| 事实或动作 | 所有者 |
| --- | --- |
| WordPress 公开文章与页面 | WordPress |
| 本地是否允许向 Cloud 投递 | Addon / WordPress 管理员 |
| 有界投递游标 | Addon，仅作为传输耐久性 |
| 固定向量档案、索引生命周期与 Zilliz 发布 | Cloud |
| Provider 秘密、成本、使用和运行证据 | Cloud |
| WordPress 编辑、审批和最终写入 | WordPress / Core |

本方案复用现有 WP-Cron reconciliation 和 Cloud runtime worker，没有新增
Cloud-to-WordPress 写入、第二队列、第二调度器、第二 ability registry 或第二
workflow registry。Site Knowledge 结果继续是 `suggestion_only`，并始终声明
`direct_wordpress_write: false`。

索引维护继续使用服务端固定的
`metering_class=site_knowledge_index_maintenance`：记录 Provider 调用、token、
成本、文章数和 chunk 数，但不消耗普通 `ai_credits`。搜索和其他用户发起的
推理仍按普通 AI 积分规则执行。

## 9. 明确拒绝或暂缓的方案

### 9.1 通用向量配置中心

暂不支持任意模型、维度、metric、Collection 或向量数据库选择。自由配置会
扩大探测、迁移、兼容、计量和客服矩阵，当前没有相应用户价值。

### 9.2 多向量库和自动迁移控制台

生产仅支持 Zilliz Cloud，PostgreSQL JSON 仅用于本地和自动化测试。暂不加入
DashVector、Milvus 自建或多个活动生产后端，也不做图形化迁移编排。

### 9.3 高级检索栈

暂不引入 Jieba 分词、reranker、多模型自动路由、混合向量空间和自动模型
评测平台。先验证 BGE-M3 单模型闭环，再用真实搜索质量决定下一步。

### 9.4 站点管理员承担平台迁移

保留站点侧显式启用/禁用投递许可，但不要求站点管理员为了平台档案变化而
手动全量同步。平台配置变化由 Cloud 发出维护意图，Addon 自动完成公开内容
投递。

## 10. 主要落地提交

### Cloud

| Commit | 作用 |
| --- | --- |
| `2aebac54` | 按 PC 运营任务重构后台工作区 |
| `cf1ce369` | 固化后台信息架构、页面模型和验收记录 |
| `fff1f63f` | 简化供应商设置并新增独立向量配置页 |
| `280b854d` | 将固定搜索与图片服务拆为独立工作区 |
| `f9f0bb97` | 对齐后台合同与新的服务工作区 |
| `5a8106c9` | 将 Provider 后台收敛为固定服务设置 |
| `aac6b241` | 将 Site Knowledge 锁定到已验证固定向量档案 |
| `126f745b` | 增加 Zilliz Endpoint/Token 配置和 schema 探测 |
| `b32883d5` | 增加连接、索引、检索三层生命周期验证 |
| `edc9ede0` | 编排 Cloud 侧自动重建维护请求和状态 |

### Cloud Addon

| Commit | 作用 |
| --- | --- |
| `0c9c81f` | 领取 Cloud 维护请求，分批投递公开内容并等待运行完成 |

这些提交记录实现事实；本文件记录它们背后的取舍，避免未来仅根据页面或类名
重新推断产品边界。

## 11. 已完成验证

本阶段已完成的自动化验证包括：

- Cloud Site Knowledge 聚焦测试：142 passed；
- Cloud maintenance 聚焦测试：4 passed；
- `pnpm run check:fast`：contract 74 passed / 1 skipped，domain 229 passed /
  3 skipped；
- `pnpm run check:seam`：516 passed；
- `pnpm run check:perimeter`：9 passed；
- `pnpm run check:anti-drift`：passed；
- Cloud Ruff 和 Mypy：passed；
- Cloud Admin TypeScript 与静态合同：passed；
- Addon `composer test:all` 及 Site Knowledge 行为/静态测试：passed。

这些结果证明合同、状态和边界在自动化环境中一致，但不能替代真实 Provider、
真实 Zilliz 和真实 WordPress 站点的端到端证据。

## 12. 尚未完成的真实闭环

当前最重要的非阻断事项是执行一次真实小规模验证：

```text
保存并探测 SiliconFlow
→ 保存并探测 Zilliz
→ 从 Cloud 管理端启动自动更新
→ Addon 自动领取维护请求
→ 同步一篇或一个小批次公开文章
→ 确认 1024 维向量进入 site_knowledge_zh_v1
→ 执行 Site Knowledge 搜索并命中文章
→ 检查索引同步没有普通 ai_credits 消费
→ 检查 Provider 调用和成本证据存在
```

发布判断应区分：

- 自动化合同已通过；
- 真实连接已通过；
- 真实索引已通过；
- 真实检索已通过。

在最后两项没有真实证据前，不应把“保存成功”或“连接成功”描述为 Site
Knowledge 已经可用。

## 13. 下一阶段建议

下一阶段不宜继续扩大后台页面或增加向量选项，应集中完成以下顺序：

1. 跑通一次真实 WordPress + SiliconFlow + Zilliz 自动维护闭环；
2. 记录耗时、文章数、chunk 数、Provider 成本、失败位置和检索命中；
3. 验证管理端的状态文案能否让运营人员准确区分连接、索引和检索；
4. 用少量真实中文文章检查 BGE-M3 的相关性，而不是先引入 reranker；
5. 只有出现真实质量瓶颈后，再选择分词、rerank 或预处理 revision 中最小的
   一个改进；
6. 只有出现真实多 Provider 或迁移需求后，才扩展 embedding space 组成和
   迁移工具；
7. PC 主流程稳定后，再按照现有 IA 合同补齐窄屏、键盘和可访问性验收。

## 14. 后续开发约束

后续修改该区域前，应先回答：

- 这是运行时细节，还是正在把 Cloud 变成第二控制面？
- 新设置是否真的需要管理员理解，还是可以由固定档案消除？
- 状态是瞬时反馈、持久 readiness、异步进度还是审计证据？
- 配置变化是否会改变 embedding space，是否需要 fail closed 和重建？
- 是否复用了现有 runtime worker、计量和审计，而不是新增平行基础设施？
- 是否仍保持 `suggestion_only` 和无 WordPress 直接写入？
- 是否有真实使用证据支持增加新的技术选项？

如果这些问题没有清晰答案，应停止扩展，先补合同或真实验证。
