#!/usr/bin/env python3
"""
Number Foundry - a small factory game about numbers.

A "1" leaves the source and rides a belt through your machines. Machines change
the number by a RANDOM amount (you only choose which machine goes where).
Whatever reaches the Export pays money equal to its value - up to the crate
limit - and money buys more machines, slots and upgrades.

Run:  python number_foundry.py        (needs only Python 3.8+ with tkinter)
"""
import json
import math
import random
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from collections import deque
from pathlib import Path
from tkinter import messagebox

# ------------------------------------------------------------------ layout --
W, H = 1200, 720
HEADER_H = 76
BELT_Y = 200
SLOT_W = 88
MAX_SLOTS, START_SLOTS = 10, 3
SRC_X1 = 118
BELT_X0 = 126
BELT_X1 = BELT_X0 + SLOT_W * MAX_SLOTS          # export starts here
SLOT_TOP, SLOT_BOT = 126, 274
LANES = (-18, 0, 18)
GAP_PX = 30                                       # min spacing between spawns
MAX_ITEMS = 500
SAVE_PATH = Path(__file__).with_name("number_foundry_save.json")

# ------------------------------------------------------------------ colors --
BG, PANEL, CARD, CARD_HOV = "#16324f", "#102741", "#1b3d61", "#244971"
LINE, TEXT, DIM = "#42709f", "#e8f1fa", "#8fb0d0"
BELT, CHEV = "#0d1f33", "#1c4062"
MONEY, GOOD, BAD = "#ffc15e", "#7be0b0", "#ff8080"
PALETTE = ["#bfe3ff", "#8ff0c4", "#f6e77a", "#ffb35c", "#ff7f73", "#f08bff", "#a996ff", "#ffffff"]

MACHINES = {
    "mul": dict(name="Multiplier", sym="\u00d7", color="#ffb347", cost=10, unlock=0),
    "div": dict(name="Divider", sym="\u00f7", color="#6ec8ff", cost=40, unlock=0),
    "pow": dict(name="Exponentiator", sym="^", color="#d6a3ff", cost=500, unlock=2500),
}
MACHINE_ORDER = ["mul", "div", "pow"]

# key: (name, max level, base cost, cost growth, value-as-function-of-level)
UPGRADES = {
    "rate": ("Source speed", 25, 25, 2.2, lambda l: 2.0 * 0.85 ** l),
    "belt": ("Belt speed", 10, 60, 2.8, lambda l: 120.0 * 1.2 ** l),
    "mulq": ("Multiplier quality", 30, 80, 3.6, lambda l: (2 + 0.4 * l, 3 + 0.8 * l)),
    "luck": ("Lucky rolls", 10, 200, 4.5, lambda l: 1 + 0.4 * l),
    "split": ("Splitter capacity", 6, 300, 6.0, lambda l: 3 + l),
    "cap": ("Export crate limit", 30, 300, 7.0, lambda l: 100.0 * 10 ** l),
    "seed": ("Seed value", 9, 600, 6.0, lambda l: 1 + l),
}
UPGRADE_ORDER = list(UPGRADES)
UPGRADE_TIPS = {
    "rate": "How often the source releases a new number. The belt can only carry so many, see Belt speed.",
    "belt": "A faster belt shortens the trip and raises the throughput limit (items can't sit closer than ~30 px).",
    "mulq": "Raises both ends of every Multiplier's random range.",
    "luck": "Multiplier rolls land nearer the top of their range. The range itself doesn't change.",
    "split": "Dividers can cut a number into more pieces at once. Each piece carries an equal share.",
    "cap": "Each delivered number pays at most this much. Anything above it is wasted, so split big numbers up.",
    "seed": "The number the source starts with. It begins at 1.",
}
SHOW = {
    "rate": lambda v: f"{v:.2f}s", "belt": lambda v: f"{v:.0f} px/s",
    "mulq": lambda v: f"\u00d7{v[0]:.1f}\u2013{v[1]:.1f}", "luck": lambda v: f"{v / (v + 1):.0%}",
    "split": lambda v: f"2\u2013{v}", "cap": lambda v: fmt(v), "seed": lambda v: str(v),
}
PREFIX = {"rate": "New item every ", "belt": "Belt ", "mulq": "Multiplier rolls ",
          "luck": "Average roll sits at ", "split": "Divider pieces ", "cap": "Crate limit ",
          "seed": "Source value "}


# ----------------------------------------------------------------- helpers --
def fmt(x):
    """Human-friendly number: 1.23K, 4.5M, ... and scientific past Decillions."""
    ax = abs(x)
    if ax < 1000:
        if abs(x - round(x)) < 0.005:
            return str(int(round(x)))
        return f"{x:.2f}" if ax < 10 else f"{x:.1f}" if ax < 100 else f"{x:.0f}"
    names = ["", "K", "M", "B", "T", "Qa", "Qi", "Sx", "Sp", "Oc", "No", "Dc"]
    e = int(math.log10(ax)) // 3
    if e < len(names):
        return f"{x / 1000 ** e:.2f}{names[e]}"
    return f"{x:.2e}"


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(ca, cb))


def slot_cx(i):
    return BELT_X0 + SLOT_W * (i + 0.5)


class Item:
    __slots__ = ("x", "lane", "val", "nxt")

    def __init__(self, x, lane, val, nxt):
        self.x, self.lane, self.val, self.nxt = x, lane, val, nxt


# --------------------------------------------------------------- simulation --
class Sim:
    def __init__(self):
        self.reset()

    def reset(self):
        self.money, self.total, self.best, self.delivered = 10.0, 0.0, 0.0, 0
        self.lv = {k: 0 for k in UPGRADES}
        self.slots_open = START_SLOTS
        self.slots = [None] * MAX_SLOTS
        self.pow_unlocked = False
        self.items, self.floaters, self.recent = [], [], deque()
        self.t = self.phase = self.since_spawn = 0.0
        self.export_flash = self.last_paid = 0.0

    # parameters derived from upgrade levels
    def p(self, key, level=None):
        return UPGRADES[key][4](self.lv[key] if level is None else level)

    def upgrade_cost(self, key):
        _, _, base, growth, _ = UPGRADES[key]
        return base * growth ** self.lv[key]

    def slot_cost(self):
        return 400.0 * 12 ** (self.slots_open - START_SLOTS)

    def income(self):
        while self.recent and self.recent[0][0] < self.t - 10:
            self.recent.popleft()
        return sum(v for _, v in self.recent) / max(2.0, min(10.0, self.t))

    # ---- player actions (return an error message or None)
    def place(self, i, typ):
        if i >= self.slots_open:
            return "That slot is still locked."
        spec, old = MACHINES[typ], self.slots[i]
        if old and old["type"] == typ:
            return None
        refund = MACHINES[old["type"]]["cost"] * 0.5 if old else 0
        if self.money + refund < spec["cost"]:
            return "Not enough money."
        self.money += refund - spec["cost"]
        self.slots[i] = {"type": typ, "last": None, "flash": 0.0}

    def sell(self, i):
        m = self.slots[i] if i < self.slots_open else None
        if m:
            self.money += MACHINES[m["type"]]["cost"] * 0.5
            self.slots[i] = None

    def unlock_slot(self):
        if self.slots_open >= MAX_SLOTS:
            return None
        if self.money < self.slot_cost():
            return "Not enough money."
        self.money -= self.slot_cost()
        self.slots_open += 1

    def unlock_machine(self, typ):
        if self.money < MACHINES[typ]["unlock"]:
            return "Not enough money."
        self.money -= MACHINES[typ]["unlock"]
        self.pow_unlocked = True

    def buy_upgrade(self, key):
        if self.lv[key] >= UPGRADES[key][1]:
            return None
        if self.money < self.upgrade_cost(key):
            return "Not enough money."
        self.money -= self.upgrade_cost(key)
        self.lv[key] += 1

    # ---- simulation
    def pop(self, x, y, text, color):
        if len(self.floaters) < 60:
            self.floaters.append([x, y, text, color, 1.0])

    def update(self, dt):
        self.t += dt
        spd = self.p("belt")
        self.phase = (self.phase + spd * dt) % 26
        self.since_spawn += dt
        need = max(self.p("rate"), GAP_PX / spd)
        if self.since_spawn >= need:
            self.since_spawn = min(self.since_spawn - need, need)
            if len(self.items) < MAX_ITEMS:
                self.items.append(Item(BELT_X0, 0, float(self.p("seed")), 0))

        keep, new = [], []
        for it in self.items:
            it.x += spd * dt
            while it.nxt < MAX_SLOTS and it.x >= slot_cx(it.nxt):
                si = it.nxt
                it.nxt += 1
                if si < self.slots_open and self.slots[si]:
                    self.process(it, si, new)
            if it.x >= BELT_X1:
                self.deliver(it)
            else:
                keep.append(it)
        self.items = keep + new

        for m in self.slots:
            if m:
                m["flash"] = max(0.0, m["flash"] - dt)
        self.export_flash = max(0.0, self.export_flash - dt)
        for f in self.floaters:
            f[1] -= 28 * dt
            f[4] -= dt * 1.1
        self.floaters = [f for f in self.floaters if f[4] > 0]

    def process(self, it, si, new):
        m = self.slots[si]
        m["flash"] = 0.25
        cx, typ = slot_cx(si), m["type"]
        color = MACHINES[typ]["color"]
        if typ == "mul":
            lo, hi = self.p("mulq")
            f = round(lo + (hi - lo) * random.random() ** (1.0 / self.p("luck")), 2)
            it.val *= f
            m["last"] = f"\u00d7{f:.2f}"
        elif typ == "pow":
            e = round(random.uniform(1.10, 1.35), 2)
            it.val **= e
            m["last"] = f"^{e:.2f}"
        else:
            d = random.randint(2, self.p("split"))
            if len(self.items) + len(new) + d > MAX_ITEMS:
                self.pop(cx, SLOT_TOP - 10, "belt full!", BAD)
                return
            it.val /= d
            it.lane = LANES[0]
            for k in range(1, d):
                new.append(Item(it.x - (k // 3) * 24, LANES[k % 3], it.val, it.nxt))
            m["last"] = f"\u00f7{d}"
        self.pop(cx, SLOT_TOP - 10, m["last"], color)

    def deliver(self, it):
        cap = self.p("cap")
        paid = min(it.val, cap)
        self.money += paid
        self.total += paid
        self.best = max(self.best, paid)
        self.delivered += 1
        self.last_paid = paid
        self.export_flash = 0.2
        self.recent.append((self.t, paid))
        self.pop(BELT_X1 + 85 + random.randint(-30, 30), 114, "+$" + fmt(paid), GOOD)
        if it.val > cap * 1.000001:
            self.pop(BELT_X1 + 85, 96, "over the limit", MONEY)

    # ---- persistence
    def save(self):
        d = dict(money=self.money, total=self.total, best=self.best, delivered=self.delivered,
                 lv=self.lv, slots_open=self.slots_open, pow_unlocked=self.pow_unlocked,
                 slots=[m["type"] if m else None for m in self.slots])
        try:
            SAVE_PATH.write_text(json.dumps(d))
        except OSError:
            pass

    def load(self):
        try:
            d = json.loads(SAVE_PATH.read_text())
            self.money, self.total = float(d["money"]), float(d["total"])
            self.best, self.delivered = float(d["best"]), int(d["delivered"])
            for k in UPGRADES:
                self.lv[k] = max(0, min(int(d["lv"].get(k, 0)), UPGRADES[k][1]))
            self.slots_open = max(START_SLOTS, min(int(d["slots_open"]), MAX_SLOTS))
            self.pow_unlocked = bool(d["pow_unlocked"])
            for i, typ in enumerate(d["slots"][:MAX_SLOTS]):
                if typ in MACHINES and i < self.slots_open:
                    self.slots[i] = {"type": typ, "last": None, "flash": 0.0}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self.reset()


# ---------------------------------------------------------------------- UI --
class App:
    def __init__(self, root):
        self.root = root
        root.title("Number Foundry")
        root.resizable(False, False)
        self.c = tk.Canvas(root, width=W, height=H, bg=BG, highlightthickness=0)
        self.c.pack()
        fams = set(tkfont.families())
        self.fam = next((f for f in ("Segoe UI", "Helvetica Neue", "DejaVu Sans", "Arial") if f in fams), "Helvetica")
        self.mono = next((f for f in ("Consolas", "Menlo", "DejaVu Sans Mono", "Courier New") if f in fams), "Courier")
        self.sim = Sim()
        self.sim.load()
        self.tool, self.paused = None, False
        self.msg, self.msg_until = "", 0.0
        self.mouse, self.hits, self.tip = (-1, -1), [], ""
        c = self.c
        c.bind("<Button-1>", lambda e: self.click(e.x, e.y, False))
        c.bind("<Button-3>", lambda e: self.click(e.x, e.y, True))
        if sys.platform == "darwin":
            c.bind("<Button-2>", lambda e: self.click(e.x, e.y, True))
            c.bind("<Control-Button-1>", lambda e: self.click(e.x, e.y, True))
        c.bind("<Motion>", lambda e: setattr(self, "mouse", (e.x, e.y)))
        c.bind("<Leave>", lambda e: setattr(self, "mouse", (-1, -1)))
        root.bind("<Key>", self.key)
        root.protocol("WM_DELETE_WINDOW", self.close)
        c.create_rectangle(0, 0, W, HEADER_H, fill=PANEL, outline="")
        c.create_rectangle(0, 346, W, H, fill=PANEL, outline="")
        c.create_rectangle(SRC_X1, BELT_Y - 32, BELT_X1, BELT_Y + 32, fill=BELT, outline=LINE)
        self.last = self.last_save = time.perf_counter()
        self.flash("You have $10. Pick the Multiplier below, then click a slot on the belt.")
        self.frame()

    # ---- fonts / drawing helpers
    def F(self, px, weight="normal"):
        return (self.fam, -px, weight)

    def text(self, x, y, s, size=12, color=TEXT, anchor="center", weight="normal", mono=False):
        font = (self.mono, -size, weight) if mono else self.F(size, weight)
        self.c.create_text(x, y, text=s, fill=color, anchor=anchor, font=font, tags="dyn")

    def rrect(self, x0, y0, x1, y1, r=8, **kw):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
               x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        self.c.create_polygon(pts, smooth=True, tags="dyn", **kw)

    def hit(self, x0, y0, x1, y1, kind, arg=None, tip=""):
        self.hits.append((x0, y0, x1, y1, kind, arg))
        mx, my = self.mouse
        hov = x0 <= mx <= x1 and y0 <= my <= y1
        if hov and tip:
            self.tip = tip
        return hov

    def flash(self, msg):
        self.msg, self.msg_until = msg, time.perf_counter() + 3.5

    # ---- input
    def key(self, e):
        s = self.sim
        if e.keysym == "space":
            self.paused = not self.paused
        elif e.keysym == "Escape":
            self.tool = None
        elif e.keysym in ("1", "2", "3"):
            k = MACHINE_ORDER[int(e.keysym) - 1]
            if k != "pow" or s.pow_unlocked:
                self.tool = None if self.tool == k else k

    def click(self, x, y, right):
        for x0, y0, x1, y1, kind, arg in reversed(self.hits):
            if x0 <= x <= x1 and y0 <= y <= y1:
                return self.act(kind, arg, right)
        if right:
            self.tool = None

    def act(self, kind, arg, right):
        s, msg = self.sim, None
        if kind == "slot":
            if right:
                s.sell(arg)
            elif self.tool:
                msg = s.place(arg, self.tool)
            elif not s.slots[arg]:
                msg = "Pick a machine below first (or press 1, 2, 3)."
        elif kind == "tool" and not right:
            if arg == "pow" and not s.pow_unlocked:
                msg = s.unlock_machine("pow")
                if s.pow_unlocked:
                    self.tool = "pow"
            else:
                self.tool = None if self.tool == arg else arg
        elif kind == "unlock":
            msg = s.unlock_slot()
        elif kind == "upgrade":
            msg = s.buy_upgrade(arg)
        elif kind == "pause":
            self.paused = not self.paused
        elif kind == "reset":
            if messagebox.askyesno("Reset", "Delete all progress and start over?"):
                s.reset()
                self.tool = None
                s.save()
        if msg:
            self.flash(msg)

    def close(self):
        self.sim.save()
        self.root.destroy()

    # ---- main loop
    def frame(self):
        now = time.perf_counter()
        dt, self.last = min(now - self.last, 0.05), now
        if not self.paused:
            self.sim.update(dt)
        if now - self.last_save > 20:
            self.sim.save()
            self.last_save = now
        self.draw()
        self.root.after(16, self.frame)

    def draw(self):
        self.c.delete("dyn")
        self.hits, self.tip = [], ""
        self.draw_header()
        self.draw_factory()
        self.draw_machines()
        self.draw_upgrades()
        self.draw_status()

    def draw_header(self):
        s = self.sim
        self.text(24, 18, "Number Foundry", 15, DIM, "w", "bold")
        self.text(24, 50, "$" + fmt(s.money), 30, MONEY, "w", "bold")
        stats = [("Income per second", "$" + fmt(s.income())), ("Total exported", "$" + fmt(s.total)),
                 ("Best delivery", "$" + fmt(s.best)), ("Numbers on belt", str(len(s.items)))]
        for i, (label, val) in enumerate(stats):
            x = 400 + i * 200
            self.text(x, 22, label, 12, DIM, "w")
            self.text(x, 50, val, 20, TEXT, "w", "bold")

    def draw_factory(self):
        s, c = self.sim, self.c
        # belt chevrons
        off = s.phase
        x = BELT_X0 + off - 26
        while x < BELT_X1 - 8:
            if x > SRC_X1:
                c.create_line(x, BELT_Y - 7, x + 7, BELT_Y, x, BELT_Y + 7, fill=CHEV, width=2, tags="dyn")
            x += 26
        # source
        self.rrect(24, 150, SRC_X1, 250, 10, fill=CARD, outline=LINE)
        self.text(71, 168, "Source", 13, DIM, weight="bold")
        self.text(71, 203, fmt(s.p("seed")), 30, MONEY, weight="bold")
        self.text(71, 234, f"every {s.p('rate'):.2f}s", 12, DIM)
        # export
        fl = s.export_flash > 0
        self.rrect(BELT_X1, 130, W - 24, 270, 10, fill=mix(CARD, GOOD, 0.35 if fl else 0.0),
                   outline=GOOD if fl else LINE)
        ex = (BELT_X1 + W - 24) / 2
        self.text(ex, 150, "Export", 15, GOOD, weight="bold")
        self.text(ex, 184, "Crate limit", 12, DIM)
        self.text(ex, 206, "$" + fmt(s.p("cap")), 20, TEXT, weight="bold")
        self.text(ex, 238, "Last delivery", 12, DIM)
        self.text(ex, 256, "$" + fmt(s.last_paid), 14, GOOD, weight="bold")
        # slots
        for i in range(MAX_SLOTS):
            self.draw_slot(i)
        # items
        dense = len(s.items) > 140
        for it in s.items:
            y = BELT_Y + it.lane
            v = it.val
            col = PALETTE[0 if v < 1000 else min(len(PALETTE) - 1, int(math.log10(v)) // 3)]
            if dense:
                c.create_oval(it.x - 4, y - 4, it.x + 4, y + 4, fill=col, outline="", tags="dyn")
            else:
                t = fmt(v)
                hw = 6 + 3.6 * len(t)
                c.create_rectangle(it.x - hw, y - 9, it.x + hw, y + 9, fill=col, outline=BELT, tags="dyn")
                self.text(it.x, y, t, 12, "#0d1f33", weight="bold", mono=True)
        # floating texts
        for x, y, t, col, life in s.floaters:
            self.text(x, y, t, 15, mix(BG, col, life * 2.2), weight="bold")

    def draw_slot(self, i):
        s = self.sim
        cx = slot_cx(i)
        x0, x1 = cx - 38, cx + 38
        if i >= s.slots_open:
            self.c.create_rectangle(x0, SLOT_TOP, x1, SLOT_BOT, outline=CHEV, dash=(3, 5), tags="dyn")
            if i == s.slots_open:
                cost = s.slot_cost()
                ok = s.money >= cost
                hov = self.hit(x0, 290, x1, 326, "unlock", tip=f"Unlock slot {i + 1} for ${fmt(cost)}.")
                self.rrect(x0, 290, x1, 326, 6, fill=CARD_HOV if hov else CARD, outline=GOOD if ok else LINE)
                self.text(cx, 300, "Unlock slot", 11, DIM)
                self.text(cx, 316, "$" + fmt(cost), 13, GOOD if ok else BAD, weight="bold")
            return
        m = s.slots[i]
        hov = self.hit(x0 - 2, SLOT_TOP - 4, x1 + 2, SLOT_BOT + 4, "slot", i)
        self.text(cx, 284, str(i + 1), 11, DIM)
        if not m:
            ghost = self.tool and hov
            col = MACHINES[self.tool]["color"] if ghost else CHEV
            self.c.create_rectangle(x0, SLOT_TOP, x1, SLOT_BOT, outline=col, dash=(4, 4), width=2 if ghost else 1, tags="dyn")
            self.text(cx, 147, MACHINES[self.tool]["sym"] if ghost else "+", 26, col, weight="bold")
            if hov:
                self.tip = "Empty slot. Choose a machine below, then click here." if not self.tool else \
                    f"Place a {MACHINES[self.tool]['name']} here for ${MACHINES[self.tool]['cost']}."
            return
        spec = MACHINES[m["type"]]
        col, on = spec["color"], m["flash"] > 0
        self.c.create_rectangle(x0, SLOT_TOP, x1, SLOT_BOT, outline=col, width=3 if on else 2, tags="dyn")
        self.c.create_rectangle(x0 + 4, SLOT_TOP + 4, x1 - 4, SLOT_TOP + 38, fill=col if on else mix(BG, col, 0.28),
                                outline="", tags="dyn")
        self.text(cx, SLOT_TOP + 22, spec["sym"], 28, BG if on else col, weight="bold")
        self.c.create_rectangle(x0 + 4, SLOT_BOT - 38, x1 - 4, SLOT_BOT - 4, fill=mix(BG, col, 0.12), outline="", tags="dyn")
        self.text(cx, SLOT_BOT - 27, self.range_text(m["type"]), 11, DIM)
        self.text(cx, SLOT_BOT - 12, m["last"] or "\u2013", 13, TEXT, weight="bold")
        if hov:
            self.tip = (f"{spec['name']}: {self.machine_desc(m['type'])}  Right-click to sell "
                        f"(+${fmt(spec['cost'] * 0.5)}).")

    def range_text(self, typ):
        s = self.sim
        if typ == "mul":
            lo, hi = s.p("mulq")
            return f"{lo:.1f}\u2013{hi:.1f}"
        return f"2\u2013{s.p('split')}" if typ == "div" else "1.10\u20131.35"

    def machine_desc(self, typ):
        r = self.range_text(typ)
        return {"mul": f"multiplies by a random \u00d7{r}.",
                "div": f"splits a number into {r.replace(chr(0x2013), ' to ')} equal pieces.",
                "pow": f"raises a number to a random power of {r.replace(chr(0x2013), ' to ')}."}[typ]

    def draw_machines(self):
        s = self.sim
        self.text(24, 366, "Machines", 15, TEXT, "w", "bold")
        for n, key in enumerate(MACHINE_ORDER):
            spec = MACHINES[key]
            x0, y0, x1, y1 = 24, 386 + n * 74, 384, 386 + n * 74 + 66
            locked = key == "pow" and not s.pow_unlocked
            price = spec["unlock"] if locked else spec["cost"]
            ok = s.money >= price
            tip = f"{spec['name']} {self.machine_desc(key)}"
            hov = self.hit(x0, y0, x1, y1, "tool", key, tip)
            sel = self.tool == key
            self.rrect(x0, y0, x1, y1, 8, fill=CARD_HOV if hov else CARD, outline=spec["color"] if sel else LINE,
                       width=2 if sel else 1)
            self.rrect(x0 + 10, y0 + 8, x0 + 60, y0 + 58, 6, fill=mix(BG, spec["color"], 0.25), outline="")
            self.text(x0 + 35, y0 + 33, spec["sym"], 28, spec["color"], weight="bold")
            self.text(x0 + 72, y0 + 22, f"{spec['name']}", 15, TEXT, "w", "bold")
            self.text(x0 + 72, y0 + 46, self.range_text(key) if not locked else "Locked", 12, DIM, "w")
            label = f"Unlock ${fmt(price)}" if locked else f"${fmt(price)}"
            self.text(x1 - 12, y0 + 22, label, 14, GOOD if ok else BAD, "e", "bold")
            self.text(x1 - 12, y0 + 46, "selected" if sel else f"key {n + 1}", 12, spec["color"] if sel else DIM, "e")
        for i, line in enumerate(("Click a slot to place the selected machine.",
                                  "Right-click a machine to sell it for half.",
                                  "Space pauses. Esc puts the machine down.")):
            self.text(24, 622 + i * 20, line, 12, DIM, "w")

    def draw_upgrades(self):
        s = self.sim
        self.text(410, 366, "Upgrades", 15, TEXT, "w", "bold")
        for n, key in enumerate(UPGRADE_ORDER):
            name, mx, *_ = UPGRADES[key]
            x0 = 410 + (n % 2) * 386
            y0 = 386 + (n // 2) * 76
            x1, y1 = x0 + 374, y0 + 68
            lvl, cost = s.lv[key], s.upgrade_cost(key)
            maxed = lvl >= mx
            ok = s.money >= cost
            hov = self.hit(x0, y0, x1, y1, "upgrade", key, UPGRADE_TIPS[key])
            self.rrect(x0, y0, x1, y1, 8, fill=CARD_HOV if hov and not maxed else CARD, outline=GOOD if ok and not maxed else LINE)
            self.text(x0 + 12, y0 + 18, name, 14, TEXT, "w", "bold")
            self.text(x1 - 12, y0 + 18, f"Level {lvl}/{mx}", 12, DIM, "e")
            cur = SHOW[key](s.p(key, lvl))
            desc = PREFIX[key] + (cur if maxed else f"{cur} \u2192 {SHOW[key](s.p(key, lvl + 1))}")
            self.text(x0 + 12, y0 + 40, desc, 12, DIM, "w")
            self.text(x1 - 12, y0 + 40, "max" if maxed else "$" + fmt(cost), 13, DIM if maxed else GOOD if ok else BAD, "e", "bold")
            self.c.create_rectangle(x0 + 12, y0 + 55, x1 - 12, y0 + 59, fill=BELT, outline="", tags="dyn")
            if lvl:
                self.c.create_rectangle(x0 + 12, y0 + 55, x0 + 12 + (x1 - x0 - 24) * lvl / mx, y0 + 59,
                                        fill=GOOD, outline="", tags="dyn")
        # pause / reset
        y0 = 386 + 3 * 76
        for j, (kind, label) in enumerate((("pause", "Resume" if self.paused else "Pause"), ("reset", "Reset save"))):
            x0 = 410 + 386 + j * 193
            hov = self.hit(x0, y0, x0 + 181, y0 + 68, kind, tip="Progress is saved automatically." if kind == "reset" else "")
            self.rrect(x0, y0, x0 + 181, y0 + 68, 8, fill=CARD_HOV if hov else CARD, outline=LINE)
            self.text(x0 + 90, y0 + 34, label, 14, TEXT, weight="bold")
        if self.paused:
            self.rrect(W / 2 - 110, 60, W / 2 + 110, 104, 10, fill=PANEL, outline=MONEY)
            self.text(W / 2, 82, "Paused. Press Space.", 15, MONEY, weight="bold")

    def draw_status(self):
        if time.perf_counter() < self.msg_until:
            self.text(24, 336, self.msg, 13, MONEY, "w", "bold")
        elif self.tip:
            self.text(24, 336, self.tip, 13, TEXT, "w")
        elif self.tool:
            self.text(24, 336, f"Placing: {MACHINES[self.tool]['name']}. Click a slot on the belt.", 13, MACHINES[self.tool]["color"], "w")
        else:
            self.text(24, 336, "Numbers pick up a random change at every machine. Reach the Export with the biggest number you can.", 13, DIM, "w")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
