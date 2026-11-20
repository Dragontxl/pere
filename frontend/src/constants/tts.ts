// TTS 音色选项
//
// 音色名称采用 edge-tts 命名（TTS 服务侧兼容），值直接透传给后端 →
// GitHub Actions → main.py --tts-voice。留空表示按文章语言自动选择默认音色。

export interface TtsVoiceOption {
  value: string;
  label: string;
}

export const ZH_TTS_VOICES: TtsVoiceOption[] = [
  { value: 'zh-CN-YunjianNeural', label: '云健 · 男声，浑厚有力（默认）' },
  { value: 'zh-CN-YunyangNeural', label: '云扬 · 男声，新闻播音' },
  { value: 'zh-CN-YunxiNeural', label: '云希 · 男声，阳光年轻' },
  { value: 'zh-CN-YunxiaNeural', label: '云夏 · 男声，少年感' },
  { value: 'zh-CN-XiaoxiaoNeural', label: '晓晓 · 女声，温暖自然' },
  { value: 'zh-CN-XiaoyiNeural', label: '晓伊 · 女声，活泼' },
  { value: 'zh-CN-liaoning-XiaobeiNeural', label: '晓北 · 女声，东北口音' },
  { value: 'zh-CN-shaanxi-XiaoniNeural', label: '晓妮 · 女声，陕西口音' },
];

export const EN_TTS_VOICES: TtsVoiceOption[] = [
  { value: 'en-US-EricNeural', label: 'Eric · Male, default' },
  { value: 'en-US-GuyNeural', label: 'Guy · Male, news' },
  { value: 'en-US-AriaNeural', label: 'Aria · Female, warm' },
  { value: 'en-US-JennyNeural', label: 'Jenny · Female, friendly' },
  { value: 'en-GB-RyanNeural', label: 'Ryan · Male, British' },
  { value: 'en-GB-SoniaNeural', label: 'Sonia · Female, British' },
];

/** 默认音色（按语言） */
export function defaultVoice(language: string): string {
  return language === 'en' ? 'en-US-EricNeural' : 'zh-CN-YunjianNeural';
}

/** 音色代码 → 可读名称；未知代码原样返回 */
export function voiceLabel(voice: string | null | undefined, language = 'zh'): string {
  if (!voice) return `跟随语言（${language === 'en' ? '英文' : '中文'}默认）`;
  const all = [...ZH_TTS_VOICES, ...EN_TTS_VOICES];
  return all.find((v) => v.value === voice)?.label || voice;
}

/** 语速候选值 */
export const TTS_SPEED_OPTIONS: { value: number; label: string }[] = [
  { value: 0.8, label: '0.8x（较慢）' },
  { value: 0.9, label: '0.9x' },
  { value: 1.0, label: '1.0x（默认）' },
  { value: 1.1, label: '1.1x' },
  { value: 1.2, label: '1.2x' },
  { value: 1.3, label: '1.3x' },
  { value: 1.5, label: '1.5x（较快）' },
];