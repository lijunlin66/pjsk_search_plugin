"""Current-event and cutoff cards with explicit region and observation times."""

import math
import time

from PIL import ImageDraw

from ..domain.catalog import ATTRS, NAMES
from ..domain.events import TYPES
from ..services.live import REGIONS, TIERS
from .render import GRAY, INK, local_date


def remaining(event, now):
    seconds = max(0, int((event["aggregateAt"] - now) / 1000))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    return f"{days}天 {hours}小时 {minutes}分钟"


def centered(renderer, draw, box, text, size=22, color=INK):
    """Center actual glyph bounds rather than the font baseline."""
    x, y, w, h = box
    value = str(text)
    font = renderer.font(size)
    left, top, right, bottom = draw.textbbox((0, 0), value, font=font)
    draw.text(
        (x + (w - right + left) / 2 - left, y + (h - bottom + top) / 2 - top),
        value,
        font=font,
        fill=color,
    )


def live_image(renderer, current, banner=None, borders=False):
    event, region = current["event"], current["region"]
    now = int(time.time() * 1000)
    title = renderer.wrap(event["name"], 32, 1080)
    ranking = current.get("ranking", {})
    tiers = [
        r for r in ranking.get("rankings", []) if r["rank"] in TIERS or r["rank"] > 100
    ][:100]
    info = []
    if not borders:
        info = [
            (
                "活动属性",
                " / ".join(ATTRS[a] for a in current.get("attrs", []))
                or "多属性 / 暂无固定属性记录",
            ),
            (
                "加成角色",
                "、".join(current.get("participants", [])) or "关联资料暂未提供",
            ),
        ]
    rows = [(label, renderer.wrap(value, 23, 780)) for label, value in info]
    details = {r["id"]: r for r in current.get("card_details", [])}
    card_ids = [
        cid for cid in current.get("cards", []) if cid in details
    ] or current.get("cards", [])
    grid_rows = math.ceil(len(card_ids) / 6)
    base = 740 + len(title) * 42
    content = (
        math.ceil(len(tiers) / 2) * 62 + 130
        if borders
        else sum(max(70, len(value) * 34 + 24) for _, value in rows)
        + grid_rows * 224
        + 130
    )
    canvas = renderer.background(1200, base + content + 180)
    d = ImageDraw.Draw(canvas)
    renderer.title_bar(
        d,
        40,
        28,
        1120,
        f"{REGIONS[region]} · {'当前活动榜线 · 综合榜' if borders else '当前正在进行的活动'}",
    )
    y = 96
    for line in title:
        centered(renderer, d, (40, y, 1120, 42), line, 32)
        y += 42
    centered(
        renderer,
        d,
        (40, y + 4, 1120, 36),
        f"活动 #{event['id']}  ·  {TYPES.get(event.get('eventType'), event.get('eventType', '未提供'))}",
        22,
        GRAY,
    )
    renderer.art(canvas, banner, (340, y + 58, 520, 220))
    y += 302
    for label, value in [
        ("开始 · UTC+8", local_date(event["startAt"])),
        ("结算 · UTC+8", local_date(event["aggregateAt"])),
        ("剩余时间", remaining(event, now)),
    ]:
        d.rounded_rectangle((40, y, 1160, y + 62), 12, fill="white", outline="#e0ebed")
        centered(renderer, d, (40, y, 260, 62), label, 22, GRAY)
        centered(renderer, d, (300, y, 860, 62), value, 23)
        y += 72
    y += 10
    if borders:
        d.rounded_rectangle((40, y, 1160, y + 50), 12, fill="#e6f8f5")
        centered(
            renderer,
            d,
            (40, y, 1120, 50),
            "榜线更新时间 · " + local_date(ranking["updated_at"]),
            22,
            "#168d85",
        )
        y += 66
        for col in range(2):
            x = 40 + col * 570
            d.rounded_rectangle((x, y, x + 550, y + 46), 10, fill="#e8f1f4")
            centered(renderer, d, (x, y, 170, 46), "档位", 21, GRAY)
            centered(renderer, d, (x + 170, y, 380, 46), "活动积分 PT", 21, GRAY)
        y += 58
        for i, row in enumerate(tiers):
            x, cy = 40 + i % 2 * 570, y + i // 2 * 62
            d.rounded_rectangle(
                (x, cy, x + 550, cy + 52), 11, fill="white", outline="#e0ebed"
            )
            centered(renderer, d, (x, cy, 170, 52), f"T{row['rank']:,}", 22, "#119f96")
            centered(renderer, d, (x + 170, cy, 380, 52), f"{row['score']:,}", 24)
        y += math.ceil(len(tiers) / 2) * 62 + 16
        note = "来源：Moesekai 社区榜线 · " + (
            "上游更新延迟 / 缓存数据"
            if current.get("ranking_stale")
            else "按需读取，可能存在采样延迟"
        )
        if current.get("ranking_clock_skew"):
            note = "来源：Moesekai 社区榜线 · 上游时钟偏差，保留原始采样时间"
    else:
        for label, values in rows:
            height = max(70, len(values) * 34 + 24)
            d.rounded_rectangle(
                (40, y, 1160, y + height - 8), 12, fill="white", outline="#e0ebed"
            )
            centered(renderer, d, (40, y, 260, height - 8), label, 22, GRAY)
            block_y = y + (height - 8 - len(values) * 34) / 2
            for i, value in enumerate(values):
                centered(renderer, d, (300, block_y + i * 34, 860, 34), value, 23)
            y += height
        y += 16
        renderer.title_bar(d, 40, y, 1120, f"活动卡面 · {len(card_ids)} 张")
        y += 60
        panel_height = max(80, grid_rows * 224 + 44)
        d.rounded_rectangle(
            (40, y, 1160, y + panel_height),
            18,
            fill="white",
            outline="#dce9eb",
            width=2,
        )
        if not card_ids:
            centered(
                renderer,
                d,
                (40, y, 1120, panel_height),
                "活动卡片资料暂不可用",
                23,
                GRAY,
            )
        for i, cid in enumerate(card_ids):
            count = min(6, len(card_ids) - i // 6 * 6)
            span = count * 140 + (count - 1) * 32
            x, cy = (1200 - span) // 2 + i % 6 * 172, y + 20 + i // 6 * 224
            card = details.get(cid)
            if card:
                renderer.thumb(
                    canvas, card, current.get("card_images", {}).get(cid), x, cy, 140
                )
            else:
                renderer.art(canvas, None, (x, cy, 140, 140), "资料待同步")
            centered(renderer, d, (x - 10, cy + 148, 160, 26), f"ID {cid}", 19)
            if card:
                name = NAMES.get(card.get("characterId"), "未知角色").split("|")[0]
                centered(renderer, d, (x - 10, cy + 176, 160, 24), name, 18, GRAY)
                centered(
                    renderer,
                    d,
                    (x - 10, cy + 201, 160, 22),
                    ATTRS.get(card.get("attr"), "属性未提供"),
                    16,
                    "#168d85",
                )
        y += panel_height + 16
        note = "活动表检查于 " + local_date(current["fetched_at"] * 1000)
        if current.get("stale") or current.get("extras_stale"):
            note += " · 部分资料使用缓存 / 暂不可用"
    centered(
        renderer, d, (40, y + 10, 1120, 32), renderer.ellipsis(note, 1100, 20), 20, GRAY
    )
    centered(
        renderer,
        d,
        (40, y + 50, 1120, 30),
        "查询时间 " + local_date(now) + " · 社区镜像",
        18,
        GRAY,
    )
    return renderer.encode(canvas.crop((0, 0, 1200, y + 104)))
