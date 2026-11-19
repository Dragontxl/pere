// Task phases for the article-to-video generation pipeline
export type TaskPhase =
  | 'ARTICLE_PARSE'
  | 'SCENE_GEN'
  | 'IMAGE_DOWNLOAD'
  | 'ASSET_MATCH'
  | 'RENDER_DECISION'
  | 'TTS_SYNTH'
  | 'VIDEO_COMPOSE';

// Task status
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
  cover_image_key: string | null;
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

// Phase order
export const phaseOrder: TaskPhase[] = [
  'ARTICLE_PARSE',
  'SCENE_GEN',
  'IMAGE_DOWNLOAD',
  'ASSET_MATCH',
  'RENDER_DECISION',
  'TTS_SYNTH',
  'VIDEO_COMPOSE',
];

// Phase status mapping
export const phaseStatusMap: Record<TaskPhase, { running: TaskStatus; done: TaskStatus }> = {
  ARTICLE_PARSE: { running: 'ARTICLE_PARSE_ING', done: 'ARTICLE_PARSE_DONE' },
  SCENE_GEN: { running: 'SCENE_GEN_ING', done: 'SCENE_GEN_DONE' },
  IMAGE_DOWNLOAD: { running: 'IMAGE_DOWNLOAD_ING', done: 'IMAGE_DOWNLOAD_DONE' },
  ASSET_MATCH: { running: 'ASSET_MATCH_ING', done: 'ASSET_MATCH_DONE' },
  RENDER_DECISION: { running: 'RENDER_DECISION_ING', done: 'RENDER_DECISION_DONE' },
  TTS_SYNTH: { running: 'TTS_SYNTH_ING', done: 'TTS_SYNTH_DONE' },
  VIDEO_COMPOSE: { running: 'VIDEO_COMPOSE_ING', done: 'COMPLETED' },
};

// Phase progress weights
export const phaseProgressWeights: Record<TaskPhase, number> = {
  ARTICLE_PARSE: 0,
  SCENE_GEN: 1,
  IMAGE_DOWNLOAD: 2,
  ASSET_MATCH: 3,
  RENDER_DECISION: 4,
  TTS_SYNTH: 5,
  VIDEO_COMPOSE: 6,
};
