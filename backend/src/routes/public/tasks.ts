import { Hono } from 'hono';
import { TaskService } from '../../services/TaskService';
import { Bindings } from '../../types/env';
import { authMiddleware } from '../../middleware/auth';

const taskRoutes = new Hono();

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

export { taskRoutes };
