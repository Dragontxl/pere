import type { ApiResponse, Task, TaskLog, LoginResponse, BgmOption } from '../types';

const API_BASE = '/api/v1';

function getAuthToken(): string {
  return localStorage.getItem('token') || '';
}

function setAuthToken(token: string): void {
  localStorage.setItem('token', token);
}

function clearAuthToken(): void {
  localStorage.removeItem('token');
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getAuthToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  const data = await response.json() as ApiResponse<T>;

  if (!response.ok) {
    throw new Error(data.msg || `请求失败 (${response.status})`);
  }

  return data.data;
}

// ── Auth ──────────────────────────────────────────────────────────────

export const authApi = {
  async login(username: string, password: string): Promise<LoginResponse> {
    const data = await request<LoginResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
    setAuthToken(data.token);
    return data;
  },

  async refresh(): Promise<{ token: string }> {
    const data = await request<{ token: string }>('/auth/refresh', {
      method: 'POST',
    });
    setAuthToken(data.token);
    return data;
  },

  logout(): void {
    clearAuthToken();
  },

  getToken(): string {
    return getAuthToken();
  },
};

// ── Tasks ──────────────────────────────────────────────────────────────

export const taskApi = {
  async list(params: { status?: string; page?: number; limit?: number } = {}): Promise<Task[]> {
    const query = new URLSearchParams();
    if (params.status) query.set('status', params.status);
    if (params.page) query.set('page', String(params.page));
    if (params.limit) query.set('limit', String(params.limit));
    return request<Task[]>(`/tasks?${query.toString()}`);
  },

  async get(id: string): Promise<Task> {
    return request<Task>(`/tasks/${id}`);
  },

  async create(data: {
    title: string;
    article_source: string;
    article_content?: string;
    article_file_key?: string;
    orientation: string;
    language: string;
    enable_subtitle: boolean;
    bgm_key?: string;
  }): Promise<Task> {
    return request<Task>('/tasks', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async cancel(id: string): Promise<Task> {
    return request<Task>(`/tasks/${id}/cancel`, {
      method: 'POST',
    });
  },

  async retry(id: string): Promise<Task> {
    return request<Task>(`/tasks/${id}/retry`, {
      method: 'POST',
    });
  },

  async delete(id: string): Promise<void> {
    await request<null>(`/tasks/${id}`, {
      method: 'DELETE',
    });
  },

  async getLogs(id: string): Promise<TaskLog[]> {
    return request<TaskLog[]>(`/tasks/${id}/logs`);
  },
};

// ── Files ──────────────────────────────────────────────────────────────

export const fileApi = {
  getPreviewUrl(key: string): string {
    return `${API_BASE}/files/preview/${encodeURIComponent(key)}?prefix=${encodeURIComponent(key.includes('/') ? key.substring(0, key.lastIndexOf('/') + 1) : '')}`;
  },

  getNoCacheUrl(key: string): string {
    return `${API_BASE}/files/nocache?key=${encodeURIComponent(key)}`;
  },

  /**
   * 上传文件到 R2（用户级，JWT 认证）。
   * 返回 R2 key，前端将其作为 bgm_key 等传入创建任务。
   */
  async upload(file: File): Promise<{ key: string; size: number; filename: string }> {
    const formData = new FormData();
    formData.append('file', file);

    const token = getAuthToken();
    const headers: Record<string, string> = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    // 注意：不要设置 Content-Type，浏览器会自动设置 multipart/form-data + boundary

    const response = await fetch(`${API_BASE}/files/upload`, {
      method: 'POST',
      headers,
      body: formData,
    });

    const data = await response.json() as ApiResponse<{ key: string; size: number; filename: string }>;

    if (!response.ok) {
      throw new Error(data.msg || `上传失败 (${response.status})`);
    }

    return data.data;
  },
};

// ── BGM ────────────────────────────────────────────────────────────────

export const bgmApi = {
  async options(): Promise<BgmOption[]> {
    return request<BgmOption[]>('/bgm/options');
  },
};
