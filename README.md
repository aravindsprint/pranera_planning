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
project (the Purchase / Production choice filters the picker by Project Type, one type at a
time; projects with no type set appear under neither), see each batch received under it, and reserve
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

**Which warehouses count as stores.** Stock in WIP and subcontractor warehouses is already
committed to an order: it is never "in stores", free, or reservable. These are recognised by
use, not by name — a warehouse Work Orders use as WIP more often than they draw from it (or one
used as WIP whose name says WIP / Work In Progress), Manufacturing Settings' default WIP
warehouse, and every Subcontracting Order supplier warehouse — plus names starting WIP / SUB /
Direct Delivery. Adjust with site config `project_stock_reservation_excluded_warehouses` /
`project_stock_reservation_pool_warehouses` (lists). The list is cached for an hour and cleared
when a Work Order or Subcontracting Order is submitted. The `release_reservations_outside_stores`
patch releases Active reservations that sit in such a warehouse.

**Use the reservation first.** While a production project still has reserved stock of an item
waiting, it must issue that item from the reservation — the reserved batch, from the reserved
warehouse (and the reserved roll) — not from other free stock or the same batch elsewhere.
Issuing more than is reserved is fine once the reserved stock is all being used; a reservation
whose stock is no longer at its location is not insisted on. Site config
`project_stock_reservation_use_reserved_first`: `"block"` (default), `"warn"` or `"off"`.

**Free stock before buying.** A Purchase Material Request may ask, per batch-tracked item and
project, for at most *requested − free stock*: stock of that item free to reserve for that project
right now (its own free stock, other projects' purchased stock, stock with no project — not stock
produced for another project). Reserve the free stock on the Stock Reservation page first; it then
stops counting as free. Saving shows an orange notice with the free stock (linked to its projects)
and the most the request can ask for; submitting is refused in Block mode.

Configured in **Stock Reservation Settings** (desk):
- *Free stock check*: Block (default) / Warn / Off.
- *Roles that may override*: users with any of these roles can submit anyway by filling in
  *Override reason* on the Material Request; the reason is added as a comment. Starts as
  Purchase Manager; change it any time.
- *Minimum per item group*: free stock below this (e.g. YARN 25 kg) doesn't count, so small
  leftovers don't block a purchase. The nearest group above an item decides.

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

**Produced section.** For a project with produced batches, the page shows them by stage, with
input vs produced per stage and where the output is now (stores, WIP, at the subcontractor).
A batch's stage is the operation that made it: the Job Card operation on its submitted Roll
Packing List (KNITTING, COLLAR KNITTING, CUFF KNITTING), else the last operation of the Work
Order that produced it, else the item code prefix (`project_stock_reservation_stages`, default
GKF → Knitting, DKF → Dyeing, SKF → Finishing). Stages on the same step (same prefix) run side by
side and share their input. Produced batches can be reserved for another project from the same
table.

**Rolls on the move.** A Stock Entry that carries a submitted Roll Wise Pick List
(`custom_roll_wise_pick_list` / `roll_wise_pick_list`, or the pick list's own `stock_entry`) says
exactly which rolls it moved: those rolls follow it (into another stores warehouse, or out of
stores), count against their own roll reservations, and are checked roll by roll when the entry is
saved — even when the entry's rows name no roll. For the check, a pick list also counts when its
own Stock Entry field points at the entry (save the entry as a draft, make the pick list, then
submit the entry). Submitting or cancelling a pick list recounts the reservations on its batches. An issue with neither roll numbers nor a pick list
fills the project's own roll reservations in that batch and warehouse, oldest first.

**Knitted rolls.** Batches move on as a whole without roll numbers on the Stock Entry, so a
batch's rolls come from its submitted Roll Packing Lists (roll no., weight). They are placed in
the stores warehouse the batch sits in, preferring the one the linked Stock Entry delivered to;
a roll whose number appears on a Stock Entry line follows the ledger instead. If part of a batch
left without roll numbers the page flags that the list may include rolls that are gone.

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


## Re-order levels (step 1 of planning)

`reorder.py` works out, per item, a min–max re-order level nightly (scheduler) and on demand
(Re-order Settings › Recalculate now), and stores it in **Item Re-order Level** (one record per item).
Formulas: `reorder_math.py`.

- **Demand** over *History (days)*: Sales Invoices that update stock + Delivery Notes (returns
  subtract), and consumption = Material Transfer for Manufacture / Manufacture / Send to
  Subcontractor lines out of stores warehouses. Read from the documents (under 1 s on live; the
  stock ledger took 38 s).
- **Lead days** = the item's stage *Days used* + every stage below it down its default BOMs to its
  bought material (finished fabric = finishing 3 + dyeing 7 + knitting 5). A bought item's own
  supplier lead days (Item › Lead Time Days, else the group rule) count for that item only, unless
  *Include bought materials' lead days* is ticked. Learned medians (Work Orders, Subcontracting
  Orders) are shown beside Days used as a guide; they're used only where Days used is empty and
  *Use learned days* is ticked — on live they include waiting time.
- **Per item group** (nearest group above the item wins): safety days, cover days, round up to,
  demand basis, bought lead days.
- **Position** = in stores (stores warehouses) − reserved for orders + WIP (open Work Orders and
  Subcontracting Orders still to deliver) + on order (open Purchase Orders + un-ordered Material
  Requests). Order now when position ≤ re-order level: suggest max − position, rounded up.
- **Made-to-stock projects**: family = the Item's Commercial Name (cleaned up), else its top item
  group; one project per family and period (Month / Quarter / Season), named by the pattern.

**Report page** `/planning-app/reorder-report` (menu: Planning › Stock Levels & Re-order): every
calculated item with average per day, lead days, safety, re-order level and qty, max, in stores,
reserved, free, WIP, on order, position, status and suggestion; Order now first, largest suggestion
first. Status chips filter (their counts ignore the status filter). Each row opens its workings,
with Refresh now (recalculates that item at once). Stages with no lead days are warned about, and
made items without lead days are flagged. Plan arrives with the Plan page (step 3).

## Plan project (step 3)

Page `/planning-app/plan` (menu: Planning › Plan Project); `planner.py` + `plan_math.py`.

- **Made to order**: pick the project (Open, Production or Purchase) and optionally its Sales Order
  (Load lines fills the open quantities). **Made to stock**: each line goes to its family's stock
  project for the period (Commercial Name, else top item group; Production for made items,
  Purchase for bought), created on Create. Lines are *Top up to* a level or *Make qty* (the
  re-order report's Plan opens with its suggestion as Make qty).
- Scenario rules (project type × order type): Purchase projects only buy; a purchase pool making
  stock doesn't borrow; made-to-order projects hold their own stock for the order.
- Per item, parents first: own stock → coming (open orders and requests, drafts included) →
  other projects' free purchased stock (reserved) → the rest is requested, rounded up, and the
  next level is worked from the rounded request. Roll items are reserved roll by roll.
- Made levels: In-house → Manufacture request; Job work → a Purchase request for ONE service
  (the one this item last used — stenter or dryer — else the stage's most common; switchable).
- Create re-checks stock, then makes the project (made to stock), the reservations and the draft
  Material Requests — all or nothing. Project gets Order type / Stock family / Stock period fields.

## Closing the known limits

- **Deliveries** (Delivery Note, Sales Invoice with Update Stock; returns ignored): a stores line
  may ship a batch only within what is free to it — stock reserved for a Sales Order ships only
  against that order, stock reserved for a project only against that project's orders, and stock
  belonging to a made-to-order project (received or produced under it) only against the
  project's Sales Order. Stock Reservation Settings › Delivery check: Block / Warn / Off.
- **Material Transfers out of stores** (to WIP, a job worker…) are issues: checked like one,
  counted in Issued, and must name the Project when the stock is reserved or owned.
- **Material Transfers between stores** carry their reservations along: free stock moves first,
  then reserved stock oldest first; a named roll carries its own. The moved part becomes a new
  reservation (Moved from / Moved by); cancelling the transfer puts it back.
- **Made-to-order ownership** covers stock received under the project, not only produced.
- **Plans**: each made level can use another active BOM (picker on the Plan page); a BOM's
  Process Loss % counts (1,000 good at 3% loss needs 1,030.9 in).
- **Integration tests** (`pranera_planning/integration_tests/test_flows.py`) run on a real site —
  a COPY, never live: `bench --site <copy> set-config allow_tests true` then
  `bench --site <copy> run-tests --module pranera_planning.integration_tests.test_flows`.

## Project Planning page (one page, three tabs)

`/planning-app/project-planning?project=<name>&tab=overview|plan|stock` (menu: Planning › Project
Planning) replaces the separate Stock Reservation and Plan Project pages; their old addresses
redirect to the right tab, so links and bookmarks keep working.

- **Overview** (`api.project_planning.get_overview`): made to order → the Order panel (Ordered,
  Ready = own free stock + what is held, In production = open orders and requests, Delivered, Not
  planned); made to stock → the Stock programme (Target from the saved plan, Held, Reserved by
  orders, Free now, In production, Free after plan). Totals, open Material Requests, and the stage
  table with a Planned column.
- **Plan**: the planner for this project (`api.plan.plan_defaults` loads its Sales Order's open
  lines, or its saved targets). Create saves the plan's lines on the project (Project › Saved plan)
  and opens its Overview.
- **Stock & reservations**: the former Stock Reservation page, embedded.
- **+ New plan** (`?new=1`, also the re-order report's Plan): made-to-stock lines that go to their
  family projects; Create opens the first one.
