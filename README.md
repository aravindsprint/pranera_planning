# Pranera Planning

Planning module for erp.pranera.in. A Vue 3 single-page app served by Frappe at
`/planning-app`, plus the Frappe app that will own the planning DocTypes.

## Run locally

```bash
cd frontend
yarn install
yarn dev            # http://localhost:3001
```

The dev server forwards `/api`, `/assets`, `/files` and `/private` to one of two backends,
and **you choose which in the app**: the **Settings** page (menu -> System -> Settings) or
the switch under the login form. A LIVE / LOCAL badge in the header shows which one you're
on, and takes you to Settings when clicked.

| Backend | Goes to | Use it for |
|---|---|---|
| **LIVE** | `https://erp.pranera.in` | Real data. pranera_planning is not deployed there yet. |
| **LOCAL** | `http://127.0.0.1:8001` | Testing new code. Run `bench --site pranera.com serve --port=8001`. |

Switching signs you out of the backend you're leaving and returns you to the login page —
the two sites have separate users and sessions. No restart of `yarn dev` is needed. The
Settings page also shows, for the backend you're on, whether pranera_planning and the
Project Stock Reservation doctype are actually installed there.

The choice is a cookie on `localhost`, read by `frontend/dev-backend-proxy.js`. It exists only
in the dev server: a production build contains no trace of it and talks to its own origin.
`.env.example` lists the optional defaults.

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

## Stock reservation

Page: `/planning-app/project-stock-reservation` (menu: Planning -> Stock Reservation). Pick a
project (the Purchase / Production checkboxes filter the picker by Project Type; both ticked
shows every type, unclassified included), see each batch received under it, and reserve
quantity for a production project. A reservation is a `Project Stock Reservation` document
held at one stock location:

| Item | Reserved by |
|---|---|
| Yarn and other batch items | warehouse + batch |
| Fabric, collar, cuff (anything under the `FABRIC` item group — collars and cuffs live there) | warehouse + batch + roll |

Roll numbers come from Stock Entry Detail's `custom_roll_no`. Rolls often enter a warehouse
without a number and only get one when they leave, so each warehouse shows its numbered rolls
plus the stock with no roll no. on record; reserving a roll number the ledger hasn't seen there
is taken out of that remainder. One active row per warehouse + batch + roll per production
project per Sales Order (`sales_order` is blank for pooled reservations).

If you ask for more than is available, the reservation is **capped** to what's available rather
than refused, and `requested_qty` keeps the original ask visible. Only a batch with nothing left
is refused. Reducing `reserved_qty` later is just an edit — it can't go below what has already
been issued against it.

The rule is enforced on Stock Entry `validate` (`reservation.py`) for Material Transfer for
Manufacture, Manufacture and Send to Subcontractor: an issue of qty `q` to project `P` is
refused unless `q <= free + still-reserved-for-P`, counted per source warehouse; and a roll
reserved for another project can't be issued to P. This covers Work Order, Job Card and
Subcontracting Order flows alike, since none of them moves stock itself — each triggers one of
these Stock Entries. Batches with no active reservation are never touched, and a bug in the
check fails open (logged) instead of blocking the floor.

Definitions:
- **In stores**: stock in warehouses other than `WIP*`, `SUB*`, `Direct Delivery*`
  (`Batch.batch_qty` is not used because it also counts WIP).
- **Remaining**: reserved qty minus what was issued to that project from that batch since the
  reservation was created.
- **Free**: in stores minus all remaining reservations.

Site config (`site_config.json`), all optional:

| key | default | effect |
|---|---|---|
| `project_stock_reservation_enforcement` | `1` | `0` turns the Stock Entry check off, no redeploy |
| `project_stock_reservation_excluded_warehouse_prefixes` | `["WIP","SUB","Direct Delivery"]` | warehouses that do not count as issuable stock |
| `project_stock_reservation_roll_item_groups` | `["FABRIC","COLLAR","CUFF"]` | item group trees reserved by roll (missing groups ignored) |
| `project_stock_reservation_roll_field` | `"custom_roll_no"` | Stock Entry Detail field holding the roll no. |

**Fulfilled.** A reservation becomes `Fulfilled` automatically when everything reserved has
been issued (checked on every Stock Entry submit of the enforced types), and goes back to
`Active` if cancelling an entry reopens it. The `mark_fulfilled_reservations` patch catches up
reservations that were already fully issued.

**Produced stock belongs to its project.** A batch produced for a project — finished item of a
Manufacture entry (Work Order's project, else the entry's) or received on a Subcontracting
Receipt (receipt item's project, else its Subcontracting Order / Purchase Order item's) — can
only be issued to another project up to what is reserved for that project on the page.
Purchased batches stay shared until reserved. Switch off with site config
`project_stock_reservation_protect_produced: 0`. To see what the rule would have blocked:

    bench --site <site> execute pranera_planning.reservation.preview_produced_conflicts --kwargs "{'days': 30}"

**Produced section.** For a project with produced batches, the page shows them by stage
(`project_stock_reservation_stages`, default GKF → Greige, DKF → Dyed, SKF → Finished, else the
item group), with input vs produced per stage, and where the output is now (stores, WIP, at the
subcontractor). Produced batches can be reserved for another project from the same table.

Which project an issue belongs to: Material Transfer for Manufacture / Manufacture take the
Work Order's project (else the entry's own). Send to Subcontractor takes, per line, the project of
the Subcontracting Order item it supplies material for (`sco_rm_detail`), else of the Purchase Order
item behind it; then the order's single item project, the SCO / Purchase Order header, an old-style
entry's Purchase Order, and finally the entry's own project.

Known limits: a reservation stays at its warehouse — moving the stock with a plain Material
Transfer leaves the reservation behind (the new warehouse's stock is unreserved); an issue line
with no roll no. counts against the warehouse, not against a roll reservation; stock returned from WIP to stores does not restore a reservation; plain
Material Transfer / Material Issue are not checked; a Send to Subcontractor line with no Subcontracting
Order, Purchase Order or project anywhere cannot be attributed, so it is not checked.

Tests (pure Python, no site needed): `python -m unittest pranera_planning.tests.test_reservation_math`,
or on a bench with `allow_tests` enabled:
`bench --site pranera.com run-tests --module pranera_planning.tests.test_reservation_math`

## Deploy

See [DEPLOY.md](DEPLOY.md).
