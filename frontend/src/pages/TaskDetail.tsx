import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { taskApi, fileApi } from '../api/client';
import type { Task, TaskLog } from '../types';
import { statusLabels, phaseLabels, phaseOrder } from '../types';
import ProgressBar from '../components/ProgressBar';

export default function TaskDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [task, setTask] = useState<Task | null>(null);
  const [logs, setLogs] = useState<TaskLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchTask = useCallback(async () => {
    if (!id) return;
    try {
      const data = await taskApi.get(id);
      setTask(data);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载任务失败');
    } finally {
      setLoading(false);
    }
  }, [id]);

  const fetchLogs = useCallback(async () => {
    if (!id) return;
    try {
      const data = await taskApi.getLogs(id);
      setLogs(data);
    } catch {
      // Logs are optional
    }
  }, [id]);

  useEffect(() => {
    fetchTask();
    fetchLogs();
  }, [fetchTask, fetchLogs]);

  // Poll for updates if task is still in progress
  useEffect(() => {
    if (task && !['COMPLETED', 'FAILED', 'CANCELLED'].includes(task.status)) {
      pollRef.current = setInterval(() => {
        fetchTask();
        fetchLogs();
      }, 8000);
    } else if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
      }
    };
  }, [task, fetchTask, fetchLogs]);

  const handleCancel = async () => {
    if (!task) return;
    try {
      await taskApi.cancel(task.id);
      fetchTask();
    } catch (err) {
      alert(err instanceof Error ? err.message : '取消失败');
    }
  };

  const handleRetry = async () => {
    if (!task) return;
    try {
      await taskApi.retry(task.id);
      fetchTask();
    } catch (err) {
      alert(err instanceof Error ? err.message : '重试失败');
    }
  };

  const handleDelete = async () => {
    if (!task) return;
    if (!confirm('确定要删除此任务吗？相关的视频文件也将被删除。')) return;
    try {
      await taskApi.delete(task.id);
      navigate('/');
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    }
  };

  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return '—';
    try {
      return new Date(dateStr).toLocaleString('zh-CN');
    } catch {
      return dateStr;
    }
  };

  if (loading) {
    return <div className="page-container"><div className="loading">加载中...</div></div>;
  }

  if (error || !task) {
    return (
      <div className="page-container">
        {error && <div className="alert alert-error">{error}</div>}
        <Link to="/" className="btn btn-ghost">返回任务列表</Link>
      </div>
    );
  }

  const isRunning = !['COMPLETED', 'FAILED', 'CANCELLED'].includes(task.status);
  const isCompleted = task.status === 'COMPLETED';
  const isFailed = task.status === 'FAILED';

  const videoUrl = task.final_video_key
    ? fileApi.getNoCacheUrl(task.final_video_key)
    : null;

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="header-left-group">
          <Link to="/" className="btn btn-ghost btn-sm">← 返回</Link>
          <h1>{task.title || '未命名任务'}</h1>
        </div>
        <div className="header-actions">
          {isRunning && (
            <button className="btn btn-secondary" onClick={handleCancel}>取消任务</button>
          )}
          {isFailed && (
            <button className="btn btn-primary" onClick={handleRetry}>重新尝试</button>
          )}
          <button className="btn btn-danger" onClick={handleDelete}>删除</button>
        </div>
      </div>

      {/* Status banner */}
      <div className={`status-banner ${isCompleted ? 'success' : isFailed ? 'error' : 'running'}`}>
        <span className="status-icon">
          {isCompleted ? '✅' : isFailed ? '❌' : '⏳'}
        </span>
        <span>
          {statusLabels[task.status] || task.status}
          {task.status_message && <span className="status-message"> — {task.status_message}</span>}
        </span>
      </div>

      {error && task.error_msg && <div className="alert alert-error">错误：{task.error_msg}</div>}

      <div className="detail-grid">
        {/* Left: Progress */}
        <div className="detail-main">
          <div className="card">
            <h2 className="card-title">进度监控</h2>
            <ProgressBar currentPhase={task.current_phase} progress={task.progress} />

            {/* Phase detail */}
            <div className="phase-detail">
              {phaseOrder.map((phase) => {
                const isCurrent = task.current_phase === phase;
                const phaseDone =
                  task.status === 'COMPLETED' ||
                  (phaseOrder.indexOf(task.current_phase || '') > phaseOrder.indexOf(phase));

                return (
                  <div
                    key={phase}
                    className={`phase-item ${isCurrent ? 'current' : ''} ${phaseDone ? 'done' : ''}`}
                  >
                    <div className="phase-item-header">
                      <span className={`phase-dot ${isCurrent ? 'active' : ''} ${phaseDone ? 'done' : ''}`} />
                      <span className="phase-item-name">{phaseLabels[phase]}</span>
                      <span className="phase-item-status">
                        {phaseDone ? '已完成' : isCurrent ? '进行中' : '等待中'}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Video preview */}
          {isCompleted && videoUrl && (
            <div className="card">
              <h2 className="card-title">视频预览</h2>
              <div className="video-preview">
                <video controls className="video-player">
                  <source src={videoUrl} type="video/mp4" />
                  您的浏览器不支持视频播放。
                </video>
              </div>
              <div className="video-actions">
                <a href={videoUrl} download className="btn btn-primary">
                  ⬇ 下载视频
                </a>
                {task.final_video_key && (
                  <span className="video-key">R2 Key: {task.final_video_key}</span>
                )}
              </div>
            </div>
          )}

          {/* Article content preview */}
          {task.article_content && (
            <div className="card">
              <h2 className="card-title">文章内容</h2>
              <pre className="article-content">{task.article_content}</pre>
            </div>
          )}
        </div>

        {/* Right: Info & Logs */}
        <div className="detail-sidebar">
          <div className="card">
            <h2 className="card-title">任务信息</h2>
            <div className="info-list">
              <div className="info-item">
                <span className="info-label">任务ID</span>
                <span className="info-value">{task.id}</span>
              </div>
              <div className="info-item">
                <span className="info-label">来源</span>
                <span className="info-value">
                  {task.article_source === 'ai_generated' ? 'AI 生成' : task.article_source === 'uploaded' ? '上传' : '粘贴'}
                </span>
              </div>
              <div className="info-item">
                <span className="info-label">方向</span>
                <span className="info-value">{task.orientation === 'portrait' ? '竖屏' : '横屏'}</span>
              </div>
              <div className="info-item">
                <span className="info-label">语言</span>
                <span className="info-value">{task.language === 'zh' ? '中文' : 'English'}</span>
              </div>
              <div className="info-item">
                <span className="info-label">字幕</span>
                <span className="info-value">{task.enable_subtitle ? '已启用' : '未启用'}</span>
              </div>
              <div className="info-item">
                <span className="info-label">进度</span>
                <span className="info-value">{task.progress}%</span>
              </div>
              <div className="info-item">
                <span className="info-label">重试次数</span>
                <span className="info-value">{task.retry_count} / {task.max_retries}</span>
              </div>
              <div className="info-item">
                <span className="info-label">创建时间</span>
                <span className="info-value">{formatDate(task.created_at)}</span>
              </div>
              <div className="info-item">
                <span className="info-label">开始时间</span>
                <span className="info-value">{formatDate(task.started_at)}</span>
              </div>
              <div className="info-item">
                <span className="info-label">完成时间</span>
                <span className="info-value">{formatDate(task.completed_at)}</span>
              </div>
            </div>
          </div>

          {/* Logs */}
          <div className="card">
            <h2 className="card-title">
              运行日志
              {logs.length > 0 && <span className="badge">{logs.length}</span>}
            </h2>
            <div className="logs-container">
              {logs.length === 0 ? (
                <p className="logs-empty">暂无日志</p>
              ) : (
                logs.slice(0, 50).map((log) => (
                  <div key={log.id} className={`log-item log-${log.level.toLowerCase()}`}>
                    <div className="log-header">
                      <span className="log-level">{log.level}</span>
                      <span className="log-phase">{log.phase}</span>
                      <span className="log-time">{formatDate(log.created_at)}</span>
                    </div>
                    <div className="log-message">{log.message}</div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
