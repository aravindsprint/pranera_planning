# Deploying pranera_planning

## 1. Build the frontend first

```bash
cd frontend
yarn build
```

The built output in `pranera_planning/public/planning_app/` is committed to git.
`bench build` does **not** run the Vite build, so if you skip this step the
deployed app silently stays on the previous frontend.

## 2. Commit and push

```bash
git add -A && git commit -m "..." && git push origin main
```

## 3. Install on erp.pranera.in

First time only: add the GitHub repo as an app on the site's bench group, deploy,
then install `pranera_planning` on erp.pranera.in. After that, every push is
"deploy the bench" (which runs `bench migrate`, creating any new DocTypes).

## 4. Stock Reservation needs the app deployed

The page calls `pranera_planning.api.reservation.*` and the Stock Entry check lives in
this app's hooks, so neither exists on erp.pranera.in until the app is installed there.
Until then, test against your local bench: run `yarn dev`, open the app, and pick **Local bench** on the login page or under Settings (no env var or restart needed). Settings also shows whether pranera_planning is installed on whichever backend you're pointed at.
Deploying runs `bench migrate`, which creates the Project Stock Reservation DocType.

## 5. Verify

Open `https://erp.pranera.in/planning-app`, hard refresh (Cmd+Shift+R), and check
that Home shows "Connected as <you>".

Notes:
- `www/planning-app.py` appends `?v=<mtime>` to `index.js`/`index.css`, so browsers
  fetch the new bundle after each deploy. Don't remove it.
- There is deliberately no service worker / PWA. Add one only if the planning app
  needs offline use; the knit app's cache issues came from that layer.
