'use client';

import React, { Component, ErrorInfo, ReactNode } from 'react';
import { LocaleContext } from '@/contexts/LocaleContext';
import { Alert } from './ui/Alert';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error?: Error;
}

/**
 * 错误边界组件
 * 捕获子组件树中的 JavaScript 错误
 */
export class ErrorBoundary extends Component<Props, State> {
  static contextType = LocaleContext;
  declare context: React.ContextType<typeof LocaleContext>;

  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
    
    if (this.props.onError) {
      this.props.onError(error, errorInfo);
    }
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: undefined });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const t = this.context?.t ?? ((key: string, _params?: Record<string, string>, fallback?: string) => fallback || key);

      return (
        <Alert
          variant="error"
          title={t('empty.error_title', undefined, 'Something went wrong')}
          onDismiss={() => this.setState({ hasError: false })}
        >
          <div className="space-y-2">
            <p>
              {this.state.error?.message || t('error.unexpected', undefined, 'An unexpected error occurred.')}
            </p>
            <button
              onClick={this.handleRetry}
              className="px-4 py-2 bg-red-600 text-white text-sm font-medium rounded hover:bg-red-700 transition-colors"
            >
              {t('common.retry', undefined, 'Retry')}
            </button>
          </div>
        </Alert>
      );
    }

    return this.props.children;
  }
}

/**
 * 错误边界钩子版本（用于函数组件）
 * 注意：这是一个简化的实现，完整的错误边界需要使用类组件
 */
interface UseErrorBoundaryReturn {
  hasError: boolean;
  error?: Error;
  clearError: () => void;
  showError: (error: Error) => void;
}

/**
 * 创建一个错误边界钩子
 * 返回错误状态和控制函数
 */
export function useErrorBoundary(): UseErrorBoundaryReturn {
  const [errorState, setErrorState] = React.useState<{ hasError: boolean; error?: Error }>({
    hasError: false,
  });

  const clearError = React.useCallback(() => {
    setErrorState({ hasError: false, error: undefined });
  }, []);

  const showError = React.useCallback((error: Error) => {
    setErrorState({ hasError: true, error });
  }, []);

  return {
    hasError: errorState.hasError,
    error: errorState.error,
    clearError,
    showError,
  };
}

export default ErrorBoundary;
