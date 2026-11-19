import { Hono } from 'hono';
import { TaskService } from '../../services/TaskService';
import { BilibiliService } from '../../services/BilibiliService';
import { CryptoService } from '../../services/CryptoService';
import { Bindings } from '../../types/env';

const callbackRoutes = new Hono();

/**
 * Verify HMAC signature for callback requests
 */
async function verifyCallbackSignature(c: any): Promise<boolean> {
  const cryptoService = new CryptoService(c.env as Bindings);
  const signature = c.req.header('X-Callback-Signature');
  const secret = (c.env as Bindings).CALLBACK_SECRET;

  if (!signature || !secret) {
    return false;
  }

  const bodyText = await c.req.text();
  return cryptoService.verifyHMAC(bodyText, signature, secret);
}

callbackRoutes.post('/github', async (c) => {
  if (!await verifyCallbackSignature(c)) {
    return c.json({ code: 401, data: null, msg: 'Invalid signature' }, 401);
  }

  const service = new TaskService(c.env as Bindings);
  const body = await c.req.json();

  const result = await service.handleGitHubCallback(body);

  return c.json({ code: 200, data: result, msg: 'Callback processed' });
});

callbackRoutes.post('/progress', async (c) => {
  if (!await verifyCallbackSignature(c)) {
    return c.json({ code: 401, data: null, msg: 'Invalid signature' }, 401);
  }

  const service = new TaskService(c.env as Bindings);
  const body = await c.req.json();

  const result = await service.updateTaskProgress(body);

  return c.json({ code: 200, data: result, msg: 'Progress updated' });
});

callbackRoutes.post('/complete', async (c) => {
  if (!await verifyCallbackSignature(c)) {
    return c.json({ code: 401, data: null, msg: 'Invalid signature' }, 401);
  }

  const service = new TaskService(c.env as Bindings);
  const body = await c.req.json();

  const result = await service.handleTaskComplete(body);

  return c.json({ code: 200, data: result, msg: 'Task completed' });
});

callbackRoutes.post('/error', async (c) => {
  if (!await verifyCallbackSignature(c)) {
    return c.json({ code: 401, data: null, msg: 'Invalid signature' }, 401);
  }

  const service = new TaskService(c.env as Bindings);
  const body = await c.req.json();

  const result = await service.handleTaskError(body);

  return c.json({ code: 200, data: result, msg: 'Error handled' });
});

/**
 * POST /api/v1/callback/bilibili
 * B站上传结果回调。CI 执行完上传脚本后发送，更新任务的 B站上传状态。
 * Body: { task_id, status, bvid?, url?, error? }
 */
callbackRoutes.post('/bilibili', async (c) => {
  if (!await verifyCallbackSignature(c)) {
    return c.json({ code: 401, data: null, msg: 'Invalid signature' }, 401);
  }

  const biliService = new BilibiliService(c.env as Bindings);
  const body = await c.req.json();

  const result = await biliService.handleUploadResult(body);

  return c.json({ code: 200, data: result, msg: 'Bilibili upload result processed' });
});

export { callbackRoutes };
