import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { prettyJSON } from 'hono/pretty-json';
import { taskRoutes } from './routes/public/tasks';
import { callbackRoutes } from './routes/public/callback';
import { authRoutes } from './routes/public/auth';
import { publicFileRoutes } from './routes/public/files';
import { adminRoutes } from './routes/admin';
import { authMiddleware } from './middleware/auth';
import { loggerMiddleware } from './middleware/logger';
import { errorHandler } from './middleware/error';
import { scheduled } from './scheduled';
import { Bindings } from './types/env';

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
app.use('/api/v1/admin/*', authMiddleware);
app.route('/api/v1/admin', adminRoutes);

// 404 handler
app.notFound((c) => {
  return c.json({ code: 404, msg: 'Not Found' }, 404);
});

export default app;

export { scheduled };
