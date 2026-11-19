import { Hono } from 'hono';
import { BilibiliService } from '../../services/BilibiliService';
import { Bindings } from '../../types/env';
import { authMiddleware } from '../../middleware/auth';

type Variables = {
  userId: string;
  role: string;
};

const bilibiliRoutes = new Hono<{ Variables: Variables }>();

// All bilibili routes require authentication
bilibiliRoutes.use('*', authMiddleware);

/**
 * GET /api/v1/bilibili/credentials
 * 获取当前用户 B站凭据状态（不返回完整 Cookie）
 */
bilibiliRoutes.get('/credentials', async (c) => {
  const userId = c.get('userId');
  const biliService = new BilibiliService(c.env as Bindings);

  try {
    const status = await biliService.getCredentialStatus(userId);
    return c.json({ code: 200, data: status, msg: 'success' });
  } catch (error) {
    console.error('Get bilibili credentials error:', error);
    return c.json({ code: 500, data: null, msg: '获取 B站凭据状态失败' }, 500);
  }
});

/**
 * POST /api/v1/bilibili/credentials
 * 保存当前用户 B站 Cookie（加密存储）
 * Body: { cookies: string } — Cookie 字符串或 JSON 数组
 */
bilibiliRoutes.post('/credentials', async (c) => {
  const userId = c.get('userId');
  const biliService = new BilibiliService(c.env as Bindings);

  try {
    const body = await c.req.json();
    const cookies = body.cookies;

    if (!cookies || typeof cookies !== 'string') {
      return c.json({ code: 400, data: null, msg: '缺少 cookies 参数' }, 400);
    }

    const status = await biliService.saveCredentials(userId, cookies);
    return c.json({ code: 200, data: status, msg: 'B站凭据已保存' });
  } catch (error) {
    console.error('Save bilibili credentials error:', error);
    return c.json({ code: 400, data: null, msg: (error as Error).message }, 400);
  }
});

/**
 * DELETE /api/v1/bilibili/credentials
 * 删除当前用户 B站凭据
 */
bilibiliRoutes.delete('/credentials', async (c) => {
  const userId = c.get('userId');
  const biliService = new BilibiliService(c.env as Bindings);

  try {
    const deleted = await biliService.deleteCredentials(userId);
    return c.json({ code: 200, data: { deleted }, msg: 'B站凭据已删除' });
  } catch (error) {
    console.error('Delete bilibili credentials error:', error);
    return c.json({ code: 500, data: null, msg: '删除 B站凭据失败' }, 500);
  }
});

export { bilibiliRoutes };
