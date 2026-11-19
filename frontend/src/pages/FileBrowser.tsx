import { useState, useEffect, useCallback, useRef } from 'react';
import { fileApi } from '../api/client';
import type { FileItem, FileListResult, FileStats } from '../types';

export default function FileBrowser() {
  const [prefix, setPrefix] = useState('');
  const [items, setItems] = useState<FileItem[]>([]);
  const [folders, setFolders] = useState<FileItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const [stats, setStats] = useState<FileStats | null>(null);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [showCreateFolder, setShowCreateFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const [previewItem, setPreviewItem] = useState<FileItem | null>(null);
  const [uploadProgress, setUploadProgress] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchFiles = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await fileApi.list(prefix);
      setItems(result.files);
      setFolders(result.folders);
      setNextCursor(result.cursor);
      setHasMore(result.truncated && !!result.cursor);
      fetchStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载文件失败');
    } finally {
      setLoading(false);
    }
  }, [prefix]);

  const fetchStats = useCallback(async () => {
    try {
      const s = await fileApi.stats(prefix);
      setStats(s);
    } catch {
      // Stats are optional
    }
  }, [prefix]);

  const loadMore = useCallback(async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    setError('');
    try {
      const result = await fileApi.list(prefix, nextCursor);
      setFolders((prev) => {
        const seen = new Set(prev.map((f) => f.key));
        return [...prev, ...result.folders.filter((f) => !seen.has(f.key))];
      });
      setItems((prev) => {
        const seen = new Set(prev.map((f) => f.key));
        return [...prev, ...result.files.filter((f) => !seen.has(f.key))];
      });
      setNextCursor(result.cursor);
      setHasMore(result.truncated && !!result.cursor);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载更多失败');
    } finally {
      setLoadingMore(false);
    }
  }, [prefix, nextCursor, loadingMore]);

  useEffect(() => {
    fetchFiles();
  }, [fetchFiles]);

  // Build breadcrumb path segments
  const getPathSegments = (prefix: string): string[] => {
    if (!prefix) return [];
    return prefix.split('/').filter(Boolean);
  };

  const navigateToPath = (path: string) => {
    setPrefix(path);
    setSelectedKeys(new Set());
  };

  const handleUpload = async (files: FileList) => {
    if (files.length === 0) return;
    setUploadProgress(`上传中... (0/${files.length})`);

    const fileList: Array<{ filename: string; content: string; contentType?: string }> = [];
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const arrayBuffer = await file.arrayBuffer();
      const base64 = btoa(String.fromCharCode(...new Uint8Array(arrayBuffer)));
      fileList.push({
        filename: file.name,
        content: base64,
        contentType: file.type || undefined,
      });
      setUploadProgress(`上传中... (${i + 1}/${files.length})`);
    }

    try {
      await fileApi.batchUpload(fileList, prefix);
      alert(`已上传 ${files.length} 个文件`);
      fetchFiles();
    } catch (err) {
      alert(err instanceof Error ? err.message : '上传失败');
    } finally {
      setUploadProgress('');
    }
  };

  const handleDelete = async (key: string, isDirectory: boolean) => {
    if (!confirm(`确定要删除 ${key} 吗？${isDirectory ? '（将递归删除文件夹内所有文件）' : ''}`)) return;
    try {
      await fileApi.delete(key, isDirectory);
      fetchFiles();
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    }
  };

  const handleBatchDelete = async () => {
    if (selectedKeys.size === 0) return;
    if (!confirm(`确定要删除选中的 ${selectedKeys.size} 个项目吗？`)) return;
    try {
      const result = await fileApi.batchDelete(Array.from(selectedKeys));
      alert(`已删除 ${result.deleted} 个对象`);
      if (result.errors.length > 0) {
        console.warn('Batch delete errors:', result.errors);
      }
      setSelectedKeys(new Set());
      fetchFiles();
    } catch (err) {
      alert(err instanceof Error ? err.message : '批量删除失败');
    }
  };

  const handleCreateFolder = async () => {
    if (!newFolderName.trim()) return;
    const folderKey = prefix
      ? `${prefix}/${newFolderName.trim()}`
      : newFolderName.trim();
    try {
      await fileApi.createFolder(folderKey);
      setNewFolderName('');
      setShowCreateFolder(false);
      fetchFiles();
    } catch (err) {
      alert(err instanceof Error ? err.message : '创建文件夹失败');
    }
  };

  const handleSelect = (key: string) => {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const handleSelectAll = () => {
    const allKeys = [...folders.map(f => f.key), ...items.map(f => f.key)];
    if (selectedKeys.size === allKeys.length) {
      setSelectedKeys(new Set());
    } else {
      setSelectedKeys(new Set(allKeys));
    }
  };

  const formatSize = (bytes: number): string => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return '—';
    try {
      return new Date(dateStr).toLocaleString('zh-CN');
    } catch {
      return dateStr;
    }
  };

  const getFileIcon = (name: string): string => {
    const ext = name.toLowerCase().split('.').pop();
    if (['mp4', 'webm', 'avi', 'mov', 'mkv'].includes(ext || '')) return '🎬';
    if (['jpg', 'jpeg', 'png', 'gif', 'bmp'].includes(ext || '')) return '🖼️';
    if (['mp3', 'wav', 'ogg', 'flac', 'm4a'].includes(ext || '')) return '🎵';
    if (ext === 'json') return '📋';
    if (ext === 'txt' || ext === 'md') return '📄';
    return '📦';
  };

  const segments = getPathSegments(prefix);

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="header-left-group">
          <h1>文件管理</h1>
        </div>
        <div className="header-actions">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            style={{ display: 'none' }}
            onChange={(e) => {
              if (e.target.files) handleUpload(e.target.files);
              e.target.value = '';
            }}
          />
          <button className="btn btn-primary" onClick={() => fileInputRef.current?.click()}>
            ⬆ 上传文件
          </button>
          <button className="btn btn-secondary" onClick={() => setShowCreateFolder(true)}>
            📁 新建文件夹
          </button>
          {selectedKeys.size > 0 && (
            <button className="btn btn-danger" onClick={handleBatchDelete}>
              🗑 批量删除 ({selectedKeys.size})
            </button>
          )}
        </div>
      </div>

      {uploadProgress && <div className="alert alert-info">{uploadProgress}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      {/* Storage stats */}
      {stats && (
        <div className="storage-stats">
          <span>📁 当前路径: {prefix || '/'}</span>
          <span>📊 文件数: {stats.totalFiles}</span>
          <span>💾 总大小: {stats.totalSizeMB} MB</span>
        </div>
      )}

      {/* Breadcrumb */}
      <div className="breadcrumb">
        <button className="breadcrumb-item" onClick={() => navigateToPath('')}>
          根目录
        </button>
        {segments.map((seg, i) => {
          const path = segments.slice(0, i + 1).join('/') + '/';
          return (
            <span key={i} className="breadcrumb-separator">
              <button className="breadcrumb-item" onClick={() => navigateToPath(path)}>
                {seg}
              </button>
            </span>
          );
        })}
      </div>

      {/* File table */}
      <div className="card">
        {loading ? (
          <div className="loading">加载中...</div>
        ) : items.length === 0 && folders.length === 0 ? (
          <div className="file-browser-empty">此目录为空</div>
        ) : (
          <table className="file-table">
            <thead>
              <tr>
                <th style={{ width: 40 }}>
                  <input
                    type="checkbox"
                    checked={selectedKeys.size > 0 && selectedKeys.size === folders.length + items.length}
                    onChange={handleSelectAll}
                  />
                </th>
                <th>名称</th>
                <th style={{ width: 80 }}>类型</th>
                <th style={{ width: 100 }}>大小</th>
                <th style={{ width: 180 }}>修改时间</th>
                <th style={{ width: 200 }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {/* Folders first */}
              {folders.map((folder) => (
                <tr key={folder.key}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selectedKeys.has(folder.key)}
                      onChange={() => handleSelect(folder.key)}
                    />
                  </td>
                  <td>
                    <button
                      className="file-name-btn"
                      onClick={() => navigateToPath(folder.key)}
                    >
                      📁 {folder.name}
                    </button>
                  </td>
                  <td><span className="file-type-tag">文件夹</span></td>
                  <td>—</td>
                  <td>—</td>
                  <td>
                    <button
                      className="btn btn-danger btn-sm"
                      onClick={() => handleDelete(folder.key, true)}
                    >
                      删除
                    </button>
                  </td>
                </tr>
              ))}
              {/* Files */}
              {items.map((file) => (
                <tr key={file.key}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selectedKeys.has(file.key)}
                      onChange={() => handleSelect(file.key)}
                    />
                  </td>
                  <td>
                    <button
                      className="file-name-btn"
                      onClick={() => setPreviewItem(file)}
                    >
                      {getFileIcon(file.name)} {file.name}
                    </button>
                  </td>
                  <td>
                    <span className="file-type-tag">
                      {file.contentType?.split('/')[0] || 'file'}
                    </span>
                  </td>
                  <td>{formatSize(file.size)}</td>
                  <td>{formatDate(file.lastModified)}</td>
                  <td>
                    <div className="file-actions">
                      <a
                        className="btn btn-ghost btn-sm"
                        href={fileApi.getAdminDownloadUrl(file.key)}
                        download
                      >
                        下载
                      </a>
                      <button
                        className="btn btn-danger btn-sm"
                        onClick={() => handleDelete(file.key, false)}
                      >
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {!loading && hasMore && (
          <div className="file-browser-footer" style={{ padding: '12px 16px', textAlign: 'center' }}>
            <span style={{ marginRight: 12 }}>
              已显示 {folders.length + items.length} 项（该目录对象较多，仅加载了一部分）
            </span>
            <button className="btn btn-secondary btn-sm" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? '加载中...' : '加载更多'}
            </button>
          </div>
        )}
      </div>

      {/* Create folder modal */}
      {showCreateFolder && (
        <div className="modal-overlay" onClick={() => setShowCreateFolder(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>新建文件夹</h3>
            <div className="form-group">
              <label className="form-label">文件夹名称</label>
              <input
                type="text"
                className="form-input"
                autoFocus
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCreateFolder()}
                placeholder="输入文件夹名称"
              />
            </div>
            <div className="modal-actions">
              <button className="btn btn-ghost" onClick={() => setShowCreateFolder(false)}>
                取消
              </button>
              <button className="btn btn-primary" onClick={handleCreateFolder}>
                创建
              </button>
            </div>
          </div>
        </div>
      )}

      {/* File preview modal */}
      {previewItem && (
        <div className="modal-overlay" onClick={() => setPreviewItem(null)}>
          <div className="modal modal-large" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{getFileIcon(previewItem.name)} {previewItem.name}</h3>
              <button className="modal-close" onClick={() => setPreviewItem(null)}>✕</button>
            </div>
            <div className="modal-body">
              <FilePreview file={previewItem} />
            </div>
            <div className="modal-actions">
              <a
                className="btn btn-primary"
                href={fileApi.getAdminDownloadUrl(previewItem.key)}
                download
              >
                ⬇ 下载
              </a>
              <button className="btn btn-ghost" onClick={() => setPreviewItem(null)}>
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// File preview component based on file type
function FilePreview({ file }: { file: FileItem }) {
  const ext = file.name.toLowerCase().split('.').pop();
  const url = fileApi.getAdminPreviewUrl(file.key);

  if (['mp4', 'webm', 'avi', 'mov', 'mkv'].includes(ext || '')) {
    return (
      <video controls className="file-preview-video">
        <source src={url} type={`video/${ext}`} />
        您的浏览器不支持视频播放。
      </video>
    );
  }

  if (['jpg', 'jpeg', 'png', 'gif', 'bmp'].includes(ext || '')) {
    return <img src={url} alt={file.name} className="file-preview-image" />;
  }

  if (['mp3', 'wav', 'ogg', 'flac', 'm4a'].includes(ext || '')) {
    return <audio controls className="file-preview-audio" src={url} />;
  }

  if (ext === 'json') {
    return (
      <pre className="file-preview-text">
        <FilePreviewFetcher url={url} />
      </pre>
    );
  }

  if (ext === 'txt' || ext === 'md' || ext === 'log') {
    return (
      <pre className="file-preview-text">
        <FilePreviewFetcher url={url} />
      </pre>
    );
  }

  return <div className="file-preview-unknown">不支持预览此文件类型</div>;
}

// Fetch and display text content for JSON/txt/md files
function FilePreviewFetcher({ url }: { url: string }) {
  const [content, setContent] = useState('');

  useEffect(() => {
    fetch(url)
      .then((resp) => resp.text())
      .then((text) => {
        try {
          const parsed = JSON.parse(text);
          setContent(JSON.stringify(parsed, null, 2));
        } catch {
          setContent(text);
        }
      })
      .catch(() => setContent('无法加载文件内容'));
  }, [url]);

  return <>{content || '加载中...'}</>;
}
