import json
import unittest

from icecamp import core
from icecamp.core import IceCamp


# 红态 1：天气阶段顺序错误（先扣氧气、后判暴风雪 / 暴风雪当天重复结算）
class WeatherOrderTest(unittest.TestCase):
    def test_blizzard_oxygen_loss_applies_same_day(self):
        camp = IceCamp(seed=6)  # 种子 6 第 1 天必为暴风雪
        oxygen_before = camp.oxygen
        self.assertEqual(camp.apply(core.CMD_END_TURN), core.MSG_OK)
        expected = (
            oxygen_before
            - camp.oxygen_heads * core.OXYGEN_PER_HEAD
            - core.OXYGEN_BLIZZARD
        )
        self.assertEqual(camp.oxygen, expected)
        self.assertIn(core.MSG_BLIZZARD, camp.log)

    def test_blizzard_weather_is_not_consumed_twice(self):
        camp = IceCamp(seed=6)  # 第 1 天暴风雪、第 2 天不是
        camp.apply(core.CMD_END_TURN)
        oxygen_before = camp.oxygen
        camp.apply(core.CMD_END_TURN)
        normal_loss = camp.oxygen_heads * core.OXYGEN_PER_HEAD
        self.assertEqual(oxygen_before - camp.oxygen, normal_loss)

    def test_calm_day_has_no_blizzard_loss(self):
        camp = IceCamp(seed=7)
        oxygen_before = camp.oxygen
        camp.apply(core.CMD_END_TURN)
        self.assertEqual(
            oxygen_before - camp.oxygen,
            camp.oxygen_heads * core.OXYGEN_PER_HEAD,
        )


# 红态 2：发电机燃料重复扣除
class FuelDeductionTest(unittest.TestCase):
    def test_fuel_deducted_once_per_day(self):
        camp = IceCamp(seed=1)
        camp.apply(core.CMD_GENERATOR_ON)
        fuel_before = camp.fuel
        self.assertEqual(camp.apply(core.CMD_END_TURN), core.MSG_OK)
        self.assertEqual(fuel_before - camp.fuel, core.GENERATOR_FUEL)
        self.assertEqual(camp.apply(core.CMD_END_TURN), core.MSG_OK)
        self.assertEqual(fuel_before - camp.fuel, 2 * core.GENERATOR_FUEL)

    def test_fuel_not_deducted_when_generator_off(self):
        camp = IceCamp(seed=1)
        camp.apply(core.CMD_GENERATOR_ON)
        fuel_before = camp.fuel
        camp.apply(core.CMD_GENERATOR_OFF)
        camp.apply(core.CMD_END_TURN)
        self.assertEqual(camp.fuel, fuel_before)

    def test_no_half_deduction_without_enough_fuel(self):
        camp = IceCamp(seed=1)
        camp.apply(core.CMD_GENERATOR_ON)
        camp.fuel = core.GENERATOR_FUEL - 1
        camp.apply(core.CMD_END_TURN)
        self.assertEqual(camp.fuel, core.GENERATOR_FUEL - 1)


# 红态 3：房间保温叠加错误（无限叠加 / 重复计层）
class InsulationStackTest(unittest.TestCase):
    def test_insulation_capped_at_max(self):
        camp = IceCamp(seed=1)
        for _ in range(6):
            camp.apply(core.CMD_REPAIR)
        self.assertEqual(camp.insulation, core.MAX_INSULATION)
        self.assertEqual(camp.apply(core.CMD_REPAIR),
                         core.MSG_INSULATION_FULL)

    def test_layers_counted_once_per_repair(self):
        camp = IceCamp(seed=1)
        camp.apply(core.CMD_REPAIR)
        self.assertEqual(camp.insulation_layers(), 1)
        camp.apply(core.CMD_REPAIR)
        self.assertEqual(camp.insulation_layers(), 2)

    def test_blizzard_loss_reduced_by_insulation_layers(self):
        calm_generator = IceCamp(seed=1)
        calm_generator.apply(core.CMD_GENERATOR_ON)
        for _ in range(2):
            calm_generator.apply(core.CMD_REPAIR)
        # 推进到一个暴风雪日（种子 1 第 4 天为暴风雪）
        blizzard_day = 4
        for _ in range(blizzard_day - 1):
            calm_generator.apply(core.CMD_END_TURN)
        oxygen_before = calm_generator.oxygen
        calm_generator.apply(core.CMD_END_TURN)
        loss = oxygen_before - calm_generator.oxygen
        self.assertEqual(
            loss,
            calm_generator.oxygen_heads * core.OXYGEN_PER_HEAD
            + max(0, core.OXYGEN_BLIZZARD - 2),
        )


# 红态 4：受伤队员氧气被重复计数 + 红态：负氧气导致错误胜负
class OxygenCountTest(unittest.TestCase):
    def test_every_member_uses_oxygen_once(self):
        camp = IceCamp(seed=7)
        self.assertEqual(camp.crew, 4)
        self.assertEqual(camp.injured, 1)
        self.assertEqual(camp.oxygen_heads, 4)
        oxygen_before = camp.oxygen
        camp.apply(core.CMD_END_TURN)
        self.assertEqual(oxygen_before - camp.oxygen,
                         4 * core.OXYGEN_PER_HEAD)

    def test_healed_member_still_counts_once(self):
        camp = IceCamp(seed=7)
        camp.apply(core.CMD_MEDKIT)
        self.assertEqual(camp.injured, 0)
        oxygen_before = camp.oxygen
        camp.apply(core.CMD_END_TURN)
        self.assertEqual(oxygen_before - camp.oxygen,
                         4 * core.OXYGEN_PER_HEAD)

    def test_oxygen_never_negative(self):
        camp = IceCamp(seed=1)
        camp.oxygen = 3
        camp.apply(core.CMD_END_TURN)
        self.assertEqual(camp.oxygen, 0)

    def test_zero_oxygen_is_defeat_not_victory(self):
        camp = IceCamp(seed=1)
        camp.day = core.VICTORY_DAY
        camp.oxygen = 3
        result = camp.apply(core.CMD_END_TURN)
        self.assertEqual(result, core.MSG_DEFEAT)
        self.assertTrue(camp.over)
        self.assertFalse(camp.victory)

    def test_survive_to_final_day_is_victory(self):
        camp = IceCamp(seed=1)
        camp.day = core.VICTORY_DAY
        camp.oxygen = 50
        result = camp.apply(core.CMD_END_TURN)
        self.assertEqual(result, core.MSG_VICTORY)
        self.assertTrue(camp.over)
        self.assertTrue(camp.victory)


# 红态 5：补给箱重复拆封
class CrateIdempotencyTest(unittest.TestCase):
    def test_crate_opens_once(self):
        camp = IceCamp(seed=1)
        self.assertEqual(camp.apply("拆封补给箱C"), core.MSG_OK)
        self.assertFalse(camp.crates["补给箱C"])
        oxygen_after = camp.oxygen
        self.assertEqual(camp.apply("拆封补给箱C"),
                         core.MSG_CRATE_EMPTY)
        self.assertEqual(camp.oxygen, oxygen_after)

    def test_each_crate_can_be_opened_independently(self):
        camp = IceCamp(seed=1)
        fuel_before = camp.fuel
        materials_before = camp.materials
        self.assertEqual(camp.apply("拆封补给箱A"), core.MSG_OK)
        self.assertEqual(camp.apply("拆封补给箱B"), core.MSG_OK)
        self.assertEqual(camp.fuel, min(core.MAX_FUEL, fuel_before + 30))
        self.assertEqual(
            camp.materials,
            min(core.MAX_MATERIALS, materials_before + 20),
        )

    def test_unknown_crate_label_is_invalid(self):
        camp = IceCamp(seed=1)
        self.assertEqual(camp.apply("拆封补给箱D"), core.MSG_INVALID)


# 红态 6：撤销维修后材料没有恢复
class UndoRepairTest(unittest.TestCase):
    def test_undo_restores_materials_and_insulation(self):
        camp = IceCamp(seed=1)
        materials_before = camp.materials
        insulation_before = camp.insulation
        self.assertEqual(camp.apply(core.CMD_REPAIR), core.MSG_OK)
        self.assertEqual(camp.apply(core.CMD_UNDO_REPAIR), core.MSG_OK)
        self.assertEqual(camp.materials, materials_before)
        self.assertEqual(camp.insulation, insulation_before)

    def test_undo_without_repair_rejected(self):
        camp = IceCamp(seed=1)
        self.assertEqual(camp.apply(core.CMD_UNDO_REPAIR),
                         core.MSG_NOTHING_TO_UNDO)

    def test_undo_only_once(self):
        camp = IceCamp(seed=1)
        camp.apply(core.CMD_REPAIR)
        camp.apply(core.CMD_UNDO_REPAIR)
        self.assertEqual(camp.apply(core.CMD_UNDO_REPAIR),
                         core.MSG_NOTHING_TO_UNDO)

    def test_undo_cannot_exceed_materials_capacity(self):
        camp = IceCamp(seed=1)
        camp.apply(core.CMD_REPAIR)
        camp.materials = core.MAX_MATERIALS
        camp.apply(core.CMD_UNDO_REPAIR)
        self.assertEqual(camp.materials, core.MAX_MATERIALS)


# 红态 7：存档后天气随机状态被重置
class WeatherReplayTest(unittest.TestCase):
    def test_same_seed_same_weather_sequence(self):
        first = IceCamp(seed=9)
        second = IceCamp(seed=9)
        for _ in range(6):
            first.apply(core.CMD_END_TURN)
            second.apply(core.CMD_END_TURN)
        self.assertEqual(first.save(), second.save())

    def test_loaded_weather_continues_instead_of_restarting(self):
        camp = IceCamp(seed=9)
        for _ in range(3):
            camp.apply(core.CMD_END_TURN)
        restored = IceCamp.load(json.loads(json.dumps(camp.save())))
        self.assertEqual(restored.log, camp.log)
        for _ in range(4):
            camp.apply(core.CMD_END_TURN)
            restored.apply(core.CMD_END_TURN)
        self.assertEqual(restored.save(), camp.save())

    def test_roundtrip_keeps_all_save_keys(self):
        camp = IceCamp(seed=5)
        camp.apply("拆封补给箱A")
        camp.apply(core.CMD_END_TURN)
        restored = IceCamp.load(json.loads(json.dumps(camp.save())))
        self.assertEqual(restored.save(), camp.save())
        self.assertEqual(set(camp.save()), set(core.SAVE_KEYS))


# 红态 8：结束回合没有锁定
class EndTurnLockTest(unittest.TestCase):
    def test_commands_rejected_after_game_over(self):
        camp = IceCamp(seed=1)
        camp.oxygen = 3
        camp.apply(core.CMD_END_TURN)
        self.assertTrue(camp.over)
        snapshot = camp.save()
        self.assertEqual(camp.apply(core.CMD_REFUEL),
                         core.MSG_GAME_OVER)
        self.assertEqual(camp.apply(core.CMD_END_TURN),
                         core.MSG_GAME_OVER)
        self.assertEqual(camp.apply("拆封补给箱A"),
                         core.MSG_GAME_OVER)
        self.assertEqual(camp.save(), snapshot)

    def test_victory_locks_game_as_well(self):
        camp = IceCamp(seed=1)
        camp.day = core.VICTORY_DAY
        camp.oxygen = 50
        self.assertEqual(camp.apply(core.CMD_END_TURN),
                         core.MSG_VICTORY)
        self.assertEqual(camp.apply(core.CMD_REPAIR),
                         core.MSG_GAME_OVER)


class IllegalCommandTest(unittest.TestCase):
    def test_unknown_command_rejected(self):
        camp = IceCamp(seed=1)
        snapshot = camp.save()
        self.assertEqual(camp.apply("打开舱门"), core.MSG_INVALID)
        self.assertEqual(camp.apply(None), core.MSG_INVALID)
        self.assertEqual(camp.apply(123), core.MSG_INVALID)
        self.assertEqual(camp.save(), snapshot)

    def test_empty_command_rejected(self):
        camp = IceCamp(seed=1)
        self.assertEqual(camp.apply(""), core.MSG_INVALID)


class EmptyDataTest(unittest.TestCase):
    def test_load_empty_save_rejected(self):
        with self.assertRaises(ValueError):
            IceCamp.load({})

    def test_load_missing_keys_rejected(self):
        with self.assertRaises(ValueError):
            IceCamp.load({"day": 1, "oxygen": 50})

    def test_none_save_rejected(self):
        with self.assertRaises(ValueError):
            IceCamp.load(None)


class CapacityBoundaryTest(unittest.TestCase):
    def test_fuel_cannot_exceed_max(self):
        camp = IceCamp(seed=1)
        camp.fuel = core.MAX_FUEL - 1
        self.assertEqual(camp.apply(core.CMD_REFUEL), core.MSG_OK)
        self.assertEqual(camp.fuel, core.MAX_FUEL)
        self.assertEqual(camp.apply(core.CMD_REFUEL),
                         core.MSG_FUEL_FULL)

    def test_oxygen_capped_at_max(self):
        camp = IceCamp(seed=1)
        camp.oxygen = core.MAX_OXYGEN
        self.assertEqual(camp.apply("拆封补给箱C"), core.MSG_OK)
        self.assertEqual(camp.oxygen, core.MAX_OXYGEN)

    def test_materials_capped_at_max(self):
        camp = IceCamp(seed=1)
        camp.materials = core.MAX_MATERIALS - 5
        self.assertEqual(camp.apply("拆封补给箱B"), core.MSG_OK)
        self.assertEqual(camp.materials, core.MAX_MATERIALS)

    def test_repair_boundary_consumes_only_available_capacity(self):
        camp = IceCamp(seed=1)
        camp.insulation = core.MAX_INSULATION - 3
        materials_before = camp.materials
        result = camp.apply(core.CMD_REPAIR)
        self.assertEqual(result, core.MSG_OK)
        self.assertEqual(camp.insulation, core.MAX_INSULATION)
        self.assertEqual(materials_before - camp.materials, 3)


class DuplicateInputTest(unittest.TestCase):
    def test_duplicate_end_turns_drive_stable_settlement(self):
        camp = IceCamp(seed=7)
        results = [camp.apply(core.CMD_END_TURN) for _ in range(3)]
        self.assertEqual(results, [core.MSG_OK] * 3)
        self.assertEqual(camp.day, 4)

    def test_duplicate_generator_toggle(self):
        camp = IceCamp(seed=1)
        camp.apply(core.CMD_GENERATOR_ON)
        camp.apply(core.CMD_GENERATOR_ON)
        fuel_before = camp.fuel
        camp.apply(core.CMD_END_TURN)
        self.assertEqual(fuel_before - camp.fuel, core.GENERATOR_FUEL)

    def test_duplicate_medkits_stop_without_injured(self):
        camp = IceCamp(seed=1)
        self.assertEqual(camp.apply(core.CMD_MEDKIT), core.MSG_OK)
        self.assertEqual(camp.apply(core.CMD_MEDKIT),
                         core.MSG_NO_INJURED)
        self.assertEqual(camp.injured, 0)

    def test_duplicate_crate_opening_is_idempotent(self):
        camp = IceCamp(seed=1)
        camp.apply("拆封补给箱A")
        fuel_after = camp.fuel
        for _ in range(3):
            self.assertEqual(camp.apply("拆封补给箱A"),
                             core.MSG_CRATE_EMPTY)
        self.assertEqual(camp.fuel, fuel_after)


class DemoTest(unittest.TestCase):
    def test_fixed_demo_runs(self):
        camp = core.run_demo()
        self.assertIsInstance(camp, IceCamp)
        self.assertGreater(camp.day, 1)
        self.assertTrue(camp.over)

    def test_demo_is_deterministic_and_successful(self):
        first = core.run_demo().save()
        second = core.run_demo().save()
        self.assertEqual(first, second)
        self.assertTrue(first["victory"])


if __name__ == "__main__":
    unittest.main()
