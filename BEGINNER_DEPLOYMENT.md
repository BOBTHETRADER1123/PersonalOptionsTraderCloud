# Put the same paper-trading app on your phone and laptop

This setup publishes one website on Vercel and connects it to one always-on backend and database. Your phone and laptop will open the same Vercel link and see the same paper trades and strategies.

You do not need to write or run code for these steps. You will use GitHub Desktop and the Render and Vercel websites. Keep your old extracted folder until the cloud app works. Start from `PersonalOptionsTrader-mobile.zip`; it does not contain your private `.env` file.

## Before you begin

Create accounts at GitHub, Render and Vercel. Install [GitHub Desktop](https://desktop.github.com/) on Windows and sign in to your GitHub account. GitHub Desktop lets you publish the project with buttons instead of typing commands; [GitHub's guide](https://docs.github.com/en/desktop/overview/creating-your-first-repository-using-github-desktop) shows the screens.

Render will create the backend, a PostgreSQL database and storage for the app's files. The included setup selects paid, always-on hosting so data is retained. Review the monthly charge shown by Render before clicking its final create/apply button. Render's free web services can sleep, and its free PostgreSQL database expires after 30 days, so do not choose a free database for trades you want to keep. See [Render's free-plan limits](https://render.com/docs/free) and [current pricing](https://render.com/pricing).

## 1. Publish the project privately on GitHub

1. Extract `PersonalOptionsTrader-mobile.zip` into a new folder. Do not extract it over your old `PersonalOptionsTrader` folder.
2. Open GitHub Desktop. Choose **File → New repository**. Name it `PersonalOptionsTraderCloud`, choose a folder under Documents, then click **Create repository**.
3. In GitHub Desktop, choose **Repository → Show in Explorer**. A File Explorer window opens to the new, mostly empty repository folder.
4. In another File Explorer window, open the folder where you extracted the new ZIP. Copy its contents into the repository folder. Do not copy any `backend\.env` file from the old folder.
5. Return to GitHub Desktop. Enter `Upload app` in the summary box at the lower left and click **Commit to main**.
6. Click **Publish repository**. Leave **Keep this code private** selected, then publish it.

## 2. Create the shared backend and database on Render

1. Sign in at Render and choose **New → Blueprint**.
2. Connect GitHub when Render asks, select the private `PersonalOptionsTraderCloud` repository, and continue.
3. Render reads the included `render.yaml` setup. It will ask you for `APP_PASSWORD`. Choose a strong password and save it somewhere private; you will use it to sign in on both devices. Never send this password to me.
4. Review the monthly plan and storage charges Render displays. If you are comfortable with the charge, click the final **Apply/Create** button. Otherwise stop here before creating the services.
5. Wait until Render shows the backend service as **Live**. Open its service page and copy the public address, which looks like `https://personal-options-trader-api.onrender.com`.
6. Check that address by adding `/api/health` at the end, for example `https://personal-options-trader-api.onrender.com/api/health`. A small JSON response with `"ok": true` means the backend is running.

## 3. Connect Vercel to that backend

The Vercel website forwards its `/api` requests to the Render address. Set that address once in the project file:

1. Open your repository on GitHub.com and open `vercel.json`.
2. Click the pencil icon to edit it. Find the line containing `https://YOUR_BACKEND_DOMAIN/api/:path*`.
3. Replace only `YOUR_BACKEND_DOMAIN` with the host from Render. For example, if Render gave you `https://personal-options-trader-api.onrender.com`, the line should read:

   ```json
   "destination": "https://personal-options-trader-api.onrender.com/api/:path*"
   ```

4. Click **Commit changes** to save the edit.
5. Sign in to Vercel and choose **Add New → Project**. Import the same private GitHub repository. Leave the project root at its default (the top-level folder containing `vercel.json`) and click **Deploy**.
6. Wait until Vercel says the deployment is ready, then copy its website link. It looks like `https://your-project.vercel.app`.

Vercel can deploy a Vite project from GitHub; its [Vite guide](https://vercel.com/docs/frameworks/frontend/vite) explains the import flow. The project already contains the build settings and API forwarding rule.

## 4. Use it from both devices

1. Open the Vercel website link on your laptop and sign in with the `APP_PASSWORD` you created in Render.
2. Open that exact same link on your phone and sign in with the same password.
3. Paper trades and strategies you enter on either device use the same hosted database and should appear on both. On your phone, use the browser menu's **Add to Home Screen** option for an app-like shortcut.

The app records paper orders only; it does not send orders to your broker. Broker market-data credentials are optional, but are needed if you want the app to receive fresh quotes and update trade P&L extrema from a feed. Keep broker credentials in Render's private environment settings, never in GitHub.

## If something does not work

Send me a screenshot of the page with the error, after hiding passwords and tokens. Do not delete your old folder or share `APP_PASSWORD`, `APP_SECRET`, broker tokens, or database addresses that contain passwords.
