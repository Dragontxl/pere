-- pexel-remotion platform database schema
-- D1 SQLite database for Cloudflare Workers

-- User table (reused from videomodifyauto)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email TEXT,
    role TEXT DEFAULT 'USER',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP,
    api_key TEXT UNIQUE
);

-- Default admin user (password: admin123)
-- salt: defaultSaltForAdmin123456
-- hash: SHA-256(admin123 + salt)
INSERT OR IGNORE INTO users (username, password_hash, role) VALUES
    ('admin', 'defaultSaltForAdmin123456:88513b6b347747a1fa8b3fcbf7335a3f64b9e43ebb301aa91be8d06b5cf15cd6', 'ADMIN');

-- Tasks table (adapted for article-to-video generation)
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT,
    article_source TEXT NOT NULL,
    article_content TEXT,
    article_file_key TEXT,
    orientation TEXT DEFAULT 'landscape',
    language TEXT DEFAULT 'zh',
    enable_subtitle BOOLEAN DEFAULT TRUE,
    bgm_key TEXT,
    bgm_name TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    current_phase TEXT,
    scenes_key TEXT,
    match_results_key TEXT,
    final_video_key TEXT,
    final_video_url TEXT,
    cover_image_key TEXT,
    bilibili_upload BOOLEAN DEFAULT FALSE,
    bilibili_status TEXT,
    bilibili_bvid TEXT,
    bilibili_url TEXT,
    progress INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    error_msg TEXT,
    status_message TEXT,
    processed_frames INTEGER DEFAULT 0,
    total_frames INTEGER DEFAULT 0,
    failed_frames INTEGER DEFAULT 0,
    start_phase TEXT,
    end_phase TEXT,
    phase_details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    expires_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id);

-- Bilibili credentials table: stores each user's B站 cookies (encrypted)
CREATE TABLE IF NOT EXISTS bilibili_credentials (
    user_id TEXT PRIMARY KEY,
    cookies_encrypted TEXT NOT NULL,
    has_sessdata BOOLEAN DEFAULT FALSE,
    has_bili_jct BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Operation logs table (reused)
CREATE TABLE IF NOT EXISTS operation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    phase TEXT,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_logs_task_id ON operation_logs(task_id);
CREATE INDEX IF NOT EXISTS idx_logs_created_at ON operation_logs(created_at);

-- System config table (reused)
CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT
);

INSERT OR IGNORE INTO system_config (key, value, description) VALUES
    ('max_concurrent_tasks', '3', '最大并发任务数'),
    ('callback_timeout', '300', '回调超时时间（秒）'),
    ('github_api_timeout', '30', 'GitHub API超时时间（秒）'),
    ('max_retry_count', '3', '最大重试次数'),
    ('task_expire_days', '7', '任务过期天数');

-- File upload tracking for chunked uploads (reused)
CREATE TABLE IF NOT EXISTS uploads (
    upload_id TEXT PRIMARY KEY,
    key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'uploading',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_uploads_status ON uploads(status);

CREATE TABLE IF NOT EXISTS upload_parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id TEXT NOT NULL,
    part_number INTEGER NOT NULL,
    etag TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (upload_id) REFERENCES uploads(upload_id)
);

CREATE INDEX IF NOT EXISTS idx_upload_parts_upload ON upload_parts(upload_id);
