interface ProgressBarProps {
  currentPhase: string | null;
  progress: number;
  processedFrames?: number;
  totalFrames?: number;
  failedFrames?: number;
  phaseDetails?: string | null;
}

const phases = [
  { key: 'ARTICLE_PARSE', label: '文章解析' },
  { key: 'SCENE_GEN', label: '分镜生成' },
  { key: 'IMAGE_DOWNLOAD', label: '素材下载' },
  { key: 'ASSET_MATCH', label: '素材匹配' },
  { key: 'RENDER_DECISION', label: '渲染决策' },
  { key: 'TTS_SYNTH', label: '语音合成' },
  { key: 'VIDEO_COMPOSE', label: '视频合成' },
];

type ComposeSubPhase = 'RENDER' | 'ASSEMBLY';

interface SubPhaseDetail {
  processed?: number;
  total?: number;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
}

interface PhaseDetail {
  processed: number;
  total: number;
  failed: number;
  updated_at: string;
  started_at?: string | null;
  sub_phase?: ComposeSubPhase;
  sub_phase_started_at?: string | null;
  render?: SubPhaseDetail;
  assembly?: SubPhaseDetail;
}

interface Step {
  key: string;
  label: string;
  phase: string;
  subPhase?: ComposeSubPhase;
}

// 拼接阶段没有逐片段计数器（只做下载 + 合并），用 2 分钟作为进度条的时间基准，
// 与后端 VIDEO_COMPOSE_SUB_PHASE_STATIC_ESTIMATES.ASSEMBLY 保持一致。
const ASSEMBLY_ESTIMATE_MS = 120_000;

function parsePhaseDetails(phaseDetails: string | null | undefined): Record<string, PhaseDetail> {
  if (!phaseDetails) return {};
  try {
    return JSON.parse(phaseDetails);
  } catch {
    return {};
  }
}

export default function ProgressBar({
  currentPhase,
  progress,
  processedFrames = 0,
  totalFrames = 0,
  failedFrames = 0,
  phaseDetails,
}: ProgressBarProps) {
  const currentPhaseIndex = phases.findIndex((p) => p.key === currentPhase);
  const isCompleted = progress >= 100;
  const details = parsePhaseDetails(phaseDetails);

  // 视频合成分为「渲染片段」（4 个 runner 并行，慢）和「拼接成片」（快）两步。
  // 后端在 phase_details.VIDEO_COMPOSE 中记录 sub_phase，据此把该阶段展开为两格。
  // 老任务没有 sub_phase（升级前已进入合成），仍按单个「视频合成」展示。
  const compose = details['VIDEO_COMPOSE'];
  const activeSubPhase: ComposeSubPhase | null =
    compose?.sub_phase === 'RENDER' || compose?.sub_phase === 'ASSEMBLY'
      ? compose.sub_phase
      : null;

  const steps: Step[] = [];
  for (const phase of phases) {
    if (phase.key === 'VIDEO_COMPOSE' && activeSubPhase) {
      steps.push({
        key: 'VIDEO_COMPOSE:RENDER',
        label: '视频渲染',
        phase: 'VIDEO_COMPOSE',
        subPhase: 'RENDER',
      });
      steps.push({
        key: 'VIDEO_COMPOSE:ASSEMBLY',
        label: '视频拼接',
        phase: 'VIDEO_COMPOSE',
        subPhase: 'ASSEMBLY',
      });
    } else {
      steps.push({ key: phase.key, label: phase.label, phase: phase.key });
    }
  }

  return (
    <div className="progress-container">
      {/* Overall progress */}
      <div className="progress-overall">
        <div className="progress-label">
          <span>总体进度</span>
          <span className="progress-value">{progress}%</span>
        </div>
        <div className="progress-bar-track">
          <div
            className="progress-bar-fill"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Frame counters */}
      {(totalFrames > 0 || processedFrames > 0 || failedFrames > 0) && (
        <div className="frame-counters">
          <div className="frame-counter">
            <span className="frame-counter-label">已完成片段</span>
            <span className="frame-counter-value">{processedFrames}</span>
          </div>
          <div className="frame-counter">
            <span className="frame-counter-label">总片段</span>
            <span className="frame-counter-value">{totalFrames}</span>
          </div>
          {failedFrames > 0 && (
            <div className="frame-counter failed">
              <span className="frame-counter-label">失败</span>
              <span className="frame-counter-value">{failedFrames}</span>
            </div>
          )}
        </div>
      )}

      {/* Phase steps with per-phase progress */}
      <div className="phase-steps">
        {steps.map((step, index) => {
          const phaseIndex = phases.findIndex((p) => p.key === step.phase);
          const isCurrentPhase = step.phase === currentPhase;
          const detail = details[step.phase];

          const phaseDone =
            isCompleted || (phaseIndex >= 0 && phaseIndex < currentPhaseIndex);

          let isDone = phaseDone;
          let processed = 0;
          let total = 0;
          let failed = 0;

          if (step.subPhase === 'RENDER') {
            const render = compose?.render;
            // 进入拼接说明渲染一定已结束（后端在该时点锁定 render 时长）
            isDone =
              phaseDone ||
              !!render?.completed_at ||
              !!render?.duration_ms ||
              activeSubPhase === 'ASSEMBLY';
            processed = render?.processed ?? detail?.processed ?? 0;
            total = render?.total ?? detail?.total ?? 0;
            failed = detail?.failed ?? 0;
          } else if (step.subPhase === 'ASSEMBLY') {
            const assembly = compose?.assembly;
            isDone = isCompleted || !!assembly?.completed_at || !!assembly?.duration_ms;
            processed = assembly?.processed ?? 0;
            total = assembly?.total ?? 0;
          } else {
            processed = detail?.processed ?? 0;
            total = detail?.total ?? 0;
            failed = detail?.failed ?? 0;
          }

          const isCurrent = isCurrentPhase && !isDone;
          const isPending = !isDone && !isCurrent;

          // Compute per-step progress percentage
          let phaseProgress = 0;
          if (isDone) {
            phaseProgress = 100;
          } else if (isCurrent) {
            if (step.subPhase === 'ASSEMBLY') {
              // 拼接无计数器：按已用时间对 2 分钟基准做保守估计，最多到 90%
              const startedAt = compose?.assembly?.started_at || compose?.sub_phase_started_at;
              const elapsed = startedAt
                ? Date.now() - new Date(startedAt).getTime()
                : 0;
              phaseProgress = Math.max(
                5,
                Math.min(90, Math.round((elapsed / ASSEMBLY_ESTIMATE_MS) * 100)),
              );
            } else if (total > 0) {
              phaseProgress = Math.round((processed / total) * 100);
            }
          }

          return (
            <div
              key={step.key}
              className={`phase-step ${isCurrent ? 'current' : ''} ${isDone ? 'done' : ''} ${isPending ? 'pending' : ''} ${step.subPhase ? 'sub-step' : ''}`}
            >
              <div className="phase-indicator">
                {isDone ? '✓' : isCurrent ? '●' : index + 1}
              </div>
              <div className="phase-info">
                <div className="phase-name">{step.label}</div>
                {(isCurrent || isDone) && total > 0 && (
                  <div className="phase-progress-text">
                    {processed}/{total}
                    {failed > 0 && <span className="phase-failed">（失败 {failed}）</span>}
                  </div>
                )}
                {isCurrent && (
                  <div className="phase-status">
                    {step.subPhase === 'RENDER'
                      ? '渲染中'
                      : step.subPhase === 'ASSEMBLY'
                        ? '拼接中'
                        : '进行中'}
                  </div>
                )}
                {isDone && <div className="phase-status">已完成</div>}
                {isPending && <div className="phase-status">等待中</div>}
              </div>
              {isCurrent && (
                <div className="phase-progress-bar-track">
                  <div
                    className="phase-progress-bar-fill"
                    style={{ width: `${phaseProgress}%` }}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}