'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import { LocaleSwitcher } from '@/components/ui/LocaleSwitcher';
import { ThemeToggle } from '@/components/ui/ThemeToggle';
import { useLocale } from '@/contexts/LocaleContext';

export function PublicSiteShell({ children }: { children: ReactNode }) {
  const { locale } = useLocale();
  const zh = locale === 'zh-CN';

  return (
    <div className="min-h-screen bg-[#f6f7f9] text-[#101828] dark:bg-[#09101c] dark:text-slate-50">
      <header className="sticky top-0 z-40 border-b border-slate-200/70 bg-[#f6f7f9]/90 backdrop-blur-xl dark:border-white/10 dark:bg-[#09101c]/88">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-5 lg:px-8">
          <Link href="/" className="group flex items-center gap-3" aria-label="Npcink AI Cloud">
            <span className="grid h-8 w-8 place-items-center bg-[#2357ff] text-sm font-black text-white transition-transform group-hover:-rotate-3">
              N
            </span>
            <span className="text-sm font-extrabold tracking-[0.18em]">NPCINK AI CLOUD</span>
          </Link>

          <nav className="hidden items-center gap-7 text-sm font-medium text-slate-600 dark:text-slate-300 md:flex">
            <Link href="/#capabilities" className="transition-colors hover:text-[#2357ff]">
              {zh ? '能力' : 'Capabilities'}
            </Link>
            <Link href="/#boundary" className="transition-colors hover:text-[#2357ff]">
              {zh ? '工作方式' : 'How it works'}
            </Link>
            <Link href="/status" className="transition-colors hover:text-[#2357ff]">
              {zh ? '服务状态' : 'Service status'}
            </Link>
            <Link href="/help" className="transition-colors hover:text-[#2357ff]">
              {zh ? '帮助' : 'Help'}
            </Link>
          </nav>

          <div className="flex items-center gap-2">
            <LocaleSwitcher />
            <ThemeToggle />
            <Link
              href="/portal/login"
              className="hidden h-10 items-center bg-[#101828] px-5 text-sm font-bold text-white transition-colors hover:bg-[#2357ff] dark:bg-white dark:text-[#101828] dark:hover:bg-[#9eb3ff] sm:inline-flex"
            >
              {zh ? '登录服务中心' : 'Sign in'}
            </Link>
          </div>
        </div>
      </header>

      {children}

      <footer className="border-t border-slate-200 bg-white dark:border-white/10 dark:bg-[#070c14]">
        <div className="mx-auto grid max-w-7xl gap-8 px-5 py-10 sm:grid-cols-[1fr_auto] lg:px-8">
          <div>
            <p className="text-sm font-extrabold tracking-[0.18em]">NPCINK AI CLOUD</p>
            <p className="mt-3 max-w-xl text-sm leading-6 text-slate-500 dark:text-slate-400">
              {zh
                ? '为 WordPress 提供托管 AI 运行、用量与服务诊断。内容最终确认与发布仍由站点管理员完成。'
                : 'Hosted AI runtime, usage evidence, and service diagnostics for WordPress. Site owners retain final review and publishing control.'}
            </p>
          </div>
          <nav className="flex flex-wrap content-start gap-x-6 gap-y-3 text-sm text-slate-600 dark:text-slate-300">
            <Link href="/privacy" className="hover:text-[#2357ff]">{zh ? '隐私政策' : 'Privacy'}</Link>
            <Link href="/terms" className="hover:text-[#2357ff]">{zh ? '服务条款' : 'Terms'}</Link>
            <Link href="/help" className="hover:text-[#2357ff]">{zh ? '帮助中心' : 'Help'}</Link>
            <Link href="/status" className="hover:text-[#2357ff]">{zh ? '服务状态' : 'Status'}</Link>
          </nav>
        </div>
        <div className="border-t border-slate-200 px-5 py-5 text-center text-xs text-slate-500 dark:border-white/10 dark:text-slate-500">
          © {new Date().getFullYear()} Npcink AI Cloud
        </div>
      </footer>
    </div>
  );
}
