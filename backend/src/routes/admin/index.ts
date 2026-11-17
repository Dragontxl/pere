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
  if (apiKey !== (c.env as Bindings).ADMIN_API_KEY) {
    return c.json({ code: 403, data: null, msg: 'Forbidden' }, 403);
  }

  await next();
});

/**
 * Upload a file to R2 (article file upload)
 */
adminRoutes.post('/files/upload', async (c) => {
  const { R2 } = c.env as Bindings;

  try {
    const formData = await c.req.formData();
    const file = formData.get('file') as File | null;
    const prefix = (formData.get('prefix') as string) || '';

    if (!file) {
      return c.json({ code: 400, data: null, msg: 'Missing file' }, 400);
    }

    const key = prefix ? `${prefix.replace(/\/$/, '')}/${file.name}` : file.name;
    const arrayBuffer = await file.arrayBuffer();

    await R2.put(key, arrayBuffer, {
      httpMetadata: {
        contentType: file.type || 'application/octet-stream',
      },
    });

    return c.json({
      code: 200,
      data: { key, size: file.size, filename: file.name },
      msg: 'Upload successful',
    });
  } catch (error) {
    console.error('File upload error:', error);
    return c.json({ code: 500, data: null, msg: 'Upload failed' }, 500);
  }
});

/**
 * Delete a file from R2
 */
adminRoutes.post('/files/delete', async (c) => {
  const { R2 } = c.env as Bindings;

  try {
    const body = await c.req.json();
    const { key } = body;

    if (!key) {
      return c.json({ code: 400, data: null, msg: 'Missing key' }, 400);
    }

    await R2.delete(key);

    return c.json({ code: 200, data: null, msg: 'File deleted' });
  } catch (error) {
    console.error('File delete error:', error);
    return c.json({ code: 500, data: null, msg: 'Delete failed' }, 500);
  }
});

/**
 * List files in R2 with a prefix
 */
adminRoutes.get('/files/list', async (c) => {
  const { R2 } = c.env as Bindings;

  try {
    const prefix = c.req.query('prefix') || '';
    const objects = await R2.list({ prefix, limit: 1000 });

    return c.json({
      code: 200,
      data: {
        objects: objects.objects.map(obj => ({
          key: obj.key,
          size: obj.size,
          lastModified: obj.uploaded,
        })),
        truncated: objects.truncated,
      },
      msg: 'success',
    });
  } catch (error) {
    console.error('File list error:', error);
    return c.json({ code: 500, data: null, msg: 'List failed' }, 500);
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
