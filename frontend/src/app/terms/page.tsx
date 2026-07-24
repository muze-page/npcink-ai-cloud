'use client';

import { DocumentSection, PublicDocument } from '@/components/public/PublicDocument';
import { useLocale } from '@/contexts/LocaleContext';

export default function TermsPage() {
  const { locale } = useLocale();
  const zh = locale === 'zh-CN';

  return (
    <PublicDocument
      eyebrow={zh ? '法律说明' : 'Legal'}
      title={zh ? '服务条款' : 'Terms of Service'}
      summary={zh ? '使用 Npcink AI Cloud 公共网站、服务中心与托管运行服务时适用的基本规则。' : 'Basic rules for the Npcink AI Cloud public website, Portal, and hosted runtime service.'}
    >
      <DocumentSection title={zh ? '服务范围' : 'Service scope'}>
        <p>{zh ? 'Cloud 提供托管 AI 运行、提供方适配、用量与套餐记录、站点连接详情和服务诊断。WordPress 站点仍负责本地内容、配置、最终确认和发布。' : 'Cloud provides hosted AI execution, provider adapters, usage and plan records, site-connection detail, and service diagnostics. WordPress remains responsible for local content, configuration, final approval, and publishing.'}</p>
      </DocumentSection>
      <DocumentSection title={zh ? '账号与安全' : 'Accounts and security'}>
        <p>{zh ? '您应妥善保护登录设备和已连接站点。不得绕过访问控制、干扰服务、批量滥用资源，或利用服务处理违法、有害或侵犯他人权益的内容。' : 'You must protect your login devices and connected sites. Do not bypass access controls, disrupt the service, abuse resources at scale, or use the service for unlawful, harmful, or infringing content.'}</p>
      </DocumentSection>
      <DocumentSection title={zh ? 'AI 输出' : 'AI output'}>
        <p>{zh ? 'AI 输出可能不准确或不完整。您应在使用或发布前进行人工审查，并对最终内容和使用方式负责。' : 'AI output may be inaccurate or incomplete. You must review it before use or publication and remain responsible for the final content and how it is used.'}</p>
      </DocumentSection>
      <DocumentSection title={zh ? '变更与中断' : 'Changes and interruptions'}>
        <p>{zh ? '我们可能为安全、维护或产品改进调整服务。计划性变更会尽量提前说明；紧急安全处置可能立即执行。' : 'We may adjust the service for security, maintenance, or product improvement. Planned changes will be announced where practical; urgent security measures may take effect immediately.'}</p>
      </DocumentSection>
    </PublicDocument>
  );
}
