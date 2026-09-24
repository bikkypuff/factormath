# Number Foundry

A Python/Tkinter factory game: build directional belts, place mathematical machines,
and export numbers to earn money.

Run with Python 3.8+ and Tkinter:

```sh
python FactorMath.py
```

- **B** selects belts. Each new tile costs **$5**; you start with three connected tiles.
- Choose a direction with the arrow buttons or arrow keys, then click tiles to build.
  Clicking an existing belt (or the source) changes its direction for free.
- **R** selects clockwise rotation. Click a belt or the source to rotate it.
- **E** moves the export to an empty tile for free. Connect the source to it by
  following belt arrows. Routes can wind around the board or form an open circle;
  a closed loop must be redirected to the export before production resumes.
- **1 / 2 / 3 / 4** select the Adder, Multiplier, Divider and Exponentiator.
  The Exponentiator is a late-game unlock.
- Select the same machine and click it again, or press **U**, to upgrade an individual
  machine through six levels. Half of all money invested is refunded when sold.
- **Right-click / X** sells a machine for half price, or an empty belt for its full $5.
- **Space / Pause** pauses production while you build.
- **F11 / Fullscreen** toggles fullscreen; **Esc** exits fullscreen or clears the tool.

The longer campaign has 18 contracts, designed to provide roughly an hour of active
progression. Claiming a completed contract awards money and a blueprint. Blueprints
fund three permanent research tracks: export efficiency, machine engineering and
longer overdrive.

Fast consecutive deliveries build a combo worth up to ×1.50. Deliveries also charge
Overdrive; at 100%, press **O** to temporarily double source and belt speed and give
every machine an extra effective level. Upgrading the cooling research extends it.

The board scales with the window. Scroll the sidebar to reach all upgrades on small
screens. Changing the belt route clears numbers in transit. Machines on unused
belts stay placed, but only the route from the source to the export produces income.

Progress saves every 20 seconds and on exit, including contracts, research, machine
levels, Overdrive charge and play time. Existing saves retain their money, upgrades,
belts and machines.

Tests:

```sh
python -m unittest discover -v
```
