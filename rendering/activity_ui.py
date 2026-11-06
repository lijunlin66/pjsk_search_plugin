"""Activity atlas, dossier and reusable local instruction cards."""

import math
from bisect import bisect_left
from itertools import pairwise

from PIL import Image, ImageDraw

from ..domain.catalog import ATTRS, NAMES
from ..domain.events import TYPES
from .render import GRAY, INK, TEAL, local_date


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


def atlas_batches(records, target_height=14000):
    """Split whole records into at most three contiguous, balanced batches."""
    if not records:
        return []
    heights = [sum(card_height(r) + 18 for r in records[col::2]) for col in (0, 1)]
    count = min(
        3, len(records), max(1, math.ceil((250 + max(heights)) / target_height))
    )
    prefix = [0]
    for record in records:
        prefix.append(prefix[-1] + card_height(record) + 18)
    cuts = [0]
    for i in range(1, count):
        target = prefix[-1] * i / count
        pos = bisect_left(prefix, target)
        candidates = [
            max(cuts[-1] + 1, min(len(records) - (count - i), p))
            for p in (pos - 1, pos)
        ]
        cuts.append(min(candidates, key=lambda p: abs(prefix[p] - target)))
    cuts.append(len(records))
    return [records[first:last] for first, last in pairwise(cuts)]


def atlas(renderer, records, media, catalog, query, page=None, bounded=False):
    columns = [records[::2], records[1::2]]
    lengths = [sum(card_height(r) + 18 for r in col) for col in columns]
    content_height = max(lengths)
    width, height = 1500, 174 + content_height + 76

    def parts():
        header = renderer.background(width, 174)
        d = ImageDraw.Draw(header)
        renderer.text(d, (42, 25), "EVENT ARCHIVE  /  日服活动", 21, TEAL)
        title = query or "全部活动"
        if page:
            title += f" · 第 {page[0]}/{page[1]} 张"
        renderer.text(d, (42, 65), renderer.ellipsis(title, 1400, 32), 32)
        renderer.text(
            d,
            (42, 118),
            (
                f"本图 {len(records)} 项 / 全部 {page[2]} 项"
                if page
                else f"共 {len(records)} 项"
            )
            + " · 各列最新在前 · /查活动 编号 查看详情",
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

    if bounded:
        ratio = min(1, math.sqrt(14_000_000 / (width * height)), 16000 / height)
        output_width, output_height = (
            max(1, int(width * ratio)),
            max(1, int(height * ratio)),
        )
        canvas = Image.new("RGB", (output_width, output_height))
        source_y, dest_y = 0, 0
        for part in parts():
            source_y += part.height
            bottom = source_y * output_height // height
            if bottom > dest_y:
                canvas.paste(
                    part.resize(
                        (output_width, bottom - dest_y), Image.Resampling.LANCZOS
                    ),
                    (0, dest_y),
                )
            dest_y = bottom
        return renderer.encode(canvas)
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
