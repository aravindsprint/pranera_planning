# Pranera Planning

Planning module for erp.pranera.in. A Vue 3 single-page app served by Frappe at
`/planning-app`, plus the Frappe app that will own the planning DocTypes.

## Run locally (against the live ERP)

```bash
cd frontend
yarn install
yarn dev            # http://localhost:3001
```

The dev server proxies `/api`, `/assets`, `/files` and `/private` to
`https://erp.pranera.in`, so you sign in with your normal ERPNext account and
work with live data. Runs alongside pranera_knit (port 3000); the login cookie
is shared between them.

To test backend code that isn't deployed yet, point at your local bench:

```bash
cp .env.example .env.local     # then set VITE_PROXY_TARGET=http://127.0.0.1:8001
```

`.env.local` is git-ignored, so nothing needs reverting before you commit.

## Layout

```
frontend/src/
  config/app.js      title, URL base, allowed roles, CSRF endpoints
  config/pages.js    every page: drives both the router and the side menu
  api/frappe.js      call(), getList(), getAllList(), getDoc(), createDoc(), updateDoc(), deleteDoc(), getCount()
  stores/auth.js     session, login/logout, Employee + roles
  components/AppHeader.vue
  pages/_template/   copy this to start a page (not routed)
pranera_planning/
  hooks.py           /planning-app route rule, apps-screen tile
  www/planning-app.* the page Frappe serves (injects CSRF token, cache-busts the bundle)
  planning/          module folder: DocTypes go in planning/doctype/<name>/
  public/planning_app/   built frontend (committed)
```

## Add a page

1. Copy `src/pages/_template/` to `src/pages/<slug>/` and rename the file.
2. Add an entry to `src/config/pages.js`.

## DocTypes

Ship them in this app (`pranera_planning/planning/doctype/<name>/`) so they are
versioned in git and applied by `bench migrate` on deploy. Create them on the
local bench with developer mode on, then commit the generated files.

## Yarn reservation

Page: `/planning-app/yarn-reservation`. Pick a purchase project, see each yarn batch bought
under it, and reserve quantity for another project's production. A reservation is a
`Yarn Reservation` document (one per batch per production project).

The rule is enforced on Stock Entry `validate` (`reservation.py`) for Material Transfer for
Manufacture, Manufacture and Send to Subcontractor: an issue of qty `q` to project `P` is
refused unless `q <= free + still-reserved-for-P`. Batches with no active reservation are
never touched, and a bug in the check fails open (logged) instead of blocking the floor.

Definitions:
- **In stores**: stock in warehouses other than `WIP*`, `SUB*`, `Direct Delivery*`
  (`Batch.batch_qty` is not used because it also counts WIP).
- **Remaining**: reserved qty minus what was issued to that project from that batch since the
  reservation was created.
- **Free**: in stores minus all remaining reservations.

Site config (`site_config.json`), all optional:

| key | default | effect |
|---|---|---|
| `yarn_reservation_enforcement` | `1` | `0` turns the Stock Entry check off, no redeploy |
| `yarn_reservation_excluded_warehouse_prefixes` | `["WIP","SUB","Direct Delivery"]` | warehouses that do not count as issuable stock |

Known limits: yarn returned from WIP to stores does not restore a reservation; plain
Material Transfer / Material Issue are not checked; a Subcontracting Order whose items span
several projects cannot be attributed to one project, so it is not checked.

Tests: `python -m unittest pranera_planning.tests.test_reservation_math`

## Deploy

See [DEPLOY.md](DEPLOY.md).
