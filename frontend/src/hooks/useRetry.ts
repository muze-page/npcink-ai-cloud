'use client';

import { useCallback, useState } from 'react';

export interface RetryOptions {
  /** 最大重试次数 */
  maxRetries?: number;
  /** 初始延迟（毫秒） */
  initialDelay?: number;
  /** 最大延迟（毫秒） */
  maxDelay?: number;
  /** 延迟倍增系数 */
  backoffMultiplier?: number;
  /** 重试回调 */
  onRetry?: (attempt: number, error: Error) => void;
  /** 失败回调 */
  onFailure?: (error: Error, attempts: number) => void;
}

export interface RetryResult<T> {
  /** 执行函数 */
  execute: () => Promise<T>;
  /** 是否正在加载 */
  isLoading: boolean;
  /** 错误信息 */
  error: Error | null;
  /** 当前重试次数 */
  attempts: number;
  /** 是否已耗尽重试次数 */
  isExhausted: boolean;
  /** 手动重试 */
  retry: () => Promise<T>;
  /** 重置状态 */
  reset: () => void;
}

/**
 * 指数退避重试 Hook
 * 
 * 使用示例：
 * ```ts
 * const { execute, isLoading, error, retry } = useRetry(
 *   () => fetch('/api/data').then(r => r.json()),
 *   { maxRetries: 3, initialDelay: 1000 }
 * );
 * 
 * // 执行
 * const data = await execute();
 * 
 * // 或手动重试
 * retry();
 * ```
 */
export function useRetry<T>(
  fn: () => Promise<T>,
  options: RetryOptions = {}
): RetryResult<T> {
  const {
    maxRetries = 3,
    initialDelay = 1000,
    maxDelay = 30000,
    backoffMultiplier = 2,
    onRetry,
    onFailure,
  } = options;

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [attempts, setAttempts] = useState(0);

  const calculateDelay = useCallback(
    (attempt: number): number => {
      const delay = initialDelay * Math.pow(backoffMultiplier, attempt - 1);
      // 添加随机抖动（±10%）避免并发请求同时重试
      const jitter = delay * 0.1 * (Math.random() * 2 - 1);
      return Math.min(delay + jitter, maxDelay);
    },
    [initialDelay, backoffMultiplier, maxDelay]
  );

  const execute = useCallback(async (): Promise<T> => {
    setIsLoading(true);
    setError(null);

    let lastError: Error | null = null;
    let currentAttempts = 0;

    while (currentAttempts <= maxRetries) {
      try {
        const result = await fn();
        setIsLoading(false);
        setAttempts(currentAttempts);
        return result;
      } catch (err) {
        lastError = err instanceof Error ? err : new Error(String(err));
        currentAttempts++;
        setAttempts(currentAttempts);

        if (currentAttempts <= maxRetries) {
          const delay = calculateDelay(currentAttempts);
          onRetry?.(currentAttempts, lastError);

          // 等待后重试
          await new Promise((resolve) => setTimeout(resolve, delay));
        }
      }
    }

    // 所有重试失败
    setIsLoading(false);
    setError(lastError);
    onFailure?.(lastError!, currentAttempts);
    throw lastError;
  }, [fn, maxRetries, calculateDelay, onRetry, onFailure]);

  const retry = useCallback(async (): Promise<T> => {
    setAttempts(0);
    return execute();
  }, [execute]);

  const reset = useCallback(() => {
    setIsLoading(false);
    setError(null);
    setAttempts(0);
  }, []);

  return {
    execute,
    isLoading,
    error,
    attempts,
    isExhausted: attempts >= maxRetries && error !== null,
    retry,
    reset,
  };
}

/**
 * 简化的重试 Hook - 用于简单场景
 */
export function useSimpleRetry<T>(
  fn: () => Promise<T>,
  maxRetries = 3
): RetryResult<T> {
  return useRetry(fn, { maxRetries, initialDelay: 1000, backoffMultiplier: 2 });
}

/**
 * 网络请求重试 Hook - 专门用于 fetch 请求
 */
export interface FetchRetryOptions extends RetryOptions {
  fetchOptions?: RequestInit;
}

export function useFetchRetry<T>(
  url: string,
  options: FetchRetryOptions = {}
): RetryResult<T> & { data: T | null } {
  const { fetchOptions = {}, ...retryOptions } = options;
  const [data, setData] = useState<T | null>(null);

  const fetchFn = useCallback(async (): Promise<T> => {
    const response = await fetch(url, fetchOptions);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    const result = await response.json();
    setData(result);
    return result;
  }, [url, fetchOptions]);

  const retryResult = useRetry(fetchFn, retryOptions);

  return {
    ...retryResult,
    data,
  };
}

export default useRetry;