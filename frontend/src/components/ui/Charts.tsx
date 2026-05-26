'use client';

import React from 'react';
import { cn } from '@/lib/utils';

// ============================================
// 类型定义
// ============================================

export interface ChartDataPoint {
  label: string;
  value: number;
  color?: string;
}

export interface LineChartDataPoint {
  label: string;
  value: number;
  date?: string;
}

// ============================================
// 工具函数
// ============================================

function formatNumber(value: number): string {
  if (value >= 1000000) {
    return `${(value / 1000000).toFixed(1)}M`;
  }
  if (value >= 1000) {
    return `${(value / 1000).toFixed(1)}K`;
  }
  return value.toString();
}

function formatLabel(label: string): string {
  // 缩短长标签
  if (label.length > 10) {
    return label.slice(0, 3) + '...' + label.slice(-3);
  }
  return label;
}

// ============================================
// 条形图组件
// ============================================

interface BarChartProps {
  data: ChartDataPoint[];
  height?: number;
  showValues?: boolean;
  showLabels?: boolean;
  className?: string;
  barColor?: string;
  maxValue?: number;
}

/**
 * 简单的条形图组件
 * 使用纯 CSS 实现，无需外部图表库
 */
export function BarChart({
  data,
  height = 200,
  showValues = true,
  showLabels = true,
  className,
  barColor = 'bg-blue-500',
  maxValue,
}: BarChartProps) {
  const max = maxValue ?? Math.max(...data.map((d) => d.value), 1);

  return (
    <div className={cn('w-full', className)}>
      <div
        className="flex items-end gap-1"
        style={{ height: `${height}px` }}
      >
        {data.map((point, index) => {
          const barHeight = (point.value / max) * 100;
          return (
            <div
              key={index}
              className="flex-1 flex flex-col items-center justify-end group relative"
            >
              {showValues && point.value > 0 && (
                <div className="absolute -top-6 left-1/2 -translate-x-1/2 text-xs text-gray-600 dark:text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-10">
                  {formatNumber(point.value)}
                </div>
              )}
              <div
                className={cn(
                  'w-full rounded-t transition-all duration-300 hover:opacity-80',
                  barColor
                )}
                style={{ height: `${Math.max(barHeight, 2)}%` }}
                title={`${point.label}: ${formatNumber(point.value)}`}
              />
            </div>
          );
        })}
      </div>
      {showLabels && (
        <div className="flex gap-1 mt-2">
          {data.map((point, index) => (
            <div
              key={index}
              className="flex-1 text-center text-xs text-gray-500 dark:text-gray-400 truncate"
              title={point.label}
            >
              {formatLabel(point.label)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================
// 堆叠条形图组件
// ============================================

interface StackedBarChartProps {
  data: Array<{
    label: string;
    segments: ChartDataPoint[];
  }>;
  height?: number;
  showLabels?: boolean;
  className?: string;
}

/**
 * 堆叠条形图组件
 */
export function StackedBarChart({
  data,
  height = 200,
  showLabels = true,
  className,
}: StackedBarChartProps) {
  const maxTotal = Math.max(
    ...data.map((d) => d.segments.reduce((sum, s) => sum + s.value, 0)),
    1
  );

  return (
    <div className={cn('w-full', className)}>
      <div
        className="flex items-end gap-2"
        style={{ height: `${height}px` }}
      >
        {data.map((item, index) => {
          const total = item.segments.reduce((sum, s) => sum + s.value, 0);
          const barHeight = (total / maxTotal) * 100;
          
          return (
            <div
              key={index}
              className="flex-1 flex flex-col items-center justify-end group"
            >
              <div
                className="w-full rounded-t overflow-hidden flex flex-col-reverse"
                style={{ height: `${Math.max(barHeight, 2)}%` }}
              >
                {item.segments.map((segment, segIndex) => {
                  const segmentHeight = total > 0 ? (segment.value / total) * 100 : 0;
                  return (
                    <div
                      key={segIndex}
                      className={cn(
                        'w-full transition-all duration-300 hover:opacity-80',
                        segment.color || 'bg-blue-500'
                      )}
                      style={{ height: `${segmentHeight}%` }}
                      title={`${segment.label}: ${formatNumber(segment.value)}`}
                    />
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
      {showLabels && (
        <div className="flex gap-2 mt-2">
          {data.map((item, index) => (
            <div
              key={index}
              className="flex-1 text-center text-xs text-gray-500 dark:text-gray-400 truncate"
              title={item.label}
            >
              {formatLabel(item.label)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================
// 折线图组件 (SVG)
// ============================================

interface LineChartProps {
  data: LineChartDataPoint[];
  height?: number;
  showPoints?: boolean;
  showGrid?: boolean;
  showLabels?: boolean;
  className?: string;
  lineColor?: string;
  fillColor?: string;
  maxValue?: number;
}

/**
 * 简单的折线图组件
 * 使用 SVG 实现
 */
export function LineChart({
  data,
  height = 200,
  showPoints = true,
  showGrid = true,
  showLabels = true,
  className,
  lineColor = '#3b82f6',
  fillColor = 'rgba(59, 130, 246, 0.1)',
  maxValue,
}: LineChartProps) {
  const max = maxValue ?? Math.max(...data.map((d) => d.value), 1);
  const min = Math.min(...data.map((d) => d.value), 0);
  const range = max - min || 1;
  const safeLabelCount = Math.max(data.length, 1);

  // 计算点坐标
  const points = data.map((point, index) => {
    const x = (index / (data.length - 1 || 1)) * 100;
    const y = 100 - ((point.value - min) / range) * 100;
    return { x, y, ...point };
  });

  // 生成折线路径
  const linePath = points
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`)
    .join(' ');

  // 生成填充路径
  const fillPath = points.length > 0
    ? `M 0 100 L ${points.map((p) => `${p.x} ${p.y}`).join(' L ')} L 100 100 Z`
    : '';

  return (
    <div className={cn('w-full', className)}>
      <svg
        viewBox="0 0 100 100"
        className="w-full"
        style={{ height: `${height}px` }}
        preserveAspectRatio="none"
      >
        {/* 网格线 */}
        {showGrid && (
          <>
            <line x1="0" y1="25" x2="100" y2="25" stroke="currentColor" className="text-gray-200 dark:text-gray-700" strokeWidth="0.5" />
            <line x1="0" y1="50" x2="100" y2="50" stroke="currentColor" className="text-gray-200 dark:text-gray-700" strokeWidth="0.5" />
            <line x1="0" y1="75" x2="100" y2="75" stroke="currentColor" className="text-gray-200 dark:text-gray-700" strokeWidth="0.5" />
          </>
        )}

        {/* 填充区域 */}
        {fillPath && (
          <path d={fillPath} fill={fillColor} />
        )}

        {/* 折线 */}
        {points.length > 0 && (
          <path
            d={linePath}
            fill="none"
            stroke={lineColor}
            strokeWidth="1.5"
            vectorEffect="non-scaling-stroke"
          />
        )}

        {/* 数据点 */}
        {showPoints &&
          points.map((point, index) => (
            <circle
              key={index}
              cx={point.x}
              cy={point.y}
              r="2"
              fill="white"
              stroke={lineColor}
              strokeWidth="1"
              vectorEffect="non-scaling-stroke"
              className="cursor-pointer hover:r-3 transition-all"
            >
              <title>{`${point.label}: ${formatNumber(point.value)}`}</title>
            </circle>
          ))}
      </svg>

      {showLabels && (
        <div className="flex justify-between mt-2">
          {data.map((point, index) => (
            <div
              key={index}
              className="text-xs text-gray-500 dark:text-gray-400 truncate text-center"
              style={{ width: `${100 / safeLabelCount}%` }}
              title={point.label}
            >
              {formatLabel(point.label)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================
// 饼图组件 (SVG)
// ============================================

interface PieChartProps {
  data: ChartDataPoint[];
  size?: number;
  showLabels?: boolean;
  showLegend?: boolean;
  showValues?: boolean;
  className?: string;
}

/**
 * 简单的饼图组件
 * 使用 SVG 实现
 */
export function PieChart({
  data,
  size = 200,
  showLabels = true,
  showLegend = true,
  showValues = true,
  className,
}: PieChartProps) {
  const total = data.reduce((sum, d) => sum + d.value, 0);
  const safeTotal = total > 0 ? total : 1;
  const colors = [
    '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
    '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1',
  ];

  const segmentState = data.reduce<{
    currentAngle: number;
    segments: Array<ChartDataPoint & {
      path: string;
      color: string;
      percentage: string;
    }>;
  }>((acc, point, index) => {
    const angle = (point.value / safeTotal) * 360;
    const startAngle = acc.currentAngle;
    const endAngle = acc.currentAngle + angle;

    // 计算弧形的路径
    const startRad = (startAngle - 90) * (Math.PI / 180);
    const endRad = (endAngle - 90) * (Math.PI / 180);

    const x1 = 50 + 40 * Math.cos(startRad);
    const y1 = 50 + 40 * Math.sin(startRad);
    const x2 = 50 + 40 * Math.cos(endRad);
    const y2 = 50 + 40 * Math.sin(endRad);

    const largeArc = angle > 180 ? 1 : 0;

    const path = `M 50 50 L ${x1} ${y1} A 40 40 0 ${largeArc} 1 ${x2} ${y2} Z`;

    acc.segments.push({
      path,
      color: point.color || colors[index % colors.length],
      ...point,
      percentage: ((point.value / safeTotal) * 100).toFixed(1),
    });
    acc.currentAngle = endAngle;

    return acc;
  }, { currentAngle: 0, segments: [] });
  const segments = segmentState.segments;

  return (
    <div className={cn('flex items-center gap-4', className)}>
      <svg
        viewBox="0 0 100 100"
        className="flex-shrink-0"
        style={{ width: `${size}px`, height: `${size}px` }}
      >
        {segments.map((segment, index) => (
          <path
            key={index}
            d={segment.path}
            fill={segment.color}
            className="hover:opacity-80 transition-opacity cursor-pointer"
          >
            <title>{`${segment.label}: ${formatNumber(segment.value)} (${segment.percentage}%)`}</title>
          </path>
        ))}
      </svg>

      {showLegend && (
        <div className="flex-1 space-y-2">
          {segments.map((segment, index) => (
            <div key={index} className="flex items-center gap-2 text-sm">
              <div
                className="w-3 h-3 rounded flex-shrink-0"
                style={{ backgroundColor: segment.color }}
              />
              <span className="text-gray-600 dark:text-gray-400 truncate flex-1">
                {segment.label}
              </span>
              {showValues && (
                <span className="text-gray-900 dark:text-gray-100 font-medium">
                  {showValues ? `${segment.percentage}%` : ''}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================
// 统计卡片组件
// ============================================

interface StatCardProps {
  title: string;
  value: string | number;
  change?: number;
  changeLabel?: string;
  icon?: React.ReactNode;
  className?: string;
}

/**
 * 统计卡片组件
 */
export function StatCard({
  title,
  value,
  change,
  changeLabel = 'vs last period',
  icon,
  className,
}: StatCardProps) {
  const isPositive = change !== undefined && change >= 0;

  return (
    <div className={cn(
      'p-4 border border-gray-200 dark:border-gray-700 rounded-lg',
      className
    )}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-gray-600 dark:text-gray-400">{title}</p>
          <p className="text-2xl font-bold mt-1">{value}</p>
          {change !== undefined && (
            <div className="flex items-center gap-1 mt-2">
              <span
                className={cn(
                  'text-xs font-medium',
                  isPositive
                    ? 'text-green-600'
                    : 'text-red-600'
                )}
              >
                {isPositive ? '↑' : '↓'} {Math.abs(change)}%
              </span>
              <span className="text-xs text-gray-500">{changeLabel}</span>
            </div>
          )}
        </div>
        {icon && (
          <div className="text-gray-400">
            {icon}
          </div>
        )}
      </div>
    </div>
  );
}
