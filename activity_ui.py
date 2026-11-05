"""Activity atlas, dossier and reusable local instruction cards."""

import math

from PIL import Image, ImageDraw

from .catalog import ATTRS, NAMES
from .events import TYPES
from .render import GRAY, INK, TEAL, local_date


def guide(renderer, kind, failed=False):
    activity = kind == "event"
    title = "活动检索指南" if activity else "卡面检索指南"
    sections = (
        [
            (
                "从这里开始",
                [
                    "/查活动 mnr  ·  查角色参与出卡的活动",
                    "/查活动 205  ·  按活动编号查看完整资料",
                    "/活动列表  ·  浏览全部已开启活动",
                ],
            ),
            (
                "用空格组合条件",
                [
                    "类型：马拉松 / 普通、5v5 / 嘉年华、WL",
                    "属性：cute / 粉花、cool / 蓝星、happy / 橙心、",
                    "pure / 绿草、mysterious / 紫月；也支持单字颜色。",
                    "团队：ln、mmj、vbs、ws / wxs、25h / n25、vs。",
                    "角色：沿用查卡的姓名、英文名、缩写和自定义别名。",
                ],
            ),
            (
                "箱活、混活与团队范围",
                [
                    "单写 mmj：匹配加成范围仅属于 MMJ 的活动。",
                    "vbs ws：匹配加成范围恰好为这两个团的活动。",
                    "25h混 / 25h加成：只要求加成范围包含 25 时。",
                    "箱活 / 混活：按加成中的真人团队数区分单团与多团。",
                    "多个角色须同时有活动卡，包含活动报酬卡。",
                    "mmjrin：只查 MMJ 支援的铃；miku 不限制支援团。",
                ],
            ),
            (
                "可以直接照着试",
                [
                    "/查活动 cute 心羽    /查活动 马拉松 橙心",
                    "/查活动 knd hnm      /查活动 mmj len",
                    "/查活动 vbs rui      /查活动 25h vbs加成",
                    "/查活动 箱活 蓝星    /查活动 混活 5v5",
                ],
            ),
            (
                "检索小提示",
                [
                    "条件之间用空格；不同筛选项同时生效。",
                    "纯数字按活动 ID 查询，镜音连请使用 len。",
                    "只展示已经开启的日服活动；结束时间按结算时刻显示。",
                    "角色检索依据活动关联卡，不代表全部剧情登场角色。",
                    "World Link 可能没有单一加成属性，页面会如实标注。",
                ],
            ),
        ]
        if activity
        else [
            (
                "输入名字或编号",
                [
                    "/查卡 mnr   /查卡 花里实乃里   /查卡 实乃里",
                    "/查卡 Hanasato Minori   /查卡 MMJ",
                    "/查卡 1395：查看花前花后、技能、属性及培养资料",
                ],
            ),
            (
                "团队与别名",
                [
                    "ln、mmj、vbs、ws / wxs、n25、vs",
                    "角色支持中日英文名与常用缩写；/查卡角色 查看完整名单。",
                    "卡名片段也可搜索；纯数字优先按卡片 ID 处理。",
                ],
            ),
            (
                "查看结果",
                [
                    "多卡结果全部合为一张长图，不分页、不截断。",
                    "输入图中的卡片 ID 可进入详情；只展示已实装卡片。",
                    "角色或团队请整体输入，查卡暂不使用活动的多条件语法。",
                ],
            ),
        ]
    )
    heights = [86 + len(lines) * 36 for _, lines in sections]
    canvas = renderer.background(1200, 238 + sum(heights) + len(sections) * 20)
    d = ImageDraw.Draw(canvas)
    renderer.text(d, (54, 32), "PJSK  /  QUICK GUIDE", 19, TEAL)
    renderer.text(d, (54, 70), title, 40)
    renderer.text(
        d,
        (54, 133),
        "暂未找到匹配结果，试试调整条件。" if failed else "选好关键词，让查询更顺手。",
        24,
        GRAY,
    )
    y = 198
    for (heading, lines), height in zip(sections, heights):
        d.rounded_rectangle(
            (42, y, 1158, y + height), 20, fill="white", outline="#dbe9e9", width=2
        )
        d.rounded_rectangle((62, y + 25, 68, y + 54), 3, fill=TEAL)
        renderer.text(d, (86, y + 20), heading, 26)
        for i, line in enumerate(lines):
            renderer.text(d, (72, y + 67 + i * 36), line, 23, GRAY)
        y += height + 20
    renderer.text(
        d,
        (54, y + 8),
        "日服社区数据 · 输入 /查活动 帮助 或 /查卡 帮助 再次查看",
        18,
        GRAY,
    )
    return renderer.encode(canvas)


def card_height(record):
    return 286 + math.ceil(len(record["cards"]) / 7) * 120


def event_tile(renderer, record, media, catalog, width=720):
    e = record["event"]
    height = card_height(record)
    canvas = Image.new("RGB", (width, height), "#f3f8fa")
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle(
        (8, 4, width - 8, height - 12), 18, fill="white", outline="#d6e6e8", width=2
    )
    identifier = f"#{e['id']:03d}"
    id_width = math.ceil(renderer.font(25).getlength(identifier))
    title = renderer.ellipsis(e.get("name", ""), width - 80 - id_width, 23)
    heading_width = id_width + 20 + renderer.font(23).getlength(title)
    heading_x = (width - heading_width) / 2
    renderer.text(d, (heading_x, 26), identifier, 25, TEAL, "lt")
    renderer.text(d, (heading_x + id_width + 20, 28), title, 23, INK, "lt")
    attributes = (
        " / ".join(ATTRS[a] for a in sorted(record["attrs"])) or "多属性 / 无固定属性"
    )
    info = [
        (TYPES.get(e.get("eventType"), e.get("eventType")), 22, INK),
        ("始 " + local_date(e.get("startAt")), 18, GRAY),
        ("终 " + local_date(e.get("aggregateAt")), 18, GRAY),
        (attributes, 18, TEAL),
    ]
    info_width = min(
        width - 368,
        math.ceil(
            max(renderer.font(size).getlength(str(text)) for text, size, _ in info)
        ),
    )
    left = (width - 280 - 24 - info_width) // 2
    renderer.art(canvas, media.get(f"event:{e['id']}"), (left, 79, 280, 122))
    for i, (text, size, color) in enumerate(info):
        renderer.text(
            d,
            (left + 304, 78 + i * 34),
            renderer.ellipsis(text, info_width, size),
            size,
            color,
            "lt",
        )
    names = (
        " · ".join(
            {
                "light_sound": "Leo/need",
                "idol": "MMJ",
                "street": "VBS",
                "theme_park": "W×S",
                "school_refusal": "25时",
                "piapro": "VS",
            }.get(u, u)
            for u in sorted(record["units"])
        )
        or "主数据未提供团队范围"
    )
    renderer.text(
        d, (width // 2, 228), renderer.ellipsis(names, width - 64, 18), 18, GRAY, "mt"
    )
    for i, card in enumerate(record["cards"]):
        row_count = min(7, len(record["cards"]) - i // 7 * 7)
        row_width = row_count * 86 + (row_count - 1) * 11
        x, y = (width - row_width) // 2 + i % 7 * 97, 270 + i // 7 * 120
        renderer.thumb(canvas, card, media.get(f"card:{card['id']}"), x, y, 86)
        renderer.text(d, (x + 43, y + 94), str(card["id"]), 15, GRAY, "mt")
    return canvas


def atlas(renderer, records, media, catalog, query):
    columns = [records[::2], records[1::2]]
    lengths = [sum(card_height(r) + 18 for r in col) for col in columns]
    content_height = max(lengths)
    width, height = 1500, 174 + content_height + 76

    def parts():
        header = renderer.background(width, 174)
        d = ImageDraw.Draw(header)
        renderer.text(d, (42, 25), "EVENT ARCHIVE  /  日服活动", 21, TEAL)
        renderer.text(d, (42, 65), renderer.ellipsis(query or "全部活动", 1150, 32), 32)
        renderer.text(
            d,
            (42, 118),
            f"共 {len(records)} 项 · 各列最新在前 · /查活动 编号 查看详情",
            21,
            GRAY,
        )
        yield header
        indices, tops, tiles = [0, 0], [0, 0], [None, None]
        for y in range(0, content_height, 512):
            bottom = min(content_height, y + 512)
            row = Image.new("RGB", (width, bottom - y), "#f3f8fa")
            for col in range(2):
                while indices[col] < len(columns[col]):
                    record = columns[col][indices[col]]
                    tile_height = card_height(record)
                    if tops[col] >= bottom:
                        break
                    if tiles[col] is None:
                        tiles[col] = event_tile(renderer, record, media, catalog)
                    first = max(y, tops[col])
                    last = min(bottom, tops[col] + tile_height)
                    if first < last:
                        row.paste(
                            tiles[col].crop(
                                (0, first - tops[col], 720, last - tops[col])
                            ),
                            (20 + col * 740, first - y),
                        )
                    if tops[col] + tile_height + 18 > bottom:
                        break
                    tops[col] += tile_height + 18
                    indices[col] += 1
                    tiles[col] = None
            yield row
        footer = Image.new("RGB", (width, 76), "#f3f8fa")
        renderer.text(
            ImageDraw.Draw(footer),
            (42, 22),
            "UTC+8 · 卡片编号可用 /查卡 查询 · 日服社区镜像",
            20,
            GRAY,
        )
        yield footer

    if width * height > 48_000_000 or height > 65000:
        return renderer.encode_png_rows(width, height, parts())
    canvas = Image.new("RGB", (width, height))
    y = 0
    for part in parts():
        canvas.paste(part, (0, y))
        y += part.height
    return renderer.encode(canvas)


def dossier(renderer, record, media, catalog):
    e, cards, gachas = record["event"], record["cards"], record["gachas"]
    title = renderer.wrap(e.get("name", ""), 34, 1120)
    participants = "、".join(
        NAMES.get(cid, str(cid)).split("|")[0] for cid in sorted(record["participants"])
    )
    people = renderer.wrap(participants or "主数据未提供", 24, 1080)
    rows = [
        (
            "活动编号 / 类型",
            f"{e['id']}  /  {TYPES.get(e.get('eventType'), e.get('eventType'))}",
        ),
        ("开始 · UTC+8", local_date(e.get("startAt"))),
        ("结算 · UTC+8", local_date(e.get("aggregateAt"))),
        ("关闭 · UTC+8", local_date(e.get("closedAt"))),
        (
            "活动加成属性",
            " / ".join(ATTRS[a] for a in sorted(record["attrs"]))
            or "多属性 / 无固定属性",
        ),
    ]
    h = (
        2000
        + len(title) * 48
        + len(people) * 34
        + math.ceil(len(cards) / 8) * 168
        + max(1, len(gachas)) * 260
    )
    canvas = renderer.background(1280, h)
    d = ImageDraw.Draw(canvas)
    renderer.text(d, (44, 28), f"EVENT DOSSIER  /  #{e['id']:03d}", 22, TEAL)
    y = 78
    for line in title:
        renderer.text(d, (44, y), line, 34)
        y += 48
    renderer.art(canvas, media.get(f"event:{e['id']}"), (44, y + 20, 1192, 340))
    y += 390
    for label, value in rows:
        d.rounded_rectangle((44, y, 1236, y + 54), 10, fill="white")
        renderer.text(d, (66, y + 12), label, 23, GRAY)
        renderer.text(d, (430, y + 12), value, 23)
        y += 62
    renderer.title_bar(d, 44, y + 12, 1192, "活动加成角色")
    y += 76
    for line in people:
        renderer.text(d, (64, y), line, 24)
        y += 34
    if record["teams"]:
        for team in record["teams"]:
            for line in renderer.wrap(
                "嘉年华队伍 · " + team.get("teamName", ""), 24, 1120
            ):
                renderer.text(d, (64, y), line, 24, TEAL)
                y += 34
    renderer.title_bar(d, 44, y + 18, 1192, "活动关联卡片 · 含报酬卡")
    y += 84
    for i, card in enumerate(cards):
        x, cy = 55 + i % 8 * 147, y + i // 8 * 168
        renderer.thumb(canvas, card, media.get(f"card:{card['id']}"), x, cy, 128)
        renderer.text(d, (x + 64, cy + 134), f"ID {card['id']}", 18, GRAY, "mt")
    y += math.ceil(len(cards) / 8) * 168
    renderer.title_bar(d, 44, y + 18, 1192, "关联首发卡池")
    y += 84
    if not gachas:
        renderer.text(d, (64, y), "未找到活动期间含本期 pickup 的首发卡池。", 24, GRAY)
        y += 64
    for g in gachas:
        renderer.art(canvas, media.get(f"gacha:{g['id']}"), (64, y, 460, 200))
        lines = renderer.wrap(g.get("name", ""), 26, 620)
        for i, line in enumerate(lines):
            renderer.text(d, (560, y + i * 36), line, 26)
        gy = y + len(lines) * 36 + 10
        renderer.text(d, (560, gy), f"卡池 ID {g['id']}", 22, TEAL)
        renderer.text(d, (560, gy + 38), "始 " + local_date(g.get("startAt")), 21, GRAY)
        renderer.text(d, (560, gy + 72), "终 " + local_date(g.get("endAt")), 21, GRAY)
        y += max(240, len(lines) * 36 + 130)
    renderer.text(
        d,
        (44, y + 24),
        "活动卡片包含报酬卡；加成角色不代表全部剧情登场角色。",
        19,
        GRAY,
    )
    return renderer.encode(canvas.crop((0, 0, 1280, min(h, y + 88))))
