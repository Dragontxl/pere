import { MiddlewareHandler } from 'hono';

export const loggerMiddleware: MiddlewareHandler = async (c, next) => {
  const start = Date.now();
  const { method, path } = c.req;

  await next();

  const elapsed = Date.now() - start;
  console.log(`[${new Date().toISOString()}] ${method} ${path} - ${elapsed}ms`);
};
