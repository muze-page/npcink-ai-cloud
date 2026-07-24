'use client';

import Link from 'next/link';
import { PublicSiteShell } from '@/components/public/PublicSiteShell';
import { QqLoginButton } from '@/components/portal/QqLoginButton';
import { useLocale } from '@/contexts/LocaleContext';

const capabilities = [
  {
    index: '01',
    zhTitle: '托管 AI 运行',
    enTitle: 'Hosted AI runtime',
    zh: '把模型调用、提供方适配和运行任务留在 Cloud，站点无需保存模型密钥。',
    en: 'Keep model calls, provider adapters, and runtime tasks in Cloud—without storing model keys in your site.',
  },
  {
    index: '02',
    zhTitle: '可核对的用量',
    enTitle: 'Reviewable usage',
    zh: '按账号与站点查看套餐、用量和运行记录，出现差异时有证据可查。',
    en: 'Review plans, usage, and runtime records by account and site with evidence when something differs.',
  },
  {
    index: '03',
    zhTitle: '面向人的诊断',
    enTitle: 'Human-readable diagnostics',
    zh: '把内部检查结果翻译为状态、影响和下一步，不要求用户理解服务内部结构。',
    en: 'Translate internal checks into status, impact, and next steps without exposing service internals.',
  },
];

export default function HomePage() {
  const { locale } = useLocale();
  const zh = locale === 'zh-CN';

  return (
    <PublicSiteShell>
      <main>
        <section className="relative overflow-hidden border-b border-slate-200 bg-[#0b1424] text-white dark:border-white/10">
          <div className="absolute inset-0 opacity-60 [background-image:linear-gradient(rgba(255,255,255,.045)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.045)_1px,transparent_1px)] [background-size:56px_56px]" />
          <div className="absolute -right-24 top-24 h-80 w-80 rounded-full bg-[#2357ff]/35 blur-3xl" />
          <div className="relative mx-auto grid min-h-[650px] max-w-7xl items-center gap-14 px-5 py-20 lg:grid-cols-[1.15fr_.85fr] lg:px-8">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.3em] text-[#9eb3ff]">
                WordPress × Hosted AI Runtime
              </p>
              <h1 className="mt-7 max-w-4xl text-5xl font-black leading-[.98] tracking-[-0.055em] sm:text-6xl lg:text-[5.25rem]">
                {zh ? (
                  <>
                    <span className="block sm:inline">让 AI 在云端</span>
                    <span className="block sm:inline">运行，</span>
                    <span className="block text-[#9eb3ff]">
                      <span className="block sm:inline">让控制权留在</span>
                      <span className="block sm:inline">站点。</span>
                    </span>
                  </>
                ) : (
                  <>
                    Run AI in the cloud.
                    <span className="block text-[#9eb3ff]">Keep control in your site.</span>
                  </>
                )}
              </h1>
              <p className="mt-7 max-w-2xl text-base leading-8 text-slate-300 sm:text-lg">
                {zh
                  ? 'Npcink AI Cloud 为 WordPress 提供托管运行、用量记录和服务诊断。内容编辑、最终确认与发布仍由您的站点完成。'
                  : 'Npcink AI Cloud provides hosted execution, usage evidence, and service diagnostics for WordPress. Editing, approval, and publishing remain in your site.'}
              </p>
              <div className="mt-10 flex flex-wrap gap-3">
                <Link href="/portal/register" className="inline-flex h-12 items-center bg-[#2357ff] px-6 text-sm font-bold text-white transition hover:bg-[#4773ff]">
                  {zh ? '免费开始' : 'Start free'}
                </Link>
                <Link href="/#boundary" className="inline-flex h-12 items-center border border-white/25 px-6 text-sm font-bold text-white transition hover:border-white hover:bg-white/5">
                  {zh ? '了解工作方式' : 'See how it works'}
                </Link>
              </div>
            </div>

            <div className="border-l border-white/15 pl-7 sm:pl-10">
              <p className="text-xs font-bold uppercase tracking-[0.24em] text-slate-400">
                {zh ? '一次运行的边界' : 'One execution path'}
              </p>
              <ol className="mt-8 space-y-0">
                {[
                  [zh ? '在 WordPress 发起' : 'Requested in WordPress', zh ? '站点上下文与用户意图' : 'Site context and user intent'],
                  [zh ? '在 Cloud 执行' : 'Executed in Cloud', zh ? '模型调用、用量与诊断' : 'Model calls, usage, and diagnostics'],
                  [zh ? '回到 WordPress 确认' : 'Reviewed in WordPress', zh ? '人工确认后再发布' : 'Human approval before publishing'],
                ].map(([title, detail], index) => (
                  <li key={title} className="relative border-t border-white/15 py-6 pl-12">
                    <span className="absolute left-0 top-6 text-sm font-black text-[#9eb3ff]">0{index + 1}</span>
                    <p className="font-bold">{title}</p>
                    <p className="mt-1 text-sm text-slate-400">{detail}</p>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </section>

        <section id="capabilities" className="mx-auto max-w-7xl px-5 py-24 lg:px-8">
          <div className="grid gap-12 lg:grid-cols-[.7fr_1.3fr]">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.26em] text-[#2357ff]">
                {zh ? '服务能力' : 'Capabilities'}
              </p>
              <h2 className="mt-5 text-4xl font-black leading-tight tracking-[-0.04em] text-[#101828] dark:text-white">
                {zh ? '运行需要复杂，使用不必复杂。' : 'The runtime can be complex. Using it should not be.'}
              </h2>
            </div>
            <div className="border-t border-slate-300 dark:border-white/15">
              {capabilities.map((item) => (
                <article key={item.index} className="grid gap-4 border-b border-slate-300 py-7 dark:border-white/15 sm:grid-cols-[4rem_1fr]">
                  <span className="font-mono text-sm text-[#2357ff]">{item.index}</span>
                  <div>
                    <h3 className="text-xl font-bold">{zh ? item.zhTitle : item.enTitle}</h3>
                    <p className="mt-2 max-w-2xl leading-7 text-slate-600 dark:text-slate-300">
                      {zh ? item.zh : item.en}
                    </p>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="boundary" className="bg-[#e9edff] dark:bg-[#101c32]">
          <div className="mx-auto grid max-w-7xl gap-12 px-5 py-24 lg:grid-cols-2 lg:px-8">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.26em] text-[#2357ff]">
                {zh ? '清晰边界' : 'Clear boundary'}
              </p>
              <h2 className="mt-5 text-4xl font-black tracking-[-0.04em]">
                {zh ? 'Cloud 负责运行，不接管您的站点。' : 'Cloud runs the service. It does not take over your site.'}
              </h2>
            </div>
            <div className="grid gap-8 sm:grid-cols-2">
              <div>
                <p className="border-b border-[#2357ff]/30 pb-3 text-sm font-black text-[#2357ff]">CLOUD</p>
                <ul className="mt-5 space-y-3 text-sm leading-6 text-slate-700 dark:text-slate-200">
                  <li>{zh ? '运行模型与提供方适配' : 'Runs models and provider adapters'}</li>
                  <li>{zh ? '记录用量与套餐证据' : 'Records usage and plan evidence'}</li>
                  <li>{zh ? '提供服务诊断与运行详情' : 'Provides diagnostics and runtime detail'}</li>
                </ul>
              </div>
              <div>
                <p className="border-b border-slate-400/40 pb-3 text-sm font-black">WORDPRESS</p>
                <ul className="mt-5 space-y-3 text-sm leading-6 text-slate-700 dark:text-slate-200">
                  <li>{zh ? '保存站点内容与配置' : 'Owns site content and settings'}</li>
                  <li>{zh ? '决定编辑、确认与发布' : 'Controls editing, approval, and publishing'}</li>
                  <li>{zh ? '管理本地能力与工作流' : 'Manages local abilities and workflows'}</li>
                </ul>
              </div>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-5 py-24 lg:px-8">
          <div className="grid items-center gap-12 bg-white p-7 shadow-[0_24px_80px_rgba(15,23,42,.08)] dark:bg-[#101827] sm:p-10 lg:grid-cols-[1fr_22rem]">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.26em] text-[#2357ff]">
                {zh ? '进入服务中心' : 'User service center'}
              </p>
              <h2 className="mt-4 text-3xl font-black tracking-[-0.035em]">
                {zh ? '查看站点、用量、套餐与服务记录。' : 'Review sites, usage, plans, and service records.'}
              </h2>
              <p className="mt-4 max-w-2xl leading-7 text-slate-600 dark:text-slate-300">
                {zh ? '可使用 QQ 快捷登录，首次授权会为您创建 Free 账号；也可以继续使用邮箱验证码。' : 'Use QQ for quick access—first authorization creates a Free account—or continue with an email code.'}
              </p>
            </div>
            <div className="space-y-3">
              <QqLoginButton />
              <Link href="/portal/login" className="flex h-12 items-center justify-center border border-slate-300 text-sm font-bold hover:border-[#2357ff] hover:text-[#2357ff] dark:border-slate-700">
                {zh ? '使用邮箱验证码' : 'Use an email code'}
              </Link>
            </div>
          </div>
        </section>
      </main>
    </PublicSiteShell>
  );
}
