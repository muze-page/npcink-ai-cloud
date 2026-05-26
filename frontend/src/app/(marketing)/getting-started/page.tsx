'use client';

import Link from 'next/link';
import { useLocale } from '@/contexts/LocaleContext';

export default function GettingStartedPage() {
  const { locale, t } = useLocale();

  const launchNotice = {
    en: 'Current routes cover hosted runtime onboarding, connected-site access, and authenticated member operations.',
    'zh-CN': '现有路由覆盖 hosted runtime 接入、已连接站点访问和已认证成员操作。',
    'zh-TW': '現有路由涵蓋 hosted runtime 接入、已連線站點存取與已驗證成員操作。',
  }[locale];

  const steps = {
    en: [
      {
        step: '01',
        title: 'Open The Portal',
        description: 'Use the member portal to inspect the current Cloud surface and sign in to your connected-site workspace.',
        code: `# Portal entry\nhttps://cloud.magick-ai.com/portal/login`,
      },
      {
        step: '02',
        title: 'Connect A Site',
        description: 'Link one or more WordPress sites so Cloud can expose hosted runtime, usage, and status context in the member workspace.',
        code: `# After plugin connection\n# the site appears in the portal`,
      },
      {
        step: '03',
        title: 'Create Site Keys',
        description: 'Generate site-scoped API keys from the portal when you need runtime access. Keys are shown once and can be rotated or revoked later.',
        code: `# In the portal:\n# Select Site > API Keys > Create Key`,
      },
      {
        step: '04',
        title: 'Exercise Hosted Runtime',
        description: 'Use the issued key to test hosted runtime calls against the current Cloud contract.',
        code: `# Example API call\ncurl -X POST https://cloud.magick-ai.com/v1/runtime/execute \\\n  -H "Authorization: Bearer YOUR_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "gpt-4", "prompt": "Hello!"}'`,
      },
      {
        step: '05',
        title: 'Observe & Operate',
        description: 'Track usage, billing snapshots, and audit events from the portal. Review runtime health and subscription status from unified surfaces.',
        code: `# In the portal:\n# - View usage summary\n# - Review billing snapshots\n# - Inspect audit events`,
      },
    ],
    'zh-CN': [
      {
        step: '01',
        title: '进入 Portal',
        description: '通过成员 Portal 查看当前 Cloud 界面，并登录你的已连接站点工作区。',
        code: `# Portal 入口\nhttps://cloud.magick-ai.com/portal/login`,
      },
      {
        step: '02',
        title: '连接站点',
        description: '将一个或多个 WordPress 站点接入 Cloud，在成员工作区中查看 hosted runtime、用量与状态上下文。',
        code: `# 通过插件连接后\n# 站点会出现在 Portal 中`,
      },
      {
        step: '03',
        title: '创建站点密钥',
        description: '需要调用 runtime 时，可在 Portal 中创建 site-scoped API key。密钥只显示一次，后续可轮换或撤销。',
        code: `# 在 Portal 中：\n# 选择站点 > API Keys > Create Key`,
      },
      {
        step: '04',
        title: '验证 Hosted Runtime',
        description: '使用已签发的 key 测试当前 Cloud 合约下的 hosted runtime 调用。',
        code: `# 示例 API 调用\ncurl -X POST https://cloud.magick-ai.com/v1/runtime/execute \\\n  -H "Authorization: Bearer YOUR_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "gpt-4", "prompt": "Hello!"}'`,
      },
      {
        step: '05',
        title: '观察与运营',
        description: '从 Portal 跟踪用量、账单快照和审计事件。从统一界面查看运行时健康和订阅状态。',
        code: `# 在 Portal 中：\n# - 查看用量摘要\n# - 审查账单快照\n# - 检查审计事件`,
      },
    ],
    'zh-TW': [
      {
        step: '01',
        title: '進入 Portal',
        description: '透過成員 Portal 查看目前的 Cloud 介面，並登入你的已連線站點工作區。',
        code: `# Portal 入口\nhttps://cloud.magick-ai.com/portal/login`,
      },
      {
        step: '02',
        title: '連接站點',
        description: '將一個或多個 WordPress 站點接入 Cloud，在成員工作區中查看 hosted runtime、用量與狀態上下文。',
        code: `# 透過外掛連接後\n# 站點會出現在 Portal 中`,
      },
      {
        step: '03',
        title: '建立站點金鑰',
        description: '需要呼叫 runtime 時，可在 Portal 中建立 site-scoped API key。金鑰只顯示一次，後續可輪換或撤銷。',
        code: `# 在 Portal 中：\n# 選擇站點 > API Keys > Create Key`,
      },
      {
        step: '04',
        title: '驗證 Hosted Runtime',
        description: '使用已簽發的 key 測試目前 Cloud 合約下的 hosted runtime 呼叫。',
        code: `# 範例 API 呼叫\ncurl -X POST https://cloud.magick-ai.com/v1/runtime/execute \\\n  -H "Authorization: Bearer YOUR_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "gpt-4", "prompt": "Hello!"}'`,
      },
      {
        step: '05',
        title: '觀察與營運',
        description: '從 Portal 追蹤用量、帳單快照和稽核事件。從統一介面檢視執行時健康和訂閱狀態。',
        code: `# 在 Portal 中：\n# - 檢視用量摘要\n# - 審查帳單快照\n# - 檢查稽核事件`,
      },
    ],
  }[locale];

  const prerequisites = {
    en: [
      'A WordPress site you want to connect',
      'Admin access to your WordPress dashboard',
      'An invited email address for portal verification-code sign-in',
    ],
    'zh-CN': [
      '一个你想要连接的 WordPress 站点',
      'WordPress 后台的管理员访问权限',
      '用于 Portal 验证码登录的受邀邮箱地址',
    ],
    'zh-TW': [
      '一個你想要連接的 WordPress 站點',
      'WordPress 後台的管理員存取權限',
      '用於 Portal 驗證碼登入的受邀電子郵件地址',
    ],
  }[locale];

  const faqItems = {
    en: [
      {
        question: 'Do I need a credit card to get started?',
        answer: 'No. You can create an account and explore the platform before entering payment details.',
      },
      {
        question: 'How do API keys work?',
        answer: 'API keys are generated inside the member portal and shown only once. Save them securely, then rotate or revoke them when needed. Keys are scoped to a specific site.',
      },
      {
        question: 'Can I manage multiple sites?',
        answer: 'You can connect multiple WordPress sites and inspect them from the current portal workspace.',
      },
      {
        question: 'Why does my key only show once?',
        answer: 'For security, API secrets are displayed exactly once at creation. If you lose the secret, you must rotate the key to generate a new one. This is intentional to prevent secret exposure.',
      },
      {
        question: 'What is the member portal?',
        answer: 'The member portal is available after authentication. It is not a public marketing page; it is the operational workspace for connected site members.',
      },
    ],
    'zh-CN': [
      {
        question: '开始使用需要信用卡吗？',
        answer: '不需要。你可以先创建账号并体验平台，再决定是否配置付款信息。',
      },
      {
        question: 'API 密钥如何工作？',
        answer: 'API 密钥在成员 Portal 中生成且只展示一次。请妥善保存，后续可按需轮换或撤销。密钥限定在特定站点范围内。',
      },
      {
        question: '我可以管理多个站点吗？',
        answer: '你可以把多个 WordPress 站点接入当前 Portal 工作区并查看上下文。',
      },
      {
        question: '为什么密钥只显示一次？',
        answer: '为了安全，API 密钥明文只在创建时展示一次。如果丢失，必须轮换密钥才能生成新的。这是有意设计，防止密钥泄露。',
      },
      {
        question: '什么是成员 Portal？',
        answer: '成员 Portal 需要认证后才能访问。它不是公开的 marketing 页面，而是已连接站点成员的运营工作区。',
      },
    ],
    'zh-TW': [
      {
        question: '開始使用需要信用卡嗎？',
        answer: '不需要。你可以先建立帳號並探索平台，再決定是否填入付款資訊。',
      },
      {
        question: 'API 金鑰如何運作？',
        answer: 'API 金鑰會在成員 Portal 中產生且只顯示一次。請妥善保存，之後可輪換或撤銷。金鑰限定在特定站點範圍內。',
      },
      {
        question: '我可以管理多個站點嗎？',
        answer: '你可以把多個 WordPress 站點接入目前的 Portal 工作區並查看上下文。',
      },
      {
        question: '為什麼金鑰只會顯示一次？',
        answer: '為了安全，API 金鑰明文只在建立時展示一次。如果遺失，必須輪換金鑰才能產生新的。這是有意設計，防止金鑰洩露。',
      },
      {
        question: '什麼是成員 Portal？',
        answer: '成員 Portal 需要認證後才能存取。它不是公開的 marketing 頁面，而是已連線站點成員的營運工作區。',
      },
    ],
  }[locale];

  return (
    <div className="flex flex-col items-center pb-16">
      {/* Hero Section */}
      <section className="w-full py-16 md:py-20">
        <div className="container mx-auto px-4">
          <div className="grid gap-8 lg:grid-cols-[0.95fr_1.05fr] lg:items-end">
            <div className="space-y-5">
              <div className="brand-chip">{t('marketing.getting_started.links_title')}</div>
              <h1 data-display="true" className="max-w-4xl text-5xl font-semibold leading-[0.95] text-slate-950 dark:text-white sm:text-6xl">
                {t('marketing.getting_started.hero_title')}
              </h1>
              <p className="max-w-2xl text-lg leading-8 text-slate-600 dark:text-slate-300">
                {t('marketing.getting_started.hero_desc')}
              </p>
              <div className="inline-flex max-w-2xl rounded-full border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/20 dark:text-amber-100">
                {launchNotice}
              </div>
            </div>
            <div className="glass-panel rounded-[2rem] p-6 lg:p-8">
              {/* Product UI - Onboarding Flow */}
              <div className="mb-4 flex items-center justify-between">
                <span className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-blue-600 dark:text-blue-300">
                  {t('mock.onboarding_flow')}
                </span>
                <span className="rounded-full border border-green-200 bg-green-50 px-2 py-0.5 text-xs font-semibold text-green-700 dark:border-green-900 dark:bg-green-950/40 dark:text-green-300">
                  {t('mock.live_surface_badge')}
                </span>
              </div>
              <div className="space-y-3">
                {/* Login Step Mock */}
                <div className="surface-panel rounded-[1.2rem] p-4">
                  <div className="flex items-center gap-3">
                    <span className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">1</span>
                    <div className="flex-1">
                      <p className="text-sm font-medium text-slate-900 dark:text-white">{t('mock.portal_login')}</p>
                      <p className="text-xs text-slate-500">{t('mock.enter_email')} → {t('mock.receive_login_code')} → {t('mock.sign_in')}</p>
                    </div>
                  </div>
                </div>
                {/* Connect Site Step Mock */}
                <div className="surface-panel rounded-[1.2rem] p-4">
                  <div className="flex items-center gap-3">
                    <span className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">2</span>
                    <div className="flex-1">
                      <p className="text-sm font-medium text-slate-900 dark:text-white">{t('mock.connect_wp_site')}</p>
                      <p className="text-xs text-slate-500">{t('mock.install_plugin')} → {t('mock.enter_site_url')} → {t('mock.verify_connection')}</p>
                    </div>
                  </div>
                </div>
                {/* Create Key Step Mock */}
                <div className="surface-panel rounded-[1.2rem] p-4">
                  <div className="flex items-center gap-3">
                    <span className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">3</span>
                    <div className="flex-1">
                      <p className="text-sm font-medium text-slate-900 dark:text-white">{t('mock.create_api_key')}</p>
                      <p className="text-xs text-slate-500">{t('mock.select_site')} → {t('mock.generate_key')} → {t('mock.copy_secret')}</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Prerequisites Section */}
      <section className="w-full py-8">
        <div className="container mx-auto px-4">
          <div className="glass-panel rounded-[2rem] p-6 lg:p-8">
            <h2 data-display="true" className="text-2xl font-semibold text-slate-950 dark:text-white">
              {locale === 'en' && 'Before You Start'}
              {locale === 'zh-CN' && '开始之前'}
              {locale === 'zh-TW' && '開始之前'}
            </h2>
            <p className="mt-3 text-base leading-7 text-slate-600 dark:text-slate-300">
              {locale === 'en' && 'Make sure you have the following before beginning the onboarding process:'}
              {locale === 'zh-CN' && '在开始 onboarding 流程之前，请确保你具备以下条件：'}
              {locale === 'zh-TW' && '在開始 onboarding 流程之前，請確保你具備以下條件：'}
            </p>
            <ul className="mt-5 space-y-3">
              {prerequisites.map((item) => (
                <li key={item} className="flex items-start gap-3 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  <span className="mt-0.5 inline-flex h-6 w-6 flex-none items-center justify-center rounded-full bg-blue-600 text-xs font-bold text-white">
                    ✓
                  </span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* Step By Step Section */}
      <section className="w-full py-8">
        <div className="container mx-auto px-4">
          <div className="mb-6">
            <h2 data-display="true" className="text-2xl font-semibold text-slate-950 dark:text-white">
              {locale === 'en' && 'Step By Step'}
              {locale === 'zh-CN' && '分步指南'}
              {locale === 'zh-TW' && '分步指南'}
            </h2>
            <p className="mt-3 text-base leading-7 text-slate-600 dark:text-slate-300">
              {locale === 'en' && 'Follow these steps to complete your onboarding:'}
              {locale === 'zh-CN' && '按照以下步骤完成你的 onboarding：'}
              {locale === 'zh-TW' && '按照以下步驟完成你的 onboarding：'}
            </p>
          </div>
          <div className="grid gap-6">
            {steps.map(({ step, title, description, code }) => (
              <div key={step} className="grid gap-5 lg:grid-cols-[0.8fr_1.2fr]">
                <div className="surface-panel rounded-[1.8rem] p-6 lg:p-7">
                  <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-blue-600 dark:text-blue-300">
                    {step}
                  </p>
                  <h2 data-display="true" className="mt-3 text-3xl font-semibold text-slate-950 dark:text-white">
                    {title}
                  </h2>
                  <p className="mt-4 text-base leading-7 text-slate-600 dark:text-slate-300">
                    {description}
                  </p>
                </div>
                <pre className="glass-panel overflow-x-auto rounded-[1.8rem] p-6 text-sm leading-6 text-slate-800 dark:text-slate-100"><code>{code}</code></pre>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Common Issues Section */}
      <section className="w-full py-10">
        <div className="container mx-auto px-4">
          <div className="glass-panel rounded-[2rem] p-6 lg:p-8">
            <h2 data-display="true" className="text-center text-3xl font-semibold text-slate-950 dark:text-white">
              {t('marketing.getting_started.faq_title')}
            </h2>
            <div className="mx-auto mt-8 grid max-w-4xl gap-4">
              {faqItems.map(({ question, answer }) => (
                <div key={question} className="surface-panel rounded-[1.5rem] p-5">
                  <h3 className="text-lg font-semibold text-slate-950 dark:text-white">{question}</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{answer}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Next Steps Section */}
      <section className="w-full py-10">
        <div className="container mx-auto px-4">
          <div className="grid gap-5 md:grid-cols-3">
            <Link href="/portal/login" className="surface-panel rounded-[1.6rem] p-6 transition-transform hover:-translate-y-1">
              <h3 className="text-xl font-semibold text-slate-950 dark:text-white">{t('marketing.getting_started.portal_link')}</h3>
              <p className="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {locale === 'en' && 'Access the member portal to inspect connected sites and current API key surfaces.'}
                {locale === 'zh-CN' && '进入成员 Portal，查看已连接站点与当前 API key 界面。'}
                {locale === 'zh-TW' && '進入成員 Portal，查看已連線站點與目前 API key 介面。'}
              </p>
            </Link>
            <Link href="/features" className="surface-panel rounded-[1.6rem] p-6 transition-transform hover:-translate-y-1">
              <h3 className="text-xl font-semibold text-slate-950 dark:text-white">{t('marketing.getting_started.features_link')}</h3>
              <p className="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {locale === 'en' && 'Explore all the capabilities available in Magick AI Cloud.'}
                {locale === 'zh-CN' && '查看 Magick AI Cloud 当前提供的全部能力。'}
                {locale === 'zh-TW' && '查看 Magick AI Cloud 目前提供的全部能力。'}
              </p>
            </Link>
            <a
              href="https://github.com/magick-ai"
              target="_blank"
              rel="noopener noreferrer"
              className="surface-panel rounded-[1.6rem] p-6 transition-transform hover:-translate-y-1"
            >
              <h3 className="text-xl font-semibold text-slate-950 dark:text-white">{t('marketing.getting_started.docs_link')}</h3>
              <p className="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {locale === 'en' && 'Read the full API documentation and integration guides.'}
                {locale === 'zh-CN' && '查看完整 API 文档和集成指南。'}
                {locale === 'zh-TW' && '查看完整 API 文件與整合指南。'}
              </p>
            </a>
          </div>
        </div>
      </section>

      {/* Final CTA Section */}
      <section className="w-full py-10">
        <div className="container mx-auto px-4">
          <div className="glass-panel rounded-[2rem] px-6 py-8 text-center lg:px-10 lg:py-10">
            <h2 data-display="true" className="text-3xl font-semibold text-slate-950 dark:text-white">
              {t('marketing.getting_started.cta_title')}
            </h2>
            <p className="mx-auto mt-4 max-w-2xl text-base leading-7 text-slate-600 dark:text-slate-300">
              {t('marketing.getting_started.cta_desc')}
            </p>
            <div className="mt-6">
              <Link href="/portal/login" className="btn btn-primary px-8 py-3">
                {t('marketing.getting_started.cta_primary')}
              </Link>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
