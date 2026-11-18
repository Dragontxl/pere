import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { prettyJSON } from 'hono/pretty-json';
import { taskRoutes } from './routes/public/tasks';
import { callbackRoutes } from './routes/public/callback';
import { authRoutes } from './routes/public/auth';
import { publicFileRoutes } from './routes/public/files';
import { bgmRoutes } from './routes/public/bgm';
import { adminRoutes } from './routes/admin';
import { authMiddleware } from './middleware/auth';
import { loggerMiddleware } from './middleware/logger';
import { errorHandler } from './middleware/error';
import { scheduled } from './scheduled';
import { Bindings } from './types/env';
import { INDEX_HTML } from './index-html';

const app = new Hono<{ Bindings: Bindings }>();

// CORS configuration
app.use('*', cors({
  origin: (origin, c) => {
    const frontendUrl = c.env.FRONTEND_URL || 'https://pere.ygtxl.dpdns.org';
    const allowedOrigins = [
      'http://localhost:3000',
      'http://localhost:5173',
      frontendUrl,
    ];
    if (allowedOrigins.includes(origin || '')) {
      return origin;
    }
    return null;
  },
  allowHeaders: ['Content-Type', 'Authorization', 'X-API-Key', 'X-Callback-Signature', 'Range'],
  allowMethods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
  maxAge: 86400,
}));
app.use('*', prettyJSON());
app.use('*', loggerMiddleware);
app.use('*', errorHandler);

// Health check
app.get('/health', (c) => {
  return c.json({
    status: 'healthy',
    timestamp: new Date().toISOString(),
    environment: c.env.ENVIRONMENT,
  });
});

// API routes
app.route('/api/v1/tasks', taskRoutes);
app.route('/api/v1/callback', callbackRoutes);
app.route('/api/v1/auth', authRoutes);
app.route('/api/v1/files', publicFileRoutes);
app.route('/api/v1/bgm', bgmRoutes);
app.use('/api/v1/admin/*', authMiddleware);
app.route('/api/v1/admin', adminRoutes);

// Catch-all: serve static assets for non-API paths (SPA routing with index.html fallback)
app.get('*', async (c) => {
  const url = new URL(c.req.url);

  // API paths should return JSON 404, not index.html
  if (url.pathname.startsWith('/api/')) {
    return c.json({ code: 404, msg: 'Not Found' }, 404);
  }

  // Try ASSETS binding first (available in newer wrangler versions)
  if (c.env.ASSETS) {
    try {
      // Try to serve the requested file
      const fileResponse = await c.env.ASSETS.fetch(c.req.raw);
      if (fileResponse && fileResponse.status === 200) {
        return fileResponse;
      }
    } catch (e) {
      // File not found, fall through to SPA fallback
    }
  }

  // SPA fallback: serve embedded index.html for client-side routes
  return c.html(INDEX_HTML);
});

// 404 handler for non-GET requests on non-API paths
app.notFound((c) => {
  return c.json({ code: 404, msg: 'Not Found' }, 404);
});

export default app;

export { scheduled };
