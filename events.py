"""Activity associations and deterministic AND filters, independent of AstrBot."""

import time
from collections import defaultdict

from .catalog import ATTRS, norm

TYPES = {
    "marathon": "马拉松",
    "cheerful_carnival": "嘉年华 · 5v5",
    "world_bloom": "World Link",
}
ATTR_ALIASES = {
    "cute": "cute|粉|粉花|花",
    "cool": "cool|蓝|蓝星|星",
    "happy": "happy|橙|黄|橙心|心",
    "pure": "pure|绿|绿草|草",
    "mysterious": "mysterious|紫|紫月|月",
}
TYPE_ALIASES = {
    "marathon": "普通|马拉松|marathon",
    "cheerful_carnival": "5v5|嘉年华|cheerful",
    "world_bloom": "wl|worldlink|worldbloom|世界链接",
}


class QueryError(ValueError):
    pass


class EventIndex:
    def __init__(self, catalog, tables):
        self.catalog = catalog
        self.records = []
        cards, bonuses = defaultdict(list), defaultdict(list)
        units = {r["id"]: r for r in tables["gameCharacterUnits"]}
        now = time.time() * 1000
        for row in tables["eventCards"]:
            card = catalog.cards.get(row["cardId"])
            if card and card.get("releaseAt", 0) <= now:
                cards[row["eventId"]].append(card)
        for row in tables["eventDeckBonuses"]:
            if row.get("bonusRate", 0) > 0:
                bonuses[row["eventId"]].append(row)
        for event in tables["events"]:
            if event.get("startAt", float("inf")) > now:
                continue
            eid = event["id"]
            deck = bonuses[eid]
            participants = {
                units[r["gameCharacterUnitId"]]["gameCharacterId"]
                for r in deck
                if r.get("gameCharacterUnitId") in units
            }
            teams = {
                units[r["gameCharacterUnitId"]]["unit"]
                for r in deck
                if r.get("gameCharacterUnitId") in units
            } - {"piapro", "none"}
            # Explicit team wins; early events used 'none' even for unit stories.
            if event.get("unit") not in (None, "none", "piapro"):
                teams = {event["unit"]}
            ecards = sorted(
                {c["id"]: c for c in cards[eid]}.values(), key=lambda c: c["id"]
            )
            if ecards and all(c["characterId"] >= 21 for c in ecards):
                teams = {"piapro"}
            ids = {c["id"] for c in ecards}
            start, end = event.get("startAt", 0), event.get("aggregateAt", 0)
            gachas = [
                g
                for g in tables.get("gachas", [])
                if start - 86400000 <= g.get("startAt", -1) <= end
                and any(p.get("cardId") in ids for p in g.get("gachaPickups", []))
            ]
            self.records.append(
                {
                    "event": event,
                    "cards": ecards,
                    "units": teams,
                    "participants": participants,
                    "attrs": {
                        r["cardAttr"] for r in deck if r.get("cardAttr") in ATTRS
                    },
                    "gachas": sorted(gachas, key=lambda g: g.get("startAt", 0)),
                    "teams": [
                        r
                        for r in tables.get("cheerfulCarnivalTeams", [])
                        if r.get("eventId") == eid
                    ],
                    "bonuses": deck,
                }
            )
        self.records.sort(
            key=lambda r: (r["event"].get("startAt", 0), r["event"]["id"]), reverse=True
        )
        self.unit_aliases = dict(catalog.unit_aliases)
        self.unit_aliases[norm("25h")] = "school_refusal"

    def search(self, query):
        query = query.strip()
        if query.isdigit():
            return [r for r in self.records if r["event"]["id"] == int(query)]
        if not query or norm(query) in {"全部", "all", "列表", "图鉴"}:
            return self.records
        units, roles, attrs, types = set(), [], set(), set()
        include, shape = False, None
        tokens = (
            [query]
            if norm(query) in self.catalog.aliases or norm(query) in self.unit_aliases
            else query.split()
        )
        for token in tokens:
            key = norm(token)
            if key in {"箱活", "混活"}:
                shape = key
                continue
            if key.endswith(("混", "加成")):
                key = key[:-2] if key.endswith("加成") else key[:-1]
                include = True
            attr = next(
                (a for a, aliases in ATTR_ALIASES.items() if key in aliases.split("|")),
                None,
            )
            typ = next(
                (a for a, aliases in TYPE_ALIASES.items() if key in aliases.split("|")),
                None,
            )
            if attr:
                attrs.add(attr)
            elif typ:
                types.add(typ)
            elif key in self.unit_aliases:
                units.add(self.unit_aliases[key])
            elif key in self.catalog.aliases:
                roles.append((self.catalog.aliases[key], None))
            else:
                scoped = next(
                    (
                        (u, key[len(alias) :])
                        for alias, u in sorted(
                            self.unit_aliases.items(), key=lambda x: -len(x[0])
                        )
                        if key.startswith(alias)
                        and key[len(alias) :] in self.catalog.aliases
                    ),
                    None,
                )
                if scoped:
                    unit, name = scoped
                    roles.append((self.catalog.aliases[name], unit))
                elif len(tokens) == 1:
                    return [
                        r
                        for r in self.records
                        if key in norm(r["event"].get("name", ""))
                    ]
                else:
                    raise QueryError(f"未识别条件：{token}")
        result = []
        for r in self.records:
            if types and r["event"].get("eventType") not in types:
                continue
            if not attrs <= r["attrs"]:
                continue
            if (
                shape == "箱活"
                and len(r["units"]) != 1
                or shape == "混活"
                and len(r["units"]) <= 1
            ):
                continue
            if units:
                actual = (
                    r["units"]
                    if "piapro" not in units
                    else r["units"]
                    | (
                        {"piapro"}
                        if any(c["characterId"] >= 21 for c in r["cards"])
                        else set()
                    )
                )
                required = set(units)
                for ids, scope in roles:
                    if not scope:
                        required |= {
                            self.catalog.characters.get(cid, {}).get("unit")
                            for cid in ids
                            if cid < 21
                        }
                if not (
                    required <= actual
                    if include or required != units
                    else required == actual
                ):
                    continue
            if all(
                any(
                    c["characterId"] in ids
                    and (scope is None or c.get("supportUnit") == scope)
                    for c in r["cards"]
                )
                for ids, scope in roles
            ):
                result.append(r)
        return result
