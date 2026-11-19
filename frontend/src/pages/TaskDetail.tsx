import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { taskApi, fileApi } from '../api/client';
import type { Task, TaskLog, TaskPhase, PhaseMaterialCheck } from '../types';
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

  // Phase control state
  const [rangeStart, setRangeStart] = useState<string>('');
  const [rangeEnd, setRangeEnd] = useState<string>('');
  const [materialChecks, setMaterialChecks] = useState<Record<string, PhaseMaterialCheck | null>>({});
  const [checkingPhase, setCheckingPhase] = useState<string | null>(null);

  // Re-render clips state
  const [rerenderScenes, setRerenderScenes] = useState('');
  const [rerenderImages, setRerenderImages] = useState('');
  const [rerenderTypes, setRerenderTypes] = useState('');
  const [rerendering, setRerendering] = useState(false);

  // Bilibili upload state
  const [bilibiliUploading, setBilibiliUploading] = useState(false);

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
    if (!confirm('确定要删除此任务吗？相关的视频文件和 R2 存储目录也将被一并删除，此操作不可撤销。')) return;
    try {
      await taskApi.delete(task.id);
      navigate('/');
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    }
  };

  const handleUploadBilibili = async () => {
    if (!task) return;
    setBilibiliUploading(true);
    try {
      await taskApi.uploadBilibili(task.id);
      alert('B站上传已触发，请稍后刷新查看结果');
      fetchTask();
    } catch (err) {
      alert(err instanceof Error ? err.message : '上传B站失败');
    } finally {
      setBilibiliUploading(false);
    }
  };

  // Phase control handlers
  const handleCheckMaterial = async (phase: string) => {
    if (!id) return;
    setCheckingPhase(phase);
    try {
      const result = await taskApi.checkPhase(id, phase);
      setMaterialChecks((prev) => ({ ...prev, [phase]: result }));
    } catch (err) {
      alert(err instanceof Error ? err.message : '素材检查失败');
    } finally {
      setCheckingPhase(null);
    }
  };

  const handleStartPhase = async (phase: string) => {
    if (!id || !task) return;
    const startPhase = rangeStart || undefined;
    const endPhase = rangeEnd || undefined;
    try {
      await taskApi.startPhase(id, phase, startPhase, endPhase);
      alert(`阶段 ${phaseLabels[phase as TaskPhase]} 已启动`);
      fetchTask();
    } catch (err) {
      alert(err instanceof Error ? err.message : '启动阶段失败');
    }
  };

  // Re-render clips handler
  const handleRerender = async () => {
    if (!id || !task) return;
    if (!rerenderScenes.trim()) {
      alert('请输入要重渲染的场景 ID（如 3,7,12 或 3-7）');
      return;
    }

    // Parse scene IDs
    const ids = new Set<number>();
    for (const part of rerenderScenes.split(',')) {
      const trimmed = part.trim();
      if (!trimmed) continue;
      if (trimmed.includes('-')) {
        const [start, end] = trimmed.split('-').map(Number);
        for (let i = start; i <= end; i++) ids.add(i);
      } else {
        ids.add(Number(trimmed));
      }
    }

    if (ids.size === 0) {
      alert('无法解析场景 ID');
      return;
    }

    // Parse image overrides
    const images: Record<number, string> = {};
    if (rerenderImages.trim()) {
      for (const spec of rerenderImages.split(';')) {
        const [sceneId, path] = spec.split(':').map(s => s.trim());
        if (sceneId && path) {
          images[Number(sceneId)] = path;
        }
      }
    }

    // Parse type overrides
    const types: Record<number, string> = {};
    if (rerenderTypes.trim()) {
      for (const spec of rerenderTypes.split(';')) {
        const [sceneId, type] = spec.split(':').map(s => s.trim());
        if (sceneId && type) {
          types[Number(sceneId)] = type;
        }
      }
    }

    setRerendering(true);
    try {
      await taskApi.rerenderClips(id, Array.from(ids), images, types);
      alert(`已触发重渲染 ${ids.size} 个场景`);
      fetchTask();
    } catch (err) {
      alert(err instanceof Error ? err.message : '重渲染失败');
    } finally {
      setRerendering(false);
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

  const formatSize = (bytes: number): string => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
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

  const coverUrl = task.cover_image_key
    ? fileApi.getNoCacheUrl(task.cover_image_key)
    : null;

  const isTerminal = isCompleted || isFailed || task.status === 'CANCELLED';

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
        {/* Left: Progress & Controls */}
        <div className="detail-main">
          {/* Progress monitoring */}
          <div className="card">
            <h2 className="card-title">进度监控</h2>
            <ProgressBar
              currentPhase={task.current_phase}
              progress={task.progress}
              processedFrames={task.processed_frames}
              totalFrames={task.total_frames}
              failedFrames={task.failed_frames}
              phaseDetails={task.phase_details}
            />
          </div>

          {/* Phase control panel */}
          <div className="card">
            <h2 className="card-title">阶段控制</h2>

            {/* Range execution selector */}
            <div className="range-selector">
              <div className="range-input-group">
                <label className="range-label">起始阶段</label>
                <select
                  className="range-select"
                  value={rangeStart}
                  onChange={(e) => setRangeStart(e.target.value)}
                >
                  <option value="">（单阶段）</option>
                  {phaseOrder.map((p) => (
                    <option key={p} value={p}>{phaseLabels[p]}</option>
                  ))}
                </select>
              </div>
              <div className="range-input-group">
                <label className="range-label">结束阶段</label>
                <select
                  className="range-select"
                  value={rangeEnd}
                  onChange={(e) => setRangeEnd(e.target.value)}
                >
                  <option value="">（单阶段）</option>
                  {phaseOrder.map((p) => (
                    <option key={p} value={p}>{phaseLabels[p]}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* Phase list with controls */}
            <div className="phase-control-list">
              {phaseOrder.map((phase) => {
                const currentIndex = task.current_phase ? phaseOrder.indexOf(task.current_phase as TaskPhase) : -1;
                const phaseIndex = phaseOrder.indexOf(phase);
                const isCurrent = task.current_phase === phase;
                const isDone = isCompleted || (currentIndex >= 0 && currentIndex > phaseIndex);
                const check = materialChecks[phase];

                return (
                  <div
                    key={phase}
                    className={`phase-control-item ${isCurrent ? 'current' : ''} ${isDone ? 'done' : ''}`}
                  >
                    <div className="phase-control-header">
                      <span className={`phase-dot ${isCurrent ? 'active' : ''} ${isDone ? 'done' : ''}`} />
                      <span className="phase-control-name">{phaseLabels[phase]}</span>
                      <span className="phase-control-status">
                        {isDone ? '✅ 已完成' : isCurrent ? '🔄 进行中' : '⏸ 等待中'}
                      </span>
                    </div>

                    {/* Material check result */}
                    {check && (
                      <div className={`material-check ${check.ready ? 'ready' : 'missing'}`}>
                        {check.ready ? (
                          <span>✅ 素材齐全</span>
                        ) : (
                          <span>❌ 缺少: {check.missing.join(', ')}</span>
                        )}
                      </div>
                    )}

                    {/* Action buttons */}
                    <div className="phase-control-actions">
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => handleCheckMaterial(phase)}
                        disabled={checkingPhase === phase}
                      >
                        {checkingPhase === phase ? '检查中...' : '检查素材'}
                      </button>
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={() => handleStartPhase(phase)}
                        disabled={!isTerminal && !isDone && !isCurrent}
                        title={isTerminal ? '启动此阶段' : isDone ? '跳过已完成阶段' : '需等待当前阶段完成'}
                      >
                        启动
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Re-render clips */}
          <div className="card">
            <h2 className="card-title">片段重渲染</h2>
            <p className="card-hint">
              重新渲染指定场景的片段并重新拼接。未指定的场景将复用已缓存的片段。
            </p>
            <div className="rerender-form">
              <div className="form-group">
                <label className="form-label">场景 ID</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="如 3,7,12 或 3-7"
                  value={rerenderScenes}
                  onChange={(e) => setRerenderScenes(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label className="form-label">替换素材（可选，格式 scene_id:path，多个用 ; 分隔）</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="如 5:/path/img.jpg"
                  value={rerenderImages}
                  onChange={(e) => setRerenderImages(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label className="form-label">修改类型（可选，格式 scene_id:type，多个用 ; 分隔）</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="如 8:data_visual"
                  value={rerenderTypes}
                  onChange={(e) => setRerenderTypes(e.target.value)}
                />
              </div>
              <button
                className="btn btn-primary"
                onClick={handleRerender}
                disabled={rerendering}
              >
                {rerendering ? '重渲染中...' : '重渲染片段'}
              </button>
            </div>
          </div>

          {/* Video cover — shown when the pipeline produced a cover image */}
          {coverUrl && (
            <div className="card">
              <h2 className="card-title">视频封面</h2>
              <div className="video-preview">
                <img
                  src={coverUrl}
                  alt="视频封面"
                  className="video-player cover-image"
                  style={{ objectFit: 'cover', width: '100%' }}
                />
              </div>
              <div className="video-actions">
                <a href={coverUrl} download className="btn btn-primary">
                  ⬇ 下载封面
                </a>
                {task.cover_image_key && (
                  <span className="video-key">R2 Key: {task.cover_image_key}</span>
                )}
              </div>
            </div>
          )}

          {/* Video preview — shown whenever a final video key exists, even if the
              task status is stuck in a non-terminal state (e.g. a stale FAILED
              flag left by an earlier failed callback). */}
          {videoUrl && (
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
                <button
                  className="btn btn-secondary"
                  onClick={handleUploadBilibili}
                  disabled={
                    bilibiliUploading ||
                    task.bilibili_status === 'pending' ||
                    task.bilibili_status === 'uploading'
                  }
                >
                  {bilibiliUploading ? '触发中...' : '📺 上传B站'}
                </button>
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
                <span className="info-label">背景音乐</span>
                <span className="info-value">{task.bgm_name || '未添加'}</span>
              </div>
              <div className="info-item">
                <span className="info-label">B站上传</span>
                <span className="info-value">
                  {task.bilibili_status === 'success' ? (
                    task.bilibili_url ? (
                      <a href={task.bilibili_url} target="_blank" rel="noreferrer" className="link">
                        {task.bilibili_bvid || task.bilibili_url}
                      </a>
                    ) : (
                      task.bilibili_bvid || '已上传'
                    )
                  ) : task.bilibili_status === 'pending' || task.bilibili_status === 'uploading' ? (
                    '上传中...'
                  ) : task.bilibili_status === 'failed' ? (
                    '上传失败'
                  ) : task.bilibili_upload ? (
                    '已选择自动上传'
                  ) : (
                    '未上传'
                  )}
                </span>
              </div>
              <div className="info-item">
                <span className="info-label">进度</span>
                <span className="info-value">{task.progress}%</span>
              </div>
              <div className="info-item">
                <span className="info-label">片段计数</span>
                <span className="info-value">
                  {task.processed_frames}/{task.total_frames}
                  {task.failed_frames > 0 && `（失败 ${task.failed_frames}）`}
                </span>
              </div>
              <div className="info-item">
                <span className="info-label">阶段范围</span>
                <span className="info-value">
                  {task.start_phase || task.current_phase || '—'}
                  {task.start_phase && task.end_phase && task.start_phase !== task.end_phase
                    ? ` → ${task.end_phase}`
                    : ''}
                </span>
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
