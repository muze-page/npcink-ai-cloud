'use client';

import React from 'react';
import { cn } from '@/lib/utils';

export interface MetricTileProps {
  label: string;
  value: React.ReactNode;
  trend?: {
    value: string | number;
    direction: 'up' | 'down' | 'neutral';
  };
  description?: string;
  icon?: React.ReactNode;
  className?: string;
  onClick?: () => void;
  footer?: React.ReactNode;
}

/**
 * 指标卡片组件 - 用于显示统计数据、KPI 等
 *
 * @example
 * <MetricTile
 *   label="Total Users"
 *   value="1,234"
 *   trend={{ value: '+12%', direction: 'up' }}
 *   description="Last 30 days"
 * />
 */
export function MetricTile({
  label,
  value,
  trend,
  description,
  icon,
  className,
  onClick,
  footer,
}: MetricTileProps) {
  const trendStyles = {
    up: 'text-green-600 dark:text-green-400',
    down: 'text-red-600 dark:text-red-400',
    neutral: 'text-gray-600 dark:text-gray-400',
  };

  const trendIcons = {
    up: '↑',
    down: '↓',
    neutral: '→',
  };

  const isClickable = !!onClick;

  return (
    <div
      className={cn(
        'rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4',
        isClickable &&
          'cursor-pointer hover:shadow-md hover:border-gray-300 dark:hover:border-gray-700 transition-all',
        className
      )}
      onClick={onClick}
      role={isClickable ? 'button' : undefined}
      tabIndex={isClickable ? 0 : undefined}
      onKeyDown={
        isClickable
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
    >
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide">
            {label}
          </p>
          <p className="mt-2 text-2xl font-semibold text-gray-900 dark:text-white truncate">
            {value}
          </p>
          {trend && (
            <div className="mt-1 flex items-center gap-1">
              <span className={cn('text-sm font-medium', trendStyles[trend.direction])}>
                {trendIcons[trend.direction]} {trend.value}
              </span>
              {description && (
                <span className="text-sm text-gray-500 dark:text-gray-500">
                  {description}
                </span>
              )}
            </div>
          )}
          {!trend && description && (
            <p className="mt-1 text-sm text-gray-500 dark:text-gray-500">
              {description}
            </p>
          )}
        </div>
        {icon && (
          <div className="flex-shrink-0 ml-4 text-gray-400 dark:text-gray-500">
            {icon}
          </div>
        )}
      </div>
      {footer && <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800">{footer}</div>}
    </div>
  );
}

/**
 * 指标条组件 - 用于在一行中显示多个指标
 */
export interface MetricStripProps {
  items: MetricTileProps[];
  className?: string;
  columns?: number;
}

export function MetricStrip({ items, className, columns = 4 }: MetricStripProps) {
  const columnClasses = {
    2: 'grid-cols-2',
    3: 'grid-cols-3',
    4: 'grid-cols-4',
    5: 'grid-cols-5',
    6: 'grid-cols-6',
  };

  return (
    <div
      className={cn(
        'grid gap-4',
        columnClasses[columns as keyof typeof columnClasses] || 'grid-cols-4',
        'sm:grid-cols-2 lg:grid-cols-4',
        className
      )}
    >
      {items.map((item, index) => (
        <MetricTile key={index} {...item} />
      ))}
    </div>
  );
}
