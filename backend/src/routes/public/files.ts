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
 * 用户上传自定义 BGM 文件到 R2。
 * 文件存储在 `bgm/` 前缀下，key 形如 `bgm/<uuid>-<filename>`。
 * 前端创建任务时将此 key 作为 `bgm_key` 传给后端，workflow 检测到 `bgm/`
 * 前缀后会从 R2 下载到本地再传给 main.py。
 */
publicFileRoutes.post('/upload', authMiddleware, async (c) => {
  const { R2 } = c.env as Bindings;

  try {
    const formData = await c.req.formData();
    const file = formData.get('file') as File | null;

    if (!file) {
      return c.json({ code: 400, data: null, msg: '缺少文件' }, 400);
    }

    // 校验文件类型：只接受音频
    const allowedTypes = ['audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/ogg', 'audio/flac', 'audio/m4a', 'audio/aac', 'audio/x-m4a'];
    const fileExt = file.name.toLowerCase().split('.').pop();
    const allowedExts = ['mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac'];
    const extOk = allowedExts.includes(fileExt || '');
    const typeOk = !file.type || allowedTypes.includes(file.type) || file.type.startsWith('audio/');

    if (!extOk && !typeOk) {
      return c.json({ code: 400, data: null, msg: '只支持音频文件（mp3, wav, ogg, flac, m4a, aac）' }, 400);
    }

    // 文件大小限制：50 MB
    const MAX_SIZE = 50 * 1024 * 1024;
    if (file.size > MAX_SIZE) {
      return c.json({ code: 400, data: null, msg: '文件大小不能超过 50MB' }, 400);
    }

    // 生成唯一 key：bgm/<uuid>-<filename>
    const uuid = crypto.randomUUID();
    const safeName = file.name.replace(/[^\w.\-]/g, '_');
    const key = `bgm/${uuid}-${safeName}`;

    const arrayBuffer = await file.arrayBuffer();

    await R2.put(key, arrayBuffer, {
      httpMetadata: {
        contentType: file.type || 'audio/mpeg',
      },
    });

    return c.json({
      code: 200,
      data: { key, size: file.size, filename: file.name },
      msg: '上传成功',
    });
  } catch (error) {
    console.error('BGM upload error:', error);
    return c.json({ code: 500, data: null, msg: '上传失败' }, 500);
  }
});

export { publicFileRoutes };
