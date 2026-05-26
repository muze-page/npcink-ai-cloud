import React from 'react';
import { cn } from '@/lib/utils';

interface SkeletonProps {
  className?: string;
  variant?: 'text' | 'circular' | 'rectangular';
  width?: string | number;
  height?: string | number;
  animation?: 'pulse' | 'wave' | false;
  style?: React.CSSProperties;
}

/**
 * 骨架屏组件
 * 用于加载状态的占位符
 */
export function Skeleton({
  className,
  variant = 'text',
  width,
  height,
  animation = 'pulse',
}: SkeletonProps) {
  const baseStyles = cn(
    'bg-gray-200 dark:bg-gray-700 rounded',
    animation === 'pulse' && 'animate-pulse',
    animation === 'wave' && 'animate-pulse',
    variant === 'circular' && 'rounded-full',
    className
  );

  const style: React.CSSProperties = {};
  if (width !== undefined) {
    style.width = typeof width === 'string' ? width : `${width}px`;
  }
  if (height !== undefined) {
    style.height = typeof height === 'string' ? height : `${height}px`;
  }
  if (variant === 'text' && !height) {
    style.height = '1em';
  }

  return <div className={baseStyles} style={style} />;
}

/**
 * 文本骨架屏
 */
interface SkeletonTextProps {
  lines?: number;
  gap?: string;
  maxLength?: string | number;
  className?: string;
}

export function SkeletonText({
  lines = 1,
  gap = '2',
  maxLength,
  className,
}: SkeletonTextProps) {
  const maxLengthStyle = typeof maxLength === 'string' ? maxLength : `${maxLength}px`;
  
  return (
    <div className={cn('space-y-2', className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          variant="text"
          className={cn(
            'w-full',
            maxLength && 'max-w-[var(--max-length)]'
          )}
          style={{ '--max-length': maxLengthStyle } as React.CSSProperties}
        />
      ))}
    </div>
  );
}

/**
 * 卡片骨架屏
 */
interface SkeletonCardProps {
  className?: string;
  showImage?: boolean;
  showTitle?: boolean;
  showDescription?: boolean;
  showFooter?: boolean;
}

export function SkeletonCard({
  className,
  showImage = true,
  showTitle = true,
  showDescription = true,
  showFooter = false,
}: SkeletonCardProps) {
  return (
    <div className={cn('p-4 border border-gray-200 dark:border-gray-700 rounded-lg', className)}>
      {showImage && (
        <Skeleton variant="rectangular" className="w-full h-32 mb-4" />
      )}
      {showTitle && (
        <SkeletonText lines={1} maxLength="60%" className="mb-2" />
      )}
      {showDescription && (
        <SkeletonText lines={2} className="mb-4" />
      )}
      {showFooter && (
        <div className="flex gap-2">
          <Skeleton variant="rectangular" width={60} height={24} />
          <Skeleton variant="rectangular" width={60} height={24} />
        </div>
      )}
    </div>
  );
}

/**
 * 表格骨架屏
 */
interface SkeletonTableProps {
  columns?: number;
  rows?: number;
  className?: string;
}

export function SkeletonTable({
  columns = 4,
  rows = 5,
  className,
}: SkeletonTableProps) {
  return (
    <div className={cn('border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden', className)}>
      {/* Table Header */}
      <div className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
        <div className="grid" style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}>
          {Array.from({ length: columns }).map((_, i) => (
            <div key={i} className="px-4 py-3">
              <Skeleton variant="text" className="w-16" />
            </div>
          ))}
        </div>
      </div>
      {/* Table Body */}
      <div className="divide-y divide-gray-200 dark:divide-gray-700">
        {Array.from({ length: rows }).map((_, rowIndex) => (
          <div
            key={rowIndex}
            className="grid"
            style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}
          >
            {Array.from({ length: columns }).map((_, colIndex) => (
              <div key={colIndex} className="px-4 py-3">
                <Skeleton variant="text" className="w-full" />
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * 图表骨架屏
 */
interface SkeletonChartProps {
  height?: string | number;
  className?: string;
}

export function SkeletonChart({
  height = 200,
  className,
}: SkeletonChartProps) {
  return (
    <div className={cn('border border-gray-200 dark:border-gray-700 rounded-lg p-4', className)}>
      <div className="flex items-center justify-between mb-4">
        <Skeleton variant="text" width={100} height={20} />
        <Skeleton variant="text" width={60} height={16} />
      </div>
      <Skeleton
        variant="rectangular"
        className="w-full"
        height={height}
      />
    </div>
  );
}

/**
 * 列表骨架屏
 */
interface SkeletonListProps {
  items?: number;
  showAvatar?: boolean;
  showDescription?: boolean;
  className?: string;
}

export function SkeletonList({
  items = 5,
  showAvatar = true,
  showDescription = true,
  className,
}: SkeletonListProps) {
  return (
    <div className={cn('space-y-3', className)}>
      {Array.from({ length: items }).map((_, i) => (
        <div key={i} className="flex items-start gap-3">
          {showAvatar && (
            <Skeleton variant="circular" width={40} height={40} />
          )}
          <div className="flex-1 space-y-2">
            <Skeleton variant="text" width="40%" />
            {showDescription && (
              <SkeletonText lines={1} />
            )}
          </div>
        </div>
      ))}
    </div>
  );
}