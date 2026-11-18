interface ProgressBarProps {
  currentPhase: string | null;
  progress: number;
  processedFrames?: number;
  totalFrames?: number;
  failedFrames?: number;
  phaseDetails?: string | null;
}

const phases = [
  { key: 'SCENE_GEN', label: '分镜生成' },
  { key: 'ASSET_MATCH', label: '素材匹配' },
  { key: 'REMOTION_RENDER', label: 'Remotion 渲染' },
  { key: 'TTS_COMPOSE', label: '语音合成' },
];

interface PhaseDetail {
  processed: number;
  total: number;
  failed: number;
  updated_at: string;
}

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
  const isCompleted = currentPhaseIndex >= 0 && progress >= 100;
  const details = parsePhaseDetails(phaseDetails);

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
        {phases.map((phase, index) => {
          const isCurrent = index === currentPhaseIndex;
          const isDone = index < currentPhaseIndex || isCompleted;
          const isPending = index > currentPhaseIndex;
          const detail = details[phase.key];

          // Compute per-phase progress percentage
          let phaseProgress = 0;
          if (isDone) {
            phaseProgress = 100;
          } else if (isCurrent && detail && detail.total > 0) {
            phaseProgress = Math.round((detail.processed / detail.total) * 100);
          } else if (isCurrent) {
            phaseProgress = 0;
          }

          return (
            <div
              key={phase.key}
              className={`phase-step ${isCurrent ? 'current' : ''} ${isDone ? 'done' : ''} ${isPending ? 'pending' : ''}`}
            >
              <div className="phase-indicator">
                {isDone ? '✓' : isCurrent ? '●' : index + 1}
              </div>
              <div className="phase-info">
                <div className="phase-name">{phase.label}</div>
                {(isCurrent || isDone) && detail && detail.total > 0 && (
                  <div className="phase-progress-text">
                    {detail.processed}/{detail.total}
                    {detail.failed > 0 && <span className="phase-failed">（失败 {detail.failed}）</span>}
                  </div>
                )}
                {isCurrent && !isCompleted && (
                  <div className="phase-status">进行中</div>
                )}
                {isDone && (
                  <div className="phase-status">已完成</div>
                )}
                {isPending && (
                  <div className="phase-status">等待中</div>
                )}
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
