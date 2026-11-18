// Task types matching the backend
export type TaskPhase =
  | 'ARTICLE_PARSE'
  | 'SCENE_GEN'
  | 'IMAGE_DOWNLOAD'
  | 'ASSET_MATCH'
  | 'RENDER_DECISION'
  | 'TTS_SYNTH'
  | 'VIDEO_COMPOSE';

export type TaskStatus =
  | 'PENDING'
  | 'ARTICLE_PARSE_PENDING'
  | 'ARTICLE_PARSE_ING'
  | 'ARTICLE_PARSE_DONE'
  | 'SCENE_GEN_PENDING'
  | 'SCENE_GEN_ING'
  | 'SCENE_GEN_DONE'
  | 'IMAGE_DOWNLOAD_PENDING'
  | 'IMAGE_DOWNLOAD_ING'
  | 'IMAGE_DOWNLOAD_DONE'
  | 'ASSET_MATCH_PENDING'
  | 'ASSET_MATCH_ING'
  | 'ASSET_MATCH_DONE'
  | 'RENDER_DECISION_PENDING'
  | 'RENDER_DECISION_ING'
  | 'RENDER_DECISION_DONE'
  | 'TTS_SYNTH_PENDING'
  | 'TTS_SYNTH_ING'
  | 'TTS_SYNTH_DONE'
  | 'VIDEO_COMPOSE_PENDING'
  | 'VIDEO_COMPOSE_ING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED';

export type ArticleSource = 'ai_generated' | 'pasted' | 'uploaded';

export interface Task {
  id: string;
  user_id: string;
  title: string;
  article_source: string;
  article_content: string | null;
  article_file_key: string | null;
  orientation: string;
  language: string;
  enable_subtitle: boolean;
  bgm_key: string | null;
  bgm_name: string | null;
  status: string;
  current_phase: string | null;
  scenes_key: string | null;
  match_results_key: string | null;
  final_video_key: string | null;
  final_video_url: string | null;
  progress: number;
  retry_count: number;
  max_retries: number;
  error_msg: string | null;
  status_message: string | null;
  processed_frames: number;
  total_frames: number;
  failed_frames: number;
  start_phase: string | null;
  end_phase: string | null;
  phase_details: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  expires_at: string | null;
}

export interface TaskLog {
  id: number;
  task_id: string;
  phase: string;
  level: string;
  message: string;
  metadata: string | null;
  created_at: string;
}

export interface LoginResponse {
  token: string;
  userId: number;
  username: string;
  role: string;
}

export interface ApiResponse<T> {
  code: number;
  data: T;
  msg: string;
}

// 背景音乐选项
export interface BgmOption {
  key: string;
  name: string;
  description?: string;
}

// Phase display names
export const phaseLabels: Record<TaskPhase, string> = {
  ARTICLE_PARSE: '文章解析',
  SCENE_GEN: '分镜生成',
  IMAGE_DOWNLOAD: '素材下载',
  ASSET_MATCH: '素材匹配',
  RENDER_DECISION: '渲染决策',
  TTS_SYNTH: '语音合成',
  VIDEO_COMPOSE: '视频合成',
};

export const phaseOrder: TaskPhase[] = [
  'ARTICLE_PARSE',
  'SCENE_GEN',
  'IMAGE_DOWNLOAD',
  'ASSET_MATCH',
  'RENDER_DECISION',
  'TTS_SYNTH',
  'VIDEO_COMPOSE',
];

// Status labels
export const statusLabels: Record<string, string> = {
  PENDING: '等待中',
  ARTICLE_PARSE_PENDING: '等待解析',
  ARTICLE_PARSE_ING: '解析文章中',
  ARTICLE_PARSE_DONE: '解析完成',
  SCENE_GEN_PENDING: '等待分镜',
  SCENE_GEN_ING: '生成分镜中',
  SCENE_GEN_DONE: '分镜完成',
  IMAGE_DOWNLOAD_PENDING: '等待下载',
  IMAGE_DOWNLOAD_ING: '下载素材中',
  IMAGE_DOWNLOAD_DONE: '下载完成',
  ASSET_MATCH_PENDING: '等待匹配',
  ASSET_MATCH_ING: '匹配素材中',
  ASSET_MATCH_DONE: '匹配完成',
  RENDER_DECISION_PENDING: '等待决策',
  RENDER_DECISION_ING: '渲染决策中',
  RENDER_DECISION_DONE: '决策完成',
  TTS_SYNTH_PENDING: '等待合成',
  TTS_SYNTH_ING: '语音合成中',
  TTS_SYNTH_DONE: '语音完成',
  VIDEO_COMPOSE_PENDING: '等待合成',
  VIDEO_COMPOSE_ING: '视频合成中',
  COMPLETED: '已完成',
  FAILED: '失败',
  CANCELLED: '已取消',
};

// 阶段素材检查结果
export interface PhaseMaterialCheck {
  ready: boolean;
  missing: string[];
  available: string[];
}

// R2 文件管理类型
export interface FileItem {
  key: string;
  name: string;
  type: 'file' | 'directory';
  size: number;
  lastModified: string | null;
  contentType?: string;
}

export interface FileListResult {
  files: FileItem[];
  folders: FileItem[];
  truncated: boolean;
  cursor: string | null;
  prefix: string;
}

export interface FileStats {
  totalSize: number;
  totalFiles: number;
  totalSizeMB: string;
  prefix: string;
}
