/**
 * 错误追踪器
 * 简单的客户端错误追踪实现
 * 可以集成 Sentry 或其他错误追踪服务
 */

export interface ErrorContext {
  userId?: string;
  sessionId?: string;
  page?: string;
  component?: string;
  action?: string;
  metadata?: Record<string, unknown>;
}

export interface TrackedError {
  error: Error;
  timestamp: number;
  context: ErrorContext;
  handled: boolean;
}

export type ErrorSeverity = 'low' | 'medium' | 'high' | 'critical';

export interface ErrorTrackerConfig {
  enabled: boolean;
  environment: 'development' | 'staging' | 'production';
  sampleRate: number; // 0-1, 采样率
  beforeSend?: (error: TrackedError) => TrackedError | null;
  onError?: (error: TrackedError) => void;
}

class ErrorTrackerClass {
  private config: ErrorTrackerConfig;
  private errorQueue: TrackedError[] = [];
  private maxQueueSize = 50;

  constructor() {
    this.config = {
      enabled: process.env.NEXT_PUBLIC_ERROR_TRACKING_ENABLED === 'true',
      environment: (process.env.NEXT_PUBLIC_ENV as 'development' | 'staging' | 'production') || 'development',
      sampleRate: 1,
    };
  }

  /**
   * 配置错误追踪器
   */
  configure(config: Partial<ErrorTrackerConfig>) {
    this.config = { ...this.config, ...config };
  }

  /**
   * 捕获错误
   */
  capture(error: unknown, context: ErrorContext = {}): string | null {
    if (!this.config.enabled) {
      return null;
    }

    // 采样
    if (Math.random() > this.config.sampleRate) {
      return null;
    }

    const trackedError: TrackedError = {
      error: error instanceof Error ? error : new Error(String(error)),
      timestamp: Date.now(),
      context: {
        ...context,
        page: context.page || (typeof window !== 'undefined' ? window.location.pathname : undefined),
      },
      handled: true,
    };

    // 预处理
    if (this.config.beforeSend) {
      const processed = this.config.beforeSend(trackedError);
      if (!processed) {
        return null;
      }
      Object.assign(trackedError, processed);
    }

    // 添加到队列
    this.errorQueue.push(trackedError);
    if (this.errorQueue.length > this.maxQueueSize) {
      this.errorQueue.shift();
    }

    // 回调
    if (this.config.onError) {
      this.config.onError(trackedError);
    }

    // 发送到服务器（如果配置了）
    this.sendToServer(trackedError);

    // 生成错误 ID
    const errorId = `err_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    console.error(`[ErrorTracker] ${errorId}:`, trackedError.error, trackedError.context);

    return errorId;
  }

  /**
   * 捕获未处理的 Promise rejection
   */
  captureUnhandledRejection(reason: unknown, context: ErrorContext = {}): void {
    this.capture(
      reason instanceof Error ? reason : new Error(`Unhandled rejection: ${String(reason)}`),
      { ...context, action: 'unhandled_rejection' }
    );
  }

  /**
   * 获取最近的错误
   */
  getRecentErrors(limit = 10): TrackedError[] {
    return this.errorQueue.slice(-limit);
  }

  /**
   * 清除错误队列
   */
  clearErrors(): void {
    this.errorQueue = [];
  }

  /**
   * 设置用户上下文
   */
  setUserContext(userId?: string, sessionId?: string): void {
    // 可以在这里集成到错误追踪服务
  }

  /**
   * 发送到服务器
   */
  private async sendToServer(error: TrackedError): Promise<void> {
    const endpoint = process.env.NEXT_PUBLIC_ERROR_REPORTING_ENDPOINT;
    if (!endpoint) return;

    try {
      await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          error: {
            message: error.error.message,
            stack: error.error.stack,
            name: error.error.name,
          },
          context: error.context,
          timestamp: error.timestamp,
          environment: this.config.environment,
        }),
      });
    } catch (e) {
      // 静默失败，避免无限循环
      console.warn('[ErrorTracker] Failed to send error to server:', e);
    }
  }

  /**
   * 获取错误严重性
   */
  getSeverity(error: TrackedError): ErrorSeverity {
    const name = error.error.name.toLowerCase();
    const message = error.error.message.toLowerCase();

    // 关键错误
    if (name.includes('fatal') || name.includes('critical')) {
      return 'critical';
    }

    // 高严重性
    if (
      name.includes('typeerror') ||
      name.includes('referenceerror') ||
      name.includes('syntaxerror') ||
      message.includes('cannot') ||
      message.includes('undefined')
    ) {
      return 'high';
    }

    // 中等严重性
    if (name.includes('error')) {
      return 'medium';
    }

    return 'low';
  }
}

// 单例
export const ErrorTracker = new ErrorTrackerClass();

/**
 * 全局错误处理设置
 */
export function setupGlobalErrorHandlers() {
  if (typeof window === 'undefined') return;

  // 未捕获的错误
  window.addEventListener('error', (event) => {
    ErrorTracker.capture(event.error || event.message, {
      action: 'window_error',
      metadata: {
        filename: event.filename,
        lineno: event.lineno,
        colno: event.colno,
      },
    });
  });

  // 未处理的 Promise rejection
  window.addEventListener('unhandledrejection', (event) => {
    ErrorTracker.captureUnhandledRejection(event.reason, {
      action: 'unhandled_rejection',
    });
  });

  console.log('[ErrorTracker] Global error handlers installed');
}

export default ErrorTracker;