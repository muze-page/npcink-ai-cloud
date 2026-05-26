/**
 * 性能监控器
 * 监控页面加载性能、API 请求性能等
 */

export interface PerfMetric {
  name: string;
  value: number;
  unit: 'ms' | 'bytes' | 'count';
  timestamp: number;
  tags?: Record<string, string>;
}

export interface WebVitals {
  fcp?: number; // First Contentful Paint
  lcp?: number; // Largest Contentful Paint
  fid?: number; // First Input Delay
  cls?: number; // Cumulative Layout Shift
  ttfb?: number; // Time to First Byte
}

export interface ApiPerfStats {
  endpoint: string;
  method: string;
  duration: number;
  status: number;
  timestamp: number;
  size?: number;
}

class PerfMonitorClass {
  private metrics: PerfMetric[] = [];
  private apiStats: ApiPerfStats[] = [];
  private webVitals: WebVitals = {};
  private maxMetrics = 100;
  private maxApiStats = 50;
  private observer?: PerformanceObserver;
  private enabled = true;

  constructor() {
    this.enabled = process.env.NEXT_PUBLIC_PERF_MONITORING_ENABLED === 'true';
  }

  /**
   * 启用性能监控
   */
  enable(): void {
    this.enabled = true;
  }

  /**
   * 禁用性能监控
   */
  disable(): void {
    this.enabled = false;
  }

  /**
   * 开始监控
   */
  start(): void {
    if (typeof window === 'undefined' || !this.enabled) return;

    // 监听 Web Vitals
    this.observeWebVitals();

    // 监听资源加载
    this.observeResources();

    // 记录页面加载开始时间
    this.mark('page_start');

    console.log('[PerfMonitor] Started');
  }

  /**
   * 记录性能标记
   */
  mark(name: string): void {
    if (!this.enabled) return;
    performance.mark(name);
  }

  /**
   * 测量时间
   */
  measure(name: string, startMark: string, endMark: string): number | null {
    if (!this.enabled) return null;

    try {
      performance.measure(name, startMark, endMark);
      const entries = performance.getEntriesByName(name, 'measure');
      if (entries.length > 0) {
        const duration = entries[0].duration;
        this.recordMetric({
          name,
          value: duration,
          unit: 'ms',
          timestamp: Date.now(),
        });
        return duration;
      }
    } catch (e) {
      console.warn('[PerfMonitor] Measure error:', e);
    }
    return null;
  }

  /**
   * 记录 API 请求性能
   */
  recordApiCall(stats: ApiPerfStats): void {
    if (!this.enabled) return;

    this.apiStats.push(stats);
    if (this.apiStats.length > this.maxApiStats) {
      this.apiStats.shift();
    }

    // 记录为指标
    this.recordMetric({
      name: `api_${stats.method}_${stats.endpoint}`,
      value: stats.duration,
      unit: 'ms',
      timestamp: stats.timestamp,
      tags: {
        status: String(stats.status),
        method: stats.method,
      },
    });
  }

  /**
   * 记录指标
   */
  recordMetric(metric: PerfMetric): void {
    this.metrics.push(metric);
    if (this.metrics.length > this.maxMetrics) {
      this.metrics.shift();
    }

    // 发送到收集端点
    this.sendMetric(metric);
  }

  /**
   * 获取 Web Vitals
   */
  getWebVitals(): WebVitals {
    return { ...this.webVitals };
  }

  /**
   * 获取 API 性能统计
   */
  getApiStats(limit = 10): ApiPerfStats[] {
    return this.apiStats.slice(-limit);
  }

  /**
   * 获取平均 API 响应时间
   */
  getAverageApiTime(): number {
    if (this.apiStats.length === 0) return 0;
    const sum = this.apiStats.reduce((acc, s) => acc + s.duration, 0);
    return sum / this.apiStats.length;
  }

  /**
   * 获取指标
   */
  getMetrics(filter?: { name?: string; since?: number }): PerfMetric[] {
    let result = this.metrics;

    if (filter?.name) {
      result = result.filter((m) => m.name.includes(filter.name!));
    }

    if (filter?.since) {
      result = result.filter((m) => m.timestamp >= filter.since!);
    }

    return result;
  }

  /**
   * 清除所有数据
   */
  clear(): void {
    this.metrics = [];
    this.apiStats = [];
    this.webVitals = {};
  }

  /**
   * 监听 Web Vitals
   */
  private observeWebVitals(): void {
    if (typeof PerformanceObserver === 'undefined') return;

    // LCP
    try {
      const lcpObserver = new PerformanceObserver((list) => {
        const entries = list.getEntries();
        const lastEntry = entries[entries.length - 1];
        this.webVitals.lcp = lastEntry.startTime;
        this.recordMetric({
          name: 'lcp',
          value: lastEntry.startTime,
          unit: 'ms',
          timestamp: Date.now(),
        });
      });
      lcpObserver.observe({ entryTypes: ['largest-contentful-paint'] });
    } catch (e) {
      // 不支持
    }

    // FCP
    try {
      const fcpObserver = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (entry.name === 'first-contentful-paint') {
            this.webVitals.fcp = entry.startTime;
            this.recordMetric({
              name: 'fcp',
              value: entry.startTime,
              unit: 'ms',
              timestamp: Date.now(),
            });
          }
        }
      });
      fcpObserver.observe({ entryTypes: ['paint'] });
    } catch (e) {
      // 不支持
    }

    // CLS - 使用 any 类型避免 TypeScript 错误
    try {
      let clsValue = 0;
      const clsObserver = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          const e = entry as any;
          if (!e.hadRecentInput) {
            clsValue += e.value;
          }
        }
        this.webVitals.cls = clsValue;
        this.recordMetric({
          name: 'cls',
          value: clsValue,
          unit: 'count',
          timestamp: Date.now(),
        });
      });
      clsObserver.observe({ entryTypes: ['layout-shift'] as any });
    } catch (e) {
      // 不支持
    }

    // TTFB (通过 navigation timing)
    const navigationEntries = performance.getEntriesByType('navigation');
    if (navigationEntries.length > 0) {
      const nav = navigationEntries[0] as PerformanceNavigationTiming;
      this.webVitals.ttfb = nav.responseStart;
      this.recordMetric({
        name: 'ttfb',
        value: nav.responseStart,
        unit: 'ms',
        timestamp: Date.now(),
      });
    }
  }

  /**
   * 监听资源加载
   */
  private observeResources(): void {
    if (typeof PerformanceObserver === 'undefined') return;

    try {
      const resourceObserver = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          const resourceEntry = entry as PerformanceResourceTiming;
          
          // 只记录重要的资源
          if (
            resourceEntry.initiatorType === 'script' ||
            resourceEntry.initiatorType === 'link' ||
            resourceEntry.initiatorType === 'img'
          ) {
            this.recordMetric({
              name: `resource_${resourceEntry.initiatorType}`,
              value: resourceEntry.duration,
              unit: 'ms',
              timestamp: Date.now(),
              tags: {
                url: resourceEntry.name,
              },
            });
          }
        }
      });
      resourceObserver.observe({ entryTypes: ['resource'] });
    } catch (e) {
      // 不支持
    }
  }

  /**
   * 发送指标到服务器
   */
  private async sendMetric(metric: PerfMetric): Promise<void> {
    const endpoint = process.env.NEXT_PUBLIC_PERF_REPORTING_ENDPOINT;
    if (!endpoint) return;

    try {
      await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          metric,
          page: typeof window !== 'undefined' ? window.location.pathname : undefined,
        }),
        keepalive: true,
      });
    } catch (e) {
      // 静默失败
    }
  }

  /**
   * 生成性能报告
   */
  generateReport(): {
    webVitals: WebVitals;
    avgApiTime: number;
    slowestApis: ApiPerfStats[];
    totalMetrics: number;
  } {
    const slowestApis = [...this.apiStats]
      .sort((a, b) => b.duration - a.duration)
      .slice(0, 5);

    return {
      webVitals: this.getWebVitals(),
      avgApiTime: this.getAverageApiTime(),
      slowestApis,
      totalMetrics: this.metrics.length,
    };
  }
}

// 单例
export const PerfMonitor = new PerfMonitorClass();

/**
 * 包装 fetch 以监控 API 性能
 */
export function createMonitoredFetch(originalFetch = globalThis.fetch) {
  return async function monitoredFetch(
    input: RequestInfo | URL,
    init?: RequestInit
  ): Promise<Response> {
    const startTime = performance.now();
    const endpoint = typeof input === 'string' ? input : input instanceof URL ? input.pathname : (input as Request).url;
    const method = init?.method || 'GET';

    try {
      const response = await originalFetch(input, init);
      const duration = performance.now() - startTime;

      PerfMonitor.recordApiCall({
        endpoint,
        method,
        duration,
        status: response.status,
        timestamp: Date.now(),
      });

      return response;
    } catch (error) {
      const duration = performance.now() - startTime;

      PerfMonitor.recordApiCall({
        endpoint,
        method,
        duration,
        status: 0,
        timestamp: Date.now(),
      });

      throw error;
    }
  };
}

export default PerfMonitor;