# REWE Service API

Base URL: `http://localhost:8020`

A Puppeteer-driven automation service for REWE.de: it keeps one logged-in Chromium
session alive and lets an agent search products and add them to the shopping cart.

## Behavior (per spec)

- One persistent headless Chromium session, reused across requests. Its profile
  (cookies, local storage) is stored on disk under `REWE_PROFILE_DIR`
  (`/app/data/profile` in the container, backed by the `rewe_profile_data` volume), so
  the session also survives container restarts.
- Login is never a tool the agent calls. Every `/search` and `/cart/add` request runs
  `ensureLoggedIn()` first, transparently, using `REWE_EMAIL` / `REWE_PASSWORD` from
  `.env`.
- Requests are processed strictly one at a time, in arrival order (`src/queue.js`), so
  the shared browser page is never driven concurrently.

## Agent Tool Definitions

- `GET /agent/tool-definitions`
  - Returns `{ tools: [...] }`: `name`, `description`, `endpoint`, `method`,
    `input_schema` for `rewe_search` and `rewe_add_to_cart`. Login is intentionally not
    a tool here.

## Endpoints

### `POST /search`
Request: `{ "query": "milk", "limit": 20 }` (`limit` optional, 1-50, default 20)
Response: `{ "products": [{ "id": "...", "name": "...", "price": "...", "url": "..." }], "count": N }`

### `POST /cart/add`
Request: `{ "productId": "<id or url from /search>", "quantity": 1 }`
Response: `{ "added": true, "quantity": 1, "productRef": "..." }`

Both endpoints return `503` with `{ "error": "Not logged in to REWE.de: ..." }` if the
automatic login could not establish a session (see Login & CAPTCHA below).

## Health

- `GET /health`
```json
{
  "status": "ok",
  "service": "utils-rewe",
  "tools": ["rewe_search", "rewe_add_to_cart"],
  "pendingRequests": 0,
  "loginState": "loggedIn",
  "lastLoginError": null,
  "debugPort": 9222
}
```
`loginState` is one of `unknown`, `loggingIn`, `loggedIn`, `blocked`.

## Login & CAPTCHA fallback

REWE puts a third-party CAPTCHA in front of its login form, so a fully scripted login
can get blocked. When that happens `loginState` becomes `blocked` and every
`/search` / `/cart/add` call returns `503` until the session is authenticated.

To recover:
1. `GET /admin/debug-info` for the current state and a reminder of the debug port.
2. Publish/open `http://<host running the container>:${REWE_CDP_PORT}` (default 9222)
   in a desktop Chrome. This is the container's Chrome DevTools endpoint — it lets you
   see and drive the exact same live page the service uses, so you can solve the
   CAPTCHA and finish the login by hand, once.
3. `POST /admin/login/retry` to re-check and record the now-authenticated session. From
   then on, that session is reused automatically and this fallback isn't needed again
   until it expires.

`/admin/*` endpoints are operational (for a human), not advertised via
`/agent/tool-definitions`.

## Selectors

`src/selectors.js` holds every CSS selector / text label used to drive shop.rewe.de.
shop.rewe.de returns HTTP 403 to non-browser requests and gates the shop behind a
cookie-consent flow, so these selectors are a best-effort starting point, not verified
against the live DOM. If a request fails with "Could not find ..." errors, open the
real site, inspect the current markup, and update the relevant array in that file.

## Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `REWE_EMAIL` | _(required)_ | REWE.de account email used for login |
| `REWE_PASSWORD` | _(required)_ | REWE.de account password used for login |
| `REWE_SERVICE_PORT` | `8020` | HTTP port for this service |
| `CDP_PORT` | `9222` | Chrome DevTools Protocol port, for the manual CAPTCHA fallback |
| `CDP_HOST` | `0.0.0.0` | Interface the CDP port binds to inside the container |
| `HEADLESS` | `true` | Whether Chromium runs headless |
| `REWE_PROFILE_DIR` | `/app/data/profile` | Persisted Chromium profile directory |
| `REWE_BASE_URL` | `https://shop.rewe.de` | Site base URL |
| `REWE_NAV_TIMEOUT_MS` | `30000` | Puppeteer navigation/action timeout |
