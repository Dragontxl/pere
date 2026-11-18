import { Hono } from 'hono';
import { Bindings } from '../../types/env';
import { authMiddleware } from '../../middleware/auth';

const publicFileRoutes = new Hono();

publicFileRoutes.get('/version/:filename', async (c) => {
  const { R2 } = c.env as Bindings;
  const filename = decodeURIComponent(c.req.param('filename'));
  const prefix = c.req.query('prefix') || '';

  const key = prefix ? `${prefix.replace(/\/$/, '')}/${filename}` : filename;

  try {
    const object = await R2.get(key);

    if (!object) {
      return c.json({ code: 404, data: null, msg: '文件不存在' }, 404);
    }

    const md = object.httpMetadata as any;
    const lastModified = md?.lastModified
      ? new Date(md.lastModified).toISOString()
      : new Date().toISOString();

    const etag = md?.etag || `"${lastModified}-${object.size}"`;

    return c.json({
      code: 200,
      data: { key, etag, lastModified, size: object.size },
      msg: 'success',
    });
  } catch (error) {
    console.error('R2 version check error:', error);
    return c.json({ code: 500, data: null, msg: '获取文件版本失败' }, 500);
  }
});

publicFileRoutes.get('/preview/:filename', async (c) => {
  const { R2, R2_PUBLIC_URL } = c.env as Bindings;
  const filename = decodeURIComponent(c.req.param('filename'));
  const prefix = c.req.query('prefix') || '';

  const key = prefix ? `${prefix}${filename}` : filename;
  const noCache = c.req.query('no_cache');

  // If R2 public URL is configured and no cache bypass, redirect to direct R2 URL
  if (R2_PUBLIC_URL && !noCache) {
    const publicUrl = `${R2_PUBLIC_URL}/${key}`;
    return c.redirect(publicUrl, 302);
  }

  try {
    const object = await R2.get(key);

    if (!object) {
      return c.json({ code: 404, data: null, msg: `文件不存在: ${key}` }, 404);
    }

    const headers = new Headers();

    const ext = filename.toLowerCase().split('.').pop();
    const contentTypes: Record<string, string> = {
      'mp4': 'video/mp4',
      'avi': 'video/x-msvideo',
      'mov': 'video/quicktime',
      'mkv': 'video/x-matroska',
      'webm': 'video/webm',
      'jpg': 'image/jpeg',
      'jpeg': 'image/jpeg',
      'png': 'image/png',
      'gif': 'image/gif',
      'json': 'application/json',
      'txt': 'text/plain; charset=utf-8',
      'log': 'text/plain; charset=utf-8',
    };

    const contentType = contentTypes[ext || ''] || object.httpMetadata?.contentType || 'application/octet-stream';
    headers.set('Content-Type', contentType);

    const contentLength = object.size;
    const range = c.req.header('Range');

    headers.set('Accept-Ranges', 'bytes');

    if (noCache) {
      headers.set('Cache-Control', 'no-cache, no-store, must-revalidate');
      headers.set('Pragma', 'no-cache');
      headers.set('Expires', '0');
    } else {
      headers.set('Cache-Control', 'public, max-age=3600');
    }

    if ((object.httpMetadata as any)?.etag) {
      headers.set('ETag', (object.httpMetadata as any).etag);
    }
    if ((object.httpMetadata as any)?.lastModified) {
      headers.set('Last-Modified', new Date((object.httpMetadata as any).lastModified).toUTCString());
    }

    if (range) {
      const match = range.match(/bytes=(\d+)-(\d*)/);
      if (match) {
        const start = parseInt(match[1], 10);
        const end = match[2] ? parseInt(match[2], 10) : contentLength - 1;

        if (start >= contentLength) {
          return new Response(null, {
            status: 416,
            headers: { 'Content-Range': `bytes */${contentLength}` },
          });
        }

        const chunkSize = end - start + 1;
        const arrayBuffer = await object.arrayBuffer();
        const chunk = arrayBuffer.slice(start, end + 1);

        headers.set('Content-Range', `bytes ${start}-${end}/${contentLength}`);
        headers.set('Content-Length', chunkSize.toString());

        return new Response(chunk, { status: 206, headers });
      }
    }

    headers.set('Content-Length', contentLength.toString());

    return new Response(object.body, { headers });
  } catch (error) {
    console.error('R2 preview error:', error);
    return c.json({ code: 500, data: null, msg: '预览文件失败' }, 500);
  }
});

publicFileRoutes.get('/nocache', async (c) => {
  const { R2 } = c.env as Bindings;
  // Read the key from the query param to avoid path-encoding issues with
  // slashes inside keys (e.g. "tasks/<id>/final_output.mp4"). A path wildcard
  // like "/nocache/*" loses multi-segment keys on some edge runtimes.
  const rawKey = c.req.query('key') ?? c.req.param('*') ?? '';
  const key = decodeURIComponent(rawKey);

  try {
    const object = await R2.get(key);

    if (!object) {
      return c.json({ code: 404, data: null, msg: `文件不存在: ${key}` }, 404);
    }

    const headers = new Headers();

    const filename = key.split('/').pop() || '';
    const ext = filename.toLowerCase().split('.').pop();
    const contentTypes: Record<string, string> = {
      'mp4': 'video/mp4',
      'avi': 'video/x-msvideo',
      'mov': 'video/quicktime',
      'mkv': 'video/x-matroska',
      'webm': 'video/webm',
      'jpg': 'image/jpeg',
      'jpeg': 'image/jpeg',
      'png': 'image/png',
      'gif': 'image/gif',
      'json': 'application/json',
    };

    const contentType = contentTypes[ext || ''] || object.httpMetadata?.contentType || 'application/octet-stream';
    headers.set('Content-Type', contentType);
    headers.set('Accept-Ranges', 'bytes');
    headers.set('Cache-Control', 'no-cache, no-store, must-revalidate');
    headers.set('Pragma', 'no-cache');
    headers.set('Expires', '0');

    if ((object.httpMetadata as any)?.etag) {
      headers.set('ETag', (object.httpMetadata as any).etag);
    }
    if ((object.httpMetadata as any)?.lastModified) {
      headers.set('Last-Modified', new Date((object.httpMetadata as any).lastModified).toUTCString());
    }

    const contentLength = object.size;
    const range = c.req.header('Range');

    if (range) {
      const match = range.match(/bytes=(\d+)-(\d*)/);
      if (match) {
        const start = parseInt(match[1], 10);
        const end = match[2] ? parseInt(match[2], 10) : contentLength - 1;

        if (start >= contentLength) {
          return new Response(null, {
            status: 416,
            headers: { 'Content-Range': `bytes */${contentLength}` },
          });
        }

        const chunkSize = end - start + 1;
        const arrayBuffer = await object.arrayBuffer();
        const chunk = arrayBuffer.slice(start, end + 1);

        headers.set('Content-Range', `bytes ${start}-${end}/${contentLength}`);
        headers.set('Content-Length', chunkSize.toString());

        return new Response(chunk, { status: 206, headers });
      }
    }

    headers.set('Content-Length', contentLength.toString());

    return new Response(object.body, { headers });
  } catch (error) {
    console.error('R2 no-cache error:', error);
    return c.json({ code: 500, data: null, msg: '获取文件失败' }, 500);
  }
});

publicFileRoutes.post('/purge', async (c) => {
  const { R2_PUBLIC_URL, CLOUDFLARE_API_TOKEN, CLOUDFLARE_ZONE_ID, ADMIN_API_KEY } = c.env as Bindings;

  const authHeader = c.req.header('Authorization');
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return c.json({ code: 401, data: null, msg: 'Unauthorized' }, 401);
  }

  const apiKey = authHeader.slice(7);
  if (apiKey !== ADMIN_API_KEY) {
    return c.json({ code: 403, data: null, msg: 'Forbidden' }, 403);
  }

  try {
    const body = await c.req.json();
    const { keys } = body;

    if (!keys || !Array.isArray(keys) || keys.length === 0) {
      return c.json({ code: 400, data: null, msg: 'Missing or invalid keys parameter' }, 400);
    }

    if (!CLOUDFLARE_API_TOKEN || !CLOUDFLARE_ZONE_ID || !R2_PUBLIC_URL) {
      return c.json({ code: 500, data: null, msg: 'Cloudflare purge configuration not set' }, 500);
    }

    const purgeUrls = keys.map(key => {
      if (key.startsWith('http')) return key;
      return `${R2_PUBLIC_URL}/${key}`;
    });

    const response = await fetch(`https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/purge_cache`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${CLOUDFLARE_API_TOKEN}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ files: purgeUrls }),
    });

    const result = await response.json() as any;

    if (result.success) {
      return c.json({ code: 200, data: { purgedUrls: purgeUrls, result }, msg: 'Cache purge successful' });
    } else {
      return c.json({
        code: 500,
        data: null,
        msg: `Cache purge failed: ${result.errors?.map((e: any) => e.message).join(', ')}`,
      }, 500);
    }
  } catch (error) {
    console.error('Cloudflare cache purge error:', error);
    return c.json({ code: 500, data: null, msg: 'Cache purge error' }, 500);
  }
});

// ── 用户级文件上传（JWT 认证）──────────────────────────────────────────

/**
 * 用户上传文件到 R2（JWT 认证）。
 * 通过可选的 `prefix` 参数决定存储路径：
 *   - `bgm/`（默认）：存储自定义背景音乐，key 形如 `bgm/<uuid>-<filename>`。
 *   - `articles/`：存储文章文件（txt/md），key 形如 `articles/<uuid>-<filename>`。
 * 前端创建任务时将此 key 作为 `bgm_key` / `article_file_key` 传给后端，
 * workflow 会从 R2 下载到本地再使用。
 *
 * 支持文件类型：音频（mp3/wav/ogg/flac/m4a/aac）与文本（txt/md/text）。
 *
 * 注意：Cloudflare Workers 环境下 multipart/form-data 的 Content-Type 会在
 * 边缘被剥离，导致 `c.req.formData()` 不可用。因此使用 JSON + base64 传输。
 */
publicFileRoutes.post('/upload', authMiddleware, async (c) => {
  const { R2 } = c.env as Bindings;

  try {
    const body = await c.req.json();
    const { filename, content, contentType, prefix } = body as {
      filename: string;
      content: string; // base64 编码的文件内容
      contentType?: string;
      prefix?: string;
    };

    if (!filename || !content) {
      return c.json({ code: 400, data: null, msg: '缺少 filename 或 content' }, 400);
    }

    // 校验 prefix：只允许字母数字、下划线、连字符和斜杠，防止路径穿越
    const safePrefix = prefix && /^[\w-]+(\/[\w-]+)*\/?$/.test(prefix) ? prefix.replace(/\/+$/, '') : 'bgm';

    // 校验文件类型：音频 + 文本
    const audioTypes = ['audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/ogg', 'audio/flac', 'audio/m4a', 'audio/aac', 'audio/x-m4a'];
    const textTypes = ['text/plain', 'text/markdown', 'text/x-markdown'];
    const fileExt = filename.toLowerCase().split('.').pop();
    const audioExts = ['mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac'];
    const textExts = ['txt', 'md', 'text'];
    const extOk = audioExts.includes(fileExt || '') || textExts.includes(fileExt || '');
    const typeOk =
      !contentType ||
      audioTypes.includes(contentType) ||
      textTypes.includes(contentType) ||
      contentType.startsWith('audio/') ||
      contentType.startsWith('text/');

    if (!extOk && !typeOk) {
      return c.json({ code: 400, data: null, msg: '不支持的文件类型（支持音频与 txt/md 文本）' }, 400);
    }

    // 文件大小限制：50 MB（base64 解码后）
    const MAX_SIZE = 50 * 1024 * 1024;
    const decoded = Uint8Array.from(atob(content), (b) => b.charCodeAt(0));
    if (decoded.byteLength > MAX_SIZE) {
      return c.json({ code: 400, data: null, msg: '文件大小不能超过 50MB' }, 400);
    }

    // 生成唯一 key：<prefix>/<uuid>-<filename>
    const uuid = crypto.randomUUID();
    const safeName = filename.replace(/[^\w.\-]/g, '_');
    const key = `${safePrefix}/${uuid}-${safeName}`;

    const defaultContentType = safePrefix === 'articles' ? 'text/plain; charset=utf-8' : 'audio/mpeg';

    await R2.put(key, decoded, {
      httpMetadata: {
        contentType: contentType || defaultContentType,
      },
    });

    return c.json({
      code: 200,
      data: { key, size: decoded.byteLength, filename },
      msg: '上传成功',
    });
  } catch (error) {
    console.error('File upload error:', error);
    const msg = error instanceof Error ? error.message : String(error);
    return c.json({ code: 500, data: null, msg: `上传失败: ${msg}` }, 500);
  }
});

export { publicFileRoutes };
