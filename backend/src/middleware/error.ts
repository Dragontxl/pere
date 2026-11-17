import { MiddlewareHandler } from 'hono';

export const errorHandler: MiddlewareHandler = async (c, next) => {
  try {
    await next();
  } catch (error) {
    console.error('API Error:', {
      path: c.req.path,
      method: c.req.method,
      message: (error as Error).message,
      stack: (error as Error).stack,
    });

    return c.json({
      code: 500,
      data: null,
      msg: (error as Error).message || 'Internal server error',
    }, 500);
  }
};
