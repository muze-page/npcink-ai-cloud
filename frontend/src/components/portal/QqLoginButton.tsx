'use client';

import { useState } from 'react';
import { useLocale } from '@/contexts/LocaleContext';
import { portalClient } from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';

export function QqLoginButton({ returnTo = '/portal' }: { returnTo?: string }) {
  const { t } = useLocale();
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle');
  const [message, setMessage] = useState('');

  const startLogin = async () => {
    setStatus('loading');
    setMessage('');
    try {
      const response = await portalClient.startQqLogin(returnTo);
      const authorizationUrl = String(response.data?.authorization_url || '').trim();
      if (!authorizationUrl) {
        throw new Error('QQ authorization URL is unavailable');
      }
      window.location.assign(authorizationUrl);
    } catch (error) {
      setStatus('error');
      setMessage(
        formatPortalErrorMessage(
          error,
          t,
          t('auth.qq_unavailable', undefined, 'QQ login is temporarily unavailable.')
        )
      );
    }
  };

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={startLogin}
        disabled={status === 'loading'}
        className="flex h-12 w-full items-center justify-center border border-[#d8e5f5] bg-white px-4 text-sm font-semibold text-[#174a78] shadow-sm transition hover:border-[#77b9ee] hover:bg-[#f4faff] disabled:cursor-wait disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:border-[#4ca6e8]"
      >
        {/* Tencent requires the standard QQ Connect mark to remain unmodified. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="https://wiki.connect.qq.com/wp-content/uploads/2016/12/Connect_logo_5.png"
          alt={t('auth.qq_login', undefined, 'QQ login')}
          width="115"
          height="24"
          className="h-6 w-auto"
        />
        <span className="sr-only">
          {status === 'loading'
            ? t('auth.qq_redirecting', undefined, 'Redirecting to QQ…')
            : t('auth.qq_login', undefined, 'QQ login')}
        </span>
      </button>
      {message ? <p className="text-sm text-red-700 dark:text-red-300">{message}</p> : null}
    </div>
  );
}
