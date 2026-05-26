'use client';

import Link from 'next/link';
import { useLocale } from '@/contexts/LocaleContext';

type PackRow = {
  pack: string;
  pointsEquivalent: string;
  recommendedPackage: string;
  runsIncrement: string;
  tokensIncrement: string;
  suitableFor: string;
  notIdealFor: string;
  currentPeriodOnly: string;
  rollsOver: string;
};

type TierFitItem = {
  packageName: string;
  recommendation: string;
};

type FaqItem = {
  question: string;
  answer: string;
};

export default function TopUpPacksExplainerPage() {
  const { locale } = useLocale();

  const copy = {
    en: {
      eyebrow: 'Top-up Guide',
      title: 'Use top-up packs as current-period headroom, not as a stored balance',
      description:
        'Top-up packs are operator-managed additions for the current active subscription period. They do not replace package upgrades and they do not turn into a stored balance.',
      notice:
        'This page is explanatory and request-oriented only. Whether top-up or a package move is the right path still goes through operator review.',
      columns: [
        'Pack',
        'Points equivalent',
        'Recommended current package',
        'Runs increment',
        'Tokens increment',
        'Suitable for',
        'Not ideal for',
        'Current-period only?',
        'Rolls over?',
      ],
      rows: [
        {
          pack: 'Small',
          pointsEquivalent: '10,000',
          recommendedPackage: 'Free / Basic',
          runsIncrement: '+10,000 runs',
          tokensIncrement: '+2,000,000 tokens',
          suitableFor: 'A smaller one-off buffer when the current period only needs modest extra room.',
          notIdealFor: 'Repeated sustained overage or a package that is already clearly undersized.',
          currentPeriodOnly: 'Yes',
          rollsOver: 'No',
        },
        {
          pack: 'Medium',
          pointsEquivalent: '35,000',
          recommendedPackage: 'Basic / Bulk',
          runsIncrement: '+35,000 runs',
          tokensIncrement: '+7,000,000 tokens',
          suitableFor: 'A meaningful current-period extension when recurring work is temporarily above the normal operating band.',
          notIdealFor: 'A pattern that already points to a package mismatch every period.',
          currentPeriodOnly: 'Yes',
          rollsOver: 'No',
        },
        {
          pack: 'Large',
          pointsEquivalent: '150,000',
          recommendedPackage: 'Bulk',
          runsIncrement: '+150,000 runs',
          tokensIncrement: '+30,000,000 tokens',
          suitableFor: 'A larger one-period headroom increase without immediately rebinding the subscription to a different package.',
          notIdealFor: 'Long-lived heavy usage that should clearly move into a larger package.',
          currentPeriodOnly: 'Yes',
          rollsOver: 'No',
        },
      ] as PackRow[],
      fitTitle: 'Start from your current package',
      tierFit: [
        {
          packageName: 'Free / Basic',
          recommendation: 'Start with Small when the package still fits and the spike is current-period only.',
        },
        {
          packageName: 'Basic / Bulk',
          recommendation: 'Check Medium when the current package is mostly right but the active period needs materially more headroom.',
        },
        {
          packageName: 'Bulk',
          recommendation: 'Escalate to Large only when current-period pressure is exceptional and operator review does not yet point to a durable package move.',
        },
      ] as TierFitItem[],
      guidanceTitle: 'When to request top-up first',
      guidance: [
        'The current package is still broadly correct, but this period needs extra room.',
        'The pressure is temporary, seasonal, or tied to a one-off workflow spike.',
        'You need additive current-period headroom without changing the package boundary yet.',
      ],
      upgradeTitle: 'When a package change is probably better',
      upgrades: [
        'You are hitting the same ceiling every period.',
        'Concurrency and batch headroom are consistently too small.',
        'The operating pattern now looks structurally closer to the next package band.',
      ],
      faqTitle: 'FAQ',
      faq: [
        {
          question: 'Does a top-up pack only affect the current period?',
          answer: 'Yes. Top-up packs are scoped to the current active subscription period.',
        },
        {
          question: 'Does unused top-up headroom roll over?',
          answer: 'No. Unused top-up headroom does not roll forward into the next period.',
        },
        {
          question: 'Does top-up turn into a stored balance?',
          answer: 'No. Top-up remains an operator-managed period extension, not a stored balance.',
        },
        {
          question: 'Does requesting top-up automatically upgrade the package?',
          answer: 'No. Package changes and top-up decisions stay separate and still go through operator review.',
        },
      ] as FaqItem[],
      requestEntryTitle: 'Request entry',
      requestAction: 'Ask an operator to review whether current-period top-up fits better than a package move',
      requestChecklist: [
        'Include the current package, the site or workflow under pressure, and whether the spike is temporary.',
        'Include the time window, expected workload change, and whether you already suspect a package upgrade may fit better.',
      ],
      packageOverview: 'View package comparison',
      portalUsage: 'View current usage',
    },
    'zh-CN': {
      eyebrow: '加量说明',
      title: '把加量包理解为当前周期 headroom，而不是长期余额',
      description:
        '加量包是对当前激活订阅周期的 operator-managed 补充。它不替代套餐升级，也不会变成可留存余额。',
      notice:
        '这页只做说明和申请引导。到底该用加量包还是改套餐，仍然通过 operator review 判断。',
      columns: ['Pack', 'points equivalent', '推荐当前套餐', 'runs 增量', 'tokens 增量', '适合场景', '不太适合', '只影响当前周期？', '会滚存？'],
      rows: [
        {
          pack: 'Small',
          pointsEquivalent: '10,000',
          recommendedPackage: 'Free / Basic',
          runsIncrement: '+10,000 runs',
          tokensIncrement: '+2,000,000 tokens',
          suitableFor: '当前周期只需要较小额外缓冲的一次性补充。',
          notIdealFor: '持续性超限，或套餐明显已经长期偏小。',
          currentPeriodOnly: '是',
          rollsOver: '否',
        },
        {
          pack: 'Medium',
          pointsEquivalent: '35,000',
          recommendedPackage: 'Basic / Bulk',
          runsIncrement: '+35,000 runs',
          tokensIncrement: '+7,000,000 tokens',
          suitableFor: '当周期内工作量临时高于常规带宽时，提供更明显的扩容。',
          notIdealFor: '每个周期都已经表现出套餐不匹配。',
          currentPeriodOnly: '是',
          rollsOver: '否',
        },
        {
          pack: 'Large',
          pointsEquivalent: '150,000',
          recommendedPackage: 'Bulk',
          runsIncrement: '+150,000 runs',
          tokensIncrement: '+30,000,000 tokens',
          suitableFor: '在不立刻改绑更大套餐前，为当前周期提供较大 headroom 增量。',
          notIdealFor: '长期高负载，已经明显该切到更高套餐。',
          currentPeriodOnly: '是',
          rollsOver: '否',
        },
      ] as PackRow[],
      fitTitle: '按当前套餐看',
      tierFit: [
        {
          packageName: 'Free / Basic',
          recommendation: '如果当前套餐总体仍然合适，只是本周期短时抬升，先看 Small。',
        },
        {
          packageName: 'Basic / Bulk',
          recommendation: '如果套餐基本对，但这个周期需要更明显的额外 headroom，优先看 Medium。',
        },
        {
          packageName: 'Bulk',
          recommendation: '只有在当前周期压力异常高、operator review 仍不判断为长期升套餐时，再看 Large。',
        },
      ] as TierFitItem[],
      guidanceTitle: '什么时候优先申请加量包',
      guidance: [
        '当前套餐总体仍然合适，只是这个周期需要额外空间。',
        '压力是临时性的、季节性的，或由一次性 workflow spike 触发。',
        '你需要的是当前周期叠加 headroom，而不是立刻改变套餐边界。',
      ],
      upgradeTitle: '什么时候更适合改套餐',
      upgrades: [
        '你几乎每个周期都在撞同一个上限。',
        '并发和批量 headroom 长期偏小。',
        '当前运行模式已经结构性地更接近下一档套餐。',
      ],
      faqTitle: '常见问题',
      faq: [
        {
          question: '加量包是否只影响当前周期？',
          answer: '是。加量包只作用于当前激活订阅周期。',
        },
        {
          question: '未用完的加量会不会滚存？',
          answer: '否。未使用的加量不会滚到下一个周期。',
        },
        {
          question: '加量会不会变成可留存余额？',
          answer: '否。它仍然是 operator-managed 的周期补充，不是可留存余额。',
        },
        {
          question: '申请加量会不会自动变成升套餐？',
          answer: '否。加量和套餐调整是两条不同判断，仍通过 operator review 处理。',
        },
      ] as FaqItem[],
      requestEntryTitle: '申请入口',
      requestAction: '请 operator 评估当前周期加量是否比直接改套餐更合适',
      requestChecklist: [
        '请说明当前套餐、受影响站点或 workflow，以及这次压力是否只是临时波动。',
        '请说明预计持续时间、预期工作量变化，以及你是否已经怀疑更适合直接升套餐。',
      ],
      packageOverview: '查看套餐对比',
      portalUsage: '查看当前用量',
    },
    'zh-TW': {
      eyebrow: '加量說明',
      title: '把加量包理解為目前週期 headroom，而不是長期餘額',
      description:
        '加量包是對目前啟用訂閱週期的 operator-managed 補充。它不取代方案升級，也不會變成可留存餘額。',
      notice:
        '這頁只做說明和申請引導。到底該用加量包還是改方案，仍透過 operator review 判斷。',
      columns: ['Pack', 'points equivalent', '推薦目前方案', 'runs 增量', 'tokens 增量', '適合場景', '不太適合', '只影響目前週期？', '會滾存？'],
      rows: [
        {
          pack: 'Small',
          pointsEquivalent: '10,000',
          recommendedPackage: 'Free / Basic',
          runsIncrement: '+10,000 runs',
          tokensIncrement: '+2,000,000 tokens',
          suitableFor: '目前週期只需要較小額外緩衝的一次性補充。',
          notIdealFor: '持續性超限，或方案明顯已經長期偏小。',
          currentPeriodOnly: '是',
          rollsOver: '否',
        },
        {
          pack: 'Medium',
          pointsEquivalent: '35,000',
          recommendedPackage: 'Basic / Bulk',
          runsIncrement: '+35,000 runs',
          tokensIncrement: '+7,000,000 tokens',
          suitableFor: '當期內工作量暫時高於常規帶寬時，提供更明顯的擴容。',
          notIdealFor: '每個週期都已經表現出方案不匹配。',
          currentPeriodOnly: '是',
          rollsOver: '否',
        },
        {
          pack: 'Large',
          pointsEquivalent: '150,000',
          recommendedPackage: 'Bulk',
          runsIncrement: '+150,000 runs',
          tokensIncrement: '+30,000,000 tokens',
          suitableFor: '在不立即改綁更大方案前，為目前週期提供較大 headroom 增量。',
          notIdealFor: '長期高負載，已明顯該切到更高方案。',
          currentPeriodOnly: '是',
          rollsOver: '否',
        },
      ] as PackRow[],
      fitTitle: '依目前方案看',
      tierFit: [
        {
          packageName: 'Free / Basic',
          recommendation: '如果目前方案整體仍合適，只是本週期短時抬升，先看 Small。',
        },
        {
          packageName: 'Basic / Bulk',
          recommendation: '如果方案基本正確，但這個週期需要更明顯的額外 headroom，優先看 Medium。',
        },
        {
          packageName: 'Bulk',
          recommendation: '只有在目前週期壓力異常高、operator review 仍不判斷為長期升方案時，再看 Large。',
        },
      ] as TierFitItem[],
      guidanceTitle: '什麼時候優先申請加量包',
      guidance: [
        '目前方案整體仍然合適，只是這個週期需要額外空間。',
        '壓力是暫時性的、季節性的，或由一次性 workflow spike 觸發。',
        '你需要的是目前週期疊加 headroom，而不是立即改變方案邊界。',
      ],
      upgradeTitle: '什麼時候更適合改方案',
      upgrades: [
        '你幾乎每個週期都在撞同一個上限。',
        '併發和批次 headroom 長期偏小。',
        '目前運行模式已結構性地更接近下一檔方案。',
      ],
      faqTitle: '常見問題',
      faq: [
        {
          question: '加量包是否只影響目前週期？',
          answer: '是。加量包只作用於目前啟用訂閱週期。',
        },
        {
          question: '未用完的加量會不會滾存？',
          answer: '否。未使用的加量不會滾到下一個週期。',
        },
        {
          question: '加量會不會變成可留存餘額？',
          answer: '否。它仍然是 operator-managed 的週期補充，不是可留存餘額。',
        },
        {
          question: '申請加量會不會自動變成升方案？',
          answer: '否。加量和方案調整是兩條不同判斷，仍透過 operator review 處理。',
        },
      ] as FaqItem[],
      requestEntryTitle: '申請入口',
      requestAction: '請 operator 評估目前週期加量是否比直接改方案更合適',
      requestChecklist: [
        '請說明目前方案、受影響站點或 workflow，以及這次壓力是否只是暫時波動。',
        '請說明預計持續時間、預期工作量變化，以及你是否已懷疑更適合直接升方案。',
      ],
      packageOverview: '查看方案對比',
      portalUsage: '查看目前用量',
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
              <Link href="/portal/usage" className="btn btn-primary">
                {copy.portalUsage}
              </Link>
              <Link href="/packages" className="btn btn-secondary">
                {copy.packageOverview}
              </Link>
            </div>
          </div>
        </div>
      </section>

      <section className="w-full py-6">
        <div className="container mx-auto px-4">
          <div className="overflow-hidden rounded-[2rem] border border-slate-200/80 bg-white/80 shadow-sm dark:border-slate-800 dark:bg-slate-950/55">
            <div className="grid grid-cols-1 gap-px bg-slate-200/80 dark:bg-slate-800 lg:grid-cols-9">
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
                  key={row.pack}
                  className="grid grid-cols-1 gap-px bg-slate-200/80 dark:bg-slate-800 lg:grid-cols-9"
                >
                  <div className="bg-white px-5 py-5 dark:bg-slate-950/55">
                    <div className="text-lg font-semibold text-slate-950 dark:text-white">{row.pack}</div>
                  </div>
                  <div className="bg-white px-5 py-5 text-sm text-slate-700 dark:bg-slate-950/55 dark:text-slate-200">
                    {row.pointsEquivalent}
                  </div>
                  <div className="bg-white px-5 py-5 text-sm text-slate-700 dark:bg-slate-950/55 dark:text-slate-200">
                    {row.recommendedPackage}
                  </div>
                  <div className="bg-white px-5 py-5 text-sm text-slate-700 dark:bg-slate-950/55 dark:text-slate-200">
                    {row.runsIncrement}
                  </div>
                  <div className="bg-white px-5 py-5 text-sm text-slate-700 dark:bg-slate-950/55 dark:text-slate-200">
                    {row.tokensIncrement}
                  </div>
                  <div className="bg-white px-5 py-5 text-sm leading-6 text-slate-700 dark:bg-slate-950/55 dark:text-slate-200">
                    {row.suitableFor}
                  </div>
                  <div className="bg-white px-5 py-5 text-sm leading-6 text-slate-700 dark:bg-slate-950/55 dark:text-slate-200">
                    {row.notIdealFor}
                  </div>
                  <div className="bg-white px-5 py-5 text-sm text-slate-700 dark:bg-slate-950/55 dark:text-slate-200">
                    {row.currentPeriodOnly}
                  </div>
                  <div className="bg-white px-5 py-5 text-sm text-slate-700 dark:bg-slate-950/55 dark:text-slate-200">
                    {row.rollsOver}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="w-full py-10">
        <div className="container mx-auto px-4">
          <div className="grid gap-5 lg:grid-cols-[1fr_1fr_0.95fr]">
            <div className="surface-panel rounded-[1.7rem] p-6">
              <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-slate-500 dark:text-slate-400">
                {copy.fitTitle}
              </p>
              <div className="mt-4 space-y-3">
                {copy.tierFit.map((item) => (
                  <div
                    key={item.packageName}
                    className="rounded-2xl border border-slate-200/80 bg-white/70 px-4 py-4 dark:border-slate-800 dark:bg-slate-950/40"
                  >
                    <p className="text-sm font-semibold text-slate-950 dark:text-white">{item.packageName}</p>
                    <p className="mt-2 text-sm leading-6 text-slate-700 dark:text-slate-200">{item.recommendation}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="surface-panel rounded-[1.7rem] p-6">
              <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-slate-500 dark:text-slate-400">
                {copy.guidanceTitle}
              </p>
              <div className="mt-4 space-y-3">
                {copy.guidance.map((item) => (
                  <div
                    key={item}
                    className="rounded-2xl border border-slate-200/80 bg-white/70 px-4 py-3 text-sm leading-6 text-slate-700 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-200"
                  >
                    {item}
                  </div>
                ))}
              </div>
            </div>
            <div className="surface-panel rounded-[1.7rem] p-6">
              <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-slate-500 dark:text-slate-400">
                {copy.upgradeTitle}
              </p>
              <div className="mt-4 space-y-3">
                {copy.upgrades.map((item) => (
                  <div
                    key={item}
                    className="rounded-2xl border border-slate-200/80 bg-white/70 px-4 py-3 text-sm leading-6 text-slate-700 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-200"
                  >
                    {item}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="w-full py-2">
        <div className="container mx-auto px-4">
          <div className="grid gap-5 lg:grid-cols-[1.05fr_0.95fr]">
            <div className="surface-panel rounded-[1.7rem] p-6">
              <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-slate-500 dark:text-slate-400">
                {copy.faqTitle}
              </p>
              <div className="mt-4 space-y-3">
                {copy.faq.map((item) => (
                  <div
                    key={item.question}
                    className="rounded-2xl border border-slate-200/80 bg-white/70 px-4 py-4 dark:border-slate-800 dark:bg-slate-950/40"
                  >
                    <p className="text-sm font-semibold text-slate-950 dark:text-white">{item.question}</p>
                    <p className="mt-2 text-sm leading-6 text-slate-700 dark:text-slate-200">{item.answer}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="surface-panel rounded-[1.7rem] p-6">
              <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-slate-500 dark:text-slate-400">
                {copy.requestEntryTitle}
              </p>
              <div className="mt-4 space-y-4">
                <div className="rounded-2xl border border-slate-200/80 bg-white/70 px-4 py-4 dark:border-slate-800 dark:bg-slate-950/40">
                  <p className="text-sm font-semibold text-slate-950 dark:text-white">{copy.requestAction}</p>
                </div>
                {copy.requestChecklist.map((item) => (
                  <div
                    key={item}
                    className="rounded-2xl border border-slate-200/80 bg-white/70 px-4 py-3 text-sm leading-6 text-slate-700 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-200"
                  >
                    {item}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
