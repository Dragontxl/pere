import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';
import { authApi } from '../api/client';
import type { LoginResponse } from '../types';

interface AuthContextType {
  user: LoginResponse | null;
  token: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<LoginResponse | null>(null);
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    const savedToken = localStorage.getItem('token');
    if (savedToken) {
      setToken(savedToken);
      // Restore user info from localStorage
      const savedUser = localStorage.getItem('user');
      if (savedUser) {
        try {
          setUser(JSON.parse(savedUser));
        } catch {
          // invalid JSON, clear
          authApi.logout();
        }
      }
    }
  }, []);

  const login = async (username: string, password: string) => {
    const data = await authApi.login(username, password);
    setUser(data);
    setToken(data.token);
    localStorage.setItem('user', JSON.stringify(data));
  };

  const logout = () => {
    authApi.logout();
    setUser(null);
    setToken(null);
    localStorage.removeItem('user');
  };

  return (
    <AuthContext.Provider value={{ user, token, login, logout, isAuthenticated: !!token }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}
