'use client';

import Link from 'next/link';
import { useLocale } from '@/contexts/LocaleContext';

export default function FeaturesPage() {
  const { locale, t } = useLocale();

  const launchNotice = {
    en: 'These cards describe the current hosted runtime, member portal, and operator/admin surfaces that ship with Cloud.',
    'zh-CN': '这些模块描述的是当前随 Cloud 一起交付的 hosted runtime、成员 Portal 与 operator/admin 界面。',
    'zh-TW': '這些模組描述的是目前隨 Cloud 一起交付的 hosted runtime、成員 Portal 與 operator/admin 介面。',
  }[locale];

  const featureGroups = {
    en: [
      {
        title: t('marketing.features.group_runtime_title'),
        description: t('marketing.features.group_runtime_desc'),
        features: [
          ['01', 'Model Catalog', 'Access multiple AI providers through a unified interface with model routing and fallback.'],
          ['02', 'Hosted Execution Routing', 'Inspect routed hosted execution with fallback, queue state, and provider selection detail.'],
          ['03', 'Hosted Metadata', 'Review pricing, capability, and profile metadata without moving local truth into Cloud.'],
          ['04', 'Real-time Execution', 'Monitor execution status, results, and diagnostics from unified surfaces.'],
        ],
      },
      {
        title: t('marketing.features.group_portal_title'),
        description: t('marketing.features.group_portal_desc'),
        features: [
          ['05', 'Connected Sites', 'Review multiple connected WordPress sites from one operational workspace.'],
          ['06', 'API Key Lifecycle', 'Issue, rotate, and revoke site-scoped API keys with one-time secret display.'],
          ['07', 'Usage Analytics', 'Track usage, cost, and performance signals across all connected sites.'],
          ['08', 'Billing', 'Inspect subscriptions, quotas, and billing snapshots for connected sites.'],
        ],
      },
      {
        title: t('marketing.features.group_admin_title'),
        description: t('marketing.features.group_admin_desc'),
        features: [
          ['09', 'Platform Controls', 'Operate runtime execution, plan state, and account-level controls from bounded surfaces.'],
          ['10', 'Audit Logs', 'Inspect an event trail for key actions, auth changes, and service activity.'],
          ['11', 'Support Impersonation', 'Start bounded read-only customer sessions for support and verification.'],
          ['12', 'Health Monitoring', 'Track platform health, subscription risk, and operator activity.'],
        ],
      },
      {
        title: t('marketing.features.group_extensibility_title'),
        description: t('marketing.features.group_extensibility_desc'),
        features: [
          ['13', 'Webhook Delivery', 'Inspect callback delivery and operator-visible runtime handoff detail.'],
          ['14', 'Hosted Health Detail', 'Review runtime health snapshots, degradation signals, and provider-facing diagnostics.'],
          ['15', 'Webhook Routing', 'Route notification events into your customer automation surface.'],
        ],
      },
    ],
    'zh-CN': [
      {
        title: t('marketing.features.group_runtime_title'),
        description: t('marketing.features.group_runtime_desc'),
        features: [
          ['01', '模型目录', '通过统一接口访问多家 AI 提供商，支持模型路由和故障转移。'],
          ['02', '托管执行路由', '查看托管执行的路由、故障转移、队列状态与提供商选择细节。'],
          ['03', '托管元数据', '查看价格、能力和 profile 元数据，而不把本地真值迁到 Cloud。'],
          ['04', '实时执行', '从统一界面监控执行状态、结果和诊断数据。'],
        ],
      },
      {
        title: t('marketing.features.group_portal_title'),
        description: t('marketing.features.group_portal_desc'),
        features: [
          ['05', '已连接站点', '在统一工作区中查看多个已连接 WordPress 站点。'],
          ['06', 'API 密钥生命周期', '签发、轮换和撤销站点范围的 API 密钥，支持一次性密钥展示。'],
          ['07', '用量分析', '跟踪所有已连接站点的用量、成本与性能信号。'],
          ['08', '账单', '查看已连接站点的订阅、额度与账单快照。'],
        ],
      },
      {
        title: t('marketing.features.group_admin_title'),
        description: t('marketing.features.group_admin_desc'),
        features: [
          ['09', '平台控制', '通过 bounded surfaces 管理运行时执行、套餐状态与账户控制。'],
          ['10', '审计日志', '查看密钥操作、认证变更与服务活动的事件轨迹。'],
          ['11', '支持模拟', '发起有边界的只读客户会话，用于支持与验证。'],
          ['12', '健康监控', '跟踪平台健康、订阅风险与运维活动。'],
        ],
      },
      {
        title: t('marketing.features.group_extensibility_title'),
        description: t('marketing.features.group_extensibility_desc'),
        features: [
          ['13', 'Webhook 投递', '查看回调投递与运行时交接的只读细节。'],
          ['14', '托管健康细节', '查看运行时健康快照、降级信号与 provider 诊断。'],
          ['15', 'Webhook 路由', '将通知事件路由到你的客户自动化面。'],
        ],
      },
    ],
    'zh-TW': [
      {
        title: t('marketing.features.group_runtime_title'),
        description: t('marketing.features.group_runtime_desc'),
        features: [
          ['01', '模型目錄', '透過統一介面存取多家 AI 提供商，支援模型路由和故障轉移。'],
          ['02', '託管執行路由', '檢視託管執行的路由、故障轉移、佇列狀態與提供者選擇細節。'],
          ['03', '託管中繼資料', '檢視價格、能力與 profile 中繼資料，而不把本地真值遷到 Cloud。'],
          ['04', '即時執行', '從統一介面監控執行狀態、結果和診斷資料。'],
        ],
      },
      {
        title: t('marketing.features.group_portal_title'),
        description: t('marketing.features.group_portal_desc'),
        features: [
          ['05', '已連線站點', '在統一工作區中查看多個已連線 WordPress 站點。'],
          ['06', 'API 金鑰生命週期', '簽發、輪換和撤銷站點範圍的 API 金鑰，支援一次性金鑰展示。'],
          ['07', '用量分析', '追蹤所有已連線站點的用量、成本與效能訊號。'],
          ['08', '帳單', '檢視已連線站點的訂閱、配額與帳單快照。'],
        ],
      },
      {
        title: t('marketing.features.group_admin_title'),
        description: t('marketing.features.group_admin_desc'),
        features: [
          ['09', '平台控制', '透過 bounded surfaces 管理執行 Runtime、方案狀態與帳戶控制。'],
          ['10', '稽核日誌', '查看金鑰操作、認證變更與服務活動的事件軌跡。'],
          ['11', '支援模擬', '發起有邊界的唯讀客戶會話，用於支援與驗證。'],
          ['12', '健康監控', '追蹤平台健康、訂閱風險與營運活動。'],
        ],
      },
      {
        title: t('marketing.features.group_extensibility_title'),
        description: t('marketing.features.group_extensibility_desc'),
        features: [
          ['13', 'Webhook 投遞', '檢視回呼投遞與 Runtime 交接的唯讀細節。'],
          ['14', '託管健康細節', '檢視 Runtime 健康快照、降級訊號與 provider 診斷。'],
          ['15', 'Webhook 路由', '將通知事件路由到你的客戶自動化介面。'],
        ],
      },
    ],
  }[locale];

  const runtimeCapabilities = {
    en: ['Model catalog with multiple AI providers', 'Workflow orchestration and chaining', 'Capability library for extensible functionality', 'Real-time execution status and results'],
    'zh-CN': ['支持多家 AI 提供商的模型目录', '工作流编排与链式执行', '可扩展能力库', '实时执行状态与结果'],
    'zh-TW': ['支援多家 AI 提供商的模型目錄', '工作流程編排與串接', '可擴充能力庫', '即時執行狀態與結果'],
  }[locale];

  const securityCapabilities = {
    en: ['API key rotation and revocation', 'Audit event logging and history', 'Granular scope permissions', 'Idempotency for write operations'],
    'zh-CN': ['API 密钥轮换与撤销', '审计事件记录与历史', '细粒度权限范围', '写操作幂等性保障'],
    'zh-TW': ['API 金鑰輪換與撤銷', '稽核事件記錄與歷史', '細緻權限範圍', '寫入操作冪等保障'],
  }[locale];

  return (
    <div className="flex flex-col items-center pb-16">
      {/* Hero Section */}
      <section className="w-full py-16 md:py-20">
        <div className="container mx-auto px-4">
          <div className="grid gap-8 lg:grid-cols-[0.95fr_1.05fr] lg:items-end">
            <div className="space-y-5">
              <div className="brand-chip">{t('marketing.features.core_title')}</div>
              <h1 data-display="true" className="max-w-4xl text-5xl font-semibold leading-[0.95] text-slate-950 dark:text-white sm:text-6xl">
                {t('marketing.features.hero_title')}
              </h1>
              <p className="max-w-2xl text-lg leading-8 text-slate-600 dark:text-slate-300">
                {t('marketing.features.hero_desc')}
              </p>
              <div className="inline-flex max-w-2xl rounded-full border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/20 dark:text-amber-100">
                {launchNotice}
              </div>
            </div>
              <div className="glass-panel rounded-[2rem] p-6 lg:p-8">
              {/* Product UI Mock - Feature Preview */}
              <div className="mb-4 flex items-center justify-between">
                <span className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-blue-600 dark:text-blue-300">
                  {t('mock.portal_keys_surface')}
                </span>
                <span className="rounded-full border border-green-200 bg-green-50 px-2 py-0.5 text-xs font-semibold text-green-700 dark:border-green-900 dark:bg-green-950/40 dark:text-green-300">
                  {t('mock.live_surface_badge')}
                </span>
              </div>
              <div className="surface-panel rounded-[1.5rem] overflow-hidden">
                <div className="border-b border-slate-200 dark:border-slate-700 px-4 py-2.5 bg-slate-50/80 dark:bg-slate-800/50">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-slate-600 dark:text-slate-300">🔑 API Keys</span>
                      <span className="text-xs text-slate-400">3 active</span>
                    </div>
                    <button className="rounded-md bg-blue-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-700">
                      + Create Key
                    </button>
                  </div>
                </div>
                <div className="divide-y divide-slate-100 dark:divide-slate-700">
                  <div className="flex items-center justify-between px-4 py-3">
                    <div>
                      <p className="text-sm font-medium text-slate-900 dark:text-white">{t('mock.support_automation')}</p>
                      <p className="text-xs text-slate-500">sk_live_••••••••</p>
                    </div>
                    <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700 dark:bg-green-900/40 dark:text-green-300">{t('mock.active')}</span>
                  </div>
                  <div className="flex items-center justify-between px-4 py-3">
                    <div>
                      <p className="text-sm font-medium text-slate-900 dark:text-white">{t('mock.content_generation')}</p>
                      <p className="text-xs text-slate-500">sk_live_••••••••</p>
                    </div>
                    <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700 dark:bg-green-900/40 dark:text-green-300">{t('mock.active')}</span>
                  </div>
                  <div className="flex items-center justify-between px-4 py-3">
                    <div>
                      <p className="text-sm font-medium text-slate-900 dark:text-white">{t('mock.analytics_reader')}</p>
                      <p className="text-xs text-slate-500">sk_live_••••••••</p>
                    </div>
                    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">{t('mock.rotated')}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Feature Groups */}
      {featureGroups.map((group, groupIndex) => (
        <section key={group.title} className="w-full py-10">
          <div className="container mx-auto px-4">
            <div className="mb-8">
              <p className="brand-chip mb-3 inline-block">{group.title}</p>
              <h2 data-display="true" className="text-2xl font-semibold text-slate-950 dark:text-white md:text-3xl">
                {group.title}
              </h2>
              <p className="mt-3 max-w-2xl text-lg leading-8 text-slate-600 dark:text-slate-300">
                {group.description}
              </p>
            </div>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              {group.features.map(([index, title, description]) => (
                <div key={title} className="surface-panel rounded-[1.6rem] p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-slate-400 dark:text-slate-500">
                        {index}
                      </p>
                      <h3 className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">{title}</h3>
                    </div>
                    <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700 dark:border-blue-900 dark:bg-blue-950/40 dark:text-blue-200">
                      Cloud
                    </span>
                  </div>
                  <p className="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-300">{description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>
      ))}

      {/* Capabilities Section */}
      <section className="w-full py-12">
        <div className="container mx-auto px-4">
          <div className="grid gap-5 lg:grid-cols-2">
            <div className="glass-panel rounded-[2rem] p-6 lg:p-8">
              <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-blue-600 dark:text-blue-300">
                {t('marketing.features.runtime_title')}
              </p>
              <h2 data-display="true" className="mt-3 text-3xl font-semibold text-slate-950 dark:text-white">
                {t('marketing.features.core_title')}
              </h2>
              <ul className="mt-5 space-y-3 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {runtimeCapabilities.map((item) => (
                  <li key={item} className="flex items-start gap-3">
                    <span className="mt-0.5 inline-flex h-6 w-6 flex-none items-center justify-center rounded-full bg-blue-600 text-xs font-bold text-white">
                      ✓
                    </span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="surface-panel rounded-[2rem] p-6 lg:p-8">
              <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-blue-600 dark:text-blue-300">
                {t('marketing.features.security_title')}
              </p>
              <h2 data-display="true" className="mt-3 text-3xl font-semibold text-slate-950 dark:text-white">
                {t('marketing.features.cta_title')}
              </h2>
              <ul className="mt-5 space-y-3 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {securityCapabilities.map((item) => (
                  <li key={item} className="flex items-start gap-3">
                    <span className="mt-0.5 inline-flex h-6 w-6 flex-none items-center justify-center rounded-full bg-slate-900 text-xs font-bold text-white dark:bg-blue-500 dark:text-slate-950">
                      ✓
                    </span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* Final CTA Section */}
      <section className="w-full py-10">
        <div className="container mx-auto px-4">
          <div className="glass-panel rounded-[2rem] px-6 py-8 text-center lg:px-10 lg:py-10">
            <h2 data-display="true" className="text-3xl font-semibold text-slate-950 dark:text-white">
              {t('marketing.features.cta_title')}
            </h2>
            <p className="mx-auto mt-4 max-w-2xl text-base leading-7 text-slate-600 dark:text-slate-300">
              {t('marketing.features.cta_desc')}
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-4">
              <Link href="/getting-started" className="btn btn-primary px-8 py-3">
                {t('marketing.features.cta_primary')}
              </Link>
              <Link href="/portal/login" className="btn btn-secondary px-8 py-3">
                {t('marketing.home.final_cta_portal')}
              </Link>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
