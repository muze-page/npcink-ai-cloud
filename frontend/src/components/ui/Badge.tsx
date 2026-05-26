'use client';

import React from 'react';
import { cn } from '@/lib/utils';

export interface BadgeProps {
  children: React.ReactNode;
  className?: string;
  variant?: 'default' | 'primary' | 'success' | 'warning' | 'error' | 'info';
  size?: 'sm' | 'md' | 'lg';
  dot?: boolean;
  as?: React.ElementType;
}

/**
 * 徽章组件 - 用于状态标签、计数等
 *
 * @example
 * <Badge variant="success">Active</Badge>
 * <Badge variant="primary" dot>New</Badge>
 * <Badge size="sm">12</Badge>
 */
export function Badge({
  children,
  className,
  variant = 'default',
  size = 'md',
  dot = false,
  as: Component = 'span',
}: BadgeProps) {
  const variantStyles = {
    default: 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300',
    primary: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300',
    success: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300',
    warning: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300',
    error: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
    info: 'bg-cyan-100 text-cyan-800 dark:bg-cyan-900/30 dark:text-cyan-300',
  };

  const sizeStyles = {
    sm: 'px-1.5 py-0.5 text-xs',
    md: 'px-2.5 py-0.5 text-xs font-medium',
    lg: 'px-3 py-1 text-sm font-semibold',
  };

  return (
    <Component
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full',
        variantStyles[variant],
        sizeStyles[size],
        className
      )}
    >
      {dot && (
        <span
          className={cn(
            'inline-block w-1.5 h-1.5 rounded-full',
            variant === 'default' && 'bg-gray-500',
            variant === 'primary' && 'bg-blue-500',
            variant === 'success' && 'bg-green-500',
            variant === 'warning' && 'bg-yellow-500',
            variant === 'error' && 'bg-red-500',
            variant === 'info' && 'bg-cyan-500'
          )}
        />
      )}
      {children}
    </Component>
  );
}

/**
 * 状态徽章组件 - 专门用于状态显示
 */
export interface StatusBadgeProps {
  status: 'active' | 'inactive' | 'pending' | 'error' | 'warning';
  label?: string;
  className?: string;
  showDot?: boolean;
}

export function StatusBadge({
  status,
  label,
  className,
  showDot = true,
}: StatusBadgeProps) {
  const statusConfig: Record<string, { variant: BadgeProps['variant']; label: string }> = {
    active: { variant: 'success', label: 'Active' },
    inactive: { variant: 'default', label: 'Inactive' },
    pending: { variant: 'warning', label: 'Pending' },
    error: { variant: 'error', label: 'Error' },
    warning: { variant: 'warning', label: 'Warning' },
  };

  const config = statusConfig[status] || statusConfig.inactive;

  return (
    <Badge variant={config.variant} dot={showDot} className={className}>
      {label || config.label}
    </Badge>
  );
}
