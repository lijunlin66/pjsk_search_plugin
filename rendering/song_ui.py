"""Song dossiers and clearly labeled approximate matches in the existing style."""

import math

from PIL import ImageDraw

from ..services.songs import DIFFICULTIES
from .help_ui import text
from .render import GRAY, local_date


def alias_layout(renderer, aliases, width=1128):
    """Center each row as a group and give its pills a shared height."""
    cells, row, used, y = [], [], 0, 0

    def finish_row():
        nonlocal row, used, y
        if not row:
            return
        height = max(h for _, h, _ in row)
        x = (width - used) / 2
        for w, _, lines in row:
            cells.append((x, y, w, height, lines))
            x += w + 12
        y += height + 12
        row, used = [], 0

    font = renderer.font(23)
    for alias in aliases:
        lines = renderer.wrap(alias, 23, width - 32)
        ink_width = max(font.getbbox(line)[2] - font.getbbox(line)[0] for line in lines)
        w = min(width, max(64, math.ceil(ink_width) + 32))
        h = len(lines) * 32 + 20
        if row and used + 12 + w > width:
            finish_row()
        used += (12 if row else 0) + w
        row.append((w, h, lines))
    finish_row()
    return cells, y - 12 if cells else 36


def alias_text_positions(renderer, box, lines):
    """Place each line by its visible ink center, independent of font baselines."""
    x, y, width, height = box
    positions = []
    for j, line in enumerate(lines):
        _, top, _, bottom = renderer.font(23).getbbox(line)
        center_y = y + height / 2 + (j - (len(lines) - 1) / 2) * 32
        positions.append((x + width / 2, center_y - (bottom - top) / 2, line))
    return positions


def song_image(renderer, songs, index, difficulties, covers, mode, stale=False):
    detail = mode == "exact" and len(songs) == 1
    heading = "歌曲资料" if detail else "请选择你要查询的歌曲"
    subtitle = (
        "国服已上线曲目"
        if detail
        else (
            "别名对应多首歌曲，请用 ID 确认。"
            if mode == "ambiguous"
            else "未找到精确匹配，以下是最接近的候选。"
        )
    )
    tiles = []
    for song in songs:
        rows = [("歌曲 ID", str(song["id"]))]
        if detail:
            rows += [
                ("国服标题", index.chinese.get(song["id"], "国服主数据暂未提供")),
                ("作词", song.get("lyricist") or "未提供"),
                ("作曲", song.get("composer") or "未提供"),
                ("编曲", song.get("arranger") or "未提供"),
                ("游戏内公开时间", local_date(song.get("publishedAt")) + " UTC+8"),
            ]
        rows += [("查询指令", f"/song {song['id']}    /谱面查询 {song['id']}")]
        wrapped = [(label, renderer.wrap(value, 25, 790)) for label, value in rows]
        title = renderer.wrap(song["title"], 34, 750)
        top = max(270, len(title) * 46 + 118)
        charts = (
            [
                r
                for level in DIFFICULTIES
                for r in difficulties
                if r.get("musicId") == song["id"] and r.get("musicDifficulty") == level
            ]
            if detail
            else []
        )
        aliases = index.display_aliases.get(song["id"], [])
        alias_cells, alias_height = alias_layout(renderer, aliases)
        h = (
            top
            + sum(max(58, len(lines) * 34 + 22) for _, lines in wrapped)
            + (100 + len(charts) * 55 if detail else 0)
            + 88
            + alias_height
            + 32
        )
        tiles.append(
            (
                song,
                title,
                wrapped,
                charts,
                top,
                alias_cells,
                len(aliases),
                h,
            )
        )
    canvas = renderer.background(1280, 220 + sum(t[-1] + 24 for t in tiles) + 100)
    draw = ImageDraw.Draw(canvas)
    text(renderer, draw, (60, 30), "PJSK  /  SONG LIBRARY", 21, "#078e86", bold=True)
    text(renderer, draw, (60, 78), heading, 40, bold=True)
    text(renderer, draw, (60, 145), subtitle, 25, GRAY)
    y = 210
    for i, (
        song,
        title,
        rows,
        charts,
        top,
        cells,
        alias_count,
        h,
    ) in enumerate(tiles):
        draw.rounded_rectangle(
            (40, y, 1240, y + h), 22, fill="white", outline="#d5e7e7", width=2
        )
        renderer.art(canvas, covers[i], (70, y + 30, 210, 210))
        for j, line in enumerate(title):
            text(renderer, draw, (320, y + 40 + j * 46), line, 34, bold=True)
        text(
            renderer,
            draw,
            (320, y + 55 + len(title) * 46),
            f"ID {song['id']}  ·  {'资料' if detail else '候选歌曲'}",
            23,
            "#078e86",
        )
        ry = y + top
        for label, lines in rows:
            height = max(58, len(lines) * 34 + 22)
            text(renderer, draw, (76, ry + 16), label, 24, bold=True)
            for j, line in enumerate(lines):
                text(renderer, draw, (390, ry + 16 + j * 34), line, 25, GRAY)
            draw.line((76, ry + height, 1204, ry + height), fill="#e7eeee")
            ry += height
        if detail:
            ry += 28
            for x, label in ((76, "难度"), (590, "等级"), (970, "总音符数")):
                text(renderer, draw, (x, ry), label, 24, "#078e86", bold=True)
            ry += 55
            for chart in charts:
                for x, value in (
                    (76, chart["musicDifficulty"].upper()),
                    (590, f"Lv.{chart.get('playLevel', '?')}"),
                    (970, str(chart.get("totalNoteCount", "未提供"))),
                ):
                    text(renderer, draw, (x, ry), value, 25)
                ry += 55
            if not charts:
                text(renderer, draw, (76, ry), "难度资料暂不可用", 25, GRAY)
                ry += 36
        ry += 34
        text(
            renderer,
            draw,
            (76, ry),
            f"全部别名 · {alias_count} 个",
            26,
            "#078e86",
            bold=True,
        )
        ry += 48
        if not cells:
            text(
                renderer,
                draw,
                (76, ry),
                "暂无别名记录；数据源异常时可稍后重试。",
                23,
                GRAY,
            )
        for x, cy, w, ch, lines in cells:
            draw.rounded_rectangle(
                (76 + x, ry + cy, 76 + x + w, ry + cy + ch),
                12,
                fill="#edf8f7",
                outline="#d5e9e6",
            )
            for cx, ty, line in alias_text_positions(
                renderer, (76 + x, ry + cy, w, ch), lines
            ):
                text(renderer, draw, (cx, ty), line, 23, center=True)
        y += h + 24
    footer = (
        "部分关联数据暂不可用或使用缓存。"
        if stale
        else "社区数据 · 谱面默认 MASTER，可在歌名后加 expert / append 等难度。"
    )
    text(renderer, draw, (60, y + 20), footer, 22, GRAY)
    return renderer.encode(canvas)
