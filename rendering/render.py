"""Reference-inspired light card atlas and two-column card dossier."""

import io
import math
import random
import struct
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from ..domain.catalog import (
    ATTRS,
    rarity,
    readable,
    skill_text,
    trained_only,
)
from ..domain.presentation import (
    SUPPLIES,
    max_power,
    power_growth,
    skill_badge,
    variants,
)

ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets"

INK, GRAY, TEAL, LINE = "#161a20", "#646a73", "#04c5b8", "#d7dcdf"


def local_date(value):
    return (
        datetime.fromtimestamp(value / 1000, timezone(timedelta(hours=8))).strftime(
            "%Y/%m/%d %H:%M"
        )
        if value
        else "未提供"
    )


class Renderer:
    def __init__(self, font_path=""):
        candidates = [
            font_path,
            str(ASSET_ROOT / "fonts/NotoSansCJKsc-Regular.otf"),
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "C:/Windows/Fonts/msyh.ttc",
        ]
        self.font_path = next((p for p in candidates if p and Path(p).is_file()), None)
        if not self.font_path:
            raise ValueError("未找到中日文字体，请设置 font_path")
        self.fonts, self.assets = {}, {}
        for path in (ASSET_ROOT / "images").glob("*.png"):
            with Image.open(path) as source:
                self.assets[path.stem] = source.convert("RGBA")

    def font(self, size):
        if size not in self.fonts:
            self.fonts[size] = ImageFont.truetype(self.font_path, size)
        return self.fonts[size]

    def text(self, draw, xy, text, size=22, fill=INK, anchor=None):
        draw.text(xy, str(text), font=self.font(size), fill=fill, anchor=anchor)

    def wrap(self, text, size, width):
        result, font = [], self.font(size)
        for paragraph in str(text).splitlines() or [""]:
            line = ""
            for char in paragraph:
                if line and font.getlength(line + char) > width:
                    result.append(line)
                    line = ""
                line += char
            result.append(line)
        return result

    def ellipsis(self, text, width, size):
        text = str(text)
        if self.font(size).getlength(text) <= width:
            return text
        while text and self.font(size).getlength(text + "…") > width:
            text = text[:-1]
        return text + "…"

    def fit_size(self, text, width, size, minimum=18):
        while size > minimum and self.font(size).getlength(str(text)) > width:
            size -= 1
        return size

    def icon(self, canvas, name, box):
        source = self.assets.get(name)
        if source is None:
            return
        x, y, w, h = box
        im = ImageOps.contain(source, (w, h), Image.Resampling.LANCZOS)
        canvas.paste(im, (x + (w - im.width) // 2, y + (h - im.height) // 2), im)

    def art(self, canvas, data, box, unavailable="图片暂不可用"):
        x, y, w, h = box
        if data:
            try:
                with Image.open(io.BytesIO(data)) as source:
                    im = ImageOps.contain(
                        source.convert("RGB"), (w, h), Image.Resampling.LANCZOS
                    )
                    canvas.paste(
                        im, (x + (w - im.width) // 2, y + (h - im.height) // 2)
                    )
                    return
            except (OSError, ValueError):
                pass
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle((x, y, x + w, y + h), 10, fill="#f1f4f6")
        self.text(d, (x + w // 2, y + h // 2), unavailable, 18, GRAY, "mm")

    def thumb(self, canvas, card, data, x, y, size=156, after=False):
        tile = Image.new("RGB", (156, 156), "white")
        self.art(tile, data, (5, 5, 146, 146))
        kind = (
            "bd"
            if card.get("cardRarityType") == "rarity_birthday"
            else card.get("cardRarityType", "rarity_1").split("_")[-1]
        )
        self.icon(tile, f"cardFrame_S_{kind}", (0, 0, 156, 156))
        self.icon(tile, "icon_attribute_" + card.get("attr", ""), (2, 2, 34, 34))
        count = 1 if kind == "bd" else int(kind) if kind.isdigit() else 1
        star = (
            "rarity_birthday"
            if kind == "bd"
            else "rarity_star_afterTraining"
            if after
            else "rarity_star_normal"
        )
        for i in range(count):
            self.icon(tile, star, (7 + i * 25, 122, 28, 28))
        self.supply_tag(tile, card)
        if size != 156:
            tile = tile.resize((size, size), Image.Resampling.LANCZOS)
        canvas.paste(tile, (x, y))

    def supply_tag(self, tile, card):
        """Small antialiased pill, inset from the frame and attribute icon."""
        style = {
            2: ("生日/周年", "#8d63aa", "#fcf6ff", "#dbc5e8"),
            3: ("期间限定", "#bd477b", "#fff5fa", "#edb8cf"),
            4: ("FES限定", "#8061b1", "#f8f3ff", "#d3c0ec"),
            5: ("FES限定", "#8061b1", "#f8f3ff", "#d3c0ec"),
            6: ("团队限定", "#288e86", "#effcf8", "#a1dcd5"),
            7: ("联动限定", "#99712e", "#fffaef", "#ead7ae"),
        }.get(
            2
            if card.get("cardRarityType") == "rarity_birthday"
            else card.get("cardSupplyId", 1)
        )
        if style is None:
            return
        label, ink, fill, border = style
        scale, font_size, h = 3, 12, 23
        w = math.ceil(self.font(font_size).getlength(label)) + 14
        badge = Image.new("RGBA", (w * scale, h * scale))
        d = ImageDraw.Draw(badge)
        d.rounded_rectangle(
            (1, 1, w * scale - 2, h * scale - 2),
            radius=8 * scale,
            fill=fill,
            outline=border,
            width=scale,
        )
        self.text(
            d, (w * scale / 2, h * scale / 2), label, font_size * scale, ink, "mm"
        )
        badge = badge.resize((w, h), Image.Resampling.LANCZOS)
        tile.paste(badge, (tile.width - w - 7, 7), badge)

    def detail_heading(self, canvas, card, catalog, x, y, width):
        """Full-width title with a unit chip above and a separate character row."""
        title = card.get("prefix", "")
        title_size = 30
        while title_size > 22 and len(self.wrap(title, title_size, width - 56)) > 2:
            title_size -= 1
        lines = self.wrap(title, title_size, width - 56)
        if len(lines) == 2 and "\n" not in title:
            font = self.font(title_size)
            candidates = []
            for cut in range(1, len(title)):
                first, second = title[:cut].rstrip(), title[cut:].lstrip()
                if not first or not second or second[0] in "、。，！？!?.,：:":
                    continue
                a, b = font.getlength(first), font.getlength(second)
                if max(a, b) <= width - 56:
                    boundary = title[cut - 1] in " 、。，,"
                    candidates.append(
                        (abs(a - b) + (0 if boundary else 18), first, second)
                    )
            if candidates:
                _, first, second = min(candidates)
                lines = [first, second]
        height = 118 + len(lines) * 38
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle((x, y, x + width, y + height), 18, fill=TEAL)
        unit = catalog.unit_label(card)
        unit_size = self.fit_size(unit, width - 86, 17, 13)
        chip_width = math.ceil(self.font(unit_size).getlength(unit)) + 26
        d.rounded_rectangle(
            (x + 26, y + 17, x + 26 + chip_width, y + 45), 14, fill="#2bd1c5"
        )
        self.text(d, (x + 39, y + 31), unit, unit_size, "#f4fffd", "lm")
        for i, line in enumerate(lines):
            self.text(d, (x + 28, y + 59 + i * 38), line, title_size, "white", "lt")
        role_y = y + height - 31
        self.text(d, (x + 28, role_y), "角色", 16, "#cefff7", "lm")
        self.text(d, (x + 77, role_y), catalog.name(card), 22, "white", "lm")
        return y + height

    def badge(self, canvas, card, catalog, x, y):
        label, color = skill_badge(card, catalog)
        d = ImageDraw.Draw(canvas)
        if label == "LIFE":
            d.ellipse(
                (x + 4, y + 5, x + 22, y + 23), fill=color, outline="white", width=2
            )
            d.ellipse(
                (x + 20, y + 5, x + 38, y + 23), fill=color, outline="white", width=2
            )
            d.polygon([(x + 4, y + 16), (x + 38, y + 16), (x + 21, y + 36)], fill=color)
            self.text(d, (x + 27, y + 20), "+", 24, "white", "mm")
        elif label == "JUDGE":
            d.polygon(
                [(x + 21, y + 2), (x + 40, y + 21), (x + 21, y + 40), (x + 2, y + 21)],
                fill=color,
                outline="white",
                width=2,
            )
            self.text(d, (x + 21, y + 20), "✧", 25, "white", "mm")
        else:
            d.polygon(
                [
                    (x + 21, y + 2),
                    (x + 39, y + 20),
                    (x + 30, y + 20),
                    (x + 30, y + 37),
                    (x + 12, y + 37),
                    (x + 12, y + 20),
                    (x + 3, y + 20),
                ],
                fill=color,
                outline="white",
                width=2,
            )
        self.text(d, (x + 21, y + 43), label, 11, color, "mm")

    def gallery_row(self, cards, images, catalog):
        width, tile_w, tile_h, margin, gap = 1500, 420, 286, 70, 50
        canvas = Image.new("RGB", (width, tile_h + gap), "#ececec")
        d = ImageDraw.Draw(canvas)
        for i, card in enumerate(cards):
            x, y = margin + i * (tile_w + gap), 0
            d.rectangle((x, y, x + tile_w, y + tile_h), fill="white")
            pair = images[i] if i < len(images) else None
            pair = pair if isinstance(pair, (tuple, list)) else (pair,)
            states = variants(card)
            start = x + (tile_w - (156 * len(states) + 20 * (len(states) - 1))) // 2
            for j, after in enumerate(states):
                self.thumb(
                    canvas,
                    card,
                    pair[j] if j < len(pair) else None,
                    start + j * 176,
                    y + 16,
                    after=after,
                )
            title = card.get("prefix", "")
            size = self.fit_size(title, tile_w - 26, 28, 19)
            self.text(
                d,
                (x + tile_w // 2, y + 187),
                self.ellipsis(title, tile_w - 26, size),
                size,
                INK,
                "ma",
            )
            self.text(d, (x + tile_w // 2, y + 229), f"id.{card['id']}", 21, GRAY, "ma")
            self.text(
                d,
                (x + tile_w // 2, y + 259),
                ATTRS.get(card.get("attr"), "") + " · " + rarity(card),
                15,
                GRAY,
                "ma",
            )
            self.badge(canvas, card, catalog, x + tile_w - 49, y + tile_h - 54)
        return canvas

    def gallery(self, cards, images, catalog, query, status):
        width, height = self.gallery_size(len(cards))

        def parts():
            header = Image.new("RGB", (width, 94), "#ececec")
            d = ImageDraw.Draw(header)
            self.text(d, (70, 30), self.ellipsis(query, 900, 25), 25, GRAY)
            self.text(d, (width - 70, 30), f"{len(cards)} 张 · 全部", 23, GRAY, "ra")
            yield header
            for start in range(0, len(cards), 3):
                yield self.gallery_row(
                    cards[start : start + 3], images[start : start + 3], catalog
                )
            footer = Image.new("RGB", (width, 60), "#ececec")
            d = ImageDraw.Draw(footer)
            self.text(d, (70, 0), "JP · 日服游戏数据社区镜像 / 非官方 API", 18, GRAY)
            self.text(d, (70, 29), status, 16, GRAY)
            yield footer

        # JPEG has a 65535-pixel dimension limit. Stream exceptionally long
        # PNGs row by row instead of allocating an enormous full RGB canvas.
        if height > 65000 or width * height > 48_000_000:
            return self.encode_png_rows(width, height, parts())
        canvas = Image.new("RGB", (width, height), "#ececec")
        y = 0
        for part in parts():
            canvas.paste(part, (0, y))
            y += part.height
        return self.encode(canvas)

    @staticmethod
    def gallery_size(count):
        return 1500, 154 + math.ceil(count / 3) * 336

    @staticmethod
    def encode_png_rows(width, height, parts):
        output = io.BytesIO()
        output.write(b"\x89PNG\r\n\x1a\n")

        def chunk(kind, data):
            output.write(struct.pack(">I", len(data)))
            output.write(kind)
            output.write(data)
            output.write(struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

        chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        compressor = zlib.compressobj(level=3)
        emitted = 0
        for part in parts:
            raw = part.convert("RGB").tobytes()
            stride = width * 3
            filtered = b"".join(
                b"\0" + raw[i : i + stride] for i in range(0, len(raw), stride)
            )
            compressed = compressor.compress(filtered)
            if compressed:
                chunk(b"IDAT", compressed)
            emitted += part.height
        if emitted != height:
            raise ValueError("长图行数不匹配")
        chunk(b"IDAT", compressor.flush())
        chunk(b"IEND", b"")
        return output.getvalue()

    def background(self, width, height):
        canvas = Image.new("RGB", (width, height), "#f5faff")
        overlay = Image.new("RGBA", canvas.size)
        d, rng = ImageDraw.Draw(overlay), random.Random(9317)
        palette = ["#8be8e7", "#ffd5ed", "#d8f3a6", "#c5d7ff", "#f7e2a5"]
        for _ in range(100):
            x, y = rng.randrange(-150, width), rng.randrange(-150, height)
            size = rng.randrange(80, 330)
            d.polygon(
                [(x, y), (x + size, y + size // 3), (x + size // 3, y + size)],
                fill=palette[rng.randrange(len(palette))] + "36",
            )
        canvas.paste(overlay, (0, 0), overlay)
        return canvas

    def title_bar(self, draw, x, y, w, title):
        draw.rounded_rectangle((x, y, x + w, y + 45), 15, fill=TEAL)
        self.text(draw, (x + w // 2, y + 22), title, 27, "white", "mm")

    def info_rows(self, card, catalog):
        level, values = max_power(card, catalog)
        skill = catalog.skills.get(card.get("skillId"), {})
        r = next(
            (
                r
                for r in catalog.tables["cardRarities"]
                if r["cardRarityType"] == card["cardRarityType"]
            ),
            {},
        )
        return [
            ("综合力", str(sum(values))),
            ("演奏", str(values[0])),
            ("技巧", str(values[1])),
            ("耐力", str(values[2])),
            ("数值口径", f"Lv.{level} · 无专精 / 无剧情加成"),
            ("属性", ATTRS.get(card.get("attr"), "未知")),
            ("类型", SUPPLIES.get(card.get("cardSupplyId", 1), "未提供")),
            ("技能名", card.get("cardSkillName", "未提供")),
            (
                "技能效果",
                "\n".join(
                    f"Lv.{lv}  {skill_text(skill, lv, catalog.name(card))}"
                    for lv in range(1, r.get("maxSkillLevel", 4) + 1)
                ),
            ),
            ("招募语", card.get("gachaPhrase", "未提供")),
            ("发布时间", local_date(card.get("releaseAt")) + " (UTC+8)"),
        ]

    def panel(self, canvas, x, y, w, title, records, media, kind):
        d = ImageDraw.Draw(canvas)
        self.title_bar(d, x, y, w, title)
        y += 66
        if not records:
            d.rounded_rectangle(
                (x, y, x + w, y + 100), 14, fill="white", outline="#aeb7c0", width=2
            )
            self.text(d, (x + w // 2, y + 50), "无关联记录 / 暂未提供", 21, GRAY, "mm")
            return y + 100
        for i, record in enumerate(records):
            h = 330 if kind == "musics" else 378
            d.rounded_rectangle(
                (x, y, x + w, y + h), 14, fill="white", outline="#aeb7c0", width=2
            )
            if kind == "musics":
                self.art(canvas, media.get(f"{kind}:{i}"), (x + 24, y + 25, 170, 170))
                for j, (label, key) in enumerate(
                    (("作词", "lyricist"), ("作曲", "composer"), ("编曲", "arranger"))
                ):
                    self.text(
                        d,
                        (x + 218, y + 42 + j * 38),
                        self.ellipsis(
                            label + "：" + record.get(key, "未提供"), w - 245, 23
                        ),
                        23,
                    )
                self.text(
                    d,
                    (x + w // 2, y + 218),
                    self.ellipsis(record.get("title", ""), w - 35, 27),
                    27,
                    INK,
                    "ma",
                )
                self.text(
                    d,
                    (x + w // 2, y + 264),
                    f"ID:{record['id']}   上线：{local_date(record.get('publishedAt'))}",
                    19,
                    GRAY,
                    "ma",
                )
            else:
                self.art(
                    canvas, media.get(f"{kind}:{i}"), (x + 22, y + 20, w - 44, 190)
                )
                self.text(
                    d,
                    (x + w // 2, y + 223),
                    self.ellipsis(record.get("name", ""), w - 28, 27),
                    27,
                    INK,
                    "ma",
                )
                self.text(
                    d, (x + w // 2, y + 266), f"ID:{record['id']}", 20, GRAY, "ma"
                )
                self.text(
                    d,
                    (x + 22, y + 303),
                    "开始：" + local_date(record.get("startAt")),
                    19,
                    GRAY,
                )
                self.text(
                    d,
                    (x + 22, y + 326),
                    "结束："
                    + local_date(record.get("endAt", record.get("aggregateAt"))),
                    19,
                    GRAY,
                )
            y += h + 18
        return y - 18

    def detail(self, card, images, catalog, extras, status, media=None):
        media, links = media or {}, extras.get("_related", {})
        width, margin, gap, col = 1500, 44, 44, 684
        left, right = margin, margin + col + gap
        row_layout = []
        for label, value in self.info_rows(card, catalog):
            lines = self.wrap(value, 24, 452)
            row_layout.append((label, lines, max(52, 18 + len(lines) * 34)))
        costumes = links.get("costumes", [])
        thumbs_h = 172
        costume_h = max(88, math.ceil(min(len(costumes), 6) / 2) * 156 + 22)
        table_h = sum(row[2] for row in row_layout) + thumbs_h + costume_h + 98
        notes = []
        notes.append("综合力成长：" + "；".join(power_growth(card, catalog)))
        if card.get("specialTrainingCosts"):
            notes.append("特训消耗：" + readable(card["specialTrainingCosts"]))
        for e in extras.get("卡片剧情 / 解锁条件 / 剧情加成", []):
            notes.append(
                f"剧情 {e.get('title', '')}：表演 +{e.get('power1BonusFixed', 0)} / 技巧 +{e.get('power2BonusFixed', 0)} / 耐力 +{e.get('power3BonusFixed', 0)}；消耗 "
                + readable(e.get("costs", []))
            )
        rewards = extras.get("专精奖励 / 服装解锁", [])
        boxes = {
            r["id"]: r
            for r in rewards
            if r.get("resourceBoxPurpose") == "master_lesson_reward"
        }
        for reward in rewards:
            if "masterRank" in reward:
                box = boxes.get(reward.get("resourceBoxId"), {})
                notes.append(
                    f"专精 Lv.{reward['masterRank']}：{box.get('name', '解锁关联衣装')}（奖励组 {reward.get('resourceBoxId', '?')}）"
                )
        notes_lines = [
            line
            for note in notes
            for line in self.wrap(note, 20, width - margin * 2 - 40)
        ]
        height = max(2000, table_h + 1200) + 200 + len(notes_lines) * 29
        canvas = self.background(width, height)
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle((44, 20, 352, 62), 21, fill=TEAL)
        self.text(d, (64, 24), "查 询 / 卡 牌", 25, "white")
        self.text(d, (width - 44, 35), f"JP   #{card['id']}", 22, GRAY, "ra")
        states = variants(card)
        for i in range(2):
            y = 128 + i * 436
            if i < len(states):
                self.art(
                    canvas, images[i] if i < len(images) else None, (left, y, col, 385)
                )
                kind = (
                    "bd"
                    if card.get("cardRarityType") == "rarity_birthday"
                    else card.get("cardRarityType", "rarity_1").split("_")[-1]
                )
                self.icon(canvas, "cardFrame_L_" + kind, (left, y, col, 385))
                self.icon(
                    canvas,
                    "icon_attribute_" + card.get("attr", ""),
                    (left + col - 61, y + 7, 53, 53),
                )
                star = (
                    "rarity_birthday"
                    if kind == "bd"
                    else "rarity_star_afterTraining"
                    if states[i]
                    else "rarity_star_normal"
                )
                count = 1 if kind == "bd" else int(kind) if kind.isdigit() else 1
                for j in range(count):
                    self.icon(
                        canvas,
                        star,
                        (left + 8, y + 385 - 49 * (count - j) - 12, 46, 46),
                    )
                self.text(
                    d,
                    (left + col // 2, y + 396),
                    "仅花后" if trained_only(card) else "花后" if states[i] else "花前",
                    18,
                    GRAY,
                    "ma",
                )
            else:
                self.art(
                    canvas,
                    None,
                    (left, y, col, 385),
                    "本卡仅有花后" if trained_only(card) else "本卡不可特训，无花后",
                )
        y = self.detail_heading(canvas, card, catalog, right, 128, col) + 26
        d.rounded_rectangle(
            (right, y, right + col, y + table_h),
            18,
            fill="white",
            outline="#aeb7c0",
            width=2,
        )
        yy = y + 14
        for label, lines, h in row_layout:
            self.text(d, (right + 25, yy + 10), label, 25)
            for j, line in enumerate(lines):
                self.text(d, (right + col - 24, yy + 10 + j * 34), line, 24, INK, "ra")
            yy += h
            d.line((right + 24, yy, right + col - 24, yy), fill=LINE, width=2)
        self.text(d, (right + 25, yy + 60), "缩略图", 25)
        for i, after in enumerate(states):
            self.thumb(
                canvas,
                card,
                media.get(f"thumb:{i}"),
                right + col - 300 + i * 142,
                yy + 20,
                126,
                after,
            )
        yy += thumbs_h
        d.line((right + 24, yy, right + col - 24, yy), fill=LINE, width=2)
        self.text(d, (right + 25, yy + 30), "衣装", 25)
        for i, costume in enumerate(costumes[:6]):
            x, cy = right + col - 320 + (i % 2) * 156, yy + 18 + (i // 2) * 156
            self.art(canvas, media.get(f"costumes:{i}"), (x, cy, 124, 118))
            label = {"hair": "发型", "head": "发饰", "body": "服装"}.get(
                costume.get("partType"), "衣装"
            )
            self.text(d, (x + 62, cy + 123), label, 20, INK, "ma")
        if not costumes:
            self.text(
                d, (right + col - 24, yy + 30), "无关联衣装 / 暂未提供", 20, GRAY, "ra"
            )
        yy += costume_h
        d.line((right + 24, yy, right + col - 24, yy), fill=LINE, width=2)
        self.text(d, (right + 25, yy + 20), "ID", 27)
        self.text(d, (right + col - 24, yy + 20), str(card["id"]), 27, INK, "ra")
        left_end = self.panel(
            canvas,
            left,
            1018,
            col,
            "当期卡池",
            links.get("gachas", []),
            media,
            "gachas",
        )
        left_end = self.panel(
            canvas,
            left,
            left_end + 42,
            col,
            "关联活动",
            links.get("events", []),
            media,
            "events",
        )
        right_end = self.panel(
            canvas,
            right,
            y + table_h + 42,
            col,
            "关联歌曲",
            links.get("musics", []),
            media,
            "musics",
        )
        bottom = max(left_end, right_end) + 42
        if notes_lines:
            h = 63 + len(notes_lines) * 29
            d.rounded_rectangle(
                (44, bottom, width - 44, bottom + h),
                14,
                fill="white",
                outline=LINE,
                width=2,
            )
            self.text(d, (66, bottom + 10), "培养与剧情资料", 23, TEAL)
            for i, line in enumerate(notes_lines):
                self.text(d, (66, bottom + 48 + i * 29), line, 20, GRAY)
            bottom += h + 22
        self.text(
            d,
            (44, bottom + 12),
            "日服游戏数据社区镜像 · 非官方 API · " + status,
            17,
            GRAY,
        )
        return self.encode(canvas.crop((0, 0, width, bottom + 62)))

    @staticmethod
    def encode(canvas):
        out = io.BytesIO()
        canvas.save(out, "JPEG", quality=92, optimize=True)
        return out.getvalue()
