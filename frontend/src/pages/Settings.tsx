import { useState, useEffect } from 'react';
import { bilibiliApi } from '../api/client';
import type { BilibiliCredentialStatus } from '../types';

const LOGIN_COMMAND = 'python scripts/bili_login.py';

export default function Settings() {
  const [credStatus, setCredStatus] = useState<BilibiliCredentialStatus | null>(null);
  const [cookies, setCookies] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showManual, setShowManual] = useState(false);
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

  const handleRefresh = async () => {
    setError('');
    setRefreshing(true);
    await loadStatus();
    setRefreshing(false);
    setMessage('状态已刷新');
    setTimeout(() => setMessage(''), 2000);
  };

  const handleCopyCommand = async () => {
    try {
      await navigator.clipboard.writeText(LOGIN_COMMAND);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError('复制失败，请手动选中命令复制');
    }
  };

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
          登录 B站后，可在创建任务时选择自动上传，或在任务详情中手动上传视频到 B站。
        </p>

        {/* 凭据状态 */}
        <div className="info-list">
          <div className="info-item">
            <span className="info-label">状态</span>
            <span className="info-value">
              {loading ? '加载中...' : credStatus?.configured ? (
                <span className="badge badge-success">已登录</span>
              ) : (
                <span className="badge badge-warning">未登录</span>
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

        <div className="form-actions">
          <button className="btn btn-ghost" onClick={handleRefresh} disabled={refreshing}>
            {refreshing ? '刷新中...' : '刷新状态'}
          </button>
        </div>

        {/* 本地扫码登录 */}
        <div className="tips-box">
          <h4>本地扫码登录（推荐）</h4>
          <p style={{ margin: '4px 0 0' }}>
            在项目目录运行一条命令，会弹出一个浏览器窗口；用 B站 App 扫码确认后，
            脚本会自动抓取全部 Cookie 并保存到当前账号，<strong>无需复制任何 Cookie</strong>。
          </p>
        </div>

        <div className="form-group">
          <label>登录命令</label>
          <div style={{ display: 'flex', gap: 8, alignItems: 'stretch' }}>
            <input
              className="mono"
              value={LOGIN_COMMAND}
              readOnly
              onFocus={(e) => e.currentTarget.select()}
              style={{ flex: 1 }}
            />
            <button className="btn btn-primary" onClick={handleCopyCommand}>
              {copied ? '已复制' : '复制命令'}
            </button>
          </div>
        </div>

        <ol style={{ margin: '0 0 8px 20px', fontSize: 14, lineHeight: 1.8 }}>
          <li>在项目根目录打开终端，运行上面的命令</li>
          <li>在弹出的浏览器窗口中用 B站 App 扫码，并在手机上点击确认</li>
          <li>看到「完成」提示后，回到本页点「刷新状态」</li>
        </ol>

        <p style={{ margin: '0 0 8px', fontSize: 13, opacity: 0.75 }}>
          首次运行会自动安装依赖提示：<code>pip install playwright</code>、
          <code>python -m playwright install chromium</code>。
          脚本启动时会询问你的平台账号密码（仅用于获取登录令牌，不会被保存）。
        </p>

        {error && <div className="alert alert-error">{error}</div>}
        {message && <div className="alert alert-success">{message}</div>}

        {/* 手动粘贴（兜底） */}
        <div style={{ marginTop: 8 }}>
          <button
            className="link-button"
            onClick={() => setShowManual((v) => !v)}
            style={{ background: 'none', border: 'none', padding: 0, color: 'inherit', opacity: 0.75, cursor: 'pointer', textDecoration: 'underline' }}
          >
            {showManual ? '收起手动粘贴' : '手动粘贴 Cookie（备用）'}
          </button>

          {showManual && (
            <div style={{ marginTop: 12 }}>
              <div className="tips-box">
                <h4>如何手动获取 B站 Cookie</h4>
                <ol>
                  <li>在浏览器中登录 <a href="https://www.bilibili.com" target="_blank" rel="noreferrer">哔哩哔哩</a></li>
                  <li>按 <code>F12</code> 打开开发者工具，切换到「应用」→「Cookie」</li>
                  <li>找到 <code>bilibili.com</code> 域名，复制所有 Cookie</li>
                  <li>粘贴到下方输入框（支持字符串或 JSON 格式）</li>
                </ol>
              </div>

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

              <div className="form-actions">
                <button
                  className="btn btn-primary"
                  onClick={handleSave}
                  disabled={saving || !cookies.trim()}
                >
                  {saving ? '保存中...' : '保存凭据'}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* 删除凭据 */}
        {credStatus?.configured && (
          <div className="form-actions" style={{ marginTop: 16 }}>
            <button className="btn btn-ghost" onClick={handleDelete} disabled={deleting}>
              {deleting ? '删除中...' : '退出登录 / 删除凭据'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}