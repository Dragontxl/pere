import { Bindings } from '../types/env';
import { Task, TaskPhase, TaskStatus, phaseOrder, phaseStatusMap } from '../types';

export class TaskService {
  constructor(public env: Bindings) {}

  getPhaseOrder(): TaskPhase[] {
    return phaseOrder;
  }

  generateUUID(seed: string): string {
    const timestamp = Date.now().toString(36);
    const random = Math.random().toString(36).substring(2, 10);
    const shortHash = seed ? seed.substring(0, 8) : 'task';
    return `${timestamp}-${random}-${shortHash}`;
  }

  async createTask(data: {
    userId: string;
    title: string;
    articleSource: string;
    articleContent: string | null;
    articleFileKey: string | null;
    orientation: string;
    language: string;
    enableSubtitle: boolean;
  }): Promise<Task> {
    const now = new Date().toISOString();
    const task: Task = {
      id: this.generateUUID(data.title || 'video'),
      user_id: data.userId,
      title: data.title || '',
      article_source: data.articleSource,
      article_content: data.articleContent,
      article_file_key: data.articleFileKey,
      orientation: data.orientation || 'landscape',
      language: data.language || 'zh',
      enable_subtitle: data.enableSubtitle !== false,
      status: 'PENDING',
      current_phase: 'SCENE_GEN',
      scenes_key: null,
      match_results_key: null,
      final_video_key: null,
      final_video_url: null,
      progress: 0,
      retry_count: 0,
      max_retries: 3,
      error_msg: null,
      status_message: null,
      created_at: now,
      updated_at: now,
      started_at: null,
      completed_at: null,
      expires_at: null,
    };

    await this.env.DB.prepare(`
      INSERT INTO tasks (
        id, user_id, title, article_source, article_content, article_file_key,
        orientation, language, enable_subtitle, status, current_phase, progress,
        retry_count, max_retries, created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      task.id,
      task.user_id,
      task.title,
      task.article_source,
      task.article_content,
      task.article_file_key,
      task.orientation,
      task.language,
      task.enable_subtitle,
      task.status,
      task.current_phase,
      task.progress,
      task.retry_count,
      task.max_retries,
      task.created_at,
      task.updated_at
    ).run();

    return task;
  }

  async getTask(id: string): Promise<Task | null> {
    const result = await this.env.DB.prepare(
      'SELECT * FROM tasks WHERE id = ?'
    ).bind(id).first();
    return result as Task | null;
  }

  async listTasks(filters: {
    userId?: string;
    status?: string;
    page?: number;
    limit?: number;
  }): Promise<Task[]> {
    const page = filters.page || 1;
    const limit = filters.limit || 20;
    const offset = (page - 1) * limit;

    let query = 'SELECT * FROM tasks WHERE 1=1';
    const params: (string | number)[] = [];

    if (filters.userId) {
      query += ' AND user_id = ?';
      params.push(filters.userId);
    }
    if (filters.status) {
      query += ' AND status = ?';
      params.push(filters.status);
    }

    query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?';
    params.push(limit, offset);

    const result = await this.env.DB.prepare(query).bind(...params).all();
    return (result.results as unknown) as Task[];
  }

  async updateTask(id: string, data: Partial<Task>): Promise<Task | null> {
    const fields = Object.keys(data).filter(k => k !== 'id');
    const setClause = fields.map(f => `${f} = ?`).join(', ');
    const values = fields.map(f => (data as any)[f]);

    await this.env.DB.prepare(`
      UPDATE tasks SET ${setClause}, updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?
    `).bind(...values, id).run();

    return this.getTask(id);
  }

  async deleteTask(id: string): Promise<boolean> {
    const task = await this.getTask(id);
    if (!task) {
      return false;
    }

    // Delete R2 objects for this task
    let deletedFileCount = 0;
    try {
      const objects = await this.env.R2.list({ prefix: `${id}/`, limit: 1000 });
      const keys = objects.objects.map(obj => obj.key);
      if (keys.length > 0) {
        await this.env.R2.delete(keys);
        deletedFileCount += keys.length;
      }
    } catch (error) {
      console.error(`Failed to delete R2 objects for task ${id}:`, error);
    }

    await this.env.DB.prepare('DELETE FROM operation_logs WHERE task_id = ?').bind(id).run();
    const result = await this.env.DB.prepare('DELETE FROM tasks WHERE id = ?').bind(id).run();

    console.log(`Deleted task ${id} and ${deletedFileCount} R2 objects`);
    return (result as any).changes > 0;
  }

  async cancelTask(id: string): Promise<Task | null> {
    const task = await this.getTask(id);
    if (!task) return null;
    if (task.status === 'COMPLETED' || task.status === 'CANCELLED') return task;

    await this.env.DB.prepare(`
      UPDATE tasks SET status = ?, updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?
    `).bind('CANCELLED', id).run();

    return this.getTask(id);
  }

  async retryTask(id: string): Promise<Task | null> {
    const task = await this.getTask(id);
    if (!task) return null;
    if (task.status !== 'FAILED') return null;

    await this.env.DB.prepare(`
      UPDATE tasks SET status = ?, retry_count = retry_count + 1, updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?
    `).bind('PENDING', id).run();

    await this.startTask(id);
    return this.getTask(id);
  }

  /**
   * Start a task: trigger the GitHub Actions workflow for the full pipeline
   */
  async startTask(id: string): Promise<Task | null> {
    const task = await this.getTask(id);
    if (!task) return null;
    if (task.status !== 'PENDING') return null;

    await this.triggerPhase(id, 'SCENE_GEN');
    return this.getTask(id);
  }

  /**
   * Trigger a GitHub Actions workflow for a specific phase
   */
  async triggerPhase(taskId: string, phase: TaskPhase): Promise<void> {
    const task = await this.getTask(taskId);
    if (!task) {
      throw new Error('Task not found');
    }

    const owner = this.env.GITHUB_REPO_OWNER;
    const repo = this.env.GITHUB_REPO_NAME;

    if (!owner || !repo) {
      throw new Error('GitHub repository not configured');
    }

    // Use GITHUB_PAT from env to authenticate with GitHub API
    const apiKey = this.env.GITHUB_PAT;
    if (!apiKey) {
      throw new Error('GITHUB_PAT not configured');
    }

    const payload = {
      event_type: 'video-generation',
      client_payload: {
        task_id: taskId,
        article_source: task.article_source,
        article_content: task.article_content || '',
        article_file_key: task.article_file_key || '',
        orientation: task.orientation,
        language: task.language,
        enable_subtitle: task.enable_subtitle,
        phase: phase,
        start_phase: phase,
        end_phase: phase,
      },
    };

    const authHeader = apiKey.startsWith('ghp_')
      ? `token ${apiKey}`
      : `Bearer ${apiKey}`;

    const githubUrl = `https://api.github.com/repos/${owner}/${repo}/dispatches`;

    const response = await fetch(githubUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': authHeader,
        'User-Agent': 'pexel-remotion-platform',
        'Accept': 'application/vnd.github.v3+json',
        'X-GitHub-Api-Version': '2022-11-28',
      },
      body: JSON.stringify(payload),
      redirect: 'follow',
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Failed to dispatch workflow: ${response.status} ${errorText}`);
    }

    // Update task status
    const runningStatus = phaseStatusMap[phase].running;
    await this.env.DB.prepare(`
      UPDATE tasks SET status = ?, current_phase = ?, started_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'), updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?
    `).bind(runningStatus, phase, taskId).run();

    await this.logTask(taskId, phase, 'INFO', `Phase ${phase} triggered`);
  }

  /**
   * Update task progress from workflow callback
   */
  async updateTaskProgress(body: any): Promise<{ success: boolean; taskId: string }> {
    const { task_id: taskId, phase, processed_count: processedCount, total_count: totalCount, message } = body;

    const taskResult = await this.env.DB.prepare('SELECT status FROM tasks WHERE id = ?').bind(taskId).first() as any;
    if (taskResult?.status === 'COMPLETED') {
      return { success: true, taskId };
    }

    const phaseIndex = phaseOrder.indexOf(phase as TaskPhase);
    const phasesCount = phaseOrder.length;
    const runningStatus = phaseStatusMap[phase as TaskPhase]?.running || phaseStatusMap[phaseOrder[0]].running;

    const terminalStatusClause = "status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED')";

    if (totalCount > 0) {
      const phaseProgress = Math.round((processedCount / totalCount) * 100);
      const progress = Math.round((phaseIndex / phasesCount) * 100 + (phaseProgress / 100) * (100 / phasesCount));

      await this.env.DB.prepare(`
        UPDATE tasks SET progress = ?, current_phase = ?, status = ?, updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ? AND ${terminalStatusClause}
      `).bind(progress, phase, runningStatus, taskId).run();
    } else {
      const progress = Math.round((phaseIndex / phasesCount) * 100);

      await this.env.DB.prepare(`
        UPDATE tasks SET progress = ?, current_phase = ?, status = ?, updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ? AND ${terminalStatusClause}
      `).bind(progress, phase, runningStatus, taskId).run();
    }

    if (message) {
      await this.env.DB.prepare(`UPDATE tasks SET status_message = ? WHERE id = ?`).bind(message, taskId).run();
    }

    return { success: true, taskId };
  }

  /**
   * Handle task completion callback
   */
  async handleTaskComplete(body: any): Promise<{ success: boolean; taskId: string }> {
    const { task_id: taskId, phase, data } = body;

    await this.env.DB.prepare(`
      UPDATE tasks SET status = ?, current_phase = ?, progress = 100, completed_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'), updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
      WHERE id = ?
    `).bind('COMPLETED', phase || 'TTS_COMPOSE', taskId).run();

    // Store final video key if provided
    if (data?.final_video_key) {
      await this.env.DB.prepare(`UPDATE tasks SET final_video_key = ?, final_video_url = ? WHERE id = ?`)
        .bind(data.final_video_key, data.final_video_url || null, taskId).run();
    }

    await this.logTask(taskId, phase, 'INFO', `Task completed: ${JSON.stringify(data || {})}`);
    return { success: true, taskId };
  }

  /**
   * Handle task error callback
   */
  async handleTaskError(body: any): Promise<{ success: boolean; taskId: string }> {
    const { task_id: taskId, phase, error } = body;

    await this.env.DB.prepare(`
      UPDATE tasks SET status = ?, error_msg = ?, updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
      WHERE id = ?
    `).bind('FAILED', error || 'Unknown error', taskId).run();

    await this.logTask(taskId, phase, 'ERROR', `Task error: ${error}`);
    return { success: true, taskId };
  }

  /**
   * Handle GitHub workflow completion callback
   */
  async handleGitHubCallback(body: any): Promise<{ success: boolean; taskId: string }> {
    const { task_id: taskId, phase, status, start_phase: startPhase, end_phase: endPhase } = body;

    await this.env.DB.prepare(`
      UPDATE tasks SET updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?
    `).bind(taskId).run();

    if (status === 'success') {
      try {
        // Range execution (start_phase !== end_phase): full pipeline completed
        if (startPhase && endPhase && startPhase !== endPhase) {
          await this.env.DB.prepare(`
            UPDATE tasks SET status = ?, completed_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'), updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
          `).bind('COMPLETED', taskId).run();
          await this.logTask(taskId, phase, 'INFO', `Range execution completed: ${startPhase} to ${endPhase}`);
        } else if (startPhase && endPhase && startPhase === endPhase) {
          // Single phase completed: advance to next phase
          await this.advancePhase(taskId);
        } else {
          await this.logTask(taskId, phase, 'WARNING', `Missing phase range: start=${startPhase}, end=${endPhase}`);
        }
      } catch (error) {
        console.error('handleGitHubCallback: Failed to process completion:', error);
        await this.env.DB.prepare(`
          UPDATE tasks SET status = ?, error_msg = ?, updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?
        `).bind('FAILED', (error as Error).message, taskId).run();
      }
    } else {
      await this.env.DB.prepare(`
        UPDATE tasks SET status = ?, error_msg = ?, updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?
      `).bind('FAILED', `Phase ${phase} failed in GitHub Actions`, taskId).run();
      await this.logTask(taskId, phase, 'ERROR', `Phase ${phase} failed`);
    }

    return { success: true, taskId };
  }

  /**
   * Advance to the next phase after current phase completes
   */
  async advancePhase(taskId: string): Promise<void> {
    const task = await this.getTask(taskId);
    if (!task) return;

    const currentPhase = task.current_phase as TaskPhase || 'SCENE_GEN';
    const currentIndex = phaseOrder.indexOf(currentPhase);
    const nextPhase = phaseOrder[currentIndex + 1];

    if (!nextPhase) {
      // Last phase completed
      if (currentPhase === 'TTS_COMPOSE') {
        await this.env.DB.prepare(`
          UPDATE tasks SET status = ?, completed_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'), updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?
        `).bind('COMPLETED', taskId).run();
      }
      return;
    }

    // Update to next phase
    const doneStatus = phaseStatusMap[currentPhase].done;
    await this.env.DB.prepare(`
      UPDATE tasks SET status = ?, current_phase = ?, updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?
    `).bind(doneStatus, nextPhase, taskId).run();

    await this.triggerPhase(taskId, nextPhase);
  }

  async logTask(taskId: string, phase: string, level: string, message: string): Promise<void> {
    await this.env.DB.prepare(`
      INSERT INTO operation_logs (task_id, phase, level, message) VALUES (?, ?, ?, ?)
    `).bind(taskId, phase, level, message).run();
  }

  async getTaskLogs(taskId: string): Promise<any[]> {
    const result = await this.env.DB.prepare(`
      SELECT * FROM operation_logs WHERE task_id = ? ORDER BY created_at DESC
    `).bind(taskId).all();
    return result.results || [];
  }

  /**
   * Clean up expired tasks
   */
  async cleanupExpiredTasks(): Promise<number> {
    const now = new Date().toISOString();
    const result = await this.env.DB.prepare(`
      SELECT id FROM tasks WHERE expires_at IS NOT NULL AND expires_at < ?
    `).bind(now).all();

    const expiredTasks = (result.results as unknown) as { id: string }[];
    for (const task of expiredTasks) {
      await this.deleteTask(task.id);
    }

    return expiredTasks.length;
  }
}
