import { Hono } from 'hono';
import { BGM_OPTIONS } from '../../constants/bgm';

// 公开的 BGM 选项接口（无需登录，创建任务表单拉取用）
const bgmRoutes = new Hono();

bgmRoutes.get('/options', (c) => {
  return c.json({ code: 200, data: BGM_OPTIONS, msg: 'success' });
});

export { bgmRoutes };
