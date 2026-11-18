"""生成可选的背景音乐（BGM）音频文件。

用 ffmpeg 合成：柔和的 pad 和弦铺底 + 拨弦琶音，循环铺满视频时长。
不依赖任何外部音频素材，纯合成、确定性、免版权。

两阶段：
1. 生成琶音 pattern（几个带衰减的拨弦音，按间隔排布）-> 临时 WAV
2. 用 -stream_loop -1 循环 pattern，叠加 pad 和弦，加 echo/lowpass 润色 -> MP3
"""
import os
import subprocess
import sys

FFMPEG = "ffmpeg"
SR = 44100
DUR = 45  # 每段 BGM 时长（秒）

# 临时目录
TMP_DIR = os.path.join(os.path.dirname(__file__), "temp", "bgm_gen")
os.makedirs(TMP_DIR, exist_ok=True)
OUT_DIR = os.path.join(os.path.dirname(__file__), "assets", "bgm")
os.makedirs(OUT_DIR, exist_ok=True)


def run(cmd):
    """运行 ffmpeg，返回 CompletedProcess；出错时打印 stderr。"""
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("FAIL:", " ".join(cmd))
        print(r.stderr[-2000:])
        sys.exit(1)
    return r


def gen_pattern(name, notes, note_dur=1.2, gap_ms=1100):
    """生成琶音 pattern WAV。

    notes: [(freq, delay_ms), ...] 按顺序排列的拨弦音。
    返回 pattern.wav 路径。
    """
    pat_wav = os.path.join(TMP_DIR, f"{name}_pattern.wav")
    n = len(notes)
    # 构造输入（每个 lavfi 源拆成独立参数，不能带引号合并成一个字符串）
    input_defs = []
    for freq, _ in notes:
        input_defs.extend(["-f", "lavfi", "-i",
                          f"aevalsrc=0.24*exp(-3.2*t)*sin(2*PI*{freq}*t):s={SR}:d={note_dur}"])
    # filter：每个音 adelay 后 amix
    parts = []
    for i, (_, delay) in enumerate(notes):
        parts.append(f"[{i}:a]adelay={delay}|{delay}[p{i}]")
    mix = "".join(f"[p{i}]" for i in range(n)) + f"amix=inputs={n}:normalize=0[out]"
    filter_complex = ";".join(parts + [mix])
    cmd = [FFMPEG, "-y", *input_defs, "-filter_complex", filter_complex,
           "-map", "[out]", "-ac", "2", "-ar", str(SR), pat_wav]
    run(cmd)
    return pat_wav


def gen_bgm(name, bass_freq, bass_vol, pads, arp_notes, arp_vol=0.6):
    """生成一段 BGM。

    bass_freq: 低音频率
    bass_vol: 低音音量
    pads: [(freq, vol, trem_f, trem_d), ...] pad 和弦层
    arp_notes: [(freq, delay_ms), ...] 琶音
    arp_vol: 琶音音量
    """
    pat_wav = gen_pattern(name, arp_notes)
    out_mp3 = os.path.join(OUT_DIR, f"{name}.mp3")

    # 输入：循环 pattern + bass + 每个 pad（拆成独立参数）
    input_defs = ["-stream_loop", "-1", "-i", pat_wav]
    input_defs.extend(["-f", "lavfi", "-i", f"sine=frequency={bass_freq}:duration={DUR}"])
    pad_labels = []
    for i, (freq, vol, tf, td) in enumerate(pads):
        input_defs.extend(["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={DUR}"])
        pad_labels.append(i + 2)  # pattern=0, bass=1, pads start at 2

    # filter
    # arp: 截取到 DUR，调音量
    # bass: 音量
    # pads: 音量 + tremolo
    parts = [
        f"[0:a]atrim=0:{DUR},volume={arp_vol}[arp]",
        f"[1:a]volume={bass_vol}[bass]",
    ]
    pad_mix_labels = []
    for i, (freq, vol, tf, td) in enumerate(pads):
        li = pad_labels[i]
        chain = f"[{li}:a]volume={vol}"
        if tf:
            chain += f",tremolo=f={tf}:d={td}"
        parts.append(f"{chain}[pd{i}]")
        pad_mix_labels.append(f"[pd{i}]")

    # pad 混合（bass + pads）
    pad_mix_labels = ["[bass]"] + [f"[pd{i}]" for i in range(len(pads))]
    pad_mix = "".join(pad_mix_labels) + f"amix=inputs={len(pads) + 1}:normalize=0[padout]"
    parts.append(pad_mix)
    # 最终：pad + arp 混合，润色
    parts.append(
        "[padout][arp]amix=inputs=2:normalize=0,"
        "aecho=0.7:0.85:900:0.2,"
        "lowpass=f=5000,"
        "volume=1.3[out]"
    )
    filter_complex = ";".join(parts)

    cmd = [FFMPEG, "-y", *input_defs, "-filter_complex", filter_complex,
           "-map", "[out]", "-acodec", "libmp3lame", "-q:a", "4",
           "-ar", str(SR), "-ac", "2", out_mp3]
    run(cmd)
    # 清理临时 pattern
    os.remove(pat_wav)
    print(f"  [OK] {name}.mp3  ({os.path.getsize(out_mp3)} bytes)")
    return out_mp3


# ── 4 段 BGM 配置 ──────────────────────────────────────────────
# 频率参考（Hz）：C2=65.41 A2=110.00 G2=98.00 等

CONFIGS = [
    # 1. 自然氛围：C 大调，慢琶音，丰富 pad
    {
        "name": "ambient",
        "bass": (65.41, 0.32),
        "pads": [
            (130.81, 0.18, 0.12, 0.5),   # C3
            (164.81, 0.15, 0.16, 0.4),   # E3
            (196.00, 0.14, 0.20, 0.4),   # G3
        ],
        "arp": [(261.63, 0), (329.63, 1100), (392.00, 2200), (523.25, 3300)],
    },
    # 2. 轻柔钢琴：C 大调，快琶音，轻 pad
    {
        "name": "piano",
        "bass": (65.41, 0.28),
        "pads": [
            (130.81, 0.12, 0.12, 0.3),   # C3
            (196.00, 0.10, 0.18, 0.3),  # G3
        ],
        "arp": [(261.63, 0), (329.63, 700), (392.00, 1400), (523.25, 2100), (659.25, 2800)],
    },
    # 3. 轻松节拍：A 小调，深沉低音，中速琶音
    {
        "name": "chill",
        "bass": (55.00, 0.40),
        "pads": [
            (110.00, 0.16, 0.12, 0.4),  # A2
            (130.81, 0.13, 0.15, 0.35), # C3
            (164.81, 0.12, 0.18, 0.35), # E3
        ],
        "arp": [(220.00, 0), (261.63, 1000), (329.63, 2000), (440.00, 3000)],
    },
    # 4. 温馨吉他：G 大调，温暖和弦，中速琶音
    {
        "name": "warm",
        "bass": (98.00, 0.34),
        "pads": [
            (98.00, 0.16, 0.12, 0.4),   # G2
            (146.83, 0.14, 0.15, 0.35), # D3
            (196.00, 0.13, 0.18, 0.35), # G3
        ],
        "arp": [(196.00, 0), (246.94, 900), (293.66, 1800), (392.00, 2700)],
    },
]


def main():
    print(f"生成 {len(CONFIGS)} 段 BGM -> {OUT_DIR}")
    for cfg in CONFIGS:
        print(f"\n生成 {cfg['name']}...")
        gen_bgm(
            cfg["name"],
            cfg["bass"][0],
            cfg["bass"][1],
            cfg["pads"],
            cfg["arp"],
        )
    print("\n全部完成。")


if __name__ == "__main__":
    main()
