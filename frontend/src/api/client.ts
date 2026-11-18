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
   * 使用 JSON + base64 传输，避免 Cloudflare Workers 环境下
   * multipart/form-data 的 Content-Type 在边缘被剥离的问题。
   * 返回 R2 key，前端将其作为 bgm_key / article_file_key 传入创建任务。
   *
   * @param file 要上传的文件
   * @param prefix 存储前缀，默认 `bgm`（背景音乐），文章文件传 `articles`
   */
  async upload(file: File, prefix = 'bgm'): Promise<{ key: string; size: number; filename: string }> {
    // 将文件读取为 base64
    const arrayBuffer = await file.arrayBuffer();
    const base64 = btoa(String.fromCharCode(...new Uint8Array(arrayBuffer)));

    const token = getAuthToken();
    const response = await fetch(`${API_BASE}/files/upload`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        filename: file.name,
        content: base64,
        contentType: file.type || undefined,
        prefix,
      }),
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
