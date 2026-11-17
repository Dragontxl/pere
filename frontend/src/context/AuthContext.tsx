import { createContext, useContext, useState, type ReactNode } from 'react';
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

function readStoredUser(): LoginResponse | null {
  try {
    const raw = localStorage.getItem('user');
    return raw ? (JSON.parse(raw) as LoginResponse) : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // Initialize synchronously from localStorage so that the first render
  // already knows whether the user is authenticated. Restoring the token
  // in a useEffect instead would make ProtectedRoute redirect to /login
  // before the effect runs (e.g. after a full page reload).
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('token'));
  const [user, setUser] = useState<LoginResponse | null>(() => readStoredUser());

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
