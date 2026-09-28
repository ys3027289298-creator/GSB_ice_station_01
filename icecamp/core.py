"""冰原科考站补给游戏回合制后端。

回合（day）原子结算，阶段顺序固定：
  1. 先由持久天气随机流判定暴风雪（每回合只推进一次）；
  2. 发电机燃料每回合整笔扣除一次，燃料不足则不发电；
  3. 保温层叠加有上限，按层数计算供暖与失温减免；
  4. 氧气按全员（含伤员）每人只计一次扣除，钳到零；
  5. 暴风雪按供暖决定新增伤员；
  6. 先判失败（氧气为零），再判胜利（超过 VICTORY_DAY）。

天气随机流状态随存档保存，读档后续走而非重放；结算期间命令锁定，
游戏结束后任何命令都不再改变状态。
"""
from __future__ import annotations

import random

SAVE_KEYS = (
    "day", "oxygen", "fuel", "materials", "insulation",
    "crew", "injured", "generator_on", "crates", "rng_state",
    "seed", "over", "victory", "log",
)

MAX_OXYGEN = 100
START_OXYGEN = 90
OXYGEN_PER_HEAD = 2
OXYGEN_BLIZZARD = 6

MAX_FUEL = 100
START_FUEL = 60
FUEL_REFILL = 20
GENERATOR_FUEL = 10
GENERATOR_HEAT = 4

MAX_MATERIALS = 100
START_MATERIALS = 40
MATERIALS_PER_MEDKIT = 5
MEDKIT_OXYGEN = 10

MAX_INSULATION = 40
INSULATION_PER_REPAIR = 10
MATERIALS_PER_INSULATION = 1
INSULATION_HEAT_PER_LAYER = 1

BLIZZARD_ROLL = 4
BLIZZARD_INJURY_HEAT = 4

VICTORY_DAY = 8

CRATE_NAMES = ("补给箱A", "补给箱B", "补给箱C")
CRATE_SUPPLIES = {
    "补给箱A": {"fuel": 30},
    "补给箱B": {"materials": 20},
    "补给箱C": {"oxygen": 20},
}

MSG_OK = "命令已执行"
MSG_INVALID = "未知命令"
MSG_FUEL_FULL = "燃料已满"
MSG_MATERIALS_FULL = "材料已满"
MSG_INSULATION_FULL = "保温层已满"
MSG_NO_MATERIALS = "材料不足"
MSG_NO_INJURED = "没有伤员"
MSG_CRATE_EMPTY = "补给箱已拆封"
MSG_NOTHING_TO_UNDO = "没有可撤销的维修"
MSG_TURN_LOCKED = "回合结算中，命令被锁定"
MSG_GAME_OVER = "科考已结束"
MSG_VICTORY = "补给坚持成功"
MSG_DEFEAT = "氧气耗尽，科考失败"
MSG_BLIZZARD = "暴风雪来袭"

CMD_REFUEL = "添加燃料"
CMD_GENERATOR_ON = "启动发电机"
CMD_GENERATOR_OFF = "关闭发电机"
CMD_REPAIR = "维修房间"
CMD_UNDO_REPAIR = "撤销维修"
CMD_MEDKIT = "救治伤员"
CMD_END_TURN = "结束回合"
CRATE_COMMANDS = {name: "拆封%s" % name for name in CRATE_NAMES}


class IceCamp:
    def __init__(self, seed=7):
        self.day = 1
        self.oxygen = START_OXYGEN
        self.fuel = START_FUEL
        self.materials = START_MATERIALS
        self.insulation = 0
        self.crew = 4
        self.injured = 1
        self.generator_on = False
        self.crates = {name: True for name in CRATE_NAMES}
        self.seed = seed
        self.over = False
        self.victory = False
        self.log = []
        self._rng = random.Random(seed)
        self._last_repair = None
        self._settling = False

    @property
    def oxygen_heads(self):
        """耗氧人数：每名队员（含伤员）每回合只计一次。"""
        return self.crew

    @property
    def healthy(self):
        return self.crew - self.injured

    def insulation_layers(self):
        return self.insulation // INSULATION_PER_REPAIR

    def generator_heat(self):
        """本回合供暖：燃料够整笔扣除时才发电，不扣半笔。"""
        if self.generator_on and self.fuel >= GENERATOR_FUEL:
            return GENERATOR_HEAT
        return 0

    def blizzard_hit(self):
        """持久天气随机流推进一格，判定当前回合是否有暴风雪。"""
        return self._rng.randint(1, BLIZZARD_ROLL) == 1

    def apply(self, command):
        if self.over:
            return MSG_GAME_OVER
        if self._settling:
            return MSG_TURN_LOCKED
        if not isinstance(command, str) or command == "":
            return MSG_INVALID
        if command == CMD_REFUEL:
            return self._refuel()
        if command == CMD_GENERATOR_ON:
            self.generator_on = True
            return MSG_OK
        if command == CMD_GENERATOR_OFF:
            self.generator_on = False
            return MSG_OK
        if command == CMD_REPAIR:
            return self._repair()
        if command == CMD_UNDO_REPAIR:
            return self._undo_repair()
        if command == CMD_MEDKIT:
            return self._medkit()
        if command in CRATE_COMMANDS.values():
            name = next(name for name, label in CRATE_COMMANDS.items()
                        if label == command)
            return self._open_crate(name)
        if command == CMD_END_TURN:
            return self._end_turn()
        return MSG_INVALID

    def _refuel(self):
        if self.fuel >= MAX_FUEL:
            return MSG_FUEL_FULL
        self.fuel = min(MAX_FUEL, self.fuel + FUEL_REFILL)
        return MSG_OK

    def _repair(self):
        points = min(INSULATION_PER_REPAIR,
                     MAX_INSULATION - self.insulation)
        if points <= 0:
            return MSG_INSULATION_FULL
        cost = points * MATERIALS_PER_INSULATION
        if self.materials < cost:
            return MSG_NO_MATERIALS
        self.materials -= cost
        self.insulation += points
        self._last_repair = (points, cost)
        return MSG_OK

    def _undo_repair(self):
        if self._last_repair is None:
            return MSG_NOTHING_TO_UNDO
        points, cost = self._last_repair
        self.insulation = max(0, self.insulation - points)
        self.materials = min(MAX_MATERIALS, self.materials + cost)
        self._last_repair = None
        return MSG_OK

    def _medkit(self):
        if self.injured <= 0:
            return MSG_NO_INJURED
        if self.materials < MATERIALS_PER_MEDKIT:
            return MSG_NO_MATERIALS
        self.materials -= MATERIALS_PER_MEDKIT
        self.injured -= 1
        self.oxygen = min(MAX_OXYGEN, self.oxygen + MEDKIT_OXYGEN)
        return MSG_OK

    def _open_crate(self, name):
        """拆封幂等：已拆封的箱子再次拆封不产生任何变化。"""
        if not self.crates.get(name, False):
            return MSG_CRATE_EMPTY
        supplies = CRATE_SUPPLIES[name]
        if "fuel" in supplies:
            self.fuel = min(MAX_FUEL, self.fuel + supplies["fuel"])
        if "materials" in supplies:
            self.materials = min(MAX_MATERIALS,
                                 self.materials + supplies["materials"])
        if "oxygen" in supplies:
            self.oxygen = min(MAX_OXYGEN,
                              self.oxygen + supplies["oxygen"])
        self.crates[name] = False
        return MSG_OK

    def _end_turn(self):
        # 阶段 1：先判定天气，后续阶段共享同一个结果，随机流只推进一次。
        blizzard = self.blizzard_hit()
        events = [MSG_BLIZZARD] if blizzard else []

        # 阶段 2：发电机燃料每回合整笔扣除一次，并决定供暖。
        heat = 0
        if self.generator_on and self.fuel >= GENERATOR_FUEL:
            self.fuel -= GENERATOR_FUEL
            heat += GENERATOR_HEAT

        # 阶段 3：保温层叠加设上限，计入供暖并削减暴风雪失温。
        self.insulation = min(MAX_INSULATION, self.insulation)
        layers = self.insulation_layers()
        heat += layers * INSULATION_HEAT_PER_LAYER
        oxygen_loss = self.oxygen_heads * OXYGEN_PER_HEAD
        if blizzard:
            oxygen_loss += max(0, OXYGEN_BLIZZARD - layers)

        # 阶段 4：氧气按全员只计一次扣除，钳到零，不允许负值。
        new_oxygen = max(0, self.oxygen - oxygen_loss)
        new_injured = self.injured
        if blizzard and heat < BLIZZARD_INJURY_HEAT and self.healthy > 0:
            new_injured += 1

        self._settling = True
        try:
            self.oxygen = new_oxygen
            self.injured = new_injured
            self.log.extend(events)
            self.day += 1
            self._last_repair = None

            # 阶段 5：先判失败再判胜利，氧气为零绝不可能误胜。
            if self.oxygen <= 0:
                self.over = True
                self.victory = False
                return MSG_DEFEAT
            if self.day > VICTORY_DAY:
                self.over = True
                self.victory = True
                return MSG_VICTORY
        finally:
            self._settling = False
        return MSG_OK

    def _dump_rng(self):
        version, internal, gauss = self._rng.getstate()
        return [version, list(internal), gauss]

    def save(self):
        data = {key: getattr(self, key) for key in SAVE_KEYS
                if key not in ("rng_state",)}
        data["crates"] = dict(self.crates)
        data["log"] = list(self.log)
        data["rng_state"] = self._dump_rng()
        return data

    @classmethod
    def load(cls, data):
        if not data:
            raise ValueError("存档数据为空")
        missing = [key for key in SAVE_KEYS if key not in data]
        if missing:
            raise ValueError("存档缺少键: %s" % ",".join(missing))
        camp = cls(seed=data["seed"])
        for key in SAVE_KEYS:
            if key == "rng_state":
                continue
            setattr(camp, key, data[key])
        camp.crates = dict(data["crates"])
        camp.log = list(data["log"])
        version, internal, gauss = data["rng_state"]
        camp._rng.setstate((version, tuple(internal), gauss))
        camp._last_repair = None
        return camp


def run_demo():
    """固定种子演示：脚本化命令序列，输出确定，数秒内跑完一轮。"""
    camp = IceCamp(seed=42)
    script = [
        CMD_GENERATOR_ON, "拆封补给箱C", CMD_REPAIR, CMD_END_TURN,
        CMD_REPAIR, CMD_UNDO_REPAIR, CMD_END_TURN,
        CMD_MEDKIT, CMD_END_TURN,
        "拆封补给箱A", CMD_END_TURN,
        CMD_REPAIR, CMD_END_TURN,
        "拆封补给箱B", CMD_END_TURN,
        CMD_END_TURN,
        CMD_GENERATOR_OFF, CMD_END_TURN,
    ]
    for command in script:
        print("第%d天 [%s] -> %s" % (camp.day, command, camp.apply(command)))
    state = camp.save()
    print("存档:", {key: state[key] for key in
                   ("day", "oxygen", "fuel", "materials",
                    "insulation", "injured", "over", "victory")})
    return camp


if __name__ == "__main__":
    run_demo()
