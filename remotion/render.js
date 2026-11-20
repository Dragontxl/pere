/**
 * Remotion 渲染脚本
 *
 * 根据镜头参数渲染编码视频片段。
 * 由 Python 主流程通过 subprocess 调用。
 *
 * 用法:
 *   node render.js --scene data_visual --props props.json --output output.mp4
 *
 * props.json 格式:
 *   {
 *     "description": "画面描述",
 *     "text": "显示文本",
 *     "duration": 5,
 *     "width": 1920,
 *     "height": 1080,
 *     "fps": 24
 *   }
 */

const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// 解析命令行参数
function parseArgs() {
    const args = {};
    const argv = process.argv.slice(2);
    for (let i = 0; i < argv.length; i++) {
        if (argv[i] === '--scene') args.scene = argv[++i];
        else if (argv[i] === '--props') args.props = argv[++i];
        else if (argv[i] === '--output') args.output = argv[++i];
    }
    return args;
}

// 映射场景类型到 composition ID（入口统一使用 Root.js，ID 仅含 a-z/0-9/-）
// 前三项为视觉类型（Python 端 visual_type），后三项为风格变体（可直接传 composition ID）
const SCENE_IDS = {
    'data_visual': 'data-visual',
    'text_animation': 'text-animation',
    'diagram': 'diagram',
    // 风格变体：main.py 渲染决策可直接传这些 composition ID
    'data-visual': 'data-visual',
    'text-animation': 'text-animation',
    'diagram': 'diagram',
    'tech': 'tech',
    'news': 'news',
    'magazine': 'magazine',
};

// 查找系统 Chrome 路径，避免 Remotion 自动下载 Headless Shell（网络受限时会失败）
function findChrome() {
    const candidates = [
        process.env.CHROME_PATH,
        'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
        'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
        '/usr/bin/google-chrome',
        '/usr/bin/chromium',
        '/usr/bin/chromium-browser',
    ];
    for (const p of candidates) {
        if (p && require('fs').existsSync(p)) {
            return p;
        }
    }
    return null;
}

function main() {
    const args = parseArgs();

    if (!args.scene || !args.props || !args.output) {
        console.error('用法: node render.js --scene <type> --props <props.json> --output <output.mp4>');
        process.exit(1);
    }

    const sceneId = SCENE_IDS[args.scene];
    if (!sceneId) {
        console.error(`❌ 不支持的场景类型: ${args.scene}`);
        process.exit(1);
    }

    const props = JSON.parse(fs.readFileSync(args.props, 'utf-8'));
    const durationInFrames = Math.round(props.duration * props.fps);

    // 构建 Remotion 渲染命令（入口统一使用 Root.js，通过 --id 选择场景）
    const chromePath = findChrome();
    if (chromePath) {
        console.log(`   浏览器: ${chromePath}`);
    } else {
        console.log('   浏览器: 将由 Remotion 自动管理');
    }

    // Remotion CLI 语法: remotion render [entry-point] [composition-id] [out-name] [options]
    // 入口文件为 Root.js，composition ID 为第二个位置参数
    // --props 使用分离参数（而非内联 --props=value），避免含盘符的绝对路径解析错误
    const renderArgs = [
        'remotion',
        'render',
        'Root.js',
        sceneId,
        args.output,
        '--props', args.props,
        '--width=' + props.width,
        '--height=' + props.height,
        '--fps=' + props.fps,
        '--codec=h264',
        '--pixel-format=yuv420p',
    ];

    // 使用系统 Chrome，避免 Remotion 下载 Headless Shell 失败
    // Windows 上 Chrome 路径含空格，shell 执行时需要加引号
    if (chromePath) {
        const quote = (process.platform === 'win32' && chromePath.includes(' ')) ? '"' : '';
        renderArgs.push(`--browser-executable=${quote}${chromePath}${quote}`);
    }

    console.log(`🎬 渲染 Remotion 场景: ${args.scene}`);
    console.log(`   输出: ${args.output}`);
    console.log(`   时长: ${props.duration}s (${durationInFrames} 帧)`);

    const result = spawnSync('npx', renderArgs, {
        cwd: __dirname,
        stdio: 'inherit',
        // Windows 上 npx 是 .cmd 文件，必须通过 shell 执行；
        // Linux/macOS 上 npx 是可执行文件，直接 spawn 即可
        shell: process.platform === 'win32'
    });

    if (result.status !== 0) {
        console.error(`❌ 渲染失败 (exit code: ${result.status})`);
        process.exit(result.status || 1);
    }

    console.log(`✅ 渲染完成: ${args.output}`);
}

main();
