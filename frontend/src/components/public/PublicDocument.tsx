'use client';

import type { ReactNode } from 'react';
import { PublicSiteShell } from '@/components/public/PublicSiteShell';

export function PublicDocument({
  eyebrow,
  title,
  summary,
  children,
}: {
  eyebrow: string;
  title: string;
  summary: string;
  children: ReactNode;
}) {
  return (
    <PublicSiteShell>
      <main className="mx-auto max-w-4xl px-5 py-16 sm:py-24 lg:px-8">
        <header className="border-b border-slate-300 pb-10 dark:border-white/15">
          <p className="text-xs font-bold uppercase tracking-[0.26em] text-[#2357ff]">{eyebrow}</p>
          <h1 className="mt-5 text-4xl font-black tracking-[-0.045em] sm:text-5xl">{title}</h1>
          <p className="mt-5 max-w-2xl text-base leading-8 text-slate-600 dark:text-slate-300">{summary}</p>
          <p className="mt-4 text-xs text-slate-500">更新日期：2026 年 7 月 24 日</p>
        </header>
        <article className="public-document mt-10 space-y-10 text-[0.96rem] leading-8 text-slate-700 dark:text-slate-300">
          {children}
        </article>
      </main>
    </PublicSiteShell>
  );
}

export function DocumentSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section>
      <h2 className="text-xl font-black text-slate-950 dark:text-white">{title}</h2>
      <div className="mt-3 space-y-3">{children}</div>
    </section>
  );
}
