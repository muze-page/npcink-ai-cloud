'use client';

import Link from 'next/link';
import { useLocale } from '@/contexts/LocaleContext';

export default function HomePage() {
  const { locale, t } = useLocale();

  const featureCards = [
    {
      eyebrow: '01',
      title: t('marketing.home.fast_title'),
      description: t('marketing.home.fast_desc'),
    },
    {
      eyebrow: '02',
      title: t('marketing.home.secure_title'),
      description: t('marketing.home.secure_desc'),
    },
    {
      eyebrow: '03',
      title: t('marketing.home.analytics_title'),
      description: t('marketing.home.analytics_desc'),
    },
  ];

  const launchTracks = [
    {
      label: t('marketing.home.fast_title'),
      detail: t('marketing.home.fast_desc'),
    },
    {
      label: t('marketing.home.secure_title'),
      detail: t('marketing.home.secure_desc'),
    },
    {
      label: t('marketing.home.analytics_title'),
      detail: t('marketing.home.analytics_desc'),
    },
  ];

  const personas = {
    en: [
      {
        icon: '🖥️',
        title: t('marketing.home.persona_wp_title'),
        description: t('marketing.home.persona_wp_desc'),
      },
      {
        icon: '🛡️',
        title: t('marketing.home.persona_admin_title'),
        description: t('marketing.home.persona_admin_desc'),
      },
      {
        icon: '🚀',
        title: t('marketing.home.persona_team_title'),
        description: t('marketing.home.persona_team_desc'),
      },
    ],
    'zh-CN': [
      {
        icon: '🖥️',
        title: t('marketing.home.persona_wp_title'),
        description: t('marketing.home.persona_wp_desc'),
      },
      {
        icon: '🛡️',
        title: t('marketing.home.persona_admin_title'),
        description: t('marketing.home.persona_admin_desc'),
      },
      {
        icon: '🚀',
        title: t('marketing.home.persona_team_title'),
        description: t('marketing.home.persona_team_desc'),
      },
    ],
    'zh-TW': [
      {
        icon: '🖥️',
        title: t('marketing.home.persona_wp_title'),
        description: t('marketing.home.persona_wp_desc'),
      },
      {
        icon: '🛡️',
        title: t('marketing.home.persona_admin_title'),
        description: t('marketing.home.persona_admin_desc'),
      },
      {
        icon: '🚀',
        title: t('marketing.home.persona_team_title'),
        description: t('marketing.home.persona_team_desc'),
      },
    ],
  }[locale];

  const howItWorksSteps = {
    en: [
      {
        step: '01',
        title: t('marketing.home.how_works_step1_title'),
        description: t('marketing.home.how_works_step1_desc'),
      },
      {
        step: '02',
        title: t('marketing.home.how_works_step2_title'),
        description: t('marketing.home.how_works_step2_desc'),
      },
      {
        step: '03',
        title: t('marketing.home.how_works_step3_title'),
        description: t('marketing.home.how_works_step3_desc'),
      },
      {
        step: '04',
        title: t('marketing.home.how_works_step4_title'),
        description: t('marketing.home.how_works_step4_desc'),
      },
    ],
    'zh-CN': [
      {
        step: '01',
        title: t('marketing.home.how_works_step1_title'),
        description: t('marketing.home.how_works_step1_desc'),
      },
      {
        step: '02',
        title: t('marketing.home.how_works_step2_title'),
        description: t('marketing.home.how_works_step2_desc'),
      },
      {
        step: '03',
        title: t('marketing.home.how_works_step3_title'),
        description: t('marketing.home.how_works_step3_desc'),
      },
      {
        step: '04',
        title: t('marketing.home.how_works_step4_title'),
        description: t('marketing.home.how_works_step4_desc'),
      },
    ],
    'zh-TW': [
      {
        step: '01',
        title: t('marketing.home.how_works_step1_title'),
        description: t('marketing.home.how_works_step1_desc'),
      },
      {
        step: '02',
        title: t('marketing.home.how_works_step2_title'),
        description: t('marketing.home.how_works_step2_desc'),
      },
      {
        step: '03',
        title: t('marketing.home.how_works_step3_title'),
        description: t('marketing.home.how_works_step3_desc'),
      },
      {
        step: '04',
        title: t('marketing.home.how_works_step4_title'),
        description: t('marketing.home.how_works_step4_desc'),
      },
    ],
  }[locale];

  const surfaces = {
    en: [
      {
        title: t('marketing.home.surface_marketing_title'),
        description: t('marketing.home.surface_marketing_desc'),
        color: 'blue',
      },
      {
        title: t('marketing.home.surface_portal_title'),
        description: t('marketing.home.surface_portal_desc'),
        color: 'indigo',
      },
      {
        title: t('marketing.home.surface_admin_title'),
        description: t('marketing.home.surface_admin_desc'),
        color: 'slate',
      },
    ],
    'zh-CN': [
      {
        title: t('marketing.home.surface_marketing_title'),
        description: t('marketing.home.surface_marketing_desc'),
        color: 'blue',
      },
      {
        title: t('marketing.home.surface_portal_title'),
        description: t('marketing.home.surface_portal_desc'),
        color: 'indigo',
      },
      {
        title: t('marketing.home.surface_admin_title'),
        description: t('marketing.home.surface_admin_desc'),
        color: 'slate',
      },
    ],
    'zh-TW': [
      {
        title: t('marketing.home.surface_marketing_title'),
        description: t('marketing.home.surface_marketing_desc'),
        color: 'blue',
      },
      {
        title: t('marketing.home.surface_portal_title'),
        description: t('marketing.home.surface_portal_desc'),
        color: 'indigo',
      },
      {
        title: t('marketing.home.surface_admin_title'),
        description: t('marketing.home.surface_admin_desc'),
        color: 'slate',
      },
    ],
  }[locale];

  const trustItems = {
    en: [
      {
        title: t('marketing.home.trust_key_title'),
        description: t('marketing.home.trust_key_desc'),
        icon: '🔑',
      },
      {
        title: t('marketing.home.trust_audit_title'),
        description: t('marketing.home.trust_audit_desc'),
        icon: '📋',
      },
      {
        title: t('marketing.home.trust_site_title'),
        description: t('marketing.home.trust_site_desc'),
        icon: '🏷️',
      },
      {
        title: t('marketing.home.trust_boundaries_title'),
        description: t('marketing.home.trust_boundaries_desc'),
        icon: '🔒',
      },
    ],
    'zh-CN': [
      {
        title: t('marketing.home.trust_key_title'),
        description: t('marketing.home.trust_key_desc'),
        icon: '🔑',
      },
      {
        title: t('marketing.home.trust_audit_title'),
        description: t('marketing.home.trust_audit_desc'),
        icon: '📋',
      },
      {
        title: t('marketing.home.trust_site_title'),
        description: t('marketing.home.trust_site_desc'),
        icon: '🏷️',
      },
      {
        title: t('marketing.home.trust_boundaries_title'),
        description: t('marketing.home.trust_boundaries_desc'),
        icon: '🔒',
      },
    ],
    'zh-TW': [
      {
        title: t('marketing.home.trust_key_title'),
        description: t('marketing.home.trust_key_desc'),
        icon: '🔑',
      },
      {
        title: t('marketing.home.trust_audit_title'),
        description: t('marketing.home.trust_audit_desc'),
        icon: '📋',
      },
      {
        title: t('marketing.home.trust_site_title'),
        description: t('marketing.home.trust_site_desc'),
        icon: '🏷️',
      },
      {
        title: t('marketing.home.trust_boundaries_title'),
        description: t('marketing.home.trust_boundaries_desc'),
        icon: '🔒',
      },
    ],
  }[locale];

  return (
    <div className="flex flex-col items-center pb-16">
      {/* Hero Section */}
      <section className="w-full py-16 md:py-20 lg:py-24">
        <div className="container mx-auto px-4">
          <div className="grid gap-8 lg:grid-cols-[1.2fr_0.8fr] lg:items-end">
            <div className="space-y-7">
              <div className="brand-chip">{t('marketing.home.platform_title')}</div>
              <div className="space-y-5">
                <h1 data-display="true" className="max-w-5xl text-5xl font-semibold leading-[0.95] text-slate-950 dark:text-white sm:text-6xl lg:text-7xl">
                  {t('marketing.home.hero_title')}
                </h1>
                <p className="max-w-2xl text-lg leading-8 text-slate-600 dark:text-slate-300 md:text-xl">
                  {t('marketing.home.hero_desc')}
                </p>
              </div>
              <div className="flex flex-col gap-3 sm:flex-row">
                <Link href="/getting-started" className="btn btn-primary px-7">
                  {t('marketing.home.hero_primary')}
                </Link>
                <Link href="/features" className="btn btn-secondary px-7">
                  {t('marketing.home.hero_secondary')}
                </Link>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                {launchTracks.map((track) => (
                  <div key={track.label} className="surface-panel rounded-[1.5rem] p-4">
                    <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-blue-600 dark:text-blue-300">
                      {track.label}
                    </p>
                    <p className="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-300">
                      {track.detail}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            <div className="glass-panel relative overflow-hidden rounded-[2rem] p-6 lg:p-8">
              <div className="absolute inset-x-0 top-0 h-24 bg-[linear-gradient(135deg,rgba(37,99,235,0.12),rgba(56,189,248,0.18))]" />
              <div className="relative space-y-5">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-blue-600 dark:text-blue-300">
                      {t('marketing.home.surface_label')}
                    </p>
                    <h2 data-display="true" className="mt-2 text-2xl font-semibold text-slate-950 dark:text-white">
                      {t('marketing.home.platform_desc')}
                    </h2>
                  </div>
                  <div className="rounded-full border border-slate-200/80 bg-white/80 px-3 py-1 text-xs font-semibold text-slate-600 dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-300">
                    {t('marketing.home.always_on')}
                  </div>
                </div>
                
                {/* Product Portal Overview */}
                <div className="surface-panel rounded-[1.5rem] overflow-hidden">
                  <div className="border-b border-slate-200 dark:border-slate-700 px-4 py-3 bg-slate-50/80 dark:bg-slate-800/50">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="flex gap-1.5">
                          <span className="w-2.5 h-2.5 rounded-full bg-red-400"></span>
                          <span className="w-2.5 h-2.5 rounded-full bg-amber-400"></span>
                          <span className="w-2.5 h-2.5 rounded-full bg-green-400"></span>
                        </div>
                        <span className="ml-3 text-xs text-slate-500 dark:text-slate-400">{t('mock.portal_workspace')}</span>
                      </div>
                      <span className="text-xs text-slate-400">{t('mock.portal_workspace_badge')}</span>
                    </div>
                  </div>
                  <div className="p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-xs text-slate-500 dark:text-slate-400">{t('mock.connected_sites')}</p>
                        <p className="text-lg font-semibold text-slate-950 dark:text-white">3</p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500 dark:text-slate-400">{t('mock.active_keys')}</p>
                        <p className="text-lg font-semibold text-slate-950 dark:text-white">5</p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500 dark:text-slate-400">{t('mock.this_month')}</p>
                        <p className="text-lg font-semibold text-green-600 dark:text-green-400">$24.50</p>
                      </div>
                    </div>
                    <div className="rounded-lg bg-slate-100 dark:bg-slate-800 p-3">
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-slate-500 dark:text-slate-400">{t('mock.usage_of_quota', { percent: '85' })}</span>
                        <span className="font-medium text-slate-700 dark:text-slate-300">8,500 / 10,000</span>
                      </div>
                      <div className="mt-2 h-2 w-full rounded-full bg-slate-200 dark:bg-slate-700">
                        <div className="h-2 w-[85%] rounded-full bg-blue-600"></div>
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div className="rounded-lg bg-green-50 dark:bg-green-950/20 p-2.5">
                        <p className="text-xs text-green-600 dark:text-green-400">{t('mock.runtime_health')}</p>
                        <p className="text-sm font-semibold text-green-700 dark:text-green-300">99.9% {t('mock.uptime')}</p>
                      </div>
                      <div className="rounded-lg bg-blue-50 dark:bg-blue-950/20 p-2.5">
                        <p className="text-xs text-blue-600 dark:text-blue-400">{t('mock.requests')}</p>
                        <p className="text-sm font-semibold text-blue-700 dark:text-blue-300">12,450</p>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="grid gap-3">
                  {featureCards.map((feature) => (
                    <div key={feature.title} className="surface-panel rounded-[1.4rem] p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-slate-400 dark:text-slate-500">
                            {feature.eyebrow}
                          </p>
                          <h3 className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">
                            {feature.title}
                          </h3>
                        </div>
                        <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700 dark:bg-blue-950/50 dark:text-blue-200">
                          {t('marketing.home.surface_live')}
                        </span>
                      </div>
                      <p className="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-300">
                        {feature.description}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Who It's For - Persona Section */}
      <section className="w-full py-12 md:py-16">
        <div className="container mx-auto px-4">
          <div className="mb-10 text-center">
            <p className="brand-chip mb-3 inline-block">{t('marketing.home.who_for_title')}</p>
            <h2 data-display="true" className="text-3xl font-semibold text-slate-950 dark:text-white md:text-4xl">
              {t('marketing.home.who_for_title')}
            </h2>
            <p className="mx-auto mt-4 max-w-2xl text-lg leading-8 text-slate-600 dark:text-slate-300">
              {t('marketing.home.who_for_desc')}
            </p>
          </div>
          <div className="grid gap-5 md:grid-cols-3">
            {personas.map((persona) => (
              <div key={persona.title} className="surface-panel rounded-[1.6rem] p-6">
                <div className="mb-4 text-4xl">{persona.icon}</div>
                <h3 className="text-xl font-semibold text-slate-950 dark:text-white">{persona.title}</h3>
                <p className="mt-3 text-sm leading-7 text-slate-600 dark:text-slate-300">
                  {persona.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How It Works Section */}
      <section className="w-full py-12 md:py-16">
        <div className="container mx-auto px-4">
          <div className="mb-10 text-center">
            <p className="brand-chip mb-3 inline-block">{t('marketing.home.how_works_title')}</p>
            <h2 data-display="true" className="text-3xl font-semibold text-slate-950 dark:text-white md:text-4xl">
              {t('marketing.home.how_works_title')}
            </h2>
            <p className="mx-auto mt-4 max-w-2xl text-lg leading-8 text-slate-600 dark:text-slate-300">
              {t('marketing.home.how_works_desc')}
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {howItWorksSteps.map((step, index) => (
              <div key={step.step} className="relative">
                <div className="surface-panel rounded-[1.6rem] p-6">
                  <div className="mb-4 flex items-center gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">
                      {step.step}
                    </span>
                    {index < howItWorksSteps.length - 1 && (
                      <div className="hidden h-px flex-1 bg-gradient-to-r from-blue-600/50 to-transparent lg:block" />
                    )}
                  </div>
                  <h3 className="text-lg font-semibold text-slate-950 dark:text-white">{step.title}</h3>
                  <p className="mt-3 text-sm leading-7 text-slate-600 dark:text-slate-300">
                    {step.description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Surface Overview Section */}
      <section className="w-full py-12 md:py-16">
        <div className="container mx-auto px-4">
          <div className="mb-10 text-center">
            <p className="brand-chip mb-3 inline-block">{t('marketing.home.surface_overview_title')}</p>
            <h2 data-display="true" className="text-3xl font-semibold text-slate-950 dark:text-white md:text-4xl">
              {t('marketing.home.surface_overview_title')}
            </h2>
            <p className="mx-auto mt-4 max-w-2xl text-lg leading-8 text-slate-600 dark:text-slate-300">
              {t('marketing.home.surface_overview_desc')}
            </p>
          </div>
          <div className="grid gap-5 md:grid-cols-3">
            {surfaces.map((surface) => (
              <div key={surface.title} className="glass-panel rounded-[1.6rem] p-6">
                <div className={`mb-4 inline-flex rounded-full border px-3 py-1 text-xs font-semibold ${
                  surface.color === 'blue' ? 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-950/40 dark:text-blue-200' :
                  surface.color === 'indigo' ? 'border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-900 dark:bg-indigo-950/40 dark:text-indigo-200' :
                  'border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-900 dark:bg-slate-950/40 dark:text-slate-200'
                }`}>
                  {surface.title}
                </div>
                <p className="text-sm leading-7 text-slate-600 dark:text-slate-300">
                  {surface.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Trust & Readiness Section */}
      <section className="w-full py-12 md:py-16">
        <div className="container mx-auto px-4">
          <div className="mb-10 text-center">
            <p className="brand-chip mb-3 inline-block">{t('marketing.home.trust_title')}</p>
            <h2 data-display="true" className="text-3xl font-semibold text-slate-950 dark:text-white md:text-4xl">
              {t('marketing.home.trust_title')}
            </h2>
            <p className="mx-auto mt-4 max-w-2xl text-lg leading-8 text-slate-600 dark:text-slate-300">
              {t('marketing.home.trust_desc')}
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {trustItems.map((item) => (
              <div key={item.title} className="surface-panel rounded-[1.6rem] p-6">
                <div className="mb-4 flex items-center gap-3">
                  <span className="text-2xl">{item.icon}</span>
                  <h3 className="text-lg font-semibold text-slate-950 dark:text-white">{item.title}</h3>
                </div>
                <p className="text-sm leading-7 text-slate-600 dark:text-slate-300">
                  {item.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Final CTA Section */}
      <section className="w-full py-12 md:py-16">
        <div className="container mx-auto px-4">
          <div className="glass-panel rounded-[2rem] px-6 py-10 text-center lg:px-10 lg:py-12">
            <h2 data-display="true" className="text-3xl font-semibold text-slate-950 dark:text-white">
              {t('marketing.home.final_cta_title')}
            </h2>
            <p className="mx-auto mt-4 max-w-2xl text-base leading-7 text-slate-600 dark:text-slate-300">
              {t('marketing.home.final_cta_desc')}
            </p>
            <div className="mt-8 flex flex-wrap justify-center gap-4">
              <Link href="/features" className="btn btn-primary px-8 py-3">
                {t('marketing.home.final_cta_features')}
              </Link>
              <Link href="/portal/login" className="btn btn-secondary px-8 py-3">
                {t('marketing.home.final_cta_portal')}
              </Link>
              <Link href="/getting-started" className="btn btn-outline px-8 py-3">
                {t('marketing.home.final_cta_onboarding')}
              </Link>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
