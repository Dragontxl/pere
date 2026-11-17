interface ProgressBarProps {
  currentPhase: string | null;
  progress: number;
}

const phases = [
  { key: 'SCENE_GEN', label: '分镜生成' },
  { key: 'ASSET_MATCH', label: '素材匹配' },
  { key: 'REMOTION_RENDER', label: 'Remotion 渲染' },
  { key: 'TTS_COMPOSE', label: '语音合成' },
];

export default function ProgressBar({ currentPhase, progress }: ProgressBarProps) {
  const currentPhaseIndex = phases.findIndex((p) => p.key === currentPhase);
  const isCompleted = currentPhaseIndex >= 0 && progress >= 100;

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

      {/* Phase steps */}
      <div className="phase-steps">
        {phases.map((phase, index) => {
          const isCurrent = index === currentPhaseIndex;
          const isDone = index < currentPhaseIndex || isCompleted;
          const isPending = index > currentPhaseIndex;

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
            </div>
          );
        })}
      </div>
    </div>
  );
}
