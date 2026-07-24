'use client';

import Link from 'next/link';
import { DocumentSection, PublicDocument } from '@/components/public/PublicDocument';
import { useLocale } from '@/contexts/LocaleContext';

export default function HelpPage() {
  const { locale } = useLocale();
  const zh = locale === 'zh-CN';

  return (
    <PublicDocument
      eyebrow={zh ? '使用帮助' : 'Help'}
      title={zh ? '从这里开始' : 'Start here'}
      summary={zh ? '登录、连接 WordPress 站点，以及遇到异常时的最短路径。' : 'The shortest path for signing in, connecting WordPress, and handling service issues.'}
    >
      <DocumentSection title={zh ? '1. 登录服务中心' : '1. Sign in to the Portal'}>
        <p>{zh ? '使用 QQ 可直接登录。首次 QQ 授权会创建 Free 账号；已有邮箱账号的用户也可以继续使用邮箱验证码，并在账号页绑定 QQ。' : 'Use QQ to sign in directly. First-time QQ authorization creates a Free account. Existing email users can keep using an email code and bind QQ from the account page.'}</p>
        <Link href="/portal/login" className="inline-flex font-bold text-[#2357ff] hover:underline">{zh ? '前往登录 →' : 'Go to sign in →'}</Link>
      </DocumentSection>
      <DocumentSection title={zh ? '2. 连接 WordPress' : '2. Connect WordPress'}>
        <p>{zh ? '在兼容的 WordPress 插件中发起连接，选择当前 Cloud 账号后返回站点完成确认。Cloud 不会替代 WordPress 的本地设置、能力或发布控制。' : 'Start the connection from a compatible WordPress plugin, select your Cloud account, then return to the site to confirm. Cloud does not replace local WordPress settings, abilities, or publishing control.'}</p>
      </DocumentSection>
      <DocumentSection title={zh ? '3. 检查服务状态' : '3. Check service status'}>
        <p>{zh ? '如果登录页或公开入口无法访问，先查看服务状态页。站点专属的运行记录和诊断只在登录后的服务中心展示。' : 'If the login or public entry is unavailable, check the service status page first. Site-specific runtime records and diagnostics appear only in the authenticated Portal.'}</p>
        <Link href="/status" className="inline-flex font-bold text-[#2357ff] hover:underline">{zh ? '查看服务状态 →' : 'View service status →'}</Link>
      </DocumentSection>
      <DocumentSection title={zh ? '4. 获取支持' : '4. Get support'}>
        <p>{zh ? '登录后从服务记录或支持入口提交问题，并附上站点名称、发生时间和可复现步骤。请勿提交密码、密钥或完整访问令牌。' : 'After signing in, submit a request from the service records or support area with the site name, time, and reproduction steps. Do not include passwords, keys, or full access tokens.'}</p>
      </DocumentSection>
    </PublicDocument>
  );
}
