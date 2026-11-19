import { useState, useEffect } from 'react';
import { bilibiliApi } from '../api/client';
import type { BilibiliCredentialStatus } from '../types';

export default function Settings() {
  const [credStatus, setCredStatus] = useState<BilibiliCredentialStatus | null>(null);
  const [cookies, setCookies] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const loadStatus = async () => {
    try {
      const status = await bilibiliApi.getCredentialStatus();
      setCredStatus(status);
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取状态失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const handleSave = async () => {
    setError('');
    setMessage('');
    if (!cookies.trim()) {
      setError('请粘贴 B站 Cookie');
      return;
    }
    setSaving(true);
    try {
      const status = await bilibiliApi.saveCredentials(cookies);
      setCredStatus(status);
      setCookies('');
      setMessage('B站凭据已保存');
      setTimeout(() => setMessage(''), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setError('');
    setMessage('');
    setDeleting(true);
    try {
      const result = await bilibiliApi.deleteCredentials();
      setCredStatus({ configured: false, hasSessdata: false, hasBiliJct: false });
      setMessage(result.deleted ? 'B站凭据已删除' : '未找到已配置的凭据');
      setTimeout(() => setMessage(''), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败');
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="page-container">
      <h1 className="page-title">设置</h1>

      <div className="card">
        <h2 className="card-title">B站上传</h2>
        <p className="card-desc">
          配置 B站 Cookie 后，可在创建任务时选择自动上传，或在任务详情中手动上传视频到 B站。
        </p>

        {/* 凭据状态 */}
        <div className="info-list">
          <div className="info-item">
            <span className="info-label">状态</span>
            <span className="info-value">
              {loading ? '加载中...' : credStatus?.configured ? (
                <span className="badge badge-success">已配置</span>
              ) : (
                <span className="badge badge-warning">未配置</span>
              )}
            </span>
          </div>
          <div className="info-item">
            <span className="info-label">SESSDATA</span>
            <span className="info-value">
              {credStatus?.hasSessdata ? (
                <span className="badge badge-success">已包含</span>
              ) : (
                <span className="badge badge-warning">缺失</span>
              )}
            </span>
          </div>
          <div className="info-item">
            <span className="info-label">bili_jct</span>
            <span className="info-value">
              {credStatus?.hasBiliJct ? (
                <span className="badge badge-success">已包含</span>
              ) : (
                <span className="badge badge-warning">缺失</span>
              )}
            </span>
          </div>
        </div>

        {/* Cookie 获取指引 */}
        <div className="tips-box">
          <h4>如何获取 B站 Cookie</h4>
          <ol>
            <li>在浏览器中登录 <a href="https://www.bilibili.com" target="_blank" rel="noreferrer">哔哩哔哩</a></li>
            <li>按 <code>F12</code> 打开开发者工具，切换到「应用」→「Cookie」</li>
            <li>找到 <code>bilibili.com</code> 域名，复制所有 Cookie</li>
            <li>粘贴到下方输入框（支持字符串或 JSON 格式）</li>
          </ol>
        </div>

        {/* Cookie 输入 */}
        <div className="form-group">
          <label>B站 Cookie</label>
          <textarea
            value={cookies}
            onChange={(e) => setCookies(e.target.value)}
            placeholder={'粘贴 Cookie，支持两种格式：\n1. 字符串：name1=value1; name2=value2\n2. JSON 数组：[{name, value, domain, path, ...}]'}
            rows={6}
            className="mono"
          />
        </div>

        {error && <div className="alert alert-error">{error}</div>}
        {message && <div className="alert alert-success">{message}</div>}

        <div className="form-actions">
          <button
            className="btn btn-primary"
            onClick={handleSave}
            disabled={saving || !cookies.trim()}
          >
            {saving ? '保存中...' : '保存凭据'}
          </button>
          {credStatus?.configured && (
            <button
              className="btn btn-ghost"
              onClick={handleDelete}
              disabled={deleting}
            >
              {deleting ? '删除中...' : '删除凭据'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
