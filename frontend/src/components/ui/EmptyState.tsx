'use client';

import React, { ReactNode } from 'react';
import { useLocale } from '@/contexts/LocaleContext';
import { cn } from '@/lib/utils';

export interface EmptyStateProps {
  /** 图标 */
  icon?: ReactNode;
  /** 标题 */
  title: string;
  /** 描述文字 */
  description?: string;
  /** 操作按钮 */
  action?: ReactNode;
  /** 额外内容 */
  children?: ReactNode;
  /** 自定义类名 */
  className?: string;
  /** 尺寸 */
  size?: 'sm' | 'md' | 'lg';
}

/**
 * 空状态组件 - 用于展示空数据、错误、成功等状态
 * 
 * @example
 * <EmptyState
 *   icon="📭"
 *   title="No items yet"
 *   description="Create your first item to get started"
 *   action={<Button>Create Item</Button>}
 * />
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  children,
  className,
  size = 'md',
}: EmptyStateProps) {
  const sizeStyles = {
    sm: 'py-4',
    md: 'py-8',
    lg: 'py-12',
  };

  const iconSizes = {
    sm: 'text-3xl',
    md: 'text-5xl',
    lg: 'text-7xl',
  };

  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center text-center',
        sizeStyles[size],
        className
      )}
      role="status"
      aria-live="polite"
    >
      {icon && (
        <div className={cn('mb-4', iconSizes[size])} aria-hidden="true">
          {icon}
        </div>
      )}
      <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-1">
        {title}
      </h3>
      {description && (
        <p className="text-gray-600 dark:text-gray-400 max-w-md mb-4">
          {description}
        </p>
      )}
      {action && <div className="mt-2">{action}</div>}
      {children}
    </div>
  );
}

/**
 * 预定义的空状态模板
 */
export const EmptyStates = {
  /** 无数据 */
  NoData: ({ title, description, action }: Omit<EmptyStateProps, 'icon' | 'title'> & { title?: string }) => {
    const { t } = useLocale();
    return (
      <EmptyState
        icon="📊"
        title={title || t('empty.no_data_title')}
        description={description || t('empty.no_data_desc')}
        action={action}
      />
    );
  },

  /** 无搜索结果 */
  NoResults: ({ searchQuery, action }: { searchQuery?: string; action?: ReactNode }) => {
    const { t } = useLocale();
    return (
      <EmptyState
        icon="🔍"
        title={t('empty.no_results_title')}
        description={
          searchQuery
            ? t('empty.no_results_desc_query', { query: searchQuery })
            : t('empty.no_results_desc')
        }
        action={action}
      />
    );
  },

  /** 无项目 */
  NoItems: ({ itemType, action }: { itemType?: string; action?: ReactNode }) => {
    const { locale, t } = useLocale();
    const plural = itemType || (locale === 'en' ? 'items' : '项目');
    const singular = itemType || (locale === 'en' ? 'item' : '项目');
    return (
      <EmptyState
        icon="📭"
        title={t('empty.no_items_title', { itemType: plural })}
        description={t('empty.no_items_desc', { itemType: singular })}
        action={action}
      />
    );
  },

  /** 无消息 */
  NoMessages: () => {
    const { t } = useLocale();
    return (
      <EmptyState
        icon="💬"
        title={t('empty.no_messages_title')}
        description={t('empty.no_messages_desc')}
      />
    );
  },

  /** 无收藏 */
  NoFavorites: () => {
    const { t } = useLocale();
    return (
      <EmptyState
        icon="⭐"
        title={t('empty.no_favorites_title')}
        description={t('empty.no_favorites_desc')}
      />
    );
  },

  /** 无权限 */
  NoAccess: ({ action }: { action?: ReactNode }) => {
    const { t } = useLocale();
    return (
      <EmptyState
        icon="🔒"
        title={t('empty.no_access_title')}
        description={t('empty.no_access_desc')}
        action={action}
        size="lg"
      />
    );
  },

  /** 错误状态 */
  Error: ({ message, action }: { message?: string; action?: ReactNode }) => {
    const { t } = useLocale();
    return (
      <EmptyState
        icon="⚠️"
        title={t('empty.error_title')}
        description={message || t('empty.error_desc')}
        action={action}
        size="lg"
      />
    );
  },

  /** 加载中 */
  Loading: ({ message }: { message?: string }) => {
    const { t } = useLocale();
    return (
      <EmptyState
        icon={
          <div className="animate-spin text-4xl">⏳</div>
        }
        title={message || t('common.loading')}
      />
    );
  },
};

export default EmptyState;
