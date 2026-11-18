import { Hono } from 'hono';
import { TaskService } from '../../services/TaskService';
import { Bindings } from '../../types/env';
import { authMiddleware } from '../../middleware/auth';

type Variables = {
  userId: string;
  role: string;
};

const taskRoutes = new Hono<{ Variables: Variables }>();

// All task routes require authentication
taskRoutes.use('*', authMiddleware);

taskRoutes.get('/', async (c) => {
  const service = new TaskService(c.env as Bindings);
  const query = c.req.query();
  const status = query.status as string | undefined;
  const page = parseInt(query.page as string || '1');
  const limit = parseInt(query.limit as string || '20');
  const userId = c.get('userId');

  const tasks = await service.listTasks({ userId, status, page, limit });

  return c.json({ code: 200, data: tasks, msg: 'success' });
});

taskRoutes.get('/:id', async (c) => {
  const service = new TaskService(c.env as Bindings);
  const task = await service.getTask(c.req.param('id'));

  if (!task) {
    return c.json({ code: 404, data: null, msg: 'Task not found' }, 404);
  }

  return c.json({ code: 200, data: task, msg: 'success' });
});

taskRoutes.get('/:id/logs', async (c) => {
  const service = new TaskService(c.env as Bindings);
  const logs = await service.getTaskLogs(c.req.param('id'));

  return c.json({ code: 200, data: logs, msg: 'success' });
});

taskRoutes.post('/', async (c) => {
  const service = new TaskService(c.env as Bindings);

  try {
    const body = await c.req.json();
    const userId = c.get('userId');

    const task = await service.createTask({
      userId,
      title: body.title || '',
      articleSource: body.article_source || 'pasted',
      articleContent: body.article_content || null,
      articleFileKey: body.article_file_key || null,
      orientation: body.orientation || 'landscape',
      language: body.language || 'zh',
      enableSubtitle: body.enable_subtitle !== false,
      bgmKey: body.bgm_key || null,
    });

    try {
      await service.startTask(task.id);
      return c.json({ code: 201, data: task, msg: 'Task created and started' }, 201);
    } catch (error) {
      console.error('Failed to start task:', error);
      return c.json({
        code: 201,
        data: task,
        msg: 'Task created but failed to start: ' + (error as Error).message,
      }, 201);
    }
  } catch (error) {
    console.error('Failed to create task:', error);
    return c.json({ code: 500, data: null, msg: 'Failed to create task: ' + (error as Error).message }, 500);
  }
});

taskRoutes.put('/:id', async (c) => {
  const service = new TaskService(c.env as Bindings);
  const body = await c.req.json();

  const updated = await service.updateTask(c.req.param('id'), body);

  if (!updated) {
    return c.json({ code: 404, data: null, msg: 'Task not found' }, 404);
  }

  return c.json({ code: 200, data: updated, msg: 'Task updated successfully' });
});

taskRoutes.delete('/:id', async (c) => {
  const service = new TaskService(c.env as Bindings);
  const deleted = await service.deleteTask(c.req.param('id'));

  if (!deleted) {
    return c.json({ code: 404, data: null, msg: 'Task not found' }, 404);
  }

  return c.json({ code: 200, data: null, msg: 'Task deleted successfully' });
});

taskRoutes.post('/:id/cancel', async (c) => {
  const service = new TaskService(c.env as Bindings);
  const cancelled = await service.cancelTask(c.req.param('id'));

  if (!cancelled) {
    return c.json({ code: 404, data: null, msg: 'Task not found' }, 404);
  }

  return c.json({ code: 200, data: cancelled, msg: 'Task cancelled successfully' });
});

taskRoutes.post('/:id/retry', async (c) => {
  const service = new TaskService(c.env as Bindings);
  const result = await service.retryTask(c.req.param('id'));

  if (!result) {
    return c.json({ code: 400, data: null, msg: 'Failed to retry task' }, 400);
  }

  return c.json({ code: 200, data: result, msg: 'Task retry scheduled' });
});

taskRoutes.post('/:id/start', async (c) => {
  const service = new TaskService(c.env as Bindings);
  try {
    const result = await service.startTask(c.req.param('id'));

    if (!result) {
      return c.json({ code: 400, data: null, msg: 'Failed to start task' }, 400);
    }

    return c.json({ code: 200, data: result, msg: 'Task started successfully' });
  } catch (error) {
    console.error('Failed to start task:', error);
    return c.json({ code: 500, data: null, msg: 'Failed to start task: ' + (error as Error).message }, 500);
  }
});

/**
 * Start a specific phase (or range) for a task.
 * Body: { start_phase?, end_phase? } — if not provided, runs the single phase.
 */
taskRoutes.post('/:id/start-phase/:phase', async (c) => {
  const service = new TaskService(c.env as Bindings);
  const phase = c.req.param('phase') as any;

  try {
    const validPhases = ['SCENE_GEN', 'ASSET_MATCH', 'REMOTION_RENDER', 'TTS_COMPOSE'];
    if (!validPhases.includes(phase)) {
      return c.json({ code: 400, data: null, msg: 'Invalid phase' }, 400);
    }

    let startPhase: string | undefined;
    let endPhase: string | undefined;

    const body = await c.req.json().catch(() => ({}));
    if (body.start_phase && validPhases.includes(body.start_phase)) {
      startPhase = body.start_phase;
    }
    if (body.end_phase && validPhases.includes(body.end_phase)) {
      endPhase = body.end_phase;
    }

    const result = await service.startPhase(c.req.param('id'), phase, startPhase as any, endPhase as any);

    if (!result) {
      return c.json({ code: 400, data: null, msg: 'Failed to start phase' }, 400);
    }

    return c.json({ code: 200, data: result, msg: 'Phase started successfully' });
  } catch (error) {
    console.error('Failed to start phase:', error);
    return c.json({ code: 500, data: null, msg: 'Failed to start phase: ' + (error as Error).message }, 500);
  }
});

/**
 * Check if required materials exist for a phase before starting.
 */
taskRoutes.get('/:id/check-phase/:phase', async (c) => {
  const service = new TaskService(c.env as Bindings);
  const phase = c.req.param('phase') as any;

  const validPhases = ['SCENE_GEN', 'ASSET_MATCH', 'REMOTION_RENDER', 'TTS_COMPOSE'];
  if (!validPhases.includes(phase)) {
    return c.json({ code: 400, data: null, msg: 'Invalid phase' }, 400);
  }

  try {
    const result = await service.checkPhaseMaterials(c.req.param('id'), phase);
    return c.json({ code: 200, data: result, msg: 'success' });
  } catch (error) {
    console.error('Material check error:', error);
    return c.json({ code: 500, data: null, msg: 'Check failed: ' + (error as Error).message }, 500);
  }
});

/**
 * Re-render specific scene clips for a task.
 * Body: { scene_ids: number[], images?: { [sceneId]: path }, types?: { [sceneId]: type } }
 */
taskRoutes.post('/:id/rerender-clips', async (c) => {
  const service = new TaskService(c.env as Bindings);

  try {
    const body = await c.req.json();
    const { scene_ids, images, types } = body;

    if (!scene_ids || !Array.isArray(scene_ids) || scene_ids.length === 0) {
      return c.json({ code: 400, data: null, msg: 'Missing or invalid scene_ids' }, 400);
    }

    const result = await service.rerenderClips(
      c.req.param('id'),
      scene_ids.map(Number),
      images,
      types,
    );

    if (!result) {
      return c.json({ code: 400, data: null, msg: 'Failed to re-render clips' }, 400);
    }

    return c.json({ code: 200, data: result, msg: 'Re-render triggered successfully' });
  } catch (error) {
    console.error('Failed to re-render clips:', error);
    return c.json({ code: 500, data: null, msg: 'Failed to re-render clips: ' + (error as Error).message }, 500);
  }
});

export { taskRoutes };
