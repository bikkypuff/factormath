import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import FactorMath as game


class FactoryTests(unittest.TestCase):
    def setUp(self):
        self.s = game.Sim()

    def run_factory(self, seconds=12):
        for _ in range(int(seconds / .05)):
            self.s.update(.05)

    def test_starter_factory_earns_money(self):
        self.assertEqual(len(self.s.belts), 3)
        self.assertFalse(self.s.route_error)
        self.run_factory()
        self.assertGreater(self.s.money, 10)

    def test_curved_route_with_machine(self):
        s = self.s
        s.money = 100
        s.move_export((5, 6))
        for cell, direction in [((4, 4), 1), ((4, 5), 1), ((4, 6), 0)]:
            self.assertIsNone(s.place_belt(cell, direction))
        s.place((4, 5), 'mul')
        self.assertFalse(s.route_error)
        self.assertIn((4, 5), s.route)
        self.run_factory()
        self.assertGreater(s.best, 1)

    def test_route_can_wrap_around(self):
        s = self.s
        s.money = 1000
        s.move_export((1, 5))
        for cell, direction in [((4, 4), 1), ((4, 5), 1), ((4, 6), 2),
                                ((3, 6), 2), ((2, 6), 2), ((1, 6), 3)]:
            s.place_belt(cell, direction)
        self.assertFalse(s.route_error)
        self.run_factory()
        self.assertGreater(s.delivered, 0)

    def test_loop_does_not_spawn_or_pay(self):
        self.s.place_belt((3, 4), 2)
        self.assertIn('Loop', self.s.route_error)
        self.run_factory()
        self.assertEqual(self.s.items, [])
        self.assertEqual(self.s.total, 0)

    def test_disconnected_route_recovers(self):
        self.s.sell((3, 4))
        self.run_factory()
        self.assertEqual(self.s.total, 0)
        self.s.place_belt((3, 4), 0)
        self.run_factory()
        self.assertGreater(self.s.total, 0)

    def test_belt_cost_rotation_and_full_refund(self):
        s = self.s
        s.place_belt((2, 2), 0)
        self.assertEqual(s.money, 5)
        s.rotate((2, 2))
        self.assertEqual(s.money, 5)
        self.assertEqual(s.belts[(2, 2)], 1)
        s.sell((2, 2))
        self.assertEqual(s.money, 10)

    def test_cannot_buy_without_money_or_build_over_export(self):
        self.s.money = 0
        self.assertIsNotNone(self.s.place_belt((0, 0), 0))
        self.assertNotIn((0, 0), self.s.belts)
        self.assertIsNotNone(self.s.place_belt(self.s.export, 0))
        self.assertIsNotNone(self.s.move_export((2, 4)))

    def test_machine_requires_belt_and_sells_before_belt(self):
        self.assertIsNotNone(self.s.place((0, 0), 'mul'))
        self.s.money = 100
        self.s.place((2, 4), 'mul')
        self.s.sell((2, 4))
        self.assertIn((2, 4), self.s.belts)
        self.assertNotIn((2, 4), self.s.machines)
        self.assertEqual(self.s.money, 62.5)

    def test_pause_freezes_simulation_but_allows_building(self):
        self.run_factory(3)
        self.s.paused = True
        before = (self.s.t, self.s.money, [(i.step, i.progress, i.val) for i in self.s.items])
        self.run_factory()
        after = (self.s.t, self.s.money, [(i.step, i.progress, i.val) for i in self.s.items])
        self.assertEqual(before, after)
        self.assertIsNone(self.s.place_belt((0, 0), 0))
        self.s.paused = False
        self.run_factory()
        self.assertGreater(self.s.total, 0)

    def test_split_conserves_value(self):
        self.s.money = 1000
        self.s.place((2, 4), 'div')
        item = game.Item(1, 0, 90)
        children = []
        self.s.process(item, (2, 4), children)
        self.assertAlmostEqual(item.val + sum(i.val for i in children), 90)
        self.assertTrue(all(i.step == 1 for i in children))

    def test_large_values_do_not_overflow(self):
        self.s.money = 100000
        self.s.pow_unlocked = True
        self.s.place((2, 4), 'pow')
        item = game.Item(1, 0, game.MAX_VALUE)
        self.s.process(item, (2, 4), [])
        self.assertLessEqual(item.val, game.MAX_VALUE)
        self.s.deliver(item)
        self.assertEqual(self.s.last_paid, self.s.p('cap'))

    def test_save_roundtrip_and_legacy_migration(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(game, 'SAVE_PATH', Path(directory) / 'save.json'):
            self.s.money = 100
            self.s.place((3, 4), 'mul')
            self.s.paused = True
            self.s.lv['belt'] = 2
            self.assertIsNone(self.s.save())
            other = game.Sim()
            self.assertIsNone(other.load())
            self.assertEqual(other.belts, self.s.belts)
            self.assertEqual(other.machines[(3, 4)]['type'], 'mul')
            self.assertTrue(other.paused)
            self.assertEqual(other.lv, self.s.lv)
            legacy = dict(money=123, total=456, best=78, delivered=9, lv={},
                          pow_unlocked=True, slots_open=10, slots=['mul', 'div', 'pow'] + [None]*7)
            game.SAVE_PATH.write_text(json.dumps(legacy))
            self.assertIsNone(other.load())
            self.assertEqual(len(other.belts), 10)
            self.assertEqual(other.money, 123)
            self.assertEqual(len(other.machines), 3)
            self.assertFalse(other.route_error)

    def test_machine_levels_cost_money_and_increase_power(self):
        self.s.money = 1000
        self.s.place((2, 4), 'add')
        cost = self.s.machine_upgrade_cost((2, 4))
        before = self.s.money
        self.assertIsNone(self.s.upgrade_machine((2, 4)))
        self.assertEqual(self.s.machines[(2, 4)]['level'], 2)
        self.assertAlmostEqual(self.s.money, before - cost)
        self.assertGreater(self.s.machines[(2, 4)]['invested'], game.MACHINES['add']['cost'])

    def test_contract_rewards_blueprint_and_research(self):
        self.s.total = game.ORDER_TARGETS[0]
        reward = self.s.order_reward()
        message = self.s.claim_order()
        self.assertIn('Contract complete', message)
        self.assertEqual(self.s.order, 1)
        self.assertEqual(self.s.blueprints, 1)
        self.assertEqual(self.s.money, 10 + reward)
        self.assertIsNone(self.s.buy_research('profit'))
        self.assertEqual(self.s.research['profit'], 1)
        self.assertEqual(self.s.blueprints, 0)

    def test_combo_increases_payout_and_expires(self):
        item = game.Item(0, 0, 10)
        self.s.deliver(item)
        first = self.s.last_paid
        self.s.deliver(item)
        self.assertGreater(self.s.last_paid, first)
        self.s.update(2)
        self.assertEqual(self.s.combo, 0)

    def test_overdrive_must_charge_and_then_expires(self):
        self.assertIsNotNone(self.s.activate_overdrive())
        self.s.overdrive_charge = 100
        self.assertIsNone(self.s.activate_overdrive())
        self.assertGreater(self.s.overdrive_time, 0)
        self.s.update(self.s.overdrive_time + .1)
        self.assertEqual(self.s.overdrive_time, 0)

    def test_invalid_save_does_not_partially_load(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(game, 'SAVE_PATH', Path(directory) / 'save.json'):
            self.s.save()
            data = json.loads(game.SAVE_PATH.read_text())
            data['money'] = 999
            data['belts'] = [[100, 100, 0]]
            game.SAVE_PATH.write_text(json.dumps(data))
            other = game.Sim()
            self.assertIsNotNone(other.load())
            self.assertEqual(other.money, 10)
            self.assertFalse(other.route_error)


if __name__ == '__main__':
    unittest.main()
