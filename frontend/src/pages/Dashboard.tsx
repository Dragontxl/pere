import { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { taskApi } from '../api/client';
import type { Task } from '../types';
import { statusLabels } from '../types';

const STATUS_FILTERS = [
  { key: '', label: '全部' },
  { key: 'PENDING', label: '进行中' },
  { key: 'COMPLETED', label: '已完成' },
  { key: 'FAILED', label: '失败' },
];

export default function Dashboard() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('');
  const [refreshInterval, setRefreshInterval] = useState<number | null>(null);

  const fetchTasks = useCallback(async () => {
    try {
      const data = await taskApi.list({ limit: 50 });
      setTasks(data);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载任务列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  // Auto-refresh if any task is in progress
  useEffect(() => {
    const hasActive = tasks.some((t) =>
      !['COMPLETED', 'FAILED', 'CANCELLED'].includes(t.status),
    );

    if (hasActive && refreshInterval === null) {
      const interval = setInterval(fetchTasks, 10000);
      setRefreshInterval(interval as unknown as number);
    } else if (!hasActive && refreshInterval !== null) {
      clearInterval(refreshInterval);
      setRefreshInterval(null);
    }

    return () => {
      if (refreshInterval !== null) {
        clearInterval(refreshInterval);
      }
    };
  }, [tasks, refreshInterval, fetchTasks]);

  const filteredTasks = filter
    ? tasks.filter((t) => t.status === filter)
    : tasks;

  const handleDelete = async (id: string) => {
    if (!confirm('确定要删除此任务吗？相关的视频文件也将被删除。')) return;
    try {
      await taskApi.delete(id);
      fetchTasks();
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    }
  };

  const handleCancel = async (id: string) => {
    try {
      await taskApi.cancel(id);
      fetchTasks();
    } catch (err) {
      alert(err instanceof Error ? err.message : '取消失败');
    }
  };

  const handleRetry = async (id: string) => {
    try {
      await taskApi.retry(id);
      fetchTasks();
    } catch (err) {
      alert(err instanceof Error ? err.message : '重试失败');
    }
  };

  const getStatusClass = (status: string): string => {
    if (status === 'COMPLETED') return 'status-completed';
    if (status === 'FAILED') return 'status-failed';
    if (status === 'CANCELLED') return 'status-cancelled';
    return 'status-running';
  };

  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return '—';
    try {
      return new Date(dateStr).toLocaleString('zh-CN');
    } catch {
      return dateStr;
    }
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <h1>任务列表</h1>
        <Link to="/create" className="btn btn-primary">
          + 创建任务
        </Link>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {/* Status filter tabs */}
      <div className="filter-tabs">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.key}
            className={`filter-tab ${filter === f.key ? 'active' : ''}`}
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="loading">加载中...</div>
      ) : filteredTasks.length === 0 ? (
        <div className="empty-state">
          <p>暂无任务</p>
          <Link to="/create" className="btn btn-primary">创建第一个任务</Link>
        </div>
      ) : (
        <div className="task-list">
          {filteredTasks.map((task) => (
            <div
              key={task.id}
              className="task-card"
              onClick={() => navigate(`/tasks/${task.id}`)}
            >
              <div className="task-card-header">
                <h3 className="task-title">{task.title || '未命名任务'}</h3>
                <span className={`status-badge ${getStatusClass(task.status)}`}>
                  {statusLabels[task.status] || task.status}
                </span>
              </div>
              <div className="task-card-meta">
                <span className="meta-item">
                  来源：{task.article_source === 'ai_generated' ? 'AI 生成' : task.article_source === 'uploaded' ? '上传' : '粘贴'}
                </span>
                <span className="meta-item">
                  方向：{task.orientation === 'portrait' ? '竖屏' : '横屏'}
                </span>
                {task.bgm_name && (
                  <span className="meta-item">
                    BGM：{task.bgm_name}
                  </span>
                )}
                <span className="meta-item">
                  创建：{formatDate(task.created_at)}
                </span>
              </div>
              <div className="task-card-progress">
                <div className="mini-progress-bar">
                  <div className="mini-progress-fill" style={{ width: `${task.progress}%` }} />
                </div>
                <span className="progress-text">{task.progress}%</span>
              </div>
              <div className="task-card-actions">
                {task.status === 'FAILED' && (
                  <button
                    className="btn btn-sm btn-secondary"
                    onClick={(e) => { e.stopPropagation(); handleRetry(task.id); }}
                  >
                    重试
                  </button>
                )}
                {!['COMPLETED', 'FAILED', 'CANCELLED'].includes(task.status) && (
                  <button
                    className="btn btn-sm btn-secondary"
                    onClick={(e) => { e.stopPropagation(); handleCancel(task.id); }}
                  >
                    取消
                  </button>
                )}
                <button
                  className="btn btn-sm btn-danger"
                  onClick={(e) => { e.stopPropagation(); handleDelete(task.id); }}
                >
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
