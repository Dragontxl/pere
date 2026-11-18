import { Hono } from 'hono';
import { CryptoService } from '../../services/CryptoService';
import { Bindings } from '../../types/env';

const adminRoutes = new Hono();

// Admin auth middleware
adminRoutes.use('*', async (c, next) => {
  const authHeader = c.req.header('Authorization');
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return c.json({ code: 401, data: null, msg: 'Unauthorized' }, 401);
  }

  const apiKey = authHeader.slice(7);
  const role = c.get('role');

  // Allow access if the token matches ADMIN_API_KEY (programmatic access)
  // or if the authenticated user has the ADMIN role (JWT-based access).
  // authMiddleware has already verified the JWT before this runs.
  if (apiKey !== (c.env as Bindings).ADMIN_API_KEY && role !== 'ADMIN') {
    return c.json({ code: 403, data: null, msg: 'Forbidden' }, 403);
  }

  await next();
});

/**
 * Upload a file to R2 (admin, JSON + base64 transport)
 * Avoids Cloudflare Workers stripping Content-Type for multipart/form-data.
 */
adminRoutes.post('/files/upload', async (c) => {
  const { R2 } = c.env as Bindings;

  try {
    const body = await c.req.json();
    const { filename, content, contentType, prefix } = body as {
      filename: string;
      content: string;
      contentType?: string;
      prefix?: string;
    };

    if (!filename || !content) {
      return c.json({ code: 400, data: null, msg: 'Missing filename or content' }, 400);
    }

    const safePrefix = prefix && /^[\w-]+(\/[\w-]+)*\/?$/.test(prefix) ? prefix.replace(/\/+$/, '') : '';
    const decoded = Uint8Array.from(atob(content), (b) => b.charCodeAt(0));
    const safeName = filename.replace(/[^\w.\-]/g, '_');
    const key = safePrefix ? `${safePrefix}/${safeName}` : safeName;

    await R2.put(key, decoded, {
      httpMetadata: {
        contentType: contentType || 'application/octet-stream',
      },
    });

    return c.json({
      code: 200,
      data: { key, size: decoded.byteLength, filename },
      msg: 'Upload successful',
    });
  } catch (error) {
    console.error('File upload error:', error);
    return c.json({ code: 500, data: null, msg: 'Upload failed' }, 500);
  }
});

/**
 * Delete a file or folder from R2
 * If is_directory is true, recursively deletes all objects under the folder prefix.
 */
adminRoutes.post('/files/delete', async (c) => {
  const { R2 } = c.env as Bindings;

  try {
    const body = await c.req.json();
    const { key, is_directory } = body;

    if (!key) {
      return c.json({ code: 400, data: null, msg: 'Missing key' }, 400);
    }

    if (is_directory) {
      // Recursively delete all objects under this folder prefix
      let totalDeleted = 0;
      let cursor: string | undefined = undefined;

      do {
        const options: any = { prefix: key, limit: 1000 };
        if (cursor) options.cursor = cursor;

        const objects = await R2.list(options);
        const keys = objects.objects.map((obj: any) => obj.key);

        if (keys.length > 0) {
          await R2.delete(keys);
          totalDeleted += keys.length;
        }

        cursor = objects.truncated ? objects.cursor : undefined;
      } while (cursor);

      // Also delete the folder marker object itself (if any)
      try {
        await R2.delete(key.replace(/\/$/, ''));
      } catch {
        // Folder marker may not exist; that's fine
      }

      console.log(`Deleted folder ${key} with ${totalDeleted} objects`);
      return c.json({ code: 200, data: { deleted: totalDeleted }, msg: 'Folder deleted' });
    }

    await R2.delete(key);
    return c.json({ code: 200, data: null, msg: 'File deleted' });
  } catch (error) {
    console.error('File delete error:', error);
    return c.json({ code: 500, data: null, msg: 'Delete failed' }, 500);
  }
});

/**
 * List files in R2 with folder structure support.
 * Uses delimiter to aggregate objects into folders and cursor for pagination.
 */
adminRoutes.get('/files/list', async (c) => {
  const { R2 } = c.env as Bindings;

  try {
    const prefix = c.req.query('prefix') || '';
    const delimiter = c.req.query('delimiter') || '/';
    const cursor = c.req.query('cursor') || undefined;
    const limit = parseInt(c.req.query('limit') || '1000');

    const options: any = { prefix, limit };
    if (delimiter) options.delimiter = delimiter;
    if (cursor) options.cursor = cursor;

    const result = await R2.list(options) as any;

    // Build folder entries from delimited prefixes
    const folders = (result.delimitedPrefixes || []).map((fp: string) => {
      const name = fp.replace(/^\/|\/$/g, '');
      return {
        key: fp,
        name,
        type: 'directory',
        size: 0,
        lastModified: null,
      };
    });

    // Build file entries from objects
    const files = result.objects.map((obj: any) => {
      const name = obj.key.split('/').pop() || obj.key;
      return {
        key: obj.key,
        name,
        type: 'file',
        size: obj.size,
        lastModified: obj.uploaded,
        contentType: obj.httpMetadata?.contentType,
      };
    });

    return c.json({
      code: 200,
      data: {
        files,
        folders,
        truncated: result.truncated,
        cursor: result.cursor || null,
        prefix,
      },
      msg: 'success',
    });
  } catch (error) {
    console.error('File list error:', error);
    return c.json({ code: 500, data: null, msg: 'List failed' }, 500);
  }
});

/**
 * Create a folder in R2 (empty object with directory content type)
 */
adminRoutes.post('/files/create-folder', async (c) => {
  const { R2 } = c.env as Bindings;

  try {
    const body = await c.req.json();
    const { key } = body;

    if (!key) {
      return c.json({ code: 400, data: null, msg: 'Missing key' }, 400);
    }

    // Ensure the key ends with a slash for folder semantics
    const folderKey = key.endsWith('/') ? key : `${key}/`;

    await R2.put(folderKey, '', {
      httpMetadata: {
        contentType: 'application/x-directory',
      },
    });

    return c.json({ code: 200, data: { key: folderKey }, msg: 'Folder created' });
  } catch (error) {
    console.error('Create folder error:', error);
    return c.json({ code: 500, data: null, msg: 'Failed to create folder' }, 500);
  }
});

/**
 * Batch delete files and folders from R2
 */
adminRoutes.post('/files/batch-delete', async (c) => {
  const { R2 } = c.env as Bindings;

  try {
    const body = await c.req.json();
    const { keys } = body;

    if (!keys || !Array.isArray(keys) || keys.length === 0) {
      return c.json({ code: 400, data: null, msg: 'Missing or invalid keys' }, 400);
    }

    let totalDeleted = 0;
    const errors: string[] = [];

    for (const key of keys) {
      try {
        // Try deleting as a single object first
        await R2.delete(key);
        totalDeleted++;
      } catch {
        // If it's a folder, recursively delete
        try {
          let cursor: string | undefined = undefined;
          do {
            const options: any = { prefix: key, limit: 1000 };
            if (cursor) options.cursor = cursor;

            const objects = await R2.list(options);
            const objKeys = objects.objects.map((obj: any) => obj.key);

            if (objKeys.length > 0) {
              await R2.delete(objKeys);
              totalDeleted += objKeys.length;
            }

            cursor = objects.truncated ? objects.cursor : undefined;
          } while (cursor);

          try { await R2.delete(key.replace(/\/$/, '')); } catch { /* ignore */ }
        } catch (err) {
          errors.push(`${key}: ${(err as Error).message}`);
        }
      }
    }

    return c.json({
      code: 200,
      data: { deleted: totalDeleted, errors },
      msg: `Deleted ${totalDeleted} objects`,
    });
  } catch (error) {
    console.error('Batch delete error:', error);
    return c.json({ code: 500, data: null, msg: 'Batch delete failed' }, 500);
  }
});

/**
 * Download a file from R2 (with attachment header)
 */
adminRoutes.get('/files/download/:filename', async (c) => {
  const { R2 } = c.env as Bindings;
  const filename = decodeURIComponent(c.req.param('filename'));
  const prefix = c.req.query('prefix') || '';

  const key = prefix ? `${prefix}${filename}` : filename;

  try {
    const object = await R2.get(key);

    if (!object) {
      return c.json({ code: 404, data: null, msg: 'File not found' }, 404);
    }

    const filenameBase = filename.split('/').pop() || filename;
    const contentType = (object.httpMetadata as any)?.contentType || 'application/octet-stream';

    return new Response(object.body, {
      headers: {
        'Content-Type': contentType,
        'Content-Length': String(object.size),
        'Content-Disposition': `attachment; filename="${filenameBase}"`,
      },
    });
  } catch (error) {
    console.error('Download error:', error);
    return c.json({ code: 500, data: null, msg: 'Download failed' }, 500);
  }
});

/**
 * Preview a file from R2 with Range support (for video/image preview)
 */
adminRoutes.get('/files/preview/:filename', async (c) => {
  const { R2 } = c.env as Bindings;
  const filename = decodeURIComponent(c.req.param('filename'));
  const prefix = c.req.query('prefix') || '';

  const key = prefix ? `${prefix}${filename}` : filename;

  try {
    const object = await R2.get(key);

    if (!object) {
      return c.json({ code: 404, data: null, msg: 'File not found' }, 404);
    }

    const headers = new Headers();

    const ext = filename.toLowerCase().split('.').pop();
    const contentTypes: Record<string, string> = {
      'mp4': 'video/mp4',
      'webm': 'video/webm',
      'jpg': 'image/jpeg',
      'jpeg': 'image/jpeg',
      'png': 'image/png',
      'gif': 'image/gif',
      'json': 'application/json',
      'txt': 'text/plain; charset=utf-8',
      'mp3': 'audio/mpeg',
      'wav': 'audio/wav',
    };

    const contentType = contentTypes[ext || ''] || (object.httpMetadata as any)?.contentType || 'application/octet-stream';
    headers.set('Content-Type', contentType);
    headers.set('Accept-Ranges', 'bytes');

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
    console.error('Preview error:', error);
    return c.json({ code: 500, data: null, msg: 'Preview failed' }, 500);
  }
});

/**
 * Batch upload files to R2 (JSON + base64, avoids multipart Content-Type stripping)
 * Body: { files: [{ filename, content, contentType? }], prefix? }
 */
adminRoutes.post('/files/batch-upload', async (c) => {
  const { R2 } = c.env as Bindings;

  try {
    const body = await c.req.json();
    const { files, prefix } = body as {
      files: Array<{ filename: string; content: string; contentType?: string }>;
      prefix?: string;
    };

    if (!files || !Array.isArray(files) || files.length === 0) {
      return c.json({ code: 400, data: null, msg: 'Missing or invalid files' }, 400);
    }

    const safePrefix = prefix && /^[\w-]+(\/[\w-]+)*\/?$/.test(prefix) ? prefix.replace(/\/+$/, '') : '';
    const results: Array<{ key: string; size: number; filename: string }> = [];
    const errors: string[] = [];

    for (const file of files) {
      try {
        const { filename, content, contentType } = file;
        if (!filename || !content) {
          errors.push(`${filename || 'unknown'}: missing filename or content`);
          continue;
        }

        const decoded = Uint8Array.from(atob(content), (b) => b.charCodeAt(0));
        const safeName = filename.replace(/[^\w.\-]/g, '_');
        const key = safePrefix ? `${safePrefix}/${safeName}` : safeName;

        await R2.put(key, decoded, {
          httpMetadata: { contentType: contentType || 'application/octet-stream' },
        });

        results.push({ key, size: decoded.byteLength, filename });
      } catch (err) {
        errors.push(`${file.filename}: ${(err as Error).message}`);
      }
    }

    return c.json({ code: 200, data: { uploaded: results, errors }, msg: `Uploaded ${results.length} files` });
  } catch (error) {
    console.error('Batch upload error:', error);
    return c.json({ code: 500, data: null, msg: 'Batch upload failed' }, 500);
  }
});

/**
 * Get R2 storage usage statistics
 */
adminRoutes.get('/files/stats', async (c) => {
  const { R2 } = c.env as Bindings;

  try {
    const prefix = c.req.query('prefix') || '';
    let totalSize = 0;
    let totalFiles = 0;
    let cursor: string | undefined = undefined;

    do {
      const options: any = { prefix, limit: 1000 };
      if (cursor) options.cursor = cursor;

      const result = await R2.list(options);
      for (const obj of result.objects) {
        totalSize += obj.size;
        totalFiles++;
      }
      cursor = result.truncated ? result.cursor : undefined;
    } while (cursor);

    return c.json({
      code: 200,
      data: {
        totalSize,
        totalFiles,
        totalSizeMB: (totalSize / 1024 / 1024).toFixed(2),
        prefix,
      },
      msg: 'success',
    });
  } catch (error) {
    console.error('Stats error:', error);
    return c.json({ code: 500, data: null, msg: 'Stats failed' }, 500);
  }
});

/**
 * Get system config
 */
adminRoutes.get('/config', async (c) => {
  const { DB } = c.env as Bindings;

  try {
    const result = await DB.prepare('SELECT * FROM system_config').all();
    return c.json({ code: 200, data: result.results, msg: 'success' });
  } catch (error) {
    console.error('Config list error:', error);
    return c.json({ code: 500, data: null, msg: 'Failed to load config' }, 500);
  }
});

/**
 * Update system config
 */
adminRoutes.put('/config', async (c) => {
  const { DB } = c.env as Bindings;

  try {
    const body = await c.req.json();
    const { key, value, description } = body;

    if (!key || !value) {
      return c.json({ code: 400, data: null, msg: 'Missing key or value' }, 400);
    }

    await DB.prepare(`
      INSERT INTO system_config (key, value, description, updated_at, updated_by)
      VALUES (?, ?, ?, STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'), 'admin')
      ON CONFLICT(key) DO UPDATE SET value = excluded.value, description = excluded.description, updated_at = excluded.updated_at
    `).bind(key, value, description || null).run();

    return c.json({ code: 200, data: null, msg: 'Config updated' });
  } catch (error) {
    console.error('Config update error:', error);
    return c.json({ code: 500, data: null, msg: 'Failed to update config' }, 500);
  }
});

/**
 * Create a new user
 */
adminRoutes.post('/users', async (c) => {
  const { DB } = c.env as Bindings;
  const cryptoService = new CryptoService(c.env as Bindings);

  try {
    const body = await c.req.json();
    const { username, password, email, role } = body;

    if (!username || !password) {
      return c.json({ code: 400, data: null, msg: 'Missing username or password' }, 400);
    }

    const passwordHash = await cryptoService.hashPassword(password);

    try {
      const result = await DB.prepare(`
        INSERT INTO users (username, password_hash, email, role) VALUES (?, ?, ?, ?)
      `).bind(username, passwordHash, email || null, role || 'USER').run();

      return c.json({
        code: 201,
        data: { id: (result as any).lastRowID },
        msg: 'User created',
      }, 201);
    } catch (insertError: any) {
      if (insertError.message && insertError.message.includes('UNIQUE')) {
        return c.json({ code: 409, data: null, msg: 'Username already exists' }, 409);
      }
      throw insertError;
    }
  } catch (error) {
    console.error('User create error:', error);
    return c.json({ code: 500, data: null, msg: 'Failed to create user' }, 500);
  }
});

export { adminRoutes };
