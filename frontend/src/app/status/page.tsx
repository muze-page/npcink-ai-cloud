'use client';

import { useEffect, useState } from 'react';
import { PublicSiteShell } from '@/components/public/PublicSiteShell';
import { useLocale } from '@/contexts/LocaleContext';

type HealthState = 'checking' | 'healthy' | 'unavailable';

export default function StatusPage() {
  const { locale } = useLocale();
  const zh = locale === 'zh-CN';
  const [state, setState] = useState<HealthState>('checking');
  const [checkedAt, setCheckedAt] = useState('');

  useEffect(() => {
    let active = true;
    fetch('/api/health', { cache: 'no-store' })
      .then(async (response) => {
        const payload = await response.json() as { status?: string; checked_at?: string };
        if (!active) return;
        setState(response.ok && payload.status === 'healthy' ? 'healthy' : 'unavailable');
        setCheckedAt(String(payload.checked_at || ''));
      })
      .catch(() => {
        if (active) setState('unavailable');
      });
    return () => {
      active = false;
    };
  }, []);

  const healthy = state === 'healthy';

  return (
    <PublicSiteShell>
      <main className="mx-auto max-w-5xl px-5 py-16 sm:py-24 lg:px-8">
        <p className="text-xs font-bold uppercase tracking-[0.26em] text-[#2357ff]">
          {zh ? '服务状态' : 'Service status'}
        </p>
        <h1 className="mt-5 text-4xl font-black tracking-[-0.045em] sm:text-5xl">
          {state === 'checking'
            ? (zh ? '正在检查公开入口…' : 'Checking public entry…')
            : healthy
              ? (zh ? '公开入口运行正常' : 'Public entry is operational')
              : (zh ? '公开入口暂时不可用' : 'Public entry is unavailable')}
        </h1>
        <p className="mt-5 max-w-2xl text-base leading-8 text-slate-600 dark:text-slate-300">
          {zh
            ? '这里展示普通用户能够理解和验证的公开可用性。账号、站点和单次运行的详细诊断只在登录后的服务中心显示。'
            : 'This page shows public availability that users can understand and verify. Account, site, and individual-run diagnostics are available only after sign-in.'}
        </p>

        <div className="mt-12 border-t border-slate-300 dark:border-white/15">
          <div className="grid items-center gap-4 border-b border-slate-300 py-7 dark:border-white/15 sm:grid-cols-[1fr_auto]">
            <div>
              <h2 className="text-lg font-bold">{zh ? '官网与服务中心入口' : 'Website and Portal entry'}</h2>
              <p className="mt-1 text-sm text-slate-500">{zh ? '页面访问和登录入口' : 'Page delivery and sign-in entry'}</p>
            </div>
            <span className={`inline-flex w-fit items-center gap-2 text-sm font-bold ${healthy ? 'text-emerald-700 dark:text-emerald-400' : state === 'checking' ? 'text-slate-500' : 'text-red-700 dark:text-red-400'}`}>
              <span className={`h-2.5 w-2.5 rounded-full ${healthy ? 'bg-emerald-500' : state === 'checking' ? 'bg-slate-400' : 'bg-red-500'}`} />
              {state === 'checking' ? (zh ? '检查中' : 'Checking') : healthy ? (zh ? '正常' : 'Operational') : (zh ? '异常' : 'Unavailable')}
            </span>
          </div>
          <div className="grid items-center gap-4 border-b border-slate-300 py-7 dark:border-white/15 sm:grid-cols-[1fr_auto]">
            <div>
              <h2 className="text-lg font-bold">{zh ? '站点运行与提供方状态' : 'Site runtime and provider status'}</h2>
              <p className="mt-1 text-sm text-slate-500">{zh ? '按账号授权展示，避免公开内部运行信息' : 'Shown per authorized account to protect internal runtime information'}</p>
            </div>
            <span className="text-sm font-bold text-slate-600 dark:text-slate-300">{zh ? '登录后查看' : 'Sign in to view'}</span>
          </div>
        </div>

        {checkedAt ? (
          <p className="mt-5 text-xs text-slate-500">
            {zh ? '最近检查：' : 'Last checked: '}
            {new Date(checkedAt).toLocaleString(zh ? 'zh-CN' : 'en-US')}
          </p>
        ) : null}
      </main>
    </PublicSiteShell>
  );
}
