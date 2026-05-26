'use client';

import React, { useMemo } from 'react';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import {
  BarChart,
  LineChart,
  PieChart,
  GaugeChart,
} from 'echarts/charts';
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  DatasetComponent,
  TransformComponent,
  MarkLineComponent,
  MarkPointComponent,
} from 'echarts/components';
import { LabelLayout, UniversalTransition } from 'echarts/features';
import { CanvasRenderer } from 'echarts/renderers';
import { useTheme } from '@/hooks/useTheme';
import { cn } from '@/lib/utils';

// Register only the components we need (tree-shake friendly)
echarts.use([
  LineChart,
  BarChart,
  PieChart,
  GaugeChart,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  DatasetComponent,
  TransformComponent,
  MarkLineComponent,
  MarkPointComponent,
  LabelLayout,
  UniversalTransition,
  CanvasRenderer,
]);

export interface AnalyticsLineChartProps {
  data: Array<{
    label: string;
    value: number;
    secondaryValue?: number;
  }>;
  height?: number;
  className?: string;
  xAxisLabel?: string;
  yAxisLabel?: string;
  primarySeriesName?: string;
  secondarySeriesName?: string;
  primaryColor?: string;
  secondaryColor?: string;
}

export function AnalyticsLineChart({
  data,
  height = 280,
  className,
  xAxisLabel,
  yAxisLabel,
  primarySeriesName = 'Primary',
  secondarySeriesName = 'Secondary',
  primaryColor = '#3b82f6',
  secondaryColor = '#10b981',
}: AnalyticsLineChartProps) {
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  const option = useMemo(() => {
    const textColor = isDark ? '#e5e7eb' : '#374151';
    const gridColor = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)';
    const tooltipBg = isDark ? 'rgba(17,24,39,0.95)' : 'rgba(255,255,255,0.95)';
    const tooltipBorder = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)';

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        backgroundColor: tooltipBg,
        borderColor: tooltipBorder,
        textStyle: { color: textColor, fontSize: 12 },
        padding: [8, 12],
        borderRadius: 8,
        axisPointer: {
          type: 'cross',
          crossStyle: { color: gridColor },
        },
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        top: '10%',
        containLabel: true,
      },
      xAxis: {
        type: 'category',
        data: data.map((d) => d.label),
        axisLine: { lineStyle: { color: gridColor } },
        axisLabel: { color: textColor, fontSize: 11 },
        axisTick: { show: false },
        name: xAxisLabel,
        nameTextStyle: { color: textColor, fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        axisLabel: { color: textColor, fontSize: 11 },
        splitLine: { lineStyle: { color: gridColor, type: 'dashed' } },
        name: yAxisLabel,
        nameTextStyle: { color: textColor, fontSize: 11 },
      },
      series: [
        {
          name: primarySeriesName,
          type: 'line',
          smooth: true,
          symbol: 'circle',
          symbolSize: 6,
          data: data.map((d) => d.value),
          itemStyle: { color: primaryColor },
          lineStyle: { width: 2.5 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: primaryColor + '40' },
              { offset: 1, color: primaryColor + '05' },
            ]),
          },
        },
        ...(data.some((d) => d.secondaryValue !== undefined)
          ? [
              {
                name: secondarySeriesName,
                type: 'line',
                smooth: true,
                symbol: 'circle',
                symbolSize: 6,
                data: data.map((d) => d.secondaryValue ?? 0),
                itemStyle: { color: secondaryColor },
                lineStyle: { width: 2.5 },
                areaStyle: {
                  color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                    { offset: 0, color: secondaryColor + '40' },
                    { offset: 1, color: secondaryColor + '05' },
                  ]),
                },
              },
            ]
          : []),
      ],
    };
  }, [data, isDark, xAxisLabel, yAxisLabel, primarySeriesName, secondarySeriesName, primaryColor, secondaryColor]);

  return (
    <ReactEChartsCore
      echarts={echarts}
      option={option}
      style={{ height }}
      className={cn('w-full', className)}
      notMerge
      lazyUpdate
    />
  );
}

export interface AnalyticsBarChartProps {
  data: Array<{
    label: string;
    value: number;
    color?: string;
  }>;
  height?: number;
  className?: string;
  horizontal?: boolean;
  barColor?: string;
}

export function AnalyticsBarChart({
  data,
  height = 280,
  className,
  horizontal = false,
  barColor = '#3b82f6',
}: AnalyticsBarChartProps) {
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  const option = useMemo(() => {
    const textColor = isDark ? '#e5e7eb' : '#374151';
    const gridColor = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)';
    const tooltipBg = isDark ? 'rgba(17,24,39,0.95)' : 'rgba(255,255,255,0.95)';
    const tooltipBorder = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)';

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        backgroundColor: tooltipBg,
        borderColor: tooltipBorder,
        textStyle: { color: textColor, fontSize: 12 },
        padding: [8, 12],
        borderRadius: 8,
        axisPointer: { type: 'shadow' },
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        top: '5%',
        containLabel: true,
      },
      xAxis: {
        type: horizontal ? 'value' : 'category',
        data: horizontal ? undefined : data.map((d) => d.label),
        axisLine: { lineStyle: { color: gridColor } },
        axisLabel: { color: textColor, fontSize: 11 },
        axisTick: { show: false },
        splitLine: horizontal ? { lineStyle: { color: gridColor, type: 'dashed' } } : undefined,
      },
      yAxis: {
        type: horizontal ? 'category' : 'value',
        data: horizontal ? data.map((d) => d.label) : undefined,
        axisLine: { show: false },
        axisLabel: { color: textColor, fontSize: 11 },
        splitLine: horizontal ? undefined : { lineStyle: { color: gridColor, type: 'dashed' } },
      },
      series: [
        {
          type: 'bar',
          data: data.map((d) => ({
            value: d.value,
            itemStyle: { color: d.color || barColor },
          })),
          barMaxWidth: 32,
          itemStyle: { borderRadius: [4, 4, 0, 0] },
        },
      ],
    };
  }, [data, isDark, horizontal, barColor]);

  return (
    <ReactEChartsCore
      echarts={echarts}
      option={option}
      style={{ height }}
      className={cn('w-full', className)}
      notMerge
      lazyUpdate
    />
  );
}

export interface AnalyticsPieChartProps {
  data: Array<{
    label: string;
    value: number;
    color?: string;
  }>;
  height?: number;
  className?: string;
  donut?: boolean;
}

export function AnalyticsPieChart({
  data,
  height = 280,
  className,
  donut = false,
}: AnalyticsPieChartProps) {
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  const option = useMemo(() => {
    const textColor = isDark ? '#e5e7eb' : '#374151';
    const tooltipBg = isDark ? 'rgba(17,24,39,0.95)' : 'rgba(255,255,255,0.95)';
    const tooltipBorder = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)';

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        backgroundColor: tooltipBg,
        borderColor: tooltipBorder,
        textStyle: { color: textColor, fontSize: 12 },
        padding: [8, 12],
        borderRadius: 8,
        formatter: '{b}: {c} ({d}%)',
      },
      legend: {
        orient: 'vertical',
        left: 'left',
        textStyle: { color: textColor, fontSize: 11 },
        itemWidth: 12,
        itemHeight: 12,
        itemGap: 8,
      },
      series: [
        {
          type: 'pie',
          radius: donut ? ['45%', '70%'] : '65%',
          center: ['60%', '50%'],
          data: data.map((d) => ({
            name: d.label,
            value: d.value,
            itemStyle: d.color ? { color: d.color } : undefined,
          })),
          emphasis: {
            itemStyle: {
              shadowBlur: 10,
              shadowOffsetX: 0,
              shadowColor: 'rgba(0, 0, 0, 0.2)',
            },
          },
          label: {
            color: textColor,
            fontSize: 11,
          },
          labelLine: {
            lineStyle: { color: isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.2)' },
          },
        },
      ],
    };
  }, [data, isDark, donut]);

  return (
    <ReactEChartsCore
      echarts={echarts}
      option={option}
      style={{ height }}
      className={cn('w-full', className)}
      notMerge
      lazyUpdate
    />
  );
}

export interface AnalyticsGaugeChartProps {
  value: number;
  min?: number;
  max?: number;
  title?: string;
  unit?: string;
  height?: number;
  className?: string;
  color?: string;
}

export function AnalyticsGaugeChart({
  value,
  min = 0,
  max = 100,
  title,
  unit = '',
  height = 200,
  className,
  color = '#3b82f6',
}: AnalyticsGaugeChartProps) {
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  const option = useMemo(() => {
    const textColor = isDark ? '#e5e7eb' : '#374151';
    const subtextColor = isDark ? '#9ca3af' : '#6b7280';

    return {
      backgroundColor: 'transparent',
      series: [
        {
          type: 'gauge',
          startAngle: 200,
          endAngle: -20,
          min,
          max,
          splitNumber: 5,
          itemStyle: { color },
          progress: {
            show: true,
            width: 18,
            roundCap: true,
          },
          pointer: {
            show: false,
          },
          axisLine: {
            lineStyle: { width: 18, color: [[1, isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)']] },
          },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { show: false },
          anchor: { show: false },
          title: {
            show: !!title,
            offsetCenter: [0, '30%'],
            fontSize: 14,
            color: textColor,
          },
          detail: {
            valueAnimation: true,
            fontSize: 28,
            fontWeight: 'bold',
            offsetCenter: [0, '0%'],
            color: textColor,
            formatter: `{value}${unit}`,
          },
          data: [{ value, name: title || '' }],
        },
      ],
    };
  }, [value, min, max, title, unit, isDark, color]);

  return (
    <ReactEChartsCore
      echarts={echarts}
      option={option}
      style={{ height }}
      className={cn('w-full', className)}
      notMerge
      lazyUpdate
    />
  );
}
