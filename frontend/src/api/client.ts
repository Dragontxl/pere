import type { ApiResponse, Task, TaskLog, LoginResponse, BgmOption, PhaseMaterialCheck, FileListResult, FileStats, BilibiliCredentialStatus } from '../types';

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
    enable_outro?: boolean;
    tts_voice?: string;
    tts_speed?: number;
    bgm_key?: string;
    bilibili_upload?: boolean;
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

  // 分阶段执行
  async startPhase(
    id: string,
    phase: string,
    startPhase?: string,
    endPhase?: string,
  ): Promise<Task> {
    const body: Record<string, string> = {};
    if (startPhase) body.start_phase = startPhase;
    if (endPhase) body.end_phase = endPhase;
    return request<Task>(`/tasks/${id}/start-phase/${phase}`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  // 素材检查
  async checkPhase(id: string, phase: string): Promise<PhaseMaterialCheck> {
    return request<PhaseMaterialCheck>(`/tasks/${id}/check-phase/${phase}`);
  },

  // 重渲染指定场景
  async rerenderClips(
    id: string,
    sceneIds: number[],
    images?: Record<number, string>,
    types?: Record<number, string>,
  ): Promise<Task> {
    return request<Task>(`/tasks/${id}/rerender-clips`, {
      method: 'POST',
      body: JSON.stringify({
        scene_ids: sceneIds,
        images,
        types,
      }),
    });
  },

  // 手动上传到 B站
  async uploadBilibili(id: string): Promise<void> {
    await request<null>(`/tasks/${id}/bilibili-upload`, {
      method: 'POST',
    });
  },
};

// ── Admin File Management ──────────────────────────────────────────────

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

  // ── 文件管理（管理员）─────────────────────────────────────────────

  /**
   * 列出 R2 文件（支持文件夹结构）
   */
  async list(prefix = '', cursor?: string): Promise<FileListResult> {
    const query = new URLSearchParams({ prefix });
    if (cursor) query.set('cursor', cursor);
    return request<FileListResult>(`/admin/files/list?${query.toString()}`);
  },

  /**
   * 删除文件或文件夹
   */
  async delete(key: string, isDirectory = false): Promise<void> {
    await request<null>('/admin/files/delete', {
      method: 'POST',
      body: JSON.stringify({ key, is_directory: isDirectory }),
    });
  },

  /**
   * 批量删除
   */
  async batchDelete(keys: string[]): Promise<{ deleted: number; errors: string[] }> {
    return request<{ deleted: number; errors: string[] }>('/admin/files/batch-delete', {
      method: 'POST',
      body: JSON.stringify({ keys }),
    });
  },

  /**
   * 创建文件夹
   */
  async createFolder(key: string): Promise<{ key: string }> {
    return request<{ key: string }>('/admin/files/create-folder', {
      method: 'POST',
      body: JSON.stringify({ key }),
    });
  },

  /**
   * 批量上传文件（JSON + base64）
   */
  async batchUpload(
    files: Array<{ filename: string; content: string; contentType?: string }>,
    prefix = '',
  ): Promise<{ uploaded: Array<{ key: string; size: number; filename: string }>; errors: string[] }> {
    return request<{ uploaded: Array<{ key: string; size: number; filename: string }>; errors: string[] }>(
      '/admin/files/batch-upload',
      {
        method: 'POST',
        body: JSON.stringify({ files, prefix }),
      },
    );
  },

  /**
   * 获取存储统计
   */
  async stats(prefix = ''): Promise<FileStats> {
    const query = new URLSearchParams({ prefix });
    return request<FileStats>(`/admin/files/stats?${query.toString()}`);
  },

  /**
   * 获取管理端文件预览 URL（带 Range 支持）
   */
  getAdminPreviewUrl(key: string): string {
    return `${API_BASE}/admin/files/preview/${encodeURIComponent(key.split('/').pop() || key)}?prefix=${encodeURIComponent(key.includes('/') ? key.substring(0, key.lastIndexOf('/') + 1) : '')}`;
  },

  /**
   * 获取管理端下载 URL
   */
  getAdminDownloadUrl(key: string): string {
    return `${API_BASE}/admin/files/download/${encodeURIComponent(key.split('/').pop() || key)}?prefix=${encodeURIComponent(key.includes('/') ? key.substring(0, key.lastIndexOf('/') + 1) : '')}`;
  },

  /**
   * 下载管理端文件（带鉴权，转 blob 触发浏览器下载）。
   *
   * 不能直接用 <a href> 下载：浏览器下载请求不携带 Authorization 头，
   * 而 /admin/files/download 需要鉴权，会返回 401 JSON，Chrome 报
   * 「无法从网站上提取文件」。改为 fetch 带鉴权头，转 blob 后触发下载。
   */
  async downloadAdminFile(key: string, fallbackName?: string): Promise<void> {
    const url = this.getAdminDownloadUrl(key);
    const token = getAuthToken();
    const headers: Record<string, string> = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(url, { headers });
    if (!response.ok) {
      let msg = `下载失败 (${response.status})`;
      try {
        const data = await response.json() as ApiResponse<unknown>;
        if (data.msg) msg = data.msg;
      } catch {
        // 非 JSON 响应，保留默认消息
      }
      throw new Error(msg);
    }

    const blob = await response.blob();
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = fallbackName || key.split('/').pop() || 'download';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(blobUrl);
  },
};

// ── BGM ────────────────────────────────────────────────────────────────

export const bgmApi = {
  async options(): Promise<BgmOption[]> {
    return request<BgmOption[]>('/bgm/options');
  },
};

// ── Bilibili ────────────────────────────────────────────────────────────

export const bilibiliApi = {
  /** 获取当前用户 B站凭据状态 */
  async getCredentialStatus(): Promise<BilibiliCredentialStatus> {
    return request<BilibiliCredentialStatus>('/bilibili/credentials');
  },

  /** 保存 B站 Cookie */
  async saveCredentials(cookies: string): Promise<BilibiliCredentialStatus> {
    return request<BilibiliCredentialStatus>('/bilibili/credentials', {
      method: 'POST',
      body: JSON.stringify({ cookies }),
    });
  },

  /** 删除 B站凭据 */
  async deleteCredentials(): Promise<{ deleted: boolean }> {
    return request<{ deleted: boolean }>('/bilibili/credentials', {
      method: 'DELETE',
    });
  },
};
