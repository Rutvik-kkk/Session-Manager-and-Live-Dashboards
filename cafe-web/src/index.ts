import { handleLogin, handleLogout, handleMe, requireSession } from "./auth";
import { handleDashboard, handleExpenses, handleMapping, handleSessions, handleStatus } from "./dashboard";
import { handleSync } from "./sync";
import { AppEnv, HttpError, json } from "./util";

type Handler = (request: Request, env: AppEnv, url: URL) => Promise<Response>;

const authed = (fn: (url: URL, env: AppEnv) => Promise<Response>): Handler => async (request, env, url) => {
  await requireSession(request, env);
  return fn(url, env);
};

const ROUTES: Record<string, Partial<Record<string, Handler>>> = {
  // Desktop uploader: authenticated with the SYNC_TOKEN bearer secret, never with cookies.
  "/api/sync": { POST: (request, env) => handleSync(request, env) },
  "/api/login": { POST: (request, env) => handleLogin(request, env) },
  "/api/logout": { POST: (request, env) => handleLogout(request, env) },
  "/api/me": { GET: async (request, env) => handleMe(await requireSession(request, env)) },
  "/api/status": { GET: authed((_url, env) => handleStatus(env)) },
  "/api/dashboard": { GET: authed(handleDashboard) },
  "/api/sessions": { GET: authed(handleSessions) },
  "/api/mapping": { GET: authed(handleMapping) },
  "/api/expenses": { GET: authed(handleExpenses) },
};

export default {
  async fetch(request, env): Promise<Response> {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(request);
    try {
      const methods = ROUTES[url.pathname];
      if (!methods) throw new HttpError(404, "Not found.");
      const handler = methods[request.method];
      if (!handler) throw new HttpError(405, "Method not allowed.", { Allow: Object.keys(methods).join(", ") });
      return await handler(request, env, url);
    } catch (err) {
      if (err instanceof HttpError) return json({ error: err.message }, err.status, err.headers);
      console.error("Unhandled error", err instanceof Error ? err.stack : err);
      return json({ error: "Something went wrong on the server." }, 500);
    }
  },
} satisfies ExportedHandler<AppEnv>;
