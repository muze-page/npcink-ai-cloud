# WordPress AI 生成参考阶段收口

Status: frozen after controlled local validation  
Date: 2026-07-12

## 1. 文档目的

本文档记录 WordPress AI “生成时参考”能力从产品设想、边界收敛、
实现、评测到阶段冻结的完整思路，供后续人员和 AI 在有明确新需求时
直接复用，避免重新设计或把运行时兼容误解为已验证的产品能力。

本阶段的一句话目标是：

> 在 AI 执行具体写作任务时，提供恰当、有界、不夹带历史事实的站点背景，
> 提升生成质量；用户只感受到结果更贴近本站风格，不需要理解向量、相关度或
> 参考文章细节。

## 2. 问题背景与产品约束

起点是云端已具备 Site Knowledge 索引、embedding 和向量检索能力，希望把
用户已公开的历史文章用于改善 AI 标题、摘要等生成结果。

实际约束包括：

- `ai-wp-admin` 是第三方插件，项目不能修改它，只能通过现有 WordPress
  Ability/connector seam 适配。
- 本地 Cloud Addon 必须保持轻量，只负责连接、本地权限和任务投影。
- Cloud 只能是 hosted runtime 增强层，不能成为第二提示词控制面、第二
  Ability/Workflow 注册表或 WordPress 写入方。
- 最终结果仍是 `suggestion_only`；用户的 WordPress 编辑、审阅、保存和发布
  权不变。
- 产品表面只保留一个简单开关，不向普通用户展示相关度、参考来源、
  向量配置或评分系统。

## 3. 产品决策的收敛过程

早期曾讨论把历史参考用于标题、摘要、摘录、Meta 描述、分类和其他
编辑任务。实现过程中逐步确认：

1. 向量检索只证明“能找到语义相关内容”，不等于证明“这些内容适合当前
   生成任务”。
2. 不同任务需要不同的历史数据：标题应学历史标题，Meta 应学已采用
   Meta，分类应学已采用的术语，不能统一塞入相关文章正文。
3. 把历史文章原文直接放进提示词容易引入旧人名、数字、事件、句子和
   特征表达，会损害事实正确性和原创性。
4. 技术接口能承载某种模式，不代表该模式已通过质量验证。
5. 系统复杂度应由已证明的用户收益驱动，不应为未来可能的任务预先建立
   复杂平台。

因此，本阶段最终只开放：

| 任务 | 本地模式 | 当前产品状态 |
| --- | --- | --- |
| 标题生成 | `site_title_style` | 受控开放 |
| 内容摘要 | `site_summary_style` | 受控试用 |

摘录、Meta 描述、分类和自定义任务继续普通生成，不注入 Site Knowledge
生成参考。

## 4. 当前实现分层

```text
ai-wp-admin / 其他 WordPress AI 调用方
    -> WordPress Ability / task contract
    -> Cloud Addon（本地开关、任务资格、签名传输）
    -> Cloud Hosted Runtime（路由、检索、背景组装、模型执行）
    -> 普通 suggestion_only 结果
    -> WordPress 本地编辑与用户决定
```

所有权分工：

- `npcink-cloud-addon`
  - 保存“生成时参考”本地开关，默认关闭。
  - 确定哪些 WordPress AI 任务有资格请求参考。
  - 把有界的 `{enabled, mode}` 投影到既有 runtime request。
  - 不接受调用方传入标题列表、参考正文或 provider 控制字段。
- `npcink-ai-cloud`
  - 校验任务与 mode 匹配。
  - 使用当前 scene input 作为 `writing_context` 查询。
  - 执行检索、证据门禁、去重、当前内容指纹排除和背景压缩。
  - 将 `generation_context.v1` 作为 provider input detail，不返回给普通
    WordPress AI 用户。
  - 检索不可用或证据不足时静默回退普通生成。
- WordPress/Core
  - 继续拥有 Ability 真值、审阅、审批、预检、审计和最终写入。

## 5. 检索与背景组装设计

当前管线采用成熟 RAG 系统常见的基本步骤，但是项目内自主实现，没有
引入 LangChain、LlamaIndex、Haystack 或 Ragas 作为运行时依赖。

```text
当前任务内容
    -> embedding
    -> 按 site_id + publish + post/page 过滤的向量检索
    -> 相关度门禁
    -> 去重与当前内容排除
    -> 可选 rerank
    -> 任务专用背景压缩
    -> 有界提示词块
    -> 生成模型
```

当前参数：

| 任务 | 最低分数 | 最多来源文章 | 最终参考 | 背景预算 |
| --- | ---: | ---: | ---: | ---: |
| 标题 | `0.35` | 6 | 1 个聚合画像 | 400 字符 |
| 摘要 | `0.35` | 5 | 1 个聚合画像 | 400 字符 |

历史文章不以原文进入生成模型：

- 标题任务从相关历史标题计算聚合风格画像。
- 摘要任务当前从相关公开文章已存储的 excerpt 计算聚合风格画像。
- 画像只包含短/中/长偏好、单句/紧凑多句、问号频率和冒号频率等定性
  信号。
- 原始 chunk、标题/excerpt 样本、分数、URL、来源数和具体比例均不进入
  provider input。

## 6. 提示词设计原则

生成背景不是第二套任务提示词，而是在本地 Ability 任务和当前 scene input
之前附加一个软性风格块。其原则是：

1. 历史参考始终是不可信数据，不是指令。
2. 当前 scene input 和任务输出合同始终优先。
3. 当前任务输入是唯一事实来源。
4. 不得从历史参考转移人名、数字、主张、事件或特征短语。
5. 聚合画像只是语气、长度、句式、标点和术语习惯的软偏好。
6. 不改变原有输出 schema，不向用户显示参考或相关度细节。

正确的长期分层是：

```text
当前资料 = 唯一事实来源
历史文章 = 站点风格画像来源
用户要求 = 本次任务方向
```

## 7. 第三方成熟方案的关系

当前代码不是从某一个开源 RAG 项目直接移植，也不依赖 LangChain 或
LlamaIndex。它采用的是成熟方案中已广泛使用的组合思路：

- document chunking + embeddings + vector store + retriever；
- metadata/site/status filtering；
- vector/lexical hybrid ordering；
- 可选 Jina reranker 和 rerank 失败后回退向量顺序；
- context compression 和严格上下文预算；
- prompt-injection/data boundary；
- baseline/reference 配对评测与盲评偏好。

不引入重型 RAG 框架的原因：

- 当前只有两个有证据的任务，现有代码已覆盖必要管线。
- 框架不能替代任务专用数据选择、提示词边界和真实用户评价。
- 新依赖会增加部署、调试、升级和跨仓认知成本，当前没有对应收益。

## 8. 质量验证过程与证据强度

本阶段实现了可重放的本地配对评测器，交替执行 baseline/reference，可导出
`wp_ai_generation_reference_eval.v2` 产物供 `npcink-eval-lab` 或人工/模型盲评。

开发期的一次本地样本包含 10 篇公开文章。在可用的标题和摘要配对中：

- 标题有 8 组双边都成功输出。
- 摘要有 7 组双边都成功输出。
- 15 组可用配对的盲评结果为：参考版 9，baseline 3，平局 3。
- 分类输出的可用性不稳定，本阶段没有开放分类参考。

这些数字是阶段验收记录，不是回归测试夹具。原始本地产物可包含文章内容和
模型输出，因此未作为公开 Cloud 仓库的长期源文件提交。

后续的本地 WordPress -> Addon -> Cloud 真实链路 smoke 还验证了：

- 标题、摘录、摘要、Meta 和分类的 baseline/reference 调用均能完成 Cloud run。
- 只有标题和摘要触发 embedding 检索；其他任务保持普通生成。
- 本地开关在评测后恢复，临时插件链接和 Cloud 路由调整也都恢复。

这些证据只支持“受控试用”，不支持“质量已被保证”，原因是：

- 样本量小，且主要来自一个站点。
- 检索层还没有带标注的 context precision/recall 基准。
- 盲评模型可能有自身偏好，不能替代真实编辑者采用率。
- 摘要当前使用 excerpt 作为风格代理，不是历史人工确认的摘要库。
- `0.35`、来源数和长度阈值是当前项目经验参数，还没有跨站点标定。

## 9. 质量管控分层

当前质量管控分为四层：

1. 合同层
   - 开关默认关闭。
   - 任务与 mode 必须精确匹配。
   - 调用方不能注入参考原文、标题列表或 provider 控制。
2. 检索层
   - 只搜索当前 site 的公开 post/page。
   - 有分数、来源数和当前内容排除门禁。
   - rerank 失败不阻断基础检索。
3. 生成层
   - 只向模型提供聚合风格画像。
   - 当前内容是唯一事实来源。
   - 不更改输出合同和 `suggestion_only` 属性。
4. 验收层
   - 先做 baseline/reference 配对。
   - 再做盲评或人工对比。
   - 最终以真实用户“直接采用 / 修改后采用 / 不采用”为产品证据。

## 10. 当前冻结结论

本阶段已完成并冻结：

- 产品面只有一个“生成时参考”本地开关。
- 只有标题和摘要会使用 Site Knowledge 生成背景。
- 用户不看到相关度或参考明细。
- 不改第三方 `ai-wp-admin`。
- 不自动写入 WordPress。
- 不引入新 RAG 框架、评分平台、仪表盘或新基础设施。
- Cloud 不保存第二份开关/任务资格真值。
- 缺少参考或检索失败时回退普通生成。

日常阶段不再增加开发工作。只需累积约 20 次真实标题/摘要使用，简单
记录：

- 直接采用；
- 修改后采用；
- 不采用；
- 一句失败原因。

没有具体失败证据时，不调整阈值、提示词或检索结构。

## 11. 未来扩展准入规则

未来可以复用现有检索和 `generation_context.v1` seam，但每个任务必须单独开发和
验证：

```text
明确任务
    -> 确定任务专用的历史数据
    -> 设计只包含必要信息的背景包
    -> baseline/reference 配对
    -> 任务专用质量门禁
    -> 真实用户试用
    -> 再启用
```

例子：

- 润色/语气调整：可使用站点级聚合风格画像，不应提供相关文章原文。
- 段落续写：风格画像与当前段落是主要输入，需独立的拷贝和事实迁移门禁。
- Meta 描述：应索引历史人工采用的 Meta，不能用普通 excerpt 替代。
- 分类推荐：应基于已采用的术语记录和当前可用 taxonomy，不能让 Cloud
  创建术语或写入 WordPress。
- 完整文章写作：事实资料和站点风格画像必须分离；文章 Ability、审阅和
  写入仍归 WordPress 本地/Core，Cloud 不得成为文章工厂。

扩展不应从“Cloud 代码已有兼容 mode”开始，而应从“真实用户任务和合适的
历史证据是什么”开始。

## 12. 关键实现与历史记录

关键代码与合同：

- `app/domain/wordpress_ai_connector/generation_context.py`
- `app/domain/runtime/service.py`
- `app/domain/site_knowledge/service.py`
- `docs/site-knowledge-runtime-contract-v1.md`
- Cloud Addon `includes/class-cloud-wordpress-ai-connector.php`
- Cloud Addon `includes/class-cloud-runtime-client.php`
- Cloud Addon `scripts/eval-wordpress-ai-generation-reference.php`

阶段合并记录：

- Cloud Addon PR `muze-page/npcink-cloud-addon#39`：自动化评测采集，并将产品参考范围
  限制为标题和摘要。
- Cloud PR `muze-page/npcink-ai-cloud#168`：WordPress AI 文本任务优先使用 GPT-5.5，
  保留原有 fallback。
- Cloud PR `muze-page/npcink-ai-cloud#169`：修正生成参考运行合同与已合并行为的偏差。

上位边界与相关记录：

- [Cloud Content Generation Boundary v1](cloud-content-generation-boundary-v1.md)
- [Site Knowledge Runtime Contract v1](site-knowledge-runtime-contract-v1.md)
- [WordPress AI Editor Runtime Closeout](wordpress-ai-editor-runtime-closeout-2026-07-07.md)
- [Cloud Runtime Reference Notes](cloud-runtime-reference-notes-2026-07.md)

## 13. 后续 AI 执行指令

若未来会话没有提供新的用户失败样本或明确的新任务，默认决策是：

> 保持当前标题+摘要范围，不新增任务、不新增 RAG 框架、不新增评分平台、
> 不调整经验阈值；先请求真实失败样本或新任务证据。

若有新任务，先回答四个问题：

1. 当前任务的唯一事实来源是什么？
2. 哪种历史已采用数据才是任务适配背景？
3. 如何防止历史事实、原句和指令污染当前生成？
4. 什么配对评测和真实用户指标才算值得开放？
