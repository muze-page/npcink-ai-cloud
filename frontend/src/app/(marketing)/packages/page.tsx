'use client';

import Link from 'next/link';
import { useLocale } from '@/contexts/LocaleContext';

type PackageRow = {
  packageName: string;
  includedPoints: string;
  concurrency: string;
  batchCeiling: string;
  gracePeriod: string;
  overLimitBehavior: string;
  headroomPosture: string;
  bestFor: string;
};

type ChoiceItem = {
  title: string;
  description: string;
};

export default function PackagesPage() {
  const { locale } = useLocale();

  const copy = {
    en: {
      eyebrow: 'Package Guide',
      title: 'Compare the current Cloud packages at a glance',
      description:
        'Free, Basic, and Bulk share the same core product surface. The real differences come from included points, concurrency, batch ceiling, and commercial headroom.',
      notice:
        'This is a read-only comparison page. Package changes remain operator-managed and do not happen through a self-serve transaction flow.',
      columns: ['Package', 'Included points', 'Concurrency', 'Batch ceiling', 'Grace period', 'Over-limit behavior', 'Headroom posture', 'Best for'],
      rows: [
        {
          packageName: 'Free',
          includedPoints: '500',
          concurrency: '1 active run',
          batchCeiling: '0',
          gracePeriod: '0 days',
          overLimitBehavior: 'Fail closed',
          headroomPosture: 'Fail closed immediately when over limit.',
          bestFor: 'Single-site / light trials',
        },
        {
          packageName: 'Basic',
          includedPoints: '10,000',
          concurrency: '2 active runs',
          batchCeiling: '10',
          gracePeriod: '3 days',
          overLimitBehavior: 'Short grace, then operator follow-up',
          headroomPosture: 'Short grace before operator intervention.',
          bestFor: 'Steady daily work / medium automation',
        },
        {
          packageName: 'Bulk',
          includedPoints: '50,000',
          concurrency: '6 active runs',
          batchCeiling: '100',
          gracePeriod: '7 days',
          overLimitBehavior: 'Short-lived overage before intervention',
          headroomPosture: 'Wider operator headroom before intervention.',
          bestFor: 'Multi-site / sustained automation / higher concurrency',
        },
      ] as PackageRow[],
      chooseTitle: 'How to choose',
      choices: [
        {
          title: 'Free',
          description: 'Single-site, lighter trials, and the most conservative over-limit policy.',
        },
        {
          title: 'Basic',
          description: 'Stable daily workflows that need more predictable headroom and short grace.',
        },
        {
          title: 'Bulk',
          description: 'Multi-site and sustained automation when higher concurrency is already normal.',
        },
      ] as ChoiceItem[],
      rulesTitle: 'What stays the same',
      rules: [
        'Core capability entry stays shared across packages.',
        'Package differences should be read through points, concurrency, batch ceiling, and policy headroom, not through sales-front feature gating.',
        'If you are between two packages, start by checking your current usage and then ask for operator follow-up.',
      ],
      currentPackage: 'Review current package posture',
      topUpGuide: 'Review top-up guidance',
      requestUpgrade: 'Ask an operator to review package fit',
    },
    'zh-CN': {
      eyebrow: '套餐说明',
      title: '一眼看懂当前 Cloud 套餐差异',
      description:
        'Free、Basic、Bulk 共享同一套核心产品面。真正的差异主要来自 included points、并发、批量上限和商业 headroom。',
      notice:
        '这是一张只读对比页。套餐调整仍由 operator-managed 处理，不通过自助交易流完成。',
      columns: ['套餐', 'included points', '并发', '批量上限', 'grace period', '超限行为', 'headroom 姿态', '最适合'],
      rows: [
        {
          packageName: 'Free',
          includedPoints: '500',
          concurrency: '1 个活跃 run',
          batchCeiling: '0',
          gracePeriod: '0 天',
          overLimitBehavior: '直接 fail closed',
          headroomPosture: '超限后立即收口。',
          bestFor: '单站点 / 轻量试用',
        },
        {
          packageName: 'Basic',
          includedPoints: '10,000',
          concurrency: '2 个活跃 run',
          batchCeiling: '10',
          gracePeriod: '3 天',
          overLimitBehavior: '短暂 grace 后 operator 跟进',
          headroomPosture: '短暂 grace 后再进入 operator 跟进。',
          bestFor: '稳定日常 / 中等自动化',
        },
        {
          packageName: 'Bulk',
          includedPoints: '50,000',
          concurrency: '6 个活跃 run',
          batchCeiling: '100',
          gracePeriod: '7 天',
          overLimitBehavior: '允许短时超限后再介入',
          headroomPosture: '在介入前保留更宽的 operator headroom。',
          bestFor: '多站点 / 持续自动化 / 高并发',
        },
      ] as PackageRow[],
      chooseTitle: '怎么选',
      choices: [
        {
          title: 'Free',
          description: '单站点、轻量试用，以及最保守的超限策略。',
        },
        {
          title: 'Basic',
          description: '稳定日常工作流，需要更可预测的 headroom 和短暂 grace。',
        },
        {
          title: 'Bulk',
          description: '多站点、持续自动化，以及更高并发已经成为常态。',
        },
      ] as ChoiceItem[],
      rulesTitle: '哪些东西不变',
      rules: [
        '核心能力入口在各套餐之间保持共享。',
        '套餐差异应该通过 points、并发、批量上限和策略 headroom 来理解，而不是销售前台式功能割裂。',
        '如果你处在两个套餐之间，先看当前使用情况，再进入 operator 跟进。',
      ],
      currentPackage: '查看当前套餐状态',
      topUpGuide: '查看加量说明',
      requestUpgrade: '请 operator 评估套餐是否需要调整',
    },
    'zh-TW': {
      eyebrow: '方案說明',
      title: '一眼看懂目前的 Cloud 方案差異',
      description:
        'Free、Basic、Bulk 共用同一套核心產品面。真正差異主要來自 included points、併發、批次上限和商業 headroom。',
      notice:
        '這是一張唯讀對比頁。方案調整仍由 operator-managed 處理，不透過自助交易流完成。',
      columns: ['方案', 'included points', '併發', '批次上限', 'grace period', '超限行為', 'headroom 姿態', '最適合'],
      rows: [
        {
          packageName: 'Free',
          includedPoints: '500',
          concurrency: '1 個活躍 run',
          batchCeiling: '0',
          gracePeriod: '0 天',
          overLimitBehavior: '直接 fail closed',
          headroomPosture: '超限後立即收口。',
          bestFor: '單站點 / 輕量試用',
        },
        {
          packageName: 'Basic',
          includedPoints: '10,000',
          concurrency: '2 個活躍 run',
          batchCeiling: '10',
          gracePeriod: '3 天',
          overLimitBehavior: '短暫 grace 後 operator 跟進',
          headroomPosture: '短暫 grace 後再進入 operator 跟進。',
          bestFor: '穩定日常 / 中等自動化',
        },
        {
          packageName: 'Bulk',
          includedPoints: '50,000',
          concurrency: '6 個活躍 run',
          batchCeiling: '100',
          gracePeriod: '7 天',
          overLimitBehavior: '允許短時超限後再介入',
          headroomPosture: '在介入前保留更寬的 operator headroom。',
          bestFor: '多站點 / 持續自動化 / 高併發',
        },
      ] as PackageRow[],
      chooseTitle: '怎麼選',
      choices: [
        {
          title: 'Free',
          description: '單站點、輕量試用，以及最保守的超限策略。',
        },
        {
          title: 'Basic',
          description: '穩定日常工作流程，需要更可預測的 headroom 和短暫 grace。',
        },
        {
          title: 'Bulk',
          description: '多站點、持續自動化，以及更高併發已成常態。',
        },
      ] as ChoiceItem[],
      rulesTitle: '哪些東西不變',
      rules: [
        '核心能力入口在各方案之間保持共享。',
        '方案差異應透過 points、併發、批次上限和策略 headroom 理解，而不是銷售前台式功能切割。',
        '如果你介於兩個方案之間，先看目前使用情況，再進入 operator 跟進。',
      ],
      currentPackage: '查看目前方案狀態',
      topUpGuide: '查看加量說明',
      requestUpgrade: '請 operator 評估方案是否需要調整',
    },
  }[locale];

  return (
    <div className="flex flex-col items-center pb-16">
      <section className="w-full py-16 md:py-20">
        <div className="container mx-auto px-4">
          <div className="space-y-5">
            <div className="brand-chip">{copy.eyebrow}</div>
            <h1
              data-display="true"
              className="max-w-5xl text-5xl font-semibold leading-[0.95] text-slate-950 dark:text-white sm:text-6xl"
            >
              {copy.title}
            </h1>
            <p className="max-w-3xl text-lg leading-8 text-slate-600 dark:text-slate-300">
              {copy.description}
            </p>
            <div className="inline-flex max-w-3xl rounded-full border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/20 dark:text-amber-100">
              {copy.notice}
            </div>
            <div className="flex flex-wrap gap-3 pt-2">
              <Link href="/portal/billing" className="btn btn-primary">
                {copy.currentPackage}
              </Link>
              <Link href="/top-up-packs" className="btn btn-secondary">
                {copy.topUpGuide}
              </Link>
            </div>
          </div>
        </div>
      </section>

      <section className="w-full py-6">
        <div className="container mx-auto px-4">
          <div className="overflow-hidden rounded-[2rem] border border-slate-200/80 bg-white/80 shadow-sm dark:border-slate-800 dark:bg-slate-950/55">
            <div className="grid grid-cols-1 gap-px bg-slate-200/80 dark:bg-slate-800 lg:grid-cols-8">
              {copy.columns.map((column) => (
                <div
                  key={column}
                  className="bg-slate-50 px-5 py-4 text-xs font-bold uppercase tracking-[0.22em] text-slate-500 dark:bg-slate-900/90 dark:text-slate-400"
                >
                  {column}
                </div>
              ))}
            </div>
            <div className="divide-y divide-slate-200/80 dark:divide-slate-800">
              {copy.rows.map((row) => (
                <div
                  key={row.packageName}
                  className="grid grid-cols-1 gap-px bg-slate-200/80 dark:bg-slate-800 lg:grid-cols-8"
                >
                  <div className="bg-white px-5 py-5 dark:bg-slate-950/55">
                    <div className="text-lg font-semibold text-slate-950 dark:text-white">{row.packageName}</div>
                  </div>
                  <div className="bg-white px-5 py-5 text-sm text-slate-700 dark:bg-slate-950/55 dark:text-slate-200">
                    {row.includedPoints}
                  </div>
                  <div className="bg-white px-5 py-5 text-sm text-slate-700 dark:bg-slate-950/55 dark:text-slate-200">
                    {row.concurrency}
                  </div>
                  <div className="bg-white px-5 py-5 text-sm text-slate-700 dark:bg-slate-950/55 dark:text-slate-200">
                    {row.batchCeiling}
                  </div>
                  <div className="bg-white px-5 py-5 text-sm text-slate-700 dark:bg-slate-950/55 dark:text-slate-200">
                    {row.gracePeriod}
                  </div>
                  <div className="bg-white px-5 py-5 text-sm leading-6 text-slate-700 dark:bg-slate-950/55 dark:text-slate-200">
                    {row.overLimitBehavior}
                  </div>
                  <div className="bg-white px-5 py-5 text-sm text-slate-700 dark:bg-slate-950/55 dark:text-slate-200">
                    {row.headroomPosture}
                  </div>
                  <div className="bg-white px-5 py-5 text-sm leading-6 text-slate-700 dark:bg-slate-950/55 dark:text-slate-200">
                    {row.bestFor}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="w-full py-10">
        <div className="container mx-auto px-4">
          <div className="grid gap-5 lg:grid-cols-[1.05fr_0.95fr]">
            <div className="surface-panel rounded-[1.7rem] p-6">
              <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-slate-500 dark:text-slate-400">
                {copy.chooseTitle}
              </p>
              <div className="mt-4 grid gap-3">
                {copy.choices.map((choice) => (
                  <div
                    key={choice.title}
                    className="rounded-2xl border border-slate-200/80 bg-white/70 px-4 py-4 dark:border-slate-800 dark:bg-slate-950/40"
                  >
                    <div className="text-base font-semibold text-slate-950 dark:text-white">{choice.title}</div>
                    <div className="mt-2 text-sm leading-6 text-slate-700 dark:text-slate-200">
                      {choice.description}
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div className="surface-panel rounded-[1.7rem] p-6">
              <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-slate-500 dark:text-slate-400">
                {copy.rulesTitle}
              </p>
              <div className="mt-4 space-y-3">
                {copy.rules.map((rule) => (
                  <div
                    key={rule}
                    className="rounded-2xl border border-slate-200/80 bg-white/70 px-4 py-3 text-sm leading-6 text-slate-700 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-200"
                  >
                    {rule}
                  </div>
                ))}
              </div>
              <div className="mt-5 flex flex-wrap gap-3">
                <Link href="/portal/billing" className="btn btn-secondary">
                  {copy.currentPackage}
                </Link>
                <Link href="/top-up-packs" className="btn btn-secondary">
                  {copy.topUpGuide}
                </Link>
                <div className="rounded-2xl border border-slate-200/80 bg-white/70 px-4 py-3 text-sm font-medium text-slate-700 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-200">
                  {copy.requestUpgrade}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
