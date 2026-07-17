'use client';

import Link from 'next/link';
import { useLocale } from '@/contexts/LocaleContext';

export function Footer() {
  const { t } = useLocale();

  return (
    <footer className="border-t border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900">
      <div className="container mx-auto px-4 py-8">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
          <div className="col-span-1 md:col-span-2">
            <Link href="/" className="flex items-center gap-2 font-semibold">
              <span className="text-xl">⚡</span>
              <span>Npcink AI Cloud</span>
            </Link>
            <p className="mt-4 text-sm text-gray-600 dark:text-gray-400 max-w-md">
              {t('footer.description')}
            </p>
          </div>
          <div>
            <h3 className="font-semibold mb-3">{t('footer.product')}</h3>
            <ul className="space-y-2 text-sm">
              <li>
                <Link href="/portal" className="text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100">
                  {t('nav.portal')}
                </Link>
              </li>
              <li>
                <Link href="/admin/login" className="text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100">
                  {t('nav.admin')}
                </Link>
              </li>
            </ul>
          </div>
          <div>
            <h3 className="font-semibold mb-3">{t('footer.account')}</h3>
            <ul className="space-y-2 text-sm">
              <li>
                <Link href="/portal/login" className="text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100">
                  {t('nav.sign_in')}
                </Link>
              </li>
              <li>
                <Link href="/portal#sites" className="text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100">
                  {t('portal.nav_sites', {}, 'Sites')}
                </Link>
              </li>
            </ul>
          </div>
        </div>
        <div className="mt-8 pt-8 border-t border-gray-200 dark:border-gray-800">
          <p className="text-sm text-gray-600 dark:text-gray-400">
            © {new Date().getFullYear()} Npcink AI Cloud. {t('footer.rights')}
          </p>
        </div>
      </div>
    </footer>
  );
}
