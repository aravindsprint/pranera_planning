"""The plan: what a project must make, buy or reserve to deliver its plan lines. Pure — no
frappe imports — so the four scenarios on the design canvas are unit-tested exactly.

Scenario rules (project type × order type):

                       explode BOMs   borrow from others   reserve own stock for the order
  Purchase · stock         no               no                      no
  Purchase · order         no               yes                     yes
  Production · stock       yes              yes                     no
  Production · order       yes              yes                     yes

  borrow  = reserve other projects' free *purchased* stock (produced stock is its owner's)

Per item, parents first (so an item needed in two places is added up before it's covered):
  need      = Σ what the plan lines and the levels above ask of it
  own       = the project's free stock of it (+ what is already reserved for the project)
  coming    = the project's open orders for it (Work / Subcontracting / Purchase Orders,
              Material Requests), as expected output
  reserve   = other projects' free purchased stock, when the scenario borrows
  shortfall = need − own − coming − reserve
  request   = shortfall rounded up (made: whole units; bought: the item group's step)
  a made item's inputs then need request × BOM ratio — worked from the ROUNDED request.

Plan line modes:
  need     deliver this qty, using stock first (made-to-order lines, and the levels below)
  top_up   bring the project's stock up to this level (own and coming count toward it)
  make     make / buy exactly this qty more — at its own level stock isn't taken off (the
           re-order report's suggestion already did that); the levels below still use stock
"""
import math

EPS = 1e-9


def scenario_rules(project_type, order_type):
    production = project_type == "Production"
    to_order = order_type == "Made to order"
    return {"explode": production, "borrow": production or to_order, "reserve_own": to_order}


def round_up(qty, step=1.0):
    step = float(step or 0) or 1.0
    return math.ceil(round(float(qty) / step, 9)) * step


def build_plan(lines, items, rules):
    """lines  [{"item", "qty", "mode": "need" | "top_up" | "make", "label"?}]
    items     {code: {"made": bool, "bom": [(input, ratio per 1 unit)], "round_to": float,
                      "own": qty, "coming": qty, "borrowable": qty, ...anything else is kept}}
    rules     scenario_rules(...)

    Returns {"levels": [row per item, in processing order], "requests": [...]} where a row is
    {"item", "need", "own", "coming", "reserve", "short", "request", "made", "depth",
     "how": [(qty, text)], "inputs": [(input, qty)]}.
    """
    explode = rules["explode"]

    def made(code):
        it = items.get(code) or {}
        return bool(explode and it.get("made") and it.get("bom"))

    # what each item is asked for: (qty, text, offsettable?)
    asks = {}
    for ln in lines:
        q = float(ln.get("qty") or 0)
        if q <= EPS:
            continue
        mode = ln.get("mode") or "need"
        # always say which mode: "make 2,000" or "level 2,000", then where the line came from
        how = {"top_up": f"level {fmt(q)}", "make": f"make {fmt(q)}"}.get(mode, f"ordered {fmt(q)}")
        text = f"{how} ({ln['label']})" if ln.get("label") else how
        asks.setdefault(ln["item"], []).append((q, text, mode))

    # reachable items and how many parents each has (parents are processed first)
    parents, seen, todo = {}, set(), list(asks)
    while todo:
        code = todo.pop()
        if code in seen:
            continue
        seen.add(code)
        parents.setdefault(code, 0)
        if made(code):
            for inp, _r in items[code]["bom"]:
                if inp != code:
                    parents[inp] = parents.get(inp, 0) + 1
                    todo.append(inp)

    depth = {c: 0 for c in asks}
    queue = sorted([c for c in seen if parents[c] == 0])
    done, levels = set(), []
    while len(done) < len(seen):
        if not queue:                                   # a loop in the BOMs: break it
            queue = [sorted(c for c in seen if c not in done)[0]]
        code = queue.pop(0)
        if code in done:
            continue
        done.add(code)
        it = items.get(code) or {}
        a = asks.get(code, [])
        offset_need = sum(q for q, _t, m in a if m != "make")
        fixed_need = sum(q for q, _t, m in a if m == "make")
        own = min(float(it.get("own") or 0), offset_need)
        coming = min(float(it.get("coming") or 0), max(0.0, offset_need - own))
        rest = max(0.0, offset_need - own - coming)
        reserve = min(float(it.get("borrowable") or 0), rest) if rules["borrow"] else 0.0
        short = max(0.0, rest - reserve) + fixed_need
        request = round_up(short, it.get("round_to") or 1) if short > EPS else 0.0
        row = {"item": code, "need": offset_need + fixed_need, "own": own, "coming": coming, "reserve": reserve,
               "short": short, "request": request, "made": made(code), "depth": depth.get(code, 0),
               "how": [(q, t) for q, t, _m in a], "inputs": []}
        if made(code):
            for inp, ratio in it["bom"]:
                if inp == code:
                    continue
                q = request * float(ratio)
                row["inputs"].append((inp, q))
                if q > EPS:
                    asks.setdefault(inp, []).append((q, f"{fmt(request)} × {fmt(ratio, 4)}", "need"))
                depth[inp] = max(depth.get(inp, 0), row["depth"] + 1)
                parents[inp] -= 1
                if parents[inp] == 0:
                    queue.append(inp)
        levels.append(row)
    # levels nobody needs anything from (stock already covered the level above) are left out
    return {"levels": [r for r in levels if r["need"] > EPS]}


def allocate_lots(lots, qty):
    """Pick lots to reserve `qty`: [{"batch_no", "warehouse", "roll_no", "qty", ...}] in the
    order given (oldest batch first is the caller's job). Takes whole lots, and only part of
    the last one. Returns (picked [{..., "qty": taken}], qty still missing)."""
    picked, need = [], float(qty or 0)
    for lot in lots:
        if need <= EPS:
            break
        take = min(float(lot["qty"]), need)
        if take > EPS:
            picked.append({**lot, "qty": take})
            need -= take
    return picked, max(0.0, need)


def fmt(x, decimals=2):
    x = float(x)
    if abs(x - round(x)) < 1e-9:
        return f"{int(round(x)):,}"
    return f"{x:,.{decimals}f}".rstrip("0").rstrip(".")


def lines_to_save(lines, levels, stock_before):
    """The plan lines kept on the project after Create, for the next re-plan.

    A make line means "this much more", once: kept as it is, re-planning would order it again
    even after it arrived. So every item with a make line is saved as one top_up line at the
    level the plan reaches — the stock it counted (own + coming) plus what it requested at
    that item's level — and a re-plan then buys only what is missing from that level.
    Other lines are kept as they are.

    lines         [{"item", "qty", "mode"}] as planned
    levels        the plan's levels [{"item", "request", ...}]
    stock_before  {item: own + coming the plan counted for that item}
    """
    made_items = {ln["item"] for ln in lines if ln.get("mode") == "make"}
    request = {}
    for lv in levels:
        request[lv["item"]] = request.get(lv["item"], 0.0) + float(lv.get("request") or 0)
    out, done = [], set()
    for ln in lines:
        item = ln["item"]
        if item not in made_items:
            out.append({"item": item, "qty": float(ln.get("qty") or 0), "mode": ln.get("mode") or "need"})
        elif item not in done:
            done.add(item)
            level = float(stock_before.get(item) or 0) + request.get(item, 0.0)
            out.append({"item": item, "qty": round(level, 6), "mode": "top_up"})
    return out
