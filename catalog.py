"""Pure search and game-data interpretation; no AstrBot dependency."""

import re
import time
import unicodedata

# IDs and romanized names follow gameCharacters.json. Chinese aliases are local.
NAMES = {
    1: "星乃一歌|一歌|ick|ichika",
    2: "天马咲希|天馬咲希|咲希|saki|ski",
    3: "望月穗波|望月穂波|穗波|穂波|hnm|honami",
    4: "日野森志步|日野森志歩|志步|志歩|shiho|shho",
    5: "花里实乃里|花里實乃里|实乃里|實乃里|mnr|minori",
    6: "桐谷遥|桐谷遙|遥|遙|hrk|haruka",
    7: "桃井爱莉|桃井愛莉|爱莉|愛莉|airi|air",
    8: "日野森雫|雫|szk|shizuku",
    9: "小豆泽心羽|小豆沢こはね|小豆澤心羽|心羽|こはね|khn|kohane",
    10: "白石杏|杏|an",
    11: "东云彰人|東雲彰人|彰人|akt|akito",
    12: "青柳冬弥|青柳冬彌|冬弥|冬彌|toya|touya|ty",
    13: "天马司|天馬司|司|tks|tsukasa",
    14: "凤笑梦|鳳笑夢|笑梦|笑夢|emu|em",
    15: "草薙宁宁|草薙寧々|草薙寧寧|宁宁|寧々|寧寧|nene|nn",
    16: "神代类|神代類|类|類|rui|ri",
    17: "宵崎奏|奏|knd|kanade",
    18: "朝比奈真冬|真冬|mfy|mafuyu",
    19: "东云绘名|東雲繪名|東雲絵名|绘名|繪名|絵名|ena|en",
    20: "晓山瑞希|曉山瑞希|暁山瑞希|瑞希|mzk|mizuki",
    21: "初音未来|初音未來|初音ミク|未来|ミク|miku|mk|39",
    22: "镜音铃|鏡音鈴|鏡音リン|铃|リン|rin|rn",
    23: "镜音连|鏡音連|鏡音レン|连|レン|len|ln",
    24: "巡音流歌|巡音ルカ|流歌|ルカ|luka|lk",
    25: "MEIKO|咲音美衣子|meiko|亲妈|mk姐",
    26: "KAITO|始音海人|kaito|大哥|kit",
}
UNITS = {
    "light_sound": ("Leo/need", "ln|leo/need|leoneed|狮子团|狮团"),
    "idol": ("MORE MORE JUMP!", "mmj|moremorejump|more more jump!|偶像团"),
    "street": ("Vivid BAD SQUAD", "vbs|vividbadsquad|街头团"),
    "theme_park": (
        "Wonderlands×Showtime",
        "ws|wxs|wonderlands×showtime|wonderlands x showtime|wonderlandsshowtime|奇幻团|天马团",
    ),
    "school_refusal": (
        "25時、ナイトコードで。",
        "25|25时|25時|25时在nightcord。|25时在nightcord|25時、ナイトコードで。|nightcord at 25:00|n25|25ji|ニーゴ|夜团",
    ),
    "piapro": (
        "VIRTUAL SINGER",
        "vs|virtual singer|virtualsinger|虚拟歌手|虛擬歌手|v家",
    ),
}
ATTRS = {
    "cool": "蓝 / Cool",
    "cute": "粉 / Cute",
    "happy": "橙 / Happy",
    "pure": "绿 / Pure",
    "mysterious": "紫 / Mysterious",
}


def norm(value):
    return re.sub(
        r"[\s/!！×、。,，:.：_\-]+",
        "",
        unicodedata.normalize("NFKC", str(value)).casefold(),
    )


def trained(card):
    return card.get("cardRarityType") in {"rarity_3", "rarity_4"} and not trained_only(
        card
    )


def trained_only(card):
    return card.get("initialSpecialTrainingStatus") == "done"


def rarity(card):
    value = card.get("cardRarityType", "")
    return (
        "生日 / 周年"
        if value == "rarity_birthday"
        else value.replace("rarity_", "") + "★"
    )


class Catalog:
    def __init__(self, tables, custom_aliases=""):
        self.tables = tables
        self.cards = {int(c["id"]): c for c in tables["cards"]}
        self.characters = {int(c["id"]): c for c in tables["gameCharacters"]}
        self.skills = {int(s["id"]): s for s in tables["skills"]}
        self.aliases = {}
        for cid, values in NAMES.items():
            for value in values.split("|"):
                self.aliases.setdefault(norm(value), set()).add(cid)
        for cid, c in self.characters.items():
            first, given = c.get("firstName", ""), c.get("givenName", "")
            enfirst, engiven = (
                c.get("firstNameEnglish", ""),
                c.get("givenNameEnglish", ""),
            )
            for value in (
                first + given,
                given,
                enfirst + engiven,
                engiven + enfirst,
                engiven,
            ):
                if value:
                    self.aliases.setdefault(norm(value), set()).add(cid)
        for line in custom_aliases.splitlines():
            if "=" in line:
                key, value = line.rsplit("=", 1)
                if (
                    value.strip().isdigit()
                    and int(value) in self.characters
                    and norm(key)
                ):
                    self.aliases[norm(key)] = {int(value)}
        self.unit_aliases = {
            norm(a): unit
            for unit, (name, aliases) in UNITS.items()
            for a in (name + "|" + aliases).split("|")
        }

    def name(self, card):
        cid = int(card["characterId"])
        c = self.characters.get(cid, {})
        return (
            NAMES[cid].split("|")[0]
            if cid in NAMES
            else c.get("firstName", "") + c.get("givenName", str(cid))
        )

    def unit(self, card):
        return self.characters.get(int(card["characterId"]), {}).get("unit", "unknown")

    def unit_label(self, card):
        unit = self.unit(card)
        label = UNITS.get(unit, (unit, ""))[0]
        support = card.get("supportUnit", "none")
        if support != "none":
            label += " · " + UNITS.get(support, (support, ""))[0]
        return label

    def search(self, query):
        key = norm(query)
        now = int(time.time() * 1000)
        released = [c for c in self.cards.values() if c.get("releaseAt", 0) <= now]
        # Exact numeric IDs take precedence over aliases such as 25 and 39.
        if query.strip().isdigit():
            result = [c for c in released if c["id"] == int(query)]
        elif key in self.aliases:
            result = [c for c in released if c["characterId"] in self.aliases[key]]
        elif key in self.unit_aliases:
            unit = self.unit_aliases[key]
            result = [
                c
                for c in released
                if self.unit(c) == unit or c.get("supportUnit") == unit
            ]
        else:
            result = [c for c in released if key in norm(c.get("prefix", ""))]
        return sorted(
            result, key=lambda c: (c.get("releaseAt", 0), c["id"]), reverse=True
        )


def skill_text(skill, level, character_name="该角色"):
    """Resolve known tokens. Unknown expressions remain explicit, never guessed."""
    effects = {int(e["id"]): e for e in skill.get("skillEffects", [])}

    def replace(match):
        ids, kind = match.group(1), match.group(2)
        if kind == "c":
            return character_name
        selected = [effects.get(int(i)) for i in ids.split(",")]
        if any(e is None for e in selected):
            return match.group(0)
        details = [
            next(
                (d for d in e.get("skillEffectDetails", []) if d.get("level") == level),
                {},
            )
            for e in selected
        ]
        if kind in {"v", "d"} and len(details) == 1:
            value = details[0].get(
                "activateEffectValue" if kind == "v" else "activateEffectDuration"
            )
            return f"{value:g}" if isinstance(value, (int, float)) else match.group(0)
        if kind in {"u", "o", "v"} and len(details) == 2:
            values = [d.get("activateEffectValue") for d in details]
            if all(isinstance(v, (int, float)) for v in values):
                return f"{sum(values):g}"
        if kind in {"r", "s"} and len(details) == 2:
            low, high = (int(i) for i in ids.split(","))
            ranked = [
                e
                for eid, e in effects.items()
                if low <= eid <= high and "activateCharacterRank" in e
            ]
            values = [
                d["activateEffectValue"]
                for e in ranked
                for d in e.get("skillEffectDetails", [])
                if d.get("level") == level
            ]
            if values:
                base = details[0].get("activateEffectValue", 0) if kind == "s" else 0
                return (
                    f"{min(values) + base:g}–{max(values) + base:g}（随角色等级变化）"
                )
        if len(selected) == 1 and kind in {"e", "m"}:
            enhance = selected[0].get("skillEnhance", {}).get("activateEffectValue")
            if enhance is not None:
                value = (
                    enhance
                    if kind == "e"
                    else enhance * 5 + details[0].get("activateEffectValue", 0)
                )
                return f"{value:g}"
        return match.group(0)

    text = re.sub(
        r"\{\{([\d,]+);([a-z]+)\}\}",
        replace,
        skill.get("description", "主数据未提供技能说明"),
    )
    return text + (" [特殊条件公式未解析，请参阅下方效果明细]" if "{{" in text else "")


RESOURCE_LABELS = {
    "id": "ID",
    "cardId": "卡片ID",
    "resourceId": "资源ID",
    "resourceType": "资源类型",
    "resourceLevel": "资源等级",
    "quantity": "数量",
    "cost": "消耗",
    "costs": "消耗",
    "resources": "奖励",
}
RESOURCE_TYPES = {"material": "培养材料", "costume3d": "3D服装", "costume_3d": "3D服装"}


def readable(value):
    """Format the nested cultivation costs used by the detail footer."""
    if isinstance(value, dict):
        return (
            " / ".join(
                f"{RESOURCE_LABELS.get(k, k)}: {readable(v)}"
                for k, v in value.items()
                if k not in {"seq", "assetbundleName", "scenarioId"}
            )
            or "无"
        )
    if isinstance(value, list):
        return "；".join(readable(v) for v in value) or "无"
    if isinstance(value, str):
        return RESOURCE_TYPES.get(value, value)
    return str(value)
