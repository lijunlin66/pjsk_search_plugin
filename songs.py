"""Released CN song search, community aliases and local chart rendering."""

import asyncio
import hashlib
import io
import re
import time
import unicodedata
from difflib import SequenceMatcher

from PIL import Image, ImageDraw, ImageFont

from .service import DataUnavailable, atomic_write

ALIASES = "https://raw.githubusercontent.com/StarMoe-org/MoeSekai-Hub/main/data/music_alias/music_aliases.json"
ALIASES_CDN = "https://cdn.jsdelivr.net/gh/StarMoe-org/MoeSekai-Hub@main/data/music_alias/music_aliases.json"
DIFFICULTIES = ("easy", "normal", "hard", "expert", "master", "append")
SHORT = {
    "ez": "easy",
    "nm": "normal",
    "hd": "hard",
    "ex": "expert",
    "exp": "expert",
    "mas": "master",
    "ma": "master",
    "apd": "append",
}


def norm(value):
    return "".join(
        c for c in unicodedata.normalize("NFKC", str(value)).casefold() if c.isalnum()
    )


def parse_chart(query):
    parts = query.rsplit(maxsplit=1)
    if len(parts) == 2 and parts[1].lower() in (*DIFFICULTIES, *SHORT):
        return parts[0].strip(), SHORT.get(parts[1].lower(), parts[1].lower())
    return query.strip(), "master"


def clean_table(data):
    if (
        not isinstance(data, list)
        or not data
        or not all(isinstance(r, dict) and "id" in r for r in data)
    ):
        raise ValueError("Invalid music table")
    return data


def clean_aliases(data):
    rows = data.get("musics") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("Invalid alias table")
    result = []
    for r in rows:
        if (
            not isinstance(r, dict)
            or not isinstance(r.get("music_id"), int)
            or not isinstance(r.get("aliases"), list)
        ):
            raise TypeError("Invalid alias record")
        result.append(
            {
                "id": r["music_id"],
                "title": r.get("title", ""),
                "aliases": [
                    s for s in r["aliases"] if isinstance(s, str) and s.strip()
                ],
            }
        )
    return result


class SongIndex:
    def __init__(self, musics, aliases, chinese=()):
        now = time.time() * 1000
        self.songs = {
            r["id"]: r
            for r in musics
            if isinstance(r.get("title"), str)
            and r.get("publishedAt", float("inf")) <= now
        }
        self.chinese = {
            r["id"]: r["title"]
            for r in chinese
            if r["id"] in self.songs and isinstance(r.get("title"), str)
        }
        self.names = {
            mid: {norm(r["title"]), norm(r.get("pronunciation", ""))}
            for mid, r in self.songs.items()
        }
        # Keep the original spelling for display; search normalization loses it.
        self.display_aliases = {mid: [] for mid in self.songs}
        seen_aliases = {mid: set() for mid in self.songs}
        for mid, title in self.chinese.items():
            self.names[mid].add(norm(title))
        for r in aliases:
            if r["id"] in self.names:
                self.names[r["id"]].update(norm(s) for s in r["aliases"])
                for value in r["aliases"]:
                    alias = value.strip()
                    if alias and alias not in seen_aliases[r["id"]]:
                        self.display_aliases[r["id"]].append(alias)
                        seen_aliases[r["id"]].add(alias)
                if isinstance(r.get("title"), str):
                    self.names[r["id"]].add(norm(r["title"]))
        for names in self.names.values():
            names.discard("")

    def search(self, query, count=2):
        query = query.strip()
        count = max(1, min(10, int(count)))
        if query.isdecimal() and int(query) in self.songs:
            return [self.songs[int(query)]], "exact"
        key = norm(query)
        if not key:
            return [], "empty"
        # A canonical title takes priority over someone else's community nickname.
        ids = [
            mid
            for mid, r in self.songs.items()
            if key == norm(r["title"]) or key == norm(self.chinese.get(mid, ""))
        ]
        if not ids:
            ids = [mid for mid, names in self.names.items() if key in names]
        if ids:
            return [self.songs[mid] for mid in sorted(ids)[:count]], "exact" if len(
                ids
            ) == 1 else "ambiguous"
        ranked = []
        for mid, names in self.names.items():
            score = max(
                (
                    SequenceMatcher(None, key, name, autojunk=False).ratio()
                    for name in names
                ),
                default=0,
            )
            ranked.append((score, mid))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [self.songs[mid] for _, mid in ranked[:count]], "suggested"


class SongService:
    def __init__(self, owner):
        self.owner = owner
        self.index = None
        self.revision = None
        self.chart_lock = asyncio.Lock()

    async def data(self):
        async def load(url, cleaner, required=False):
            try:
                return await self.owner.live.load(url, 21600, 7 * 86400, cleaner)
            except DataUnavailable:
                if required:
                    raise DataUnavailable("歌曲主数据暂不可用，请稍后重试。") from None
                return [], 0, True

        base = self.owner.live.master("cn")
        alias_url = self.owner.config.get("song_alias_url", ALIASES)
        if not alias_url.startswith("https://"):
            raise DataUnavailable("歌曲别名地址必须使用 HTTPS。")
        music, difficulty, aliases, japanese = await asyncio.gather(
            load(f"{base}/musics.json", clean_table, True),
            load(f"{base}/musicDifficulties.json", clean_table),
            load(alias_url, clean_aliases),
            load(f"{self.owner.master_base}/musics.json", clean_table),
        )
        if not aliases[0] and alias_url == ALIASES:
            aliases = await load(ALIASES_CDN, clean_aliases)
        # Japanese master only adds searchable titles to the already released CN IDs.
        aliases = (
            aliases[0]
            + [
                {"id": r["id"], "aliases": [r["title"]]}
                for r in japanese[0]
                if isinstance(r.get("title"), str)
            ],
            aliases[1],
            aliases[2],
        )
        revision = tuple(r[1] for r in (music, aliases, japanese))
        if self.index is None or revision != self.revision:
            self.index = await asyncio.to_thread(
                SongIndex, music[0], aliases[0], music[0]
            )
            self.revision = revision
        now = time.time() * 1000
        return (
            self.index,
            [r for r in difficulty[0] if r.get("publishedAt", 0) <= now],
            any(r[2] for r in (music, difficulty, aliases, japanese)),
        )

    async def chart(self, music, difficulty, level, font_path):
        music_id = music["id"]
        if (
            difficulty not in DIFFICULTIES
            or not isinstance(music_id, int)
            or music_id <= 0
        ):
            raise DataUnavailable("谱面编号或难度无效。")
        base = self.owner.config.get(
            "cn_asset_base", "https://storage.exmeaning.com/sekai-cn-assets"
        ).rstrip("/")
        if not base.startswith("https://"):
            raise DataUnavailable("国服图片地址必须使用 HTTPS。")
        url = f"{base}/music/music_score/{music_id:04d}_01/{difficulty}.txt"
        key = f"cn-chart-v1|{url}|{music['title']}|{level}|{font_path}"
        path = self.owner.render_dir / (
            hashlib.sha256(key.encode()).hexdigest() + ".png"
        )
        async with self.chart_lock:
            if path.exists() and time.time() - path.stat().st_mtime < 86400:
                data = await asyncio.to_thread(path.read_bytes)
                try:
                    await asyncio.to_thread(self.verify_chart, data)
                    return data
                except (OSError, ValueError):
                    path.unlink(missing_ok=True)
            try:
                async with (
                    self.owner.sem,
                    self.owner.client.stream("GET", url, timeout=25) as response,
                ):
                    response.raise_for_status()
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 2 * 1024 * 1024:
                            raise ValueError("Chart data too large")
                data = await asyncio.to_thread(
                    self.render_chart,
                    bytes(raw).decode("utf-8-sig"),
                    music,
                    difficulty,
                    level,
                    font_path,
                )
                await asyncio.to_thread(self.verify_chart, data)
                await asyncio.to_thread(atomic_write, path, data)
                return data
            except Exception as exc:
                self.owner.log.warning(f"国服谱面生成失败：{type(exc).__name__}")
                raise DataUnavailable(
                    "该难度国服谱面暂未收录或生成失败，请稍后重试或换一个难度。"
                ) from exc

    @staticmethod
    def render_chart(sus, music, difficulty, level, font_path):
        import pjsekai_scores_rs as scores

        score = scores.Score.from_str(sus)
        score.set_meta(
            title=music["title"],
            artist=music.get("composer", ""),
            difficulty=difficulty,
            playlevel=str(level),
            songid=str(music["id"]),
            subtitle="CN / 国服",
        )
        drawing = scores.Drawing(
            generator="pjsk查询工具",
            font_paths=[font_path],
            style_sheet="text { fill: #202936; } .background { fill: #ffffff; } .lane { fill: #253441; } .bar-count-text { fill: #253441; }",
        )
        svg = drawing.svg(score)
        match = re.search(r'<svg[^>]*width="([0-9.]+)"[^>]*height="([0-9.]+)"', svg)
        if not match or float(match[1]) * float(match[2]) > 60_000_000:
            raise ValueError("Chart canvas too large")
        data = drawing.png(score)
        # Keep the footer readable across native renderer font backends.
        with Image.open(io.BytesIO(data)) as source:
            canvas = source.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        draw.rectangle(
            (0, canvas.height - 224, canvas.width, canvas.height), fill="white"
        )
        title_font = ImageFont.truetype(font_path, 46)
        title = music["title"]
        while title and title_font.getlength(title) > canvas.width - 120:
            title = title[:-1]
        if title != music["title"]:
            title += "…"
        draw.text((60, canvas.height - 170), title, font=title_font, fill="#202936")
        draw.text(
            (60, canvas.height - 90),
            f"CN 国服  ·  ID {music['id']}  ·  {difficulty.upper()}  Lv.{level}",
            font=ImageFont.truetype(font_path, 32),
            fill="#078e86",
        )
        output = io.BytesIO()
        canvas.save(output, "PNG")
        return output.getvalue()

    @staticmethod
    def verify_chart(data):
        with Image.open(io.BytesIO(data)) as im:
            if im.format != "PNG" or im.width * im.height > 60_000_000:
                raise ValueError("Invalid chart image")
            im.verify()

    def jacket(self, music):
        bundle = music.get("assetbundleName", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", bundle):
            raise DataUnavailable("歌曲封面资源名异常。")
        base = self.owner.config.get(
            "cn_asset_base", "https://storage.exmeaning.com/sekai-cn-assets"
        ).rstrip("/")
        return f"{base}/music/jacket/{bundle}/{bundle}.webp"
