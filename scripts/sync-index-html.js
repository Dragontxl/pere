/**
 * 构建后同步脚本：将 frontend/dist/index.html 的内容写入 backend/src/index-html.ts
 *
 * 这样每次前端重新构建后，Worker 内嵌的 HTML 自动更新，
 * 避免资源哈希变化导致 SPA 路由回退时引用过期的 JS/CSS 文件。
 */
const fs = require('fs');
const path = require('path');

const distHtmlPath = path.join(__dirname, '..', 'frontend', 'dist', 'index.html');
const targetPath = path.join(__dirname, '..', 'backend', 'src', 'index-html.ts');

if (!fs.existsSync(distHtmlPath)) {
    console.error('[sync-index-html] frontend/dist/index.html not found. Run frontend build first.');
    process.exit(0);
}

const html = fs.readFileSync(distHtmlPath, 'utf-8');
const content = `// Auto-generated from ../frontend/dist/index.html — do not edit manually\nexport const INDEX_HTML = ${JSON.stringify(html)};\n`;

fs.writeFileSync(targetPath, content, 'utf-8');
console.log('[sync-index-html] backend/src/index-html.ts updated');
