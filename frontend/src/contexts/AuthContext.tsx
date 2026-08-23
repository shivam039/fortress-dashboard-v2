// src/contexts/AuthContext.tsx — React context for authentication state
'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import { authApi, type UserProfile } from '@/lib/api';

interface AuthState {
  user: UserProfile | null;
  isLoading: boolean;
  isAuthenticated: boolean;
}

interface AuthContextValue extends AuthState {
  login: (username: string, password: string) => Promise<void>;
  signup: (data: { username: string; password: string; full_name?: string; email?: string }) => Promise<void>;
  guestLogin: () => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    isLoading: true,
    isAuthenticated: false,
  });

  const refreshUser = useCallback(async () => {
    try {
      const profile = await authApi.me();
      setState({ user: profile, isLoading: false, isAuthenticated: true });
    } catch {
      setState({ user: null, isLoading: false, isAuthenticated: false });
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refreshUser();
  }, [refreshUser]);

  const login = async (username: string, password: string) => {
    await authApi.login(username, password);
    // Cookie is set by the backend — just fetch the profile
    const profile = await authApi.me();
    setState({ user: profile, isLoading: false, isAuthenticated: true });
  };

  const signup = async (data: { username: string; password: string; full_name?: string; email?: string }) => {
    await authApi.signup(data);
    const profile = await authApi.me();
    setState({ user: profile, isLoading: false, isAuthenticated: true });
  };

  const guestLogin = async () => {
    await authApi.guest();
    const profile = await authApi.me();
    setState({ user: profile, isLoading: false, isAuthenticated: true });
  };

  const logout = async () => {
    try {
      await authApi.logout();
    } catch {}
    setState({ user: null, isLoading: false, isAuthenticated: false });
  };

  return (
    <AuthContext.Provider
      value={{
        ...state,
        login,
        signup,
        guestLogin,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
