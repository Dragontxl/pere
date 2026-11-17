/**
 * Build script: reads ../frontend/dist/index.html and generates src/index-html.ts
 * This allows the Worker to serve index.html for SPA routes without needing
 * the ASSETS binding (which is not exposed in wrangler v3).
 */
const fs = require('fs');
const path = require('path');

const indexHtmlPath = path.join(__dirname, '..', 'frontend', 'dist', 'index.html');
const outputPath = path.join(__dirname, 'src', 'index-html.ts');

if (!fs.existsSync(indexHtmlPath)) {
  console.error('Error: frontend/dist/index.html not found. Build the frontend first.');
  process.exit(1);
}

const html = fs.readFileSync(indexHtmlPath, 'utf-8');

const tsContent = `// Auto-generated from ../frontend/dist/index.html — do not edit manually
export const INDEX_HTML = ${JSON.stringify(html)};
`;

fs.writeFileSync(outputPath, tsContent, 'utf-8');
console.log(`Generated ${outputPath} (${html.length} bytes)`);
