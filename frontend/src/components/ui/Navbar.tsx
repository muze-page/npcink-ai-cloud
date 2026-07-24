'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState, useEffect, useCallback } from 'react';
import { cn } from '@/lib/utils';
import { useLocale } from '@/contexts/LocaleContext';
import { ThemeToggle } from './ThemeToggle';
import { LocaleSwitcher } from './LocaleSwitcher';

export function Navbar() {
  const pathname = usePathname();
  const { t } = useLocale();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Close mobile menu on escape key
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setMobileMenuOpen(false);
      }
    };
    
    if (mobileMenuOpen) {
      document.addEventListener('keydown', handleEscape);
      document.body.style.overflow = 'hidden';
    }
    
    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = '';
    };
  }, [mobileMenuOpen]);

  const navItems = [
    { href: '/', label: t('nav.home', undefined, 'Home') },
    { href: '/portal/login', label: t('nav.portal', undefined, 'Portal') },
    { href: '/status', label: t('service_status.health', undefined, 'Status') },
  ];

  const toggleMobileMenu = useCallback(() => {
    setMobileMenuOpen(prev => !prev);
  }, []);

  return (
    <header 
      className="sticky top-0 z-50 w-full border-b border-slate-200/70 bg-white/72 backdrop-blur-xl dark:border-slate-800 dark:bg-slate-950/70"
      role="banner"
    >
      <nav 
        className="container mx-auto flex h-16 items-center justify-between gap-4 px-4"
        aria-label="Main navigation"
      >
        <div className="flex items-center gap-8">
          <Link
            href="/" 
            className="flex items-center gap-3"
            aria-label={`Npcink AI Cloud ${t('nav.home', undefined, 'Home')}`}
          >
            <span className="brand-mark" aria-hidden="true">
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none">
                <path d="M6 15.25 12.2 4l.6 6.55H18l-6.2 9.45-.5-6.2H6Z" fill="currentColor" />
              </svg>
            </span>
            <span className="flex flex-col leading-none">
              <span className="text-[0.68rem] font-bold uppercase tracking-[0.3em] text-blue-600 dark:text-blue-300">
                Npcink AI
              </span>
              <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                {t('brand.subtitle', undefined, 'Cloud Control Surface')}
              </span>
            </span>
          </Link>
          
          {/* Desktop Navigation */}
          <div className="hidden md:flex items-center gap-1 rounded-full border border-slate-200/80 bg-white/70 p-1 shadow-sm dark:border-slate-700 dark:bg-slate-900/70" role="navigation" aria-label="Main navigation">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'rounded-full px-4 py-2 text-sm font-medium transition-all',
                  pathname === item.href
                    ? 'bg-slate-900 text-white shadow-sm dark:bg-blue-500 dark:text-slate-950'
                    : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white'
                )}
                aria-current={pathname === item.href ? 'page' : undefined}
              >
                {item.label}
              </Link>
            ))}
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          {/* Desktop Actions */}
          <div className="hidden md:flex items-center gap-2">
            <LocaleSwitcher />
            <ThemeToggle />
            <div className="mx-1 h-6 w-px bg-slate-200 dark:bg-slate-700" />
            <Link
              href="/portal/login"
              className="rounded-full px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
            >
              {t('nav.sign_in', undefined, 'Sign In')}
            </Link>
            <Link
              href="/portal"
              className="btn btn-primary text-sm"
            >
              {t('nav.portal', undefined, 'Portal')}
            </Link>
          </div>
          
          {/* Mobile Menu Button */}
          <button
            type="button"
              className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-slate-200/80 bg-white/85 text-slate-600 shadow-sm transition hover:border-slate-300 hover:text-slate-900 dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-white md:hidden"
              onClick={toggleMobileMenu}
              aria-expanded={mobileMenuOpen}
              aria-controls="mobile-menu"
              aria-label={mobileMenuOpen ? t('common.close', undefined, 'Close') : t('common.open_menu', undefined, 'Open menu')}
            >
            {mobileMenuOpen ? (
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            ) : (
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            )}
          </button>
        </div>
      </nav>
      
      {/* Mobile Menu */}
      <div
        id="mobile-menu"
        className={cn(
          'border-t border-slate-200/70 bg-white/92 backdrop-blur dark:border-slate-800 dark:bg-slate-950/92 md:hidden',
          mobileMenuOpen ? 'block' : 'hidden'
        )}
        role="navigation"
        aria-label="Mobile navigation"
      >
        <div className="container mx-auto space-y-4 px-4 py-4">
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                'block rounded-2xl px-4 py-3 text-sm font-medium transition-colors',
                pathname === item.href
                  ? 'bg-slate-900 text-white dark:bg-blue-500 dark:text-slate-950'
                  : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white'
              )}
              aria-current={pathname === item.href ? 'page' : undefined}
              onClick={() => setMobileMenuOpen(false)}
            >
              {item.label}
            </Link>
          ))}
          <div className="space-y-3 border-t border-slate-200 pt-4 dark:border-slate-800">
            <div className="flex items-center gap-2">
              <LocaleSwitcher />
              <ThemeToggle />
            </div>
            <Link
              href="/portal/login"
              className="block rounded-2xl px-4 py-3 text-sm font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
              onClick={() => setMobileMenuOpen(false)}
            >
              {t('nav.sign_in', undefined, 'Sign In')}
            </Link>
            <Link
              href="/portal"
              className="btn btn-primary text-sm w-full justify-center"
              onClick={() => setMobileMenuOpen(false)}
            >
              {t('nav.portal', undefined, 'Portal')}
            </Link>
          </div>
        </div>
      </div>
    </header>
  );
}
