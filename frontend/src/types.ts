// Task types matching the backend
export type TaskPhase = 'SCENE_GEN' | 'ASSET_MATCH' | 'REMOTION_RENDER' | 'TTS_COMPOSE';

export type TaskStatus =
  | 'PENDING'
  | 'SCENE_GEN_PENDING'
  | 'SCENE_GEN_ING'
  | 'SCENE_GEN_DONE'
  | 'ASSET_MATCH_PENDING'
  | 'ASSET_MATCH_ING'
  | 'ASSET_MATCH_DONE'
  | 'REMOTION_RENDER_PENDING'
  | 'REMOTION_RENDER_ING'
  | 'REMOTION_RENDER_DONE'
  | 'TTS_COMPOSE_PENDING'
  | 'TTS_COMPOSE_ING'
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
  SCENE_GEN: '分镜生成',
  ASSET_MATCH: '素材匹配',
  REMOTION_RENDER: 'Remotion 渲染',
  TTS_COMPOSE: '语音合成',
};

export const phaseOrder: TaskPhase[] = ['SCENE_GEN', 'ASSET_MATCH', 'REMOTION_RENDER', 'TTS_COMPOSE'];

// Status labels
export const statusLabels: Record<string, string> = {
  PENDING: '等待中',
  SCENE_GEN_PENDING: '等待分镜',
  SCENE_GEN_ING: '生成分镜中',
  SCENE_GEN_DONE: '分镜完成',
  ASSET_MATCH_PENDING: '等待匹配',
  ASSET_MATCH_ING: '匹配素材中',
  ASSET_MATCH_DONE: '匹配完成',
  REMOTION_RENDER_PENDING: '等待渲染',
  REMOTION_RENDER_ING: '渲染中',
  REMOTION_RENDER_DONE: '渲染完成',
  TTS_COMPOSE_PENDING: '等待合成',
  TTS_COMPOSE_ING: '合成中',
  COMPLETED: '已完成',
  FAILED: '失败',
  CANCELLED: '已取消',
};
