'use client';

import { createContext, createElement, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { portalClient, type PortalSession, type Site } from '@/lib/portal-client';

export interface SessionState {
  session: PortalSession | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  error: Error | null;
}

export interface UseSessionReturn extends SessionState {
  requestLoginCode: (email: string) => Promise<{ code?: string }>;
  verifyLoginCode: (email: string, code: string, options?: { rememberMe?: boolean }) => Promise<void>;
  logout: () => Promise<void>;
  selectSite: (siteId: string) => Promise<void>;
  refresh: () => Promise<void>;
}

const SessionContext = createContext<UseSessionReturn | undefined>(undefined);

/**
 * Session 管理 Hook
 * 处理 Portal 认证、Session 刷新、站点选择等
 */
function useSessionController(): UseSessionReturn {
  const [state, setState] = useState<SessionState>({
    session: null,
    isLoading: true,
    isAuthenticated: false,
    error: null,
  });

  /**
   * 加载 Session
   */
  const loadSession = useCallback(async () => {
    try {
      const response = await portalClient.getSession();
      setState({
        session: response.data,
        isLoading: false,
        isAuthenticated: true,
        error: null,
      });
    } catch (error) {
      setState({
        session: null,
        isLoading: false,
        isAuthenticated: false,
        error: error instanceof Error ? error : new Error('Failed to load session'),
      });
    }
  }, []);

  /**
   * 请求邮箱验证码
   */
  const requestLoginCode = useCallback(async (email: string): Promise<{ code?: string }> => {
    try {
      const response = await portalClient.requestLoginCode({ email });
      return {
        code: response.data?.code,
      };
    } catch (error) {
      throw error instanceof Error ? error : new Error('Failed to request login code');
    }
  }, []);

  /**
   * 验证邮箱验证码
   */
  const verifyLoginCode = useCallback(async (
    email: string,
    code: string,
    options: { rememberMe?: boolean } = {}
  ): Promise<void> => {
    try {
      await portalClient.verifyLoginCode({ email, code, remember_me: Boolean(options.rememberMe) });
      await loadSession();
    } catch (error) {
      throw error instanceof Error ? error : new Error('Failed to verify login code');
    }
  }, [loadSession]);

  /**
   * 登出
   */
  const logout = useCallback(async (): Promise<void> => {
    try {
      await portalClient.logout();
    } catch (error) {
      // 忽略登出错误
    }
    setState({
      session: null,
      isLoading: false,
      isAuthenticated: false,
      error: null,
    });
  }, []);

  /**
   * 选择站点
   */
  const selectSite = useCallback(async (siteId: string): Promise<void> => {
    try {
      const response = await portalClient.selectSite(siteId);
      setState((prev) => ({
        ...prev,
        session: response.data,
      }));
    } catch (error) {
      throw error instanceof Error ? error : new Error('Failed to select site');
    }
  }, []);

  /**
   * 刷新 Session
   */
  const refresh = useCallback(async (): Promise<void> => {
    await loadSession();
  }, [loadSession]);

  // 初始加载
  useEffect(() => {
    loadSession();
  }, [loadSession]);

  return {
    ...state,
    requestLoginCode,
    verifyLoginCode,
    logout,
    selectSite,
    refresh,
  };
}

export function PortalSessionProvider({ children }: { children: ReactNode }) {
  const session = useSessionController();

  return createElement(SessionContext.Provider, { value: session }, children);
}

export function useSession(): UseSessionReturn {
  const context = useContext(SessionContext);
  if (context === undefined) {
    throw new Error('useSession must be used within a PortalSessionProvider');
  }
  return context;
}

/**
 * 获取当前选中的站点
 */
export function useSelectedSite(): Site | null {
  const { session } = useSession();
  return session?.selected_context?.site || null;
}

/**
 * 获取可用的站点列表
 */
export function useSites(): Site[] {
  const { session } = useSession();
  if (!session) return [];
  return session.sites;
}

export default useSession;
