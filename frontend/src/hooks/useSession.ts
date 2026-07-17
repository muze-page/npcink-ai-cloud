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

type RawSessionSite = {
  site?: {
    site_id?: string;
    account_id?: string;
    name?: string;
    site_name?: string;
    status?: string;
    created_at?: string;
    provisioned_at?: string;
    plan_name?: string;
    site_url?: string;
    platform_kind?: 'wordpress';
    metadata?: Record<string, unknown>;
  };
};

type RawPortalSession = Omit<PortalSession, 'sites'> & {
  site?: RawSessionSite['site'];
  sites?: Array<RawSessionSite | Site>;
};

function normalizeSite(raw?: RawSessionSite['site'] | Site | null): Site {
  if (!raw) {
    return {
      site_id: '',
      site_name: '',
      account_id: '',
      status: 'inactive',
      created_at: '',
      site_url: '',
      platform_kind: 'wordpress',
    };
  }

  const site = raw as Record<string, unknown>;
  const metadata =
    site.metadata && typeof site.metadata === 'object'
      ? (site.metadata as Record<string, unknown>)
      : undefined;
  return {
    site_id: String(site.site_id || ''),
    site_name: String(site.site_name || site.name || site.site_id || ''),
    account_id: String(site.account_id || ''),
    status: (site.status as Site['status']) || 'inactive',
    created_at: String(site.created_at || site.provisioned_at || ''),
    plan_name: String(site.plan_name || ''),
    site_url: String(site.site_url || ''),
    platform_kind: 'wordpress',
    metadata,
  };
}

function normalizePortalSession(raw: RawPortalSession): PortalSession {
  const nestedSites = Array.isArray(raw.sites)
    ? raw.sites
        .map((entry) => {
          const candidate = entry as RawSessionSite & Site;
          return normalizeSite(candidate.site || candidate);
        })
        .filter((site) => Boolean(site.site_id))
    : [];
  const currentSite = raw.site ? normalizeSite(raw.site) : null;
  const sites = currentSite && !nestedSites.some((site) => site.site_id === currentSite.site_id)
    ? [currentSite, ...nestedSites]
    : nestedSites;

  return {
    ...raw,
    sites,
  };
}

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
        session: normalizePortalSession(response.data as RawPortalSession),
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
        session: normalizePortalSession(response.data as RawPortalSession),
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
  if (!session) return null;
  
  const selectedSiteId = session.site_id;
  if (!selectedSiteId) return session.sites[0] || null;
  
  return session.sites.find((s) => s.site_id === selectedSiteId) || null;
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
