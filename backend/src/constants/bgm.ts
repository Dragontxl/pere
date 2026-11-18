// 可选背景音乐（BGM）目录 —— 单一数据源。
// key 是 assets/bgm/ 下的文件名，workflow 通过 actions/checkout 拿到该文件后
// 传给 main.py 的 --bgm 参数。新增 BGM：把 mp3 放进 assets/bgm/，在这里加一项。

export interface BgmOption {
  key: string;       // assets/bgm/ 下的文件名，如 "ambient.mp3"
  name: string;      // 前端下拉显示的名称
  description?: string;
}

export const BGM_OPTIONS: BgmOption[] = [
  { key: 'ambient.mp3', name: '自然氛围', description: '舒缓的环境铺底，适合科普/叙事' },
  { key: 'piano.mp3', name: '轻柔钢琴', description: '清亮的钢琴琶音，适合人文/生活' },
  { key: 'chill.mp3', name: '轻松节拍', description: '低沉舒缓的节拍，适合科技/资讯' },
  { key: 'warm.mp3', name: '温馨吉他', description: '温暖的吉他和弦，适合情感/故事' },
];

/** 根据 key 查找 BGM 名称。
 * - 预设 BGM（assets/bgm/ 下的文件名）返回目录中的名称。
 * - 自定义上传的 BGM（key 以 `bgm/` 开头）返回「自定义：filename」。
 * - 找不到返回 null（无 BGM）。
 */
export function findBgmName(key: string | null | undefined): string | null {
  if (!key) return null;
  const opt = BGM_OPTIONS.find((o) => o.key === key);
  if (opt) return opt.name;
  // 自定义上传：key 形如 "bgm/<uuid>-song.mp3"
  if (key.startsWith('bgm/')) {
    const filename = key.split('/').pop() || key;
    return `自定义：${filename}`;
  }
  return null;
}
