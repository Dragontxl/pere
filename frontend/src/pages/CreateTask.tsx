import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { taskApi } from '../api/client';

type ArticleMode = 'ai' | 'paste' | 'upload';

export default function CreateTask() {
  const [mode, setMode] = useState<ArticleMode>('paste');
  const [title, setTitle] = useState('');
  const [topic, setTopic] = useState('');
  const [article, setArticle] = useState('');
  const [fileKey, setFileKey] = useState('');
  const [orientation, setOrientation] = useState('landscape');
  const [language, setLanguage] = useState('zh');
  const [enableSubtitle, setEnableSubtitle] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const navigate = useNavigate();

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setError('');
    try {
      // Upload file to R2 via admin API
      const formData = new FormData();
      formData.append('file', file);
      formData.append('prefix', 'articles');

      const token = localStorage.getItem('token');
      const response = await fetch('/api/v1/admin/files/upload', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
        },
        body: formData,
      });

      const data = await response.json();
      if (response.ok) {
        setFileKey(data.data.key);
        if (!title) {
          setTitle(file.name.replace(/\.[^.]+$/, ''));
        }
      } else {
        setError(data.msg || '文件上传失败');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '文件上传失败');
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const articleSource = mode === 'ai' ? 'ai_generated' : mode === 'upload' ? 'uploaded' : 'pasted';

      const data = await taskApi.create({
        title: title || '未命名任务',
        article_source: articleSource,
        article_content: mode === 'paste' ? article : undefined,
        article_file_key: mode === 'upload' ? fileKey : undefined,
        orientation,
        language,
        enable_subtitle: enableSubtitle,
      });

      navigate(`/tasks/${data.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建任务失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <h1>创建视频生成任务</h1>
      </div>

      <form onSubmit={handleSubmit} className="create-form">
        {error && <div className="alert alert-error">{error}</div>}

        {/* Article source mode */}
        <div className="form-section">
          <h2 className="section-title">文章来源</h2>
          <div className="mode-tabs">
            <button
              type="button"
              className={`mode-tab ${mode === 'ai' ? 'active' : ''}`}
              onClick={() => setMode('ai')}
            >
              <span className="mode-icon">🤖</span>
              <span>AI 生成</span>
            </button>
            <button
              type="button"
              className={`mode-tab ${mode === 'paste' ? 'active' : ''}`}
              onClick={() => setMode('paste')}
            >
              <span className="mode-icon">📝</span>
              <span>粘贴文章</span>
            </button>
            <button
              type="button"
              className={`mode-tab ${mode === 'upload' ? 'active' : ''}`}
              onClick={() => setMode('upload')}
            >
              <span className="mode-icon">📁</span>
              <span>上传文件</span>
            </button>
          </div>

          {mode === 'ai' && (
            <div className="form-group">
              <label>话题或文章要求</label>
              <textarea
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="输入话题或文章要求，AI 将自动生成口播文章。例如：介绍人工智能在医疗领域的应用"
                rows={5}
                required
              />
            </div>
          )}

          {mode === 'paste' && (
            <div className="form-group">
              <label>文章内容</label>
              <textarea
                value={article}
                onChange={(e) => setArticle(e.target.value)}
                placeholder="粘贴或输入文章内容..."
                rows={10}
                required
              />
              <p className="form-hint">{article.length} 字</p>
            </div>
          )}

          {mode === 'upload' && (
            <div className="form-group">
              <label>上传文章文件（txt 等）</label>
              <input
                ref={fileInputRef}
                type="file"
                accept=".txt,.md,.text"
                onChange={handleFileUpload}
                style={{ display: fileKey ? 'none' : 'block' }}
              />
              {fileKey && (
                <div className="upload-success">
                  <span className="upload-icon">✅</span>
                  <span>已上传：{fileKey}</span>
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost"
                    onClick={() => {
                      setFileKey('');
                      if (fileInputRef.current) {
                        fileInputRef.current.value = '';
                      }
                    }}
                  >
                    重新上传
                  </button>
                </div>
              )}
              <p className="form-hint">支持 .txt, .md 格式</p>
            </div>
          )}
        </div>

        {/* Basic settings */}
        <div className="form-section">
          <h2 className="section-title">基本设置</h2>

          <div className="form-group">
            <label>任务标题</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="为任务起一个名字（可选）"
            />
          </div>

          <div className="form-row">
            <div className="form-group">
              <label>画面方向</label>
              <select
                value={orientation}
                onChange={(e) => setOrientation(e.target.value)}
              >
                <option value="landscape">横屏（16:9）</option>
                <option value="portrait">竖屏（9:16）</option>
              </select>
            </div>

            <div className="form-group">
              <label>文章语言</label>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
              >
                <option value="zh">中文</option>
                <option value="en">English</option>
              </select>
            </div>
          </div>

          <div className="form-group checkbox-group">
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={enableSubtitle}
                onChange={(e) => setEnableSubtitle(e.target.checked)}
              />
              <span>添加字幕</span>
            </label>
          </div>
        </div>

        {/* Actions */}
        <div className="form-actions">
          <button type="button" className="btn btn-ghost" onClick={() => navigate(-1)}>
            取消
          </button>
          <button type="submit" className="btn btn-primary" disabled={loading}>
            {loading ? '创建中...' : '创建并开始'}
          </button>
        </div>
      </form>
    </div>
  );
}
