"""Display smoke check; uses an isolated save and closes its test window."""
import tempfile
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import FactorMath as game


def main():
    with tempfile.TemporaryDirectory() as directory, patch.object(game, 'SAVE_PATH', Path(directory) / 'save.json'):
        root = tk.Tk()
        errors = []
        root.report_callback_exception = lambda *args: errors.append(args)
        try:
            app = game.App(root)
            for geometry in ('1280x800', '1000x680', '1600x900'):
                root.geometry(geometry)
                root.update()
                app.draw()
                root.update_idletasks()
                assert app.c.winfo_width() > 600, geometry
                assert app.c.winfo_height() > 300, geometry
                ox, oy, size = app.view
                for cell in ((0, 0), (17, 9), (2, 4)):
                    assert app.cell_at(ox + (cell[0] + .5) * size,
                                       oy + (cell[1] + .5) * size) == cell
                assert len(app.c.find_all()) >= game.COLS * game.ROWS
            app.toggle_pause()
            assert app.sim.paused
            app.select_tool('add')
            ox, oy, size = app.view
            app.click(SimpleNamespace(x=ox + 2.5 * size, y=oy + 4.5 * size), False)
            assert app.sim.machines[(2, 4)]['type'] == 'add'
            app.draw()
            app.key(SimpleNamespace(keysym='Up'))
            assert app.direction == 3
            app.toggle_fullscreen()
            root.update()
            assert root.attributes('-fullscreen')
            app.key(SimpleNamespace(keysym='Escape'))
            root.update()
            assert not root.attributes('-fullscreen')
            assert not errors, errors
            print('UI checks passed: three window sizes, canvas hit testing, machine placement, pause, fullscreen and Esc.')
        finally:
            root.destroy()


if __name__ == '__main__':
    main()
