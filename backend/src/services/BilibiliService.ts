import { Bindings } from '../types/env';
import { CryptoService } from './CryptoService';

export interface BilibiliCredentialStatus {
  configured: boolean;
  hasSessdata: boolean;
  hasBiliJct: boolean;
}

interface BilibiliCookie {
  name: string;
  value: string;
  domain: string;
  path: string;
  secure: boolean;
  httpOnly: boolean;
  sameSite: string;
  expirationDate?: number;
}

/**
 * B站（哔哩哔哩）上传服务
 *
 * - 凭据管理：用户级 Cookie 加密存储（AES-GCM），支持字符串和 JSON 两种输入格式
 * - 上传触发：通过 GitHub Actions workflow 执行浏览器自动化上传
 * - 结果处理：接收上传回调，更新任务的 B站状态
 */
export class BilibiliService {
  private crypto: CryptoService;

  constructor(private env: Bindings) {
    this.crypto = new CryptoService(env);
  }

  /**
   * 保存用户 B站凭据
   *
   * 接受 Cookie 字符串（"name1=value1; name2=value2"，浏览器 DevTools 复制格式）
   * 或 JSON 数组格式，统一转为 JSON 数组后加密存储。
   *
   * @param userId 用户 ID
   * @param cookiesInput Cookie 字符串或 JSON 数组
   * @returns 凭据状态
   * @throws 缺少 SESSDATA 时抛出错误
   */
  async saveCredentials(userId: string, cookiesInput: string): Promise<BilibiliCredentialStatus> {
    const cookies = this.parseCookies(cookiesInput);
    return this.saveCredentialsFromCookies(userId, cookies);
  }

  /**
   * 直接以 Cookie 数组保存（供本地扫码助手 / 后端内部调用）
   */
  async saveCredentialsFromCookies(
    userId: string,
    cookies: BilibiliCookie[],
  ): Promise<BilibiliCredentialStatus> {
    if (cookies.length === 0) {
      throw new Error('未解析到任何 Cookie，请检查输入格式');
    }

    const hasSessdata = cookies.some(c => c.name === 'SESSDATA');
    const hasBiliJct = cookies.some(c => c.name === 'bili_jct');

    if (!hasSessdata) {
      throw new Error('Cookie 中缺少 SESSDATA，无法登录 B站。请重新从浏览器复制完整 Cookie。');
    }

    const cookiesJson = JSON.stringify(cookies);
    const encrypted = await this.crypto.encrypt(cookiesJson);

    await this.env.DB.prepare(`
      INSERT INTO bilibili_credentials (user_id, cookies_encrypted, has_sessdata, has_bili_jct, updated_at)
      VALUES (?, ?, ?, ?, STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
      ON CONFLICT(user_id) DO UPDATE SET
        cookies_encrypted = excluded.cookies_encrypted,
        has_sessdata = excluded.has_sessdata,
        has_bili_jct = excluded.has_bili_jct,
        updated_at = excluded.updated_at
    `).bind(userId, encrypted, hasSessdata, hasBiliJct).run();

    return { configured: true, hasSessdata, hasBiliJct };
  }

  /**
   * 获取用户 B站凭据（解密后返回 JSON 字符串）
   */
  async getCredentials(userId: string): Promise<string | null> {
    const row = await this.env.DB.prepare(
      'SELECT cookies_encrypted FROM bilibili_credentials WHERE user_id = ?'
    ).bind(userId).first();

    if (!row) return null;

    const decrypted = await this.crypto.decrypt((row as any).cookies_encrypted);
    return decrypted;
  }

  /**
   * 获取用户凭据状态（不返回完整 Cookie，用于前端展示）
   */
  async getCredentialStatus(userId: string): Promise<BilibiliCredentialStatus> {
    const row = await this.env.DB.prepare(
      'SELECT has_sessdata, has_bili_jct FROM bilibili_credentials WHERE user_id = ?'
    ).bind(userId).first();

    if (!row) {
      return { configured: false, hasSessdata: false, hasBiliJct: false };
    }

    return {
      configured: true,
      hasSessdata: !!(row as any).has_sessdata,
      hasBiliJct: !!(row as any).has_bili_jct,
    };
  }

  /**
   * 删除用户凭据
   */
  async deleteCredentials(userId: string): Promise<boolean> {
    const result = await this.env.DB.prepare(
      'DELETE FROM bilibili_credentials WHERE user_id = ?'
    ).bind(userId).run();
    // D1 的变更行数在 result.meta.changes（旧版本为 result.changes）
    const changes = (result as any)?.meta?.changes ?? (result as any)?.changes ?? 0;
    return changes > 0;
  }

  /**
   * 触发 B站上传
   *
   * 校验任务视频已生成、凭据已配置后，dispatch GitHub Actions workflow
   * 执行浏览器自动化上传。
   *
   * @param taskId 任务 ID
   * @param userId 用户 ID
   * @throws 任务无视频、凭据未配置、上传进行中、GitHub 未配置时抛出错误
   */
  async triggerUpload(taskId: string, userId: string): Promise<void> {
    const task = await this.env.DB.prepare(
      'SELECT * FROM tasks WHERE id = ?'
    ).bind(taskId).first() as any;

    if (!task) {
      throw new Error('任务不存在');
    }

    if (!task.final_video_key) {
      throw new Error('任务尚未生成视频，无法上传 B站');
    }

    // 状态卡在 pending/uploading 但实际 workflow 可能未执行或回调未到达，
    // 会导致按钮永久不可用。用户已在前端确认重传，这里重置状态并重新触发，
    // 避免任务被永久卡死（下面的 UPDATE 会把状态重新置为 pending）。
    if (task.bilibili_status === 'pending' || task.bilibili_status === 'uploading') {
      await this.logTask(taskId, 'BILIBILI', 'WARN', '检测到上次上传状态未正常完成，重置状态后重新触发');
    }

    // 获取用户凭据
    const credentials = await this.getCredentials(userId);
    if (!credentials) {
      throw new Error('未配置 B站凭据，请先在设置页面配置 Cookie');
    }

    // 将解密后的 Cookie 写入 R2 临时存储，CI 脚本从中下载（避免 Cookie 出现在 workflow payload 中）
    const cookiesR2Key = `bilibili_upload/${taskId}/cookies.json`;
    await this.env.R2.put(cookiesR2Key, credentials, {
      httpMetadata: { contentType: 'application/json' },
    });

    // 更新上传状态
    await this.env.DB.prepare(`
      UPDATE tasks SET bilibili_status = 'pending', updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?
    `).bind(taskId).run();

    // Dispatch GitHub Actions workflow
    const owner = this.env.GITHUB_REPO_OWNER;
    const repo = this.env.GITHUB_REPO_NAME;
    const apiKey = this.env.GITHUB_PAT;

    if (!owner || !repo || !apiKey) {
      throw new Error('GitHub 仓库未配置');
    }

    const payload = {
      event_type: 'bilibili-upload',
      client_payload: {
        task_id: taskId,
        video_key: task.final_video_key,
        cover_key: task.cover_image_key || '',
        title: task.title || '',
        article_content: task.article_content || '',
        orientation: task.orientation || 'landscape',
        cookies_key: cookiesR2Key,
      },
    };

    // 与 upload-bilibili.yml 的 `repository_dispatch: types: [bilibili-upload]` 保持一致，
    // 与 TaskService 使用同一个 repository_dispatch 端点（fine-grained 权限：Contents: write）
    const resp = await fetch(
      `https://api.github.com/repos/${owner}/${repo}/dispatches`,
      {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${apiKey}`,
          Accept: 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
          'Content-Type': 'application/json',
          'User-Agent': 'pexel-remotion-platform',
        },
        body: JSON.stringify(payload),
      }
    );

    if (!resp.ok) {
      const errText = await resp.text();
      // 回滚上传状态
      await this.env.DB.prepare(`
        UPDATE tasks SET bilibili_status = NULL, updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?
      `).bind(taskId).run();
      throw new Error(`GitHub Actions 触发失败: ${resp.status} ${errText}`);
    }

    await this.logTask(taskId, 'BILIBILI', 'INFO', 'B站上传任务已触发，等待 CI 执行');
  }

  /**
   * 处理 B站上传结果回调
   *
   * @param body 回调体，含 task_id, status, bvid, url, error
   */
  async handleUploadResult(body: any): Promise<{ success: boolean; taskId: string }> {
    const { task_id: taskId, status, bvid, url, error } = body;

    const newStatus = status === 'success' ? 'success' : 'failed';

    await this.env.DB.prepare(`
      UPDATE tasks SET bilibili_status = ?, bilibili_bvid = ?, bilibili_url = ?,
        updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
      WHERE id = ?
    `).bind(newStatus, bvid || null, url || null, taskId).run();

    if (error) {
      await this.logTask(taskId, 'BILIBILI', 'ERROR', `B站上传失败: ${error}`);
    } else if (bvid || url) {
      await this.logTask(taskId, 'BILIBILI', 'INFO', `B站上传成功: ${url || `https://www.bilibili.com/video/${bvid}`}`);
    } else {
      await this.logTask(taskId, 'BILIBILI', 'INFO', 'B站上传已提交（审核中，链接待生成）');
    }

    return { success: true, taskId };
  }

  /**
   * 解析 Cookie 输入，统一为 JSON 数组格式
   *
   * 支持两种输入：
   * 1. 字符串格式："name1=value1; name2=value2"（浏览器 DevTools 复制格式）
   * 2. JSON 数组格式：[{name, value, domain, path, ...}]
   */
  private parseCookies(input: string): BilibiliCookie[] {
    const trimmed = input.trim();

    // 尝试 JSON 数组格式
    if (trimmed.startsWith('[')) {
      try {
        const parsed = JSON.parse(trimmed);
        if (Array.isArray(parsed)) {
          return parsed.map((c: any) => ({
            name: c.name,
            value: c.value,
            domain: c.domain || '.bilibili.com',
            path: c.path || '/',
            secure: c.secure !== false,
            httpOnly: c.httpOnly || false,
            sameSite: c.sameSite || 'Lax',
            expirationDate: c.expirationDate,
          }));
        }
      } catch {
        // 不是有效 JSON，回退到字符串格式
      }
    }

    // 字符串格式："name1=value1; name2=value2"
    const cookies: BilibiliCookie[] = [];
    const pairs = trimmed.split(';').map(p => p.trim()).filter(p => p);
    for (const pair of pairs) {
      const eqIndex = pair.indexOf('=');
      if (eqIndex <= 0) continue;
      const name = pair.substring(0, eqIndex).trim();
      const value = pair.substring(eqIndex + 1).trim();
      if (name && value) {
        cookies.push({
          name,
          value,
          domain: '.bilibili.com',
          path: '/',
          secure: true,
          httpOnly: false,
          sameSite: 'Lax',
        });
      }
    }

    return cookies;
  }

  private async logTask(taskId: string, phase: string, level: string, message: string): Promise<void> {
    await this.env.DB.prepare(`
      INSERT INTO operation_logs (task_id, phase, level, message, created_at)
      VALUES (?, ?, ?, ?, STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
    `).bind(taskId, phase, level, message).run();
  }
}
