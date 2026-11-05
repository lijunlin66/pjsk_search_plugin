"""Small, pure projections of master records used by the visual layouts."""

from .catalog import trained, trained_only

SUPPLIES = {
    1: "通常",
    2: "生日 / 周年",
    3: "期间限定",
    4: "Colorful Fes限定",
    5: "Bloom Fes限定",
    6: "团队活动限定",
    7: "联动限定",
}


def variants(card):
    return [True] if trained_only(card) else [False, True] if trained(card) else [False]


def rarity_info(card, catalog):
    return next(
        (
            r
            for r in catalog.tables["cardRarities"]
            if r["cardRarityType"] == card["cardRarityType"]
        ),
        {},
    )


def power_at_level(card, level, after=False):
    values = {
        p["cardParameterType"]: p["power"]
        for p in card.get("cardParameters", [])
        if p.get("cardLevel") == level
    }
    return [
        values.get(f"param{i}", 0)
        + (card.get(f"specialTrainingPower{i}BonusFixed", 0) if after else 0)
        for i in (1, 2, 3)
    ]


def max_power(card, catalog):
    rarity = rarity_info(card, catalog)
    level = rarity.get("trainingMaxLevel", rarity.get("maxLevel", 1))
    return level, power_at_level(card, level, trained(card))


def power_growth(card, catalog):
    rarity = rarity_info(card, catalog)
    levels = sorted(
        {
            1,
            rarity.get("maxLevel", 1),
            rarity.get("trainingMaxLevel", rarity.get("maxLevel", 1)),
        }
    )
    lines = []
    for level in levels:
        after = trained(card) and level == rarity.get("trainingMaxLevel")
        values = power_at_level(card, level, after)
        lines.append(
            f"Lv.{level}{' 特训后' if after else ''}：表演 {values[0]} / 技巧 {values[1]} / 耐力 {values[2]} / 总合 {sum(values)}"
        )
    return lines


def skill_badge(card, catalog):
    types = {
        e.get("skillEffectType")
        for e in catalog.skills.get(card.get("skillId"), {}).get("skillEffects", [])
    }
    if "life_recovery" in types:
        return "LIFE", "#67cd4b"
    if "judgment_up" in types:
        return "JUDGE", "#a88aec"
    return "SCORE", "#20c8e1"


def compact_table(name, rows):
    keys = {
        "gachas": {"id", "name", "assetbundleName", "startAt", "endAt", "gachaPickups"},
        "events": {
            "id",
            "name",
            "assetbundleName",
            "startAt",
            "aggregateAt",
            "closedAt",
            "eventType",
            "unit",
        },
        "costume3ds": {
            "id",
            "name",
            "partType",
            "colorId",
            "colorName",
            "characterId",
            "assetbundleName",
            "howToObtain",
        },
        "costume3dModels": {"id", "costume3dId", "unit", "thumbnailAssetbundleName"},
    }.get(name)
    return (
        [{k: v for k, v in row.items() if k in keys} for row in rows] if keys else rows
    )


def related(card, tables, unit):
    release = card.get("releaseAt", 0)
    # First release pickup banner, not every historical pool containing this card.
    gachas = [
        g
        for g in tables.get("gachas", [])
        if any(p.get("cardId") == card["id"] for p in g.get("gachaPickups", []))
    ]
    gachas.sort(key=lambda g: (abs(g.get("startAt", 0) - release), g["id"]))
    event_ids = {
        r["eventId"]
        for r in tables.get("eventCards", [])
        if r.get("cardId") == card["id"] and r.get("isDisplayCardStory", True)
    }
    events = [e for e in tables.get("events", []) if e["id"] in event_ids]
    events.sort(key=lambda e: (abs(e.get("startAt", 0) - release), e["id"]))
    events = events[:1]
    event_ids = {e["id"] for e in events}
    music_ids = {
        m["musicId"] for m in tables.get("eventMusics", []) if m["eventId"] in event_ids
    }
    musics = [m for m in tables.get("musics", []) if m["id"] in music_ids]
    costume_ids = {
        r["costume3dId"]
        for r in tables.get("cardCostume3ds", [])
        if r.get("cardId") == card["id"]
    }
    costumes = [
        c.copy() for c in tables.get("costume3ds", []) if c["id"] in costume_ids
    ]
    costumes.sort(
        key=lambda c: (
            c.get("colorId", 1),
            {"hair": 0, "head": 1, "body": 2}.get(c.get("partType"), 3),
            c["id"],
        )
    )
    for costume in costumes:
        models = [
            m
            for m in tables.get("costume3dModels", [])
            if m.get("costume3dId") == costume["id"]
        ]
        model = next(
            (m for m in models if m.get("unit") == unit), next(iter(models), {})
        )
        costume["thumbnailAssetbundleName"] = model.get("thumbnailAssetbundleName")
    return {
        "gachas": gachas[:1],
        "events": events,
        "musics": musics[:2],
        "costumes": costumes[:6],
    }
