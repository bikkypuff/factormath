#!/usr/bin/env python3
"""
Number Foundry - a small factory game about numbers.

A "1" leaves the source and rides a belt through your machines. Machines change
the number by a RANDOM amount (you only choose which machine goes where).
Whatever reaches the Export pays money equal to its value - up to the crate
limit - and money buys more machines, belt tiles and upgrades.

Run:  python FactorMath.py        (needs only Python 3.8+ with tkinter)
"""
import json
import math
import random
import time
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import messagebox

# ------------------------------------------------------------------ layout --
W, H = 1280, 800
COLS, ROWS = 18, 10
TILE_COST = 5
TILE_DISTANCE = 64.0
MAX_ITEMS = 500
MAX_VALUE = 1e100
DIRECTIONS = ((1, 0), (0, 1), (-1, 0), (0, -1))
ARROWS = ("\u2192", "\u2193", "\u2190", "\u2191")
SAVE_PATH = Path(__file__).with_name("number_foundry_save.json")

# ------------------------------------------------------------------ colors --
BG, PANEL, CARD, CARD_HOV = "#16324f", "#102741", "#1b3d61", "#244971"
LINE, TEXT, DIM = "#42709f", "#e8f1fa", "#8fb0d0"
BELT, CHEV = "#0d1f33", "#1c4062"
MONEY, GOOD, BAD = "#ffc15e", "#7be0b0", "#ff8080"
PALETTE = ["#bfe3ff", "#8ff0c4", "#f6e77a", "#ffb35c", "#ff7f73", "#f08bff", "#a996ff", "#ffffff"]

MACHINES = {
    "add": dict(name="Adder", sym="+", color="#7be0b0", cost=10, unlock=0),
    "mul": dict(name="Multiplier", sym="\u00d7", color="#ffb347", cost=75, unlock=0),
    "div": dict(name="Divider", sym="\u00f7", color="#6ec8ff", cost=500, unlock=0),
    "pow": dict(name="Exponentiator", sym="^", color="#d6a3ff", cost=50000, unlock=100000),
}
MACHINE_ORDER = ["add", "mul", "div", "pow"]
MAX_MACHINE_LEVEL = 6

# Eighteen escalating contracts form an hour-ish campaign. The exact time depends
# on how actively the player redesigns and upgrades the factory.
ORDER_TARGETS = (50, 250, 1000, 5000, 25000, 100000, 500000, 2e6, 10e6,
                 50e6, 250e6, 1e9, 5e9, 25e9, 100e9, 500e9, 2e12, 10e12)
RESEARCH = {
    "profit": ("Export efficiency", 5, lambda level: level + 1),
    "power": ("Machine engineering", 3, lambda level: (level + 1) * 2),
    "drive": ("Overdrive cooling", 4, lambda level: level + 1),
}

# key: (name, max level, base cost, cost growth, value-as-function-of-level)
UPGRADES = {
    "rate": ("Source speed", 12, 50, 2.3, lambda l: 2.5 * 0.88 ** l),
    "belt": ("Belt speed", 10, 75, 2.5, lambda l: 100.0 * 1.18 ** l),
    "mulq": ("Multiplier quality", 12, 250, 2.7, lambda l: (1.5 + 0.15 * l, 2.0 + 0.25 * l)),
    "luck": ("Lucky rolls", 8, 500, 3.0, lambda l: 1 + 0.35 * l),
    "split": ("Splitter capacity", 6, 1000, 3.0, lambda l: 2 + l),
    "cap": ("Export crate limit", 18, 1000, 4.0, lambda l: 100.0 * 4 ** l),
    "seed": ("Seed value", 12, 2000, 4.0, lambda l: 1 + 2 * l),
}
UPGRADE_ORDER = list(UPGRADES)
UPGRADE_TIPS = {
    "rate": "How often the source releases a new number. A connected route is required to release numbers.",
    "belt": "A faster belt shortens the trip through your factory.",
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



def inside(cell):
    return 0 <= cell[0] < COLS and 0 <= cell[1] < ROWS


def machine(typ, level=1, invested=None):
    return dict(type=typ, level=level,
                invested=MACHINES[typ]["cost"] if invested is None else invested,
                last=None, flash=0.0)


def clock(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class Item:
    __slots__ = ('step', 'progress', 'val')

    def __init__(self, step, progress, val):
        self.step, self.progress, self.val = step, progress, val


class Sim:
    def __init__(self):
        self.reset()

    def reset(self):
        self.money, self.total, self.best, self.delivered = 10.0, 0.0, 0.0, 0
        self.lv = {k: 0 for k in UPGRADES}
        self.research = {k: 0 for k in RESEARCH}
        self.blueprints = self.order = 0
        self.source, self.export, self.source_dir = (1, 4), (5, 4), 0
        self.belts = {(x, 4): 0 for x in range(2, 5)}
        self.machines = {}
        self.pow_unlocked = False
        self.paused = False
        self.items, self.recent = [], deque()
        self.t = self.since_spawn = self.last_paid = 0.0
        self.combo = 0
        self.last_delivery_time = -100.0
        self.overdrive_charge = self.overdrive_time = 0.0
        self.rebuild_route()

    def p(self, key, level=None):
        return UPGRADES[key][4](self.lv[key] if level is None else level)

    def upgrade_cost(self, key):
        _, _, base, growth, _ = UPGRADES[key]
        return base * growth ** self.lv[key]

    def income(self):
        while self.recent and self.recent[0][0] < self.t - 10:
            self.recent.popleft()
        return sum(v for _, v in self.recent) / max(2.0, min(10.0, self.t))

    def order_target(self):
        return ORDER_TARGETS[self.order] if self.order < len(ORDER_TARGETS) else None

    def order_reward(self):
        target = self.order_target()
        return target * 0.25 if target is not None else 0

    def claim_order(self):
        target = self.order_target()
        if target is None:
            return 'All contracts complete. You built a legendary foundry!'
        if self.total < target:
            return f'Export ${fmt(target - self.total)} more to finish this contract.'
        reward = self.order_reward()
        self.money += reward
        self.blueprints += 1
        self.order += 1
        return f'Contract complete: +${fmt(reward)} and +1 blueprint.'

    def research_cost(self, key):
        return RESEARCH[key][2](self.research[key])

    def buy_research(self, key):
        if key not in RESEARCH:
            return 'Unknown research.'
        if self.research[key] >= RESEARCH[key][1]:
            return 'This research is already complete.'
        cost = self.research_cost(key)
        if self.blueprints < cost:
            return f'You need {cost} blueprints.'
        self.blueprints -= cost
        self.research[key] += 1

    def activate_overdrive(self):
        if self.overdrive_time > 0:
            return 'Overdrive is already active.'
        if self.overdrive_charge < 100:
            return f'Overdrive is only {self.overdrive_charge:.0f}% charged.'
        self.overdrive_charge = 0.0
        self.overdrive_time = 15.0 + 5.0 * self.research['drive']

    def machine_upgrade_cost(self, cell):
        m = self.machines[cell]
        return MACHINES[m['type']]['cost'] * 2.5 ** m['level']

    def upgrade_machine(self, cell):
        if cell not in self.machines:
            return 'Place a machine here first.'
        m = self.machines[cell]
        if m['level'] >= MAX_MACHINE_LEVEL:
            return 'This machine is already at maximum level.'
        cost = self.machine_upgrade_cost(cell)
        if self.money < cost:
            return f'You need ${fmt(cost)} to upgrade this machine.'
        self.money -= cost
        m['invested'] += cost
        m['level'] += 1

    def rebuild_route(self):
        # Editing clears in-flight numbers, so an item never repeats a machine
        # because the path underneath it was rearranged.
        self.items = []
        self.since_spawn = 0.0
        self.route = [self.source]
        seen = {self.source}
        cell, direction = self.source, self.source_dir
        while True:
            dx, dy = DIRECTIONS[direction]
            cell = (cell[0] + dx, cell[1] + dy)
            if cell == self.export:
                self.route.append(cell)
                self.route_error = ''
                return
            if cell in seen:
                self.route_error = 'Loop: turn a tile toward the export to finish the route.'
                return
            if not inside(cell) or cell not in self.belts:
                self.route_error = 'Disconnected: follow the arrows and connect the source to export.'
                return
            seen.add(cell)
            self.route.append(cell)
            direction = self.belts[cell]

    def place_belt(self, cell, direction):
        if not inside(cell) or cell == self.export:
            return 'Choose an empty grid tile or an existing belt.'
        if cell == self.source:
            if self.source_dir != direction:
                self.source_dir = direction
                self.rebuild_route()
            return
        if cell not in self.belts:
            if self.money < TILE_COST:
                return 'Not enough money. One belt tile costs $5.'
            self.money -= TILE_COST
        elif self.belts[cell] == direction:
            return
        self.belts[cell] = direction
        self.rebuild_route()

    def rotate(self, cell):
        if cell == self.source:
            return self.place_belt(cell, (self.source_dir + 1) % 4)
        if cell in self.belts:
            return self.place_belt(cell, (self.belts[cell] + 1) % 4)
        return 'Click a belt or the source to rotate it.'

    def move_export(self, cell):
        if cell == self.export:
            return
        if not inside(cell) or cell == self.source or cell in self.belts:
            return 'Place the export on an empty tile beside the end of your belt.'
        self.export = cell
        self.rebuild_route()

    def place(self, cell, typ):
        if cell not in self.belts:
            return 'Machines must be placed on belt tiles.'
        if typ not in MACHINES or (typ == 'pow' and not self.pow_unlocked):
            return 'Unlock the Exponentiator first.'
        old = self.machines.get(cell)
        if old and old['type'] == typ:
            return self.upgrade_machine(cell)
        refund = old['invested'] * 0.5 if old else 0
        if self.money + refund < MACHINES[typ]['cost']:
            return 'Not enough money.'
        self.money += refund - MACHINES[typ]['cost']
        self.machines[cell] = machine(typ)

    def sell(self, cell):
        if cell in self.machines:
            self.money += self.machines.pop(cell)['invested'] * 0.5
        elif cell in self.belts:
            del self.belts[cell]
            self.money += TILE_COST
            self.rebuild_route()
        else:
            return 'Click a machine or belt to sell it. Source and export cannot be sold.'

    def unlock_machine(self, typ):
        if self.pow_unlocked:
            return
        if self.money < MACHINES[typ]['unlock']:
            return 'Not enough money.'
        self.money -= MACHINES[typ]['unlock']
        self.pow_unlocked = True

    def buy_upgrade(self, key):
        if self.lv[key] >= UPGRADES[key][1]:
            return
        if self.money < self.upgrade_cost(key):
            return 'Not enough money.'
        self.money -= self.upgrade_cost(key)
        self.lv[key] += 1

    def update(self, dt):
        if self.paused:
            return
        self.t += dt
        self.overdrive_time = max(0.0, self.overdrive_time - dt)
        if self.t - self.last_delivery_time > 1.5:
            self.combo = 0
        for m in self.machines.values():
            m['flash'] = max(0.0, m['flash'] - dt)
        if self.route_error:
            return
        drive = 2.0 if self.overdrive_time > 0 else 1.0
        spawn_rate = self.p('rate') / drive
        self.since_spawn += dt
        if self.since_spawn >= spawn_rate:
            self.since_spawn = min(self.since_spawn - spawn_rate, spawn_rate)
            if len(self.items) < MAX_ITEMS:
                self.items.append(Item(0, 0.0, float(self.p('seed'))))
        keep, new = [], []
        for it in self.items:
            it.progress += self.p('belt') * drive * dt / TILE_DISTANCE
            while it.progress >= 1 and it.step < len(self.route) - 1:
                it.progress -= 1
                it.step += 1
                cell = self.route[it.step]
                if cell in self.machines:
                    self.process(it, cell, new)
            if it.step == len(self.route) - 1:
                self.deliver(it)
            else:
                keep.append(it)
        self.items = keep + new

    def process(self, it, cell, new):
        m = self.machines[cell]
        m['flash'] = 0.25
        typ = m['type']
        effective_level = m['level'] + self.research['power'] + (1 if self.overdrive_time > 0 else 0)
        if typ == 'add':
            amount = random.randint(effective_level, 3 * effective_level)
            it.val = min(MAX_VALUE, it.val + amount)
            m['last'] = f'+{amount}'
        elif typ == 'mul':
            lo, hi = self.p('mulq')
            lo += 0.12 * (effective_level - 1)
            hi += 0.20 * (effective_level - 1)
            factor = round(lo + (hi - lo) * random.random() ** (1.0 / self.p('luck')), 2)
            it.val = min(MAX_VALUE, it.val * factor)
            m['last'] = f'×{factor:.2f}'
        elif typ == 'pow':
            exponent = round(random.uniform(1.04 + .015 * effective_level,
                                            1.08 + .025 * effective_level), 2)
            # Logarithms prevent an overflow on long, powerful factory routes.
            it.val = 10 ** min(100.0, math.log10(it.val) * exponent) if it.val > 0 else 0.0
            m['last'] = f'^{exponent:.2f}'
        else:
            pieces = random.randint(2, self.p('split') + effective_level - 1)
            if len(self.items) + len(new) + pieces - 1 > MAX_ITEMS:
                m['last'] = 'Full'
                return
            it.val /= pieces
            for _ in range(pieces - 1):
                new.append(Item(it.step, it.progress, it.val))
            m['last'] = f'÷{pieces}'

    def deliver(self, it):
        if self.t - self.last_delivery_time <= 1.5:
            self.combo = min(20, self.combo + 1)
        else:
            self.combo = 0
        self.last_delivery_time = self.t
        combo_bonus = 1.0 + self.combo * 0.025
        research_bonus = 1.0 + self.research['profit'] * 0.15
        paid = min(it.val, self.p('cap')) * combo_bonus * research_bonus
        self.money += paid
        self.total += paid
        self.best = max(self.best, paid)
        self.delivered += 1
        self.last_paid = paid
        self.recent.append((self.t, paid))
        if self.overdrive_time <= 0:
            self.overdrive_charge = min(100.0, self.overdrive_charge + 1.5 +
                                        8.5 * min(1.0, it.val / self.p('cap')))

    def save(self):
        data = dict(version=3, money=self.money, total=self.total, best=self.best,
                    delivered=self.delivered, lv=self.lv, pow_unlocked=self.pow_unlocked,
                    source=list(self.source), source_dir=self.source_dir, export=list(self.export),
                    belts=[[x, y, direction] for (x, y), direction in self.belts.items()],
                    machines=[[x, y, m['type'], m['level'], m['invested']]
                              for (x, y), m in self.machines.items()],
                    paused=self.paused, research=self.research, blueprints=self.blueprints,
                    order=self.order, overdrive_charge=self.overdrive_charge,
                    overdrive_time=self.overdrive_time, play_time=self.t)
        try:
            temporary = SAVE_PATH.with_suffix('.tmp')
            temporary.write_text(json.dumps(data), encoding='utf-8')
            temporary.replace(SAVE_PATH)
        except OSError:
            return 'Could not save progress. Check that the game folder is writable.'

    def load(self):
        if not SAVE_PATH.exists():
            return
        try:
            data = json.loads(SAVE_PATH.read_text(encoding='utf-8'))
            loaded = Sim()
            for key in ('money', 'total', 'best'):
                value = float(data[key])
                if not math.isfinite(value) or value < 0:
                    raise ValueError('Invalid money')
                setattr(loaded, key, value)
            loaded.delivered = max(0, int(data['delivered']))
            loaded.lv = {k: max(0, min(int(data['lv'].get(k, 0)), UPGRADES[k][1])) for k in UPGRADES}
            loaded.pow_unlocked = bool(data['pow_unlocked'])
            version = int(data.get('version', 1))
            if version == 1:
                # Retain every old purchased slot and its machine in a straight route.
                count = max(3, min(10, int(data['slots_open'])))
                loaded.belts = {(x + 2, 4): 0 for x in range(count)}
                loaded.export = (count + 2, 4)
                loaded.machines = {(i + 2, 4): machine(typ)
                                   for i, typ in enumerate(data['slots'][:count]) if typ in MACHINES}
            elif version in (2, 3):
                def cell(value):
                    if len(value) != 2 or any(type(v) is not int for v in value):
                        raise ValueError('Invalid cell')
                    result = tuple(value)
                    if not inside(result):
                        raise ValueError('Cell outside grid')
                    return result
                loaded.source, loaded.export = cell(data['source']), cell(data['export'])
                loaded.source_dir = int(data['source_dir'])
                if loaded.source == loaded.export or loaded.source_dir not in range(4):
                    raise ValueError('Invalid terminals')
                loaded.belts, loaded.machines = {}, {}
                for x, y, direction in data['belts']:
                    pos = cell([x, y])
                    if type(direction) is not int or direction not in range(4) or pos in (loaded.source, loaded.export):
                        raise ValueError('Invalid belt')
                    loaded.belts[pos] = direction
                for entry in data['machines']:
                    if len(entry) not in (3, 5):
                        raise ValueError('Invalid machine')
                    x, y, typ = entry[:3]
                    pos = cell([x, y])
                    if pos not in loaded.belts or typ not in MACHINES:
                        raise ValueError('Invalid machine')
                    if len(entry) == 5:
                        level, invested = int(entry[3]), float(entry[4])
                        if level not in range(1, MAX_MACHINE_LEVEL + 1) or not math.isfinite(invested) or invested < 0:
                            raise ValueError('Invalid machine level')
                        loaded.machines[pos] = machine(typ, level, invested)
                    else:
                        loaded.machines[pos] = machine(typ)
                loaded.paused = bool(data.get('paused', False))
                if version == 3:
                    loaded.research = {k: max(0, min(int(data.get('research', {}).get(k, 0)), RESEARCH[k][1]))
                                       for k in RESEARCH}
                    loaded.blueprints = max(0, int(data.get('blueprints', 0)))
                    loaded.order = max(0, min(int(data.get('order', 0)), len(ORDER_TARGETS)))
                    loaded.overdrive_charge = max(0.0, min(100.0, float(data.get('overdrive_charge', 0))))
                    loaded.overdrive_time = max(0.0, min(60.0, float(data.get('overdrive_time', 0))))
                    loaded.t = max(0.0, float(data.get('play_time', 0)))
            else:
                raise ValueError('Unsupported save version')
            loaded.rebuild_route()
            self.__dict__.update(loaded.__dict__)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
            return 'Save could not be loaded. A fresh factory is open.'


class App:
    def __init__(self, root):
        self.root = root
        root.title('Number Foundry — build your own factory')
        root.geometry(f'{W}x{H}')
        root.minsize(1000, 680)
        root.configure(bg=BG)
        self.sim = Sim()
        load_error = self.sim.load()
        self.tool, self.direction, self.fullscreen = 'belt', 0, False
        self.hover = None
        self.msg_until = 0.0
        self.view = (0, 0, 1)
        self.buttons, self.upgrade_buttons, self.research_buttons = {}, {}, {}
        self.header = tk.Frame(root, bg=PANEL, padx=16, pady=10)
        self.header.pack(fill='x')
        self.balance = self.label(self.header, '', 23, MONEY)
        self.balance.pack(side='left')
        self.stats = self.label(self.header, '', 11, DIM)
        self.stats.pack(side='left', padx=24)
        self.button(self.header, 'Fullscreen · F11', self.toggle_fullscreen).pack(side='right', padx=4)
        self.pause_button = self.button(self.header, 'Pause · Space', self.toggle_pause)
        self.pause_button.pack(side='right', padx=4)
        body = tk.Frame(root, bg=BG)
        body.pack(fill='both', expand=True)
        side_container = tk.Frame(body, bg=PANEL)
        side_container.pack(side='right', fill='y')
        side_canvas = tk.Canvas(side_container, width=290, bg=PANEL, highlightthickness=0)
        scrollbar = tk.Scrollbar(side_container, orient='vertical', command=side_canvas.yview)
        scrollbar.pack(side='right', fill='y')
        side_canvas.pack(side='left', fill='y')
        side_canvas.configure(yscrollcommand=scrollbar.set)
        sidebar = tk.Frame(side_canvas, bg=PANEL, padx=12, pady=8)
        side_window = side_canvas.create_window(0, 0, window=sidebar, anchor='nw', width=290)
        sidebar.bind('<Configure>', lambda e: side_canvas.configure(scrollregion=side_canvas.bbox('all')))
        side_canvas.bind('<Configure>', lambda e: side_canvas.itemconfigure(side_window, width=e.width))
        self.label(sidebar, 'BUILD YOUR FACTORY', 13, TEXT).pack(anchor='w', pady=(0, 6))
        self.add_tool(sidebar, 'belt', 'Belt tile · $5 [B]')
        directions = tk.Frame(sidebar, bg=PANEL)
        directions.pack(fill='x', pady=3)
        self.dir_buttons = []
        for i, arrow in enumerate(ARROWS):
            button = self.button(directions, arrow, lambda i=i: self.set_direction(i))
            button.pack(side='left', expand=True, fill='x', padx=2)
            self.dir_buttons.append(button)
        self.add_tool(sidebar, 'rotate', 'Rotate existing tile · free [R]')
        self.add_tool(sidebar, 'export', 'Move export · free [E]')
        self.add_tool(sidebar, 'sell', 'Sell machine / belt [X]')
        self.add_tool(sidebar, 'machine_up', 'Upgrade placed machine [U]')
        self.label(sidebar, 'MACHINES · place on a belt', 12, DIM).pack(anchor='w', pady=(10, 4))
        for i, typ in enumerate(MACHINE_ORDER):
            self.add_tool(sidebar, typ, f"{MACHINES[typ]['name']} · ${MACHINES[typ]['cost']} [{i + 1}]")
        self.label(sidebar, 'CONTRACT', 12, DIM).pack(anchor='w', pady=(10, 4))
        self.contract_label = self.label(sidebar, '', 10, TEXT)
        self.contract_label.pack(fill='x', pady=2)
        self.claim_button = self.button(sidebar, 'Claim contract reward',
                                        lambda: self.action(self.sim.claim_order))
        self.claim_button.pack(fill='x', pady=2)
        self.overdrive_button = self.button(sidebar, '', lambda: self.action(self.sim.activate_overdrive))
        self.overdrive_button.pack(fill='x', pady=(8, 2))
        self.label(sidebar, 'BLUEPRINT RESEARCH', 12, DIM).pack(anchor='w', pady=(10, 4))
        for key in RESEARCH:
            b = self.button(sidebar, '', lambda key=key: self.action(self.sim.buy_research, key))
            b.pack(fill='x', pady=2)
            self.research_buttons[key] = b
        self.label(sidebar, 'UPGRADES', 12, DIM).pack(anchor='w', pady=(10, 4))
        for key in UPGRADES:
            b = self.button(sidebar, '', lambda key=key: self.action(self.sim.buy_upgrade, key))
            b.pack(fill='x', pady=2)
            b.bind('<Enter>', lambda e, key=key: self.flash(UPGRADE_TIPS[key]))
            self.upgrade_buttons[key] = b
        self.button(sidebar, 'Reset save', self.reset).pack(fill='x', pady=(12, 6))
        def scroll(event):
            side_canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
        def bind_scroll(widget):
            widget.bind('<MouseWheel>', scroll)
            for child in widget.winfo_children():
                bind_scroll(child)
        bind_scroll(sidebar)
        side_canvas.bind('<MouseWheel>', scroll)
        workspace = tk.Frame(body, bg=BG)
        workspace.pack(side='left', fill='both', expand=True)
        self.route_label = self.label(workspace, '', 12, GOOD)
        self.route_label.pack(anchor='w', padx=16, pady=(12, 4))
        self.tool_label = self.label(workspace, '', 11, DIM)
        self.tool_label.pack(anchor='w', padx=16)
        self.c = tk.Canvas(workspace, bg=BG, highlightthickness=0)
        self.c.pack(fill='both', expand=True, padx=12, pady=8)
        self.label(workspace, 'Click to build • Arrow keys choose direction • Right-click sells • Space pauses', 11, DIM).pack(pady=2)
        self.label(workspace, 'Belts refund $5; machines refund 50%. Changing the route clears numbers in transit.', 10, DIM).pack(pady=(0, 10))
        self.status = self.label(root, '', 11, MONEY)
        self.status.pack(fill='x', padx=16, pady=8)
        self.c.bind('<Button-1>', lambda e: self.click(e, False))
        self.c.bind('<Button-3>', lambda e: self.click(e, True))
        self.c.bind('<Motion>', self.motion)
        self.c.bind('<Leave>', lambda e: setattr(self, 'hover', None))
        root.bind('<KeyPress>', self.key)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.last = self.last_save = time.perf_counter()
        self.flash(load_error or 'Start with a $10 Adder. Finish contracts to earn blueprints and grow your factory.')
        self.frame()

    def label(self, parent, text, size=12, color=TEXT):
        return tk.Label(parent, text=text, font=('Segoe UI', size), bg=parent.cget('bg'), fg=color, anchor='w')

    def button(self, parent, text, command):
        return tk.Button(parent, text=text, command=command, font=('Segoe UI', 10),
                         bg=CARD, fg=TEXT, activebackground=CARD_HOV, activeforeground=TEXT,
                         relief='flat', bd=0, padx=8, pady=4, cursor='hand2', takefocus=False)

    def add_tool(self, parent, tool, text):
        button = self.button(parent, text, lambda: self.select_tool(tool))
        button.pack(fill='x', pady=2)
        self.buttons[tool] = button

    def select_tool(self, tool):
        if tool == 'pow' and not self.sim.pow_unlocked:
            error = self.sim.unlock_machine(tool)
            if error:
                self.flash(error)
                return
        self.tool = tool

    def set_direction(self, direction):
        self.direction, self.tool = direction, 'belt'

    def toggle_pause(self):
        self.sim.paused = not self.sim.paused

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self.root.attributes('-fullscreen', self.fullscreen)

    def key(self, event):
        key = event.keysym
        if key == 'F11':
            self.toggle_fullscreen()
        elif key == 'Escape':
            if self.fullscreen:
                self.toggle_fullscreen()
            else:
                self.tool = None
        elif key == 'space':
            self.toggle_pause()
        elif key in ('Right', 'Down', 'Left', 'Up'):
            self.set_direction(('Right', 'Down', 'Left', 'Up').index(key))
        elif key.lower() == 'o':
            self.action(self.sim.activate_overdrive)
        elif key.lower() in ('b', 'r', 'e', 'x', 'u', '1', '2', '3', '4'):
            self.select_tool(dict(b='belt', r='rotate', e='export', x='sell', u='machine_up',
                                  **{'1': 'add', '2': 'mul', '3': 'div', '4': 'pow'})[key.lower()])
        return 'break'

    def cell_at(self, x, y):
        ox, oy, size = self.view
        cell = (int((x - ox) // size), int((y - oy) // size))
        return cell if inside(cell) else None

    def motion(self, event):
        self.hover = self.cell_at(event.x, event.y)

    def click(self, event, right):
        cell = self.cell_at(event.x, event.y)
        if cell is None:
            return
        s = self.sim
        if right or self.tool == 'sell':
            self.action(s.sell, cell)
        elif self.tool == 'belt':
            self.action(s.place_belt, cell, self.direction)
        elif self.tool == 'rotate':
            self.action(s.rotate, cell)
        elif self.tool == 'export':
            self.action(s.move_export, cell)
        elif self.tool == 'machine_up':
            self.action(s.upgrade_machine, cell)
        elif self.tool in MACHINES:
            self.action(s.place, cell, self.tool)

    def action(self, fn, *args):
        error = fn(*args)
        if error:
            self.flash(error)

    def flash(self, text):
        self.status.configure(text=text)
        self.msg_until = time.perf_counter() + 6

    def reset(self):
        if messagebox.askyesno('Reset', 'Delete all progress and start over?', parent=self.root):
            self.sim.reset()
            self.action(self.sim.save)

    def close(self):
        error = self.sim.save()
        if error:
            messagebox.showerror('Save failed', error, parent=self.root)
            return
        self.root.destroy()

    def frame(self):
        now = time.perf_counter()
        dt, self.last = min(now - self.last, 0.05), now
        self.sim.update(dt)
        if now - self.last_save > 20:
            self.action(self.sim.save)
            self.last_save = now
        self.draw()
        self.frame_id = self.root.after(33, self.frame)

    def draw(self):
        s, c = self.sim, self.c
        self.balance.configure(text='$' + fmt(s.money))
        self.stats.configure(text=f'Income ${fmt(s.income())}/s   •   Exported ${fmt(s.total)}\n'
                                  f'Combo ×{1 + s.combo * .025:.2f}   •   Play time {clock(s.t)}   •   Last +${fmt(s.last_paid)}')
        self.pause_button.configure(text='Resume · Space' if s.paused else 'Pause · Space',
                                    bg=MONEY if s.paused else CARD, fg=BG if s.paused else TEXT)
        route_text = s.route_error or f'Connected to export • {len(s.route) - 2} belt tiles on your route'
        available = max(300, self.c.winfo_width() - 12)
        self.route_label.configure(wraplength=available, justify='left')
        self.tool_label.configure(wraplength=available, justify='left')
        self.route_label.configure(text=('PAUSED — build freely  |  ' if s.paused else '') + route_text,
                                   fg=MONEY if s.paused else BAD if s.route_error else GOOD)
        descriptions = {'belt': f'Belt {ARROWS[self.direction]} · $5 per new tile · changing direction is free',
                        'rotate': 'Rotate: click a belt or source to turn it clockwise',
                        'export': 'Export: click an empty tile at the end of your route',
                        'sell': 'Sell: click once for the machine, again for the belt',
                        'machine_up': 'Upgrade: click a placed machine to improve only that machine',
                        None: 'Choose a building tool or machine from the sidebar'}
        self.tool_label.configure(text=descriptions.get(self.tool, 'Machine: click a belt to place it'))
        for key, button in self.buttons.items():
            button.configure(bg=CARD_HOV if self.tool == key else CARD,
                             fg=MONEY if self.tool == key else TEXT)
        for i, typ in enumerate(MACHINE_ORDER):
            spec = MACHINES[typ]
            self.buttons[typ].configure(text=f"{spec['name']} · ${fmt(spec['cost'])} [{i + 1}]")
        if not s.pow_unlocked:
            self.buttons['pow'].configure(text=f"Unlock Exponentiator · ${fmt(MACHINES['pow']['unlock'])} [4]")
        target = s.order_target()
        if target is None:
            self.contract_label.configure(text='All 18 contracts complete!\nYour foundry is legendary.', fg=GOOD)
            self.claim_button.configure(text='Campaign complete', state='disabled')
        else:
            progress = min(1.0, s.total / target)
            self.contract_label.configure(
                text=f'Contract {s.order + 1}/{len(ORDER_TARGETS)}\nExport ${fmt(target)} total  ({progress:.0%})\n'
                     f'Reward: ${fmt(s.order_reward())} + 1 blueprint', fg=TEXT)
            self.claim_button.configure(text='Claim reward' if progress >= 1 else f'Progress {progress:.0%}',
                                        state='normal', fg=GOOD if progress >= 1 else TEXT)
        active_drive = s.overdrive_time > 0
        self.overdrive_button.configure(
            text=(f'OVERDRIVE ACTIVE · {s.overdrive_time:.1f}s' if active_drive else
                  f'Overdrive · {s.overdrive_charge:.0f}% [O]'),
            bg=MONEY if active_drive else CARD_HOV if s.overdrive_charge >= 100 else CARD,
            fg=BG if active_drive else GOOD if s.overdrive_charge >= 100 else TEXT)
        for key, button in self.research_buttons.items():
            name, maximum, _ = RESEARCH[key]
            level = s.research[key]
            cost = s.research_cost(key)
            button.configure(text=f'{name} {level}/{maximum} · ' + ('MAX' if level >= maximum else f'{cost} BP'),
                             fg=DIM if level >= maximum else GOOD if s.blueprints >= cost else TEXT)
        for i, button in enumerate(self.dir_buttons):
            button.configure(bg=GOOD if i == self.direction else CARD, fg=BG if i == self.direction else TEXT)
        for key, button in self.upgrade_buttons.items():
            name, mx, *_ = UPGRADES[key]
            maxed = s.lv[key] >= mx
            price = 'MAX' if maxed else '$' + fmt(s.upgrade_cost(key))
            button.configure(text=f'{name}  {s.lv[key]}/{mx} · {price}',
                             fg=DIM if maxed else GOOD if s.money >= s.upgrade_cost(key) else TEXT)
        if time.perf_counter() > self.msg_until:
            self.status.configure(text=f'{s.blueprints} blueprints • Crate limit ${fmt(s.p("cap"))} • '
                                       'Autosaves every 20 seconds • F11 fullscreen')
        c.delete('all')
        width, height = max(1, c.winfo_width()), max(1, c.winfo_height())
        size = max(1, min(width / COLS, height / ROWS))
        ox, oy = (width - size * COLS) / 2, (height - size * ROWS) / 2
        self.view = (ox, oy, size)
        def center(cell):
            return ox + (cell[0] + 0.5) * size, oy + (cell[1] + 0.5) * size
        font_size = max(8, int(size * 0.2))
        active = set(s.route)
        for y in range(ROWS):
            for x in range(COLS):
                cell = (x, y)
                cx, cy = center(cell)
                half = size / 2
                color = BELT if cell in s.belts else BG
                outline = MONEY if cell == self.hover else CHEV
                c.create_rectangle(cx-half+1, cy-half+1, cx+half-1, cy+half-1, fill=color, outline=outline)
                if cell in s.belts:
                    direction = s.belts[cell]
                    dx, dy = DIRECTIONS[direction]
                    c.create_line(cx-dx*size*.3, cy-dy*size*.3, cx+dx*size*.32, cy+dy*size*.32,
                                  arrow='last', fill=GOOD if cell in active and not s.route_error else DIM, width=2)
                if cell in s.machines:
                    m = s.machines[cell]
                    spec = MACHINES[m['type']]
                    c.create_rectangle(cx-size*.38, cy-size*.43, cx+size*.38, cy-size*.03,
                                       fill=spec['color'] if m['flash'] else CARD, outline=spec['color'])
                    c.create_text(cx, cy-size*.23, text=spec['sym'], fill=BG if m['flash'] else spec['color'],
                                  font=('Segoe UI', font_size+3, 'bold'))
                    detail = f"Lv{m['level']}" + (f"  {m['last']}" if m['last'] else '')
                    c.create_text(cx, cy+size*.34, text=detail, fill=spec['color'],
                                  font=('Segoe UI', max(7, font_size-1)))
        for cell, title, color, detail in ((s.source, 'SOURCE', MONEY, ARROWS[s.source_dir]),
                                           (s.export, 'EXPORT', GOOD, '$')):
            cx, cy = center(cell)
            c.create_rectangle(cx-size*.47, cy-size*.47, cx+size*.47, cy+size*.47, fill=CARD, outline=color, width=2)
            c.create_text(cx, cy-size*.18, text=title, fill=color, font=('Segoe UI', max(7, font_size-1), 'bold'))
            c.create_text(cx, cy+size*.16, text=detail, fill=color, font=('Segoe UI', font_size+5, 'bold'))
        for i, item in enumerate(s.items):
            if item.step >= len(s.route) - 1:
                continue
            x0, y0 = center(s.route[item.step])
            x1, y1 = center(s.route[item.step + 1])
            progress = min(1.0, item.progress)
            cx, cy = x0 + (x1-x0)*progress, y0 + (y1-y0)*progress
            radius = max(3, size*.085)
            c.create_oval(cx-radius, cy-radius, cx+radius, cy+radius, fill=MONEY, outline=BG)
            if len(s.items) < 60:
                c.create_text(cx, cy+size*.2, text=fmt(item.val), fill=TEXT, font=('Segoe UI', max(7, font_size-1)))
        if self.hover is not None and self.tool == 'belt' and self.hover not in s.belts and self.hover not in (s.source, s.export):
            cx, cy = center(self.hover)
            c.create_text(cx, cy, text=ARROWS[self.direction], fill=DIM, font=('Segoe UI', font_size+8))


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
