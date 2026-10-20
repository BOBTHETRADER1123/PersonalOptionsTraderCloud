# Deploy the phone-friendly paper trading app

For the no-command-line, beginner setup, follow [BEGINNER_DEPLOYMENT.md](BEGINNER_DEPLOYMENT.md). It uses the included Render Blueprint to deploy the shared backend and database through dashboards, then connects the Vercel website.

The Vercel project serves the React/PWA website. The FastAPI service stays on a separate always-on Docker host because it owns the paper-trade database and can keep broker market-data connections open. The website talks to that service through a same-origin `/api/*` rewrite. The app remains paper-only; no live-order endpoint is included. The builder lets you combine any number of option legs and give a custom strategy a name. During a trade, each received broker quote updates its best and worst recorded net P&L with the timestamp; the trade list retains those extrema after closing.

## 1. Host the backend first

Use a Docker host that can keep containers and persistent storage running. This project already includes FastAPI, PostgreSQL, persistent Docker volumes and Caddy HTTPS in `docker-compose.yml`.

1. Give the backend a public DNS name, for example `api.example.com`, pointing to the Docker host.
2. On the host, copy `backend/.env.example` to `backend/.env` and set a unique `APP_SECRET`, a strong `APP_PASSWORD_HASH`, and `COOKIE_SECURE=true`. Leave broker credentials empty if you only need paper entries without live quotes.
3. Set `CORS_ORIGINS` to the exact Vercel website origin after creating the Vercel project, for example `https://your-project.vercel.app`. Add a custom website domain too if you use one. Separate multiple origins with commas.
4. Copy `deploy.env.example` to the repository root as `.env`; set `DOMAIN=api.example.com` and a strong `POSTGRES_PASSWORD`.
5. From the project root, start the backend with `docker compose up -d --build`.
6. Check `https://api.example.com/api/health`. It should return JSON with `"ok": true` and `"orders_enabled": false`.

Keep the host's persistent `postgres_data` and `trader_data` volumes. Expose HTTPS through Caddy; do not expose PostgreSQL or port 8000 to the public internet.

To generate a password hash, run `python -m app.password_hash` from the backend directory on a machine with the project's Python dependencies installed. Put the resulting `pbkdf2_sha256$...` value in `backend/.env` as `APP_PASSWORD_HASH=...`, and clear `APP_PASSWORD`.

## 2. Point Vercel at the backend

Edit the `destination` in the root `vercel.json`. Replace `YOUR_BACKEND_DOMAIN` with the backend hostname, keeping the `/api/:path*` suffix. For example:

```json
"destination": "https://api.example.com/api/:path*"
```

The `/api/*` rewrite forwards browser requests through Vercel without changing the website URL. Its response headers explicitly disable caching because these routes include authenticated state and paper-trade actions. [Vercel external rewrites](https://vercel.com/docs/routing/rewrites)

## 3. Deploy the website to Vercel

1. Create a Vercel account and a new project for this folder. The repository can be connected through Git, or you can use the Vercel CLI.
2. Keep the project root at the folder containing `vercel.json`. The build command and `frontend/dist` output directory are already configured there.
3. Deploy a preview first, sign in using the `APP_PASSWORD` you set on the backend, and confirm the dashboard loads. Then promote/deploy to production.
4. If you add a custom domain to Vercel, add its exact `https://...` origin to backend `CORS_ORIGINS` and restart the backend.

The website is a Vite static frontend; Vercel documents Vite deployment and external-origin API rewrites. [Vite on Vercel](https://vercel.com/docs/frameworks/frontend/vite)

### Windows CLI option

From PowerShell in the project root, if the portable Node folder is still inside the project, run:

```powershell
$nodeDir = Join-Path $PWD 'node-v24.22.0-win-x64'
$env:Path = "$nodeDir;$env:Path"
npx.cmd vercel
```

Sign in when the CLI prompts you. Use the production flag only after checking the preview deployment:

```powershell
npx.cmd vercel --prod
```

If you installed Node with the normal Windows installer instead, open a new PowerShell window and run `npx.cmd vercel` from the project root.

## 4. Open it on your phone

Open the Vercel HTTPS URL on your phone and sign in with the backend desk password. Use the browser's **Add to Home Screen** command to install the responsive PWA. The backend must remain online for login, trade recording and updates. The app refreshes through HTTP polling; Vercel Functions do not act as WebSocket servers, so the Vercel deployment does not use the local WebSocket connection. [Vercel WebSocket limits](https://vercel.com/docs/limits)

## Before publishing

- Use a unique secret and a strong desk password; do not commit either environment file.
- Set `COOKIE_SECURE=true` on the HTTPS backend.
- Keep broker access tokens only in the backend environment. They are optional for paper entries and fresh market prices.
- Vercel hosts the website only. The app data and feeds remain on the separate backend and its persistent database.
- The current release records paper orders only. It cannot send orders to Dhan, Kotak Neo or 5paisa.
