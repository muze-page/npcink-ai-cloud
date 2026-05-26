'use client';

import React, { useMemo } from 'react';
import { useLocale } from '@/contexts/LocaleContext';
import { cn } from '@/lib/utils';

export interface UsageDataPoint {
  date: string;
  requests: number;
  tokens: number;
  cost?: number;
}

export interface UsageChartProps {
  data: UsageDataPoint[];
  type?: 'requests' | 'tokens' | 'cost';
  height?: number;
  className?: string;
  showGrid?: boolean;
  showTooltip?: boolean;
}

/**
 * 简单的 SVG 使用量图表组件
 * 支持 requests、tokens、cost 三种类型
 */
export function UsageChart({
  data,
  type = 'requests',
  height = 200,
  className,
  showGrid = true,
  showTooltip = true,
}: UsageChartProps) {
  const { t } = useLocale();
  const [hoveredIndex, setHoveredIndex] = React.useState<number | null>(null);

  // 计算图表数据
  const { points, maxValue, labels } = useMemo(() => {
    if (!data || data.length === 0) {
      return { points: '', maxValue: 0, labels: [] };
    }

    const values = data.map((d) => {
      if (type === 'cost') return d.cost || 0;
      if (type === 'tokens') return d.tokens;
      return d.requests;
    });

    const max = Math.max(...values, 1);
    const width = 100;
    const step = width / (data.length - 1 || 1);

    const pts = data
      .map((d, i) => {
        const x = i * step;
        const value = type === 'cost' ? d.cost || 0 : type === 'tokens' ? d.tokens : d.requests;
        const y = 100 - (value / max) * 100;
        return `${x},${y}`;
      })
      .join(' ');

    const dateLabels = data.map((d) => d.date);

    return { points: pts, maxValue: max, labels: dateLabels };
  }, [data, type]);

  // 格式化数值
  const formatValue = (value: number) => {
    if (type === 'cost') {
      return `$${value.toFixed(2)}`;
    }
    if (type === 'tokens') {
      if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
      if (value >= 1000) return `${(value / 1000).toFixed(0)}K`;
      return value.toString();
    }
    if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
    if (value >= 1000) return `${(value / 1000).toFixed(0)}K`;
    return value.toString();
  };

  // 生成面积路径
  const areaPath = useMemo(() => {
    if (!points) return '';
    const pts = points.split(' ');
    if (pts.length === 0) return '';
    
    const firstX = pts[0].split(',')[0];
    const lastX = pts[pts.length - 1].split(',')[0];
    
    return `M ${firstX},100 L ${points} L ${lastX},100 Z`;
  }, [points]);

  if (!data || data.length === 0) {
    return (
      <div className={cn('flex items-center justify-center', className)} style={{ height }}>
        <p className="text-gray-500 dark:text-gray-400 text-sm">{t('usage.no_data')}</p>
      </div>
    );
  }

  return (
    <div className={cn('relative w-full', className)} style={{ height }}>
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        className="w-full h-full"
        role="img"
        aria-label={`${type} usage chart`}
      >
        {/* 网格线 */}
        {showGrid && (
          <g className="stroke-gray-200 dark:stroke-gray-700" strokeWidth="0.5">
            <line x1="0" y1="25" x2="100" y2="25" />
            <line x1="0" y1="50" x2="100" y2="50" />
            <line x1="0" y1="75" x2="100" y2="75" />
          </g>
        )}

        {/* 面积填充 */}
        <path
          d={areaPath}
          className="fill-blue-500/10 dark:fill-blue-400/10"
        />

        {/* 折线 */}
        <polyline
          points={points}
          fill="none"
          className="stroke-blue-500 dark:stroke-blue-400"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* 数据点 */}
        {data.map((_, i) => {
          const x = (i / (data.length - 1 || 1)) * 100;
          const value = type === 'cost' ? (data[i].cost || 0) : type === 'tokens' ? data[i].tokens : data[i].requests;
          const y = 100 - (value / maxValue) * 100;
          
          return (
            <g key={i}>
              <circle
                cx={x}
                cy={y}
                r={hoveredIndex === i ? 4 : 2}
                className={cn(
                  'transition-all duration-150',
                  hoveredIndex === i
                    ? 'fill-blue-600 dark:fill-blue-300'
                    : 'fill-blue-500 dark:fill-blue-400'
                )}
              />
              {/* 透明悬停区域 */}
              {showTooltip && (
                <rect
                  x={x - (50 / data.length)}
                  y="0"
                  width={100 / data.length}
                  height="100"
                  fill="transparent"
                  className="cursor-pointer"
                  onMouseEnter={() => setHoveredIndex(i)}
                  onMouseLeave={() => setHoveredIndex(null)}
                />
              )}
            </g>
          );
        })}
      </svg>

      {/* 工具提示 */}
      {showTooltip && hoveredIndex !== null && data[hoveredIndex] && (
        <div
          className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-full mt-2 px-3 py-2 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 text-xs rounded shadow-lg pointer-events-none z-10"
          style={{
            left: `${(hoveredIndex / (data.length - 1 || 1)) * 100}%`,
          }}
        >
          <div className="font-medium">{labels[hoveredIndex]}</div>
          <div className="mt-1">
            {formatValue(
              type === 'cost'
                ? (data[hoveredIndex].cost || 0)
                : type === 'tokens'
                ? data[hoveredIndex].tokens
                : data[hoveredIndex].requests
            )}
          </div>
        </div>
      )}

      {/* X 轴标签 */}
      <div className="flex justify-between mt-2 text-xs text-gray-500 dark:text-gray-400">
        <span>{labels[0]}</span>
        <span>{labels[labels.length - 1]}</span>
      </div>
    </div>
  );
}

/**
 * 条形图组件
 */
export function UsageBarChart({
  data,
  type = 'requests',
  height = 200,
  className,
}: UsageChartProps) {
  const { t } = useLocale();
  const maxValue = useMemo(() => {
    if (!data || data.length === 0) return 0;
    return Math.max(
      ...data.map((d) => (type === 'cost' ? d.cost || 0 : type === 'tokens' ? d.tokens : d.requests)),
      1
    );
  }, [data, type]);

  const formatValue = (value: number) => {
    if (type === 'cost') return `$${value.toFixed(2)}`;
    if (type === 'tokens') {
      if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
      if (value >= 1000) return `${(value / 1000).toFixed(0)}K`;
      return value.toString();
    }
    if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
    if (value >= 1000) return `${(value / 1000).toFixed(0)}K`;
    return value.toString();
  };

  if (!data || data.length === 0) {
    return (
      <div className={cn('flex items-center justify-center', className)} style={{ height }}>
        <p className="text-gray-500 dark:text-gray-400 text-sm">{t('usage.no_data')}</p>
      </div>
    );
  }

  return (
    <div className={cn('w-full flex items-end gap-1', className)} style={{ height }}>
      {data.map((item, index) => {
        const value = type === 'cost' ? (item.cost || 0) : type === 'tokens' ? item.tokens : item.requests;
        const barHeight = (value / maxValue) * 100;
        
        return (
          <div
            key={index}
            className="flex-1 flex flex-col items-center group relative"
          >
            {/* 工具提示 */}
            <div className="absolute bottom-full mb-2 px-2 py-1 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-10">
              <div>{item.date}</div>
              <div>{formatValue(value)}</div>
            </div>
            
            {/* 条形 */}
            <div
              className="w-full bg-blue-500 dark:bg-blue-400 rounded-t transition-all duration-150 group-hover:bg-blue-600 dark:group-hover:bg-blue-300"
              style={{ height: `${barHeight}%` }}
            />
          </div>
        );
      })}
    </div>
  );
}

/**
 * 按模型分类的使用量图表
 */
export function UsageByModelChart({
  data,
  className,
}: {
  data: { model: string; requests: number; tokens: number; cost: number }[];
  className?: string;
}) {
  const totalRequests = data.reduce((sum, d) => sum + d.requests, 0);
  const totalTokens = data.reduce((sum, d) => sum + d.tokens, 0);
  const totalCost = data.reduce((sum, d) => sum + d.cost, 0);

  const colors = [
    'bg-blue-500',
    'bg-purple-500',
    'bg-green-500',
    'bg-yellow-500',
    'bg-red-500',
    'bg-indigo-500',
    'bg-pink-500',
    'bg-cyan-500',
  ];

  return (
    <div className={cn('space-y-4', className)}>
      {/* 汇总卡片 */}
      <div className="grid grid-cols-3 gap-4">
        <div className="text-center p-4 bg-gray-50 dark:bg-gray-800 rounded-lg">
          <div className="text-2xl font-bold">{(totalRequests / 1000).toFixed(0)}K</div>
          <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">Total Requests</div>
        </div>
        <div className="text-center p-4 bg-gray-50 dark:bg-gray-800 rounded-lg">
          <div className="text-2xl font-bold">{(totalTokens / 1000000).toFixed(1)}M</div>
          <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">Total Tokens</div>
        </div>
        <div className="text-center p-4 bg-gray-50 dark:bg-gray-800 rounded-lg">
          <div className="text-2xl font-bold">${totalCost.toFixed(2)}</div>
          <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">Total Cost</div>
        </div>
      </div>

      {/* 按模型分类 */}
      <div className="space-y-3">
        {data.map((item, index) => {
          const percentage = totalRequests > 0 ? (item.requests / totalRequests) * 100 : 0;
          const color = colors[index % colors.length];
          
          return (
            <div key={item.model} className="space-y-1">
              <div className="flex justify-between text-sm">
                <span className="font-medium">{item.model}</span>
                <span className="text-gray-500 dark:text-gray-400">
                  {(item.requests / 1000).toFixed(0)}K requests
                </span>
              </div>
              <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={cn('h-full rounded-full transition-all duration-300', color)}
                  style={{ width: `${percentage}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default UsageChart;
