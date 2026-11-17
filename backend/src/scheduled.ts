import { Bindings } from './types/env';
import { TaskService } from './services/TaskService';

/**
 * Scheduled tasks for the pexel-remotion platform
 *
 * Cron schedules:
 * - */5 * * * * : Scan PENDING tasks and auto-start
 * - */30 * * * * : Clean up expired tasks and R2 files
 * - 0 0 * * * : Daily statistics reset
 */
export async function scheduled(event: ScheduledEvent, env: Bindings): Promise<void> {
  const service = new TaskService(env);

  const cron = event.cron;

  console.log(`[Scheduled] Cron: ${cron}, triggered at ${new Date().toISOString()}`);

  if (cron === '*/5 * * * *') {
    // Scan for PENDING tasks and auto-start them
    try {
      const pendingTasks = await service.listTasks({ status: 'PENDING', limit: 10 });
      console.log(`[Scheduled] Found ${pendingTasks.length} pending tasks to start`);

      for (const task of pendingTasks) {
        try {
          await service.startTask(task.id);
          console.log(`[Scheduled] Auto-started task: ${task.id}`);
        } catch (error) {
          console.error(`[Scheduled] Failed to auto-start task ${task.id}:`, error);
        }
      }
    } catch (error) {
      console.error('[Scheduled] Error scanning pending tasks:', error);
    }
  }

  if (cron === '*/30 * * * *') {
    // Clean up expired tasks
    try {
      const deleted = await service.cleanupExpiredTasks();
      console.log(`[Scheduled] Cleaned up ${deleted} expired tasks`);
    } catch (error) {
      console.error('[Scheduled] Error cleaning up expired tasks:', error);
    }
  }

  if (cron === '0 0 * * *') {
    // Daily statistics reset (placeholder for future metrics)
    console.log('[Scheduled] Daily statistics reset');
  }
}
