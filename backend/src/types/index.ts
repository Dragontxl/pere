// Task phases for the article-to-video generation pipeline
export type TaskPhase = 'SCENE_GEN' | 'ASSET_MATCH' | 'REMOTION_RENDER' | 'TTS_COMPOSE';

// Task status
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

// Article source types
export type ArticleSource = 'ai_generated' | 'pasted' | 'uploaded';

// Task interface
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

// Phase order
export const phaseOrder: TaskPhase[] = ['SCENE_GEN', 'ASSET_MATCH', 'REMOTION_RENDER', 'TTS_COMPOSE'];

// Phase status mapping
export const phaseStatusMap: Record<TaskPhase, { running: TaskStatus; done: TaskStatus }> = {
  SCENE_GEN: { running: 'SCENE_GEN_ING', done: 'SCENE_GEN_DONE' },
  ASSET_MATCH: { running: 'ASSET_MATCH_ING', done: 'ASSET_MATCH_DONE' },
  REMOTION_RENDER: { running: 'REMOTION_RENDER_ING', done: 'REMOTION_RENDER_DONE' },
  TTS_COMPOSE: { running: 'TTS_COMPOSE_ING', done: 'COMPLETED' },
};

// Phase progress weights
export const phaseProgressWeights: Record<TaskPhase, number> = {
  SCENE_GEN: 0,
  ASSET_MATCH: 1,
  REMOTION_RENDER: 2,
  TTS_COMPOSE: 3,
};
