# Personal Options Trader

A mobile-friendly, paper-only options dashboard for index and MCX commodity options. The first release includes a FastAPI backend, React/TypeScript frontend, SQLite for local use, PostgreSQL deployment configuration, append-only quote journaling and one Excel workbook per simulated trade and broker.

For a step-by-step setup without command-line work, see [BEGINNER_DEPLOYMENT.md](BEGINNER_DEPLOYMENT.md). It deploys one shared backend/database and connects the Vercel website for phone and laptop access.

## Safety and what is implemented

- Every order action in this release is a paper simulation. There is no live order submission client or endpoint. The “Live trading” panel stays disabled.
- A new action can create a distinct simulation for any combination of Dhan, Kotak Neo and 5paisa, using one shared action ID and one trade ID per broker. Retries with the same idempotency key return the prior result.
- Paper P&L uses weighted-average entry accounting. Long gross P&L is `(mark - average entry) × open lots × lot size`; short gross P&L is `(average entry - mark) × open lots × lot size`. Charges and configured slippage are shown separately and subtracted from net P&L.
- The contract selector reads imported broker instrument-master CSV files. Choose the underlying, expiry, strike, call/put, side and number of lots from available contracts; strike, expiry and lot size are not typed manually. Enter a paper fill price yourself or use a fresh quote when the selected broker feed provides one.
- Build a strategy from any combination of option legs, choose a built-in strategy label or name your own. The paper ledger tracks each trade's best and worst recorded net P&L and the quote timestamp when each occurred, including after a trade is closed. Times are displayed in India Standard Time; the workbook stores UTC timestamps.
- The broker integrations are read-only market-data workers. They reconnect with backoff and rebuild subscriptions from the imported instrument master. They have not been verified against a real account in this workspace. Real quotes require your broker credentials, correct account permissions and a current instrument master.
- Dhan's binary market feed parser in this release handles its documented ticker packet. Kotak Neo uses the maintained SFeed Python SDK. 5paisa uses the Xstream authenticated feed. Quote fields that a feed does not send remain blank; the app does not synthesize exchange events.
- Market paper entries use the explicit fill price entered by you. A single-leg limit simulation stays pending until a fresh quote from the selected broker crosses its limit; you can cancel it. Multi-leg limit orders and partial fills are not implemented. This is a practical first release, not an exchange-certified trading system. Broker margin estimates, broker account margin, margin/hedge benefit, automated stop-loss/target, and real-account/API verification are not implemented. Do not use paper P&L as broker P&L.

## Project layout

```text
backend/                 FastAPI, SQLAlchemy models, feed adapters, paper ledger and Excel export
  app/brokers/            Independent Dhan, Kotak Neo and 5paisa read-only feed code
  sample-data/            Example paper trade request (example contracts/prices only)
  tests/                  P&L, adapter codec and paper-action tests
frontend/                 React + TypeScript responsive PWA
OptionsTraderData/        Created at runtime: journal and broker/year/month/trade workbooks
start-windows.ps1         Local Windows setup and launch
Dockerfile                Production image
docker-compose.yml        PostgreSQL + app + Caddy TLS reverse proxy
```

## Install and run on Windows

1. Install Python 3.11 or newer and Node.js 20 or newer. During Python setup, enable the option to add Python to PATH.
2. Extract the project into a normal user folder. Open that folder in File Explorer.
3. Right-click `start-windows.ps1` and choose **Run with PowerShell**, or open PowerShell in this folder and run:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\start-windows.ps1
   ```

   The script creates a Python virtual environment, installs the listed packages, builds the frontend, starts the API and opens `http://127.0.0.1:8000`.

4. The first run creates `backend/.env` from `backend/.env.example`. Stop the app, edit that file, set a long unique `APP_SECRET`, and change `APP_PASSWORD`. Restart the app. The first local default, when no `.env` file exists, is `paper-only`.
5. Sign in using the `APP_PASSWORD` value. Open **Data & settings** to see broker prerequisites and import a current CSV instrument master. Configure any market-feed credentials in `backend/.env`, restart the backend, and check the feed state in the sidebar.
6. Open **Data & settings** and import a current instrument-master CSV for the broker you want to use as the contract source. Then select the underlying, expiry and strike in **New paper trade**. You can select one or more brokers for separate simulations; nothing is sent to a broker. A live quote is optional; without one, enter the paper fill price.
7. Open **Positions & trades** to add lots, partially exit a leg, exit a leg or close the strategy. For an exit, leaving the exit-price field blank uses the current stored mark; without quotes that mark remains the original paper fill assumption.
8. Download the trade workbook from **Reports & exports**. Workbooks contain Trade Summary, P&L Timeline, Trade Events and Strategy Legs sheets. The JSONL journal is stored at `backend/OptionsTraderData/journal/events.jsonl` by default.

To update an existing Windows install, extract the new ZIP into the same parent folder and choose **Replace the files** when asked. The ZIP does not contain `backend/.env` or local database/report data, so they stay in place. The launcher closes a previous server started from that same project virtual environment before starting the updated app.

### Manual startup commands

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env  # only the first time
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In a second PowerShell window:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Then open `http://127.0.0.1:5173`. Vite proxies `/api` and the WebSocket route to FastAPI. To use the React UI through FastAPI without Vite, run `npm.cmd run build` once; FastAPI serves `frontend/dist` when present. `start-windows.ps1` calls `npm.cmd` and recognizes a `node-v*-win-x64` portable Node folder extracted into the project root.

## Broker feed configuration

Use official broker documentation and the API program available on your own account. Broker requirements, subscriptions and permissions can change, so verify them before connecting.

- **Dhan:** set `DHAN_CLIENT_ID` and a valid `DHAN_ACCESS_TOKEN`. DhanHQ v2's market feed is a binary WebSocket with exchange/security IDs; subscription messages allow up to 100 instruments and their docs describe a 5,000-instrument connection limit. This implementation uses ticker data. Dhan currently documents 24-hour access-token validity. [Dhan v2 Live Market Feed](https://dhanhq.co/docs/v2/live-market-feed/), [Dhan API releases](https://dhanhq.co/docs/v2/releases/).
- **Kotak Neo:** set `KOTAK_CONSUMER_KEY`, `KOTAK_MOBILE_NUMBER`, `KOTAK_UCC`, `KOTAK_MPIN` and your backend-only `KOTAK_TOTP_SECRET`. The worker generates a current TOTP code at authentication time. New setup uses the maintained `kotakneoapi` v3 Python SDK and SFeed WebSocket. Do not follow setup guides for the retired `kotak-neo-api-v2` SDK or legacy callback market-data feed. [Official Kotak Neo Python SDK](https://github.com/Kotak-Neo/kotak-neo-python).
- **5paisa:** set `FIVEPAISA_CLIENT_CODE` and a current `FIVEPAISA_ACCESS_TOKEN`. The App Key is used to obtain credentials in the broker's portal/API flow; access tokens expire and may need renewal. [5paisa Xstream WebSocket](https://xstream.5paisa.com/dev-docs/market-data-system/web-socket), [5paisa Xstream docs](https://xstream.5paisa.com/dev-docs/).

MCX option masters are normalized to Dhan's `MCX_COMM`, Kotak Neo's `mcx_fo` and 5paisa's MCX exchange plus derivatives segment. The default `FEED_UNDERLYINGS` list includes common MCX roots; edit it in `backend/.env` to match the exact commodity root names in your broker master. Contract selection can show any imported option root, while live prices still depend on feed credentials and broker permissions.

In **Data & settings**, import a CSV file downloaded from the selected broker. The importer recognizes common names such as `underlying_symbol`, `sem_underlying_symbol`, `expiry_date`/`sem_expiry_date`, `strike_price`/`sem_strike_price`, `option_type`, `lot_size`/`sem_lot_units`, `security_id`, and `scrip_code`. Check the number of imported contracts and search for an expected symbol before using the master. A contract file is only current as of its download time.

Broker APIs may require account/API enrollment, market-data entitlements or session renewal. Their published limits may apply. The app reports connection and quote freshness; it cannot guarantee data delivery time or feed completeness. Timestamp precision is a representation detail, not a market-latency promise.

## Security and mobile deployment

For a Vercel website with a separate always-on backend, follow [VERCEL_DEPLOYMENT.md](VERCEL_DEPLOYMENT.md). The root `vercel.json` builds the mobile-ready PWA and proxies `/api/*` to the backend hostname you set there. The backend still needs persistent PostgreSQL and storage for the paper ledger and event journal.

Do not expose the Windows development server to the public internet. For access away from home, deploy to an always-on server with a static public IP where broker APIs require it. A domain must point to the server and ports 80/443 must be reachable. Install Docker and Docker Compose, then:

1. Copy `backend/.env.example` to `backend/.env`. Set a unique `APP_SECRET`, a strong `APP_PASSWORD`, and broker credentials. Do not commit this file.
2. Create a root `.env` file with `DOMAIN=your.domain.example` and a long random `POSTGRES_PASSWORD`.
3. Set `APP_PASSWORD_HASH` instead of `APP_PASSWORD` for production. Generate a PBKDF2 hash with `python -m app.password_hash` from `backend/`, then put the printed value in `backend/.env` as `APP_PASSWORD_HASH=...`; clear `APP_PASSWORD`.
4. Run `docker compose up -d --build`. Caddy requests and renews HTTPS certificates. App sessions use secure cookies, PostgreSQL persists data, and the volume `/data` retains the event journal and Excel files.
5. Open your HTTPS domain on Android. Use the browser's **Add to Home screen** option. The interface is responsive; the host and database must remain running for quotes and logging to continue.

Hosting, domain and static-IP costs depend on the provider. Broker market-data/API fees, if applicable to your account, are separate. Confirm current requirements with each broker. Use the server's firewall to expose only SSH and HTTPS; do not publish PostgreSQL or port 8000. Back up both the PostgreSQL volume and `trader_data` volume. Restore the database first, then restore the `OptionsTraderData` journal/report directory.

The local cookie is HttpOnly, SameSite strict and paired with a CSRF token. Login attempts are throttled per remote address. Set `COOKIE_SECURE=true` only when accessing through HTTPS. The live-trading feature flag is not consulted by any order route because there is no order route in this release.

## Event journal and workbooks

Each quote event received by an adapter is assigned a local UTC receive timestamp and appended to `journal/events.jsonl` with an fsync before the database write. When the backend starts, quote records absent from SQLite are restored from that journal. The database uses a transaction for paper actions, while each trade event is also appended to the journal. The app does not manufacture intermediate ticks or one-second snapshots.

Excel is generated on export and finalized in a background thread when a strategy closes, rather than saving a workbook on every quote. The event journal remains the primary record; if Excel is locked, the journal and database continue to be available. The workbook writer replaces only the workbook for its own trade. CSV export and an operator-facing full journal rebuild UI are not included yet.

The local directory layout is:

```text
OptionsTraderData/{Dhan|KotakNeo|5paisa}/YYYY/MM/Trade_<trade_id>/Trade_<trade_id>.xlsx
OptionsTraderData/journal/events.jsonl
```

## Checks and test report

Run the automated tests from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The tests cover long/short P&L, option payoff, Dhan ticker packet decoding, 5paisa feed subscription shape, paper-only multi-broker creation, idempotent retries, broker-specific limit fills and cancellation, exit accounting, CSRF enforcement and workbook generation. Test databases and reports use an automatically cleaned temporary directory. The tests do not verify live broker authentication, current-account entitlements, live quote mapping, production server network policy, or mobile access through a deployed domain. Those require your broker accounts and hosted environment.

## Troubleshooting

- **Sign-in rejected:** check `APP_PASSWORD`/`APP_PASSWORD_HASH` and restart. A lockout after repeated failed attempts clears after five minutes.
- **Broker remains disconnected:** check its required environment variables; verify token validity, account API enrollment and network access. Review the backend console/log output and broker's official API portal. Never paste a token into a browser field or support chat.
- **Feed connected but no quotes:** import the correct broker's current option instrument master and verify that contracts for the intended underlying and segment were imported. Each broker token maps differently.
- **Prices marked stale:** the source stopped sending updates or the market/contract has no recent provider event. The UI retains the last quote and labels its age; it does not convert that into a fresh value.
- **Workbook not downloading:** close the workbook if Excel holds a lock, then export again. SQLite/JSONL data remains authoritative.
- **Port already in use:** stop the existing `uvicorn` process or change the port in `start-windows.ps1` and the Vite proxy.
- **Restore a missing quote event:** stop the service, back up the database, then restart; startup replays journaled quotes whose event keys are absent from SQLite. Do not edit the JSONL file while the service is running.
