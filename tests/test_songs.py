import asyncio
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
from PIL import Image, ImageChops, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from astrbot_plugin_pjsk.rendering.render import Renderer
from astrbot_plugin_pjsk.rendering.song_ui import (
    alias_layout,
    alias_text_positions,
    song_image,
)
from astrbot_plugin_pjsk.services.songs import (
    SongIndex,
    SongService,
    clean_aliases,
    parse_chart,
)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.index = SongIndex(
            [
                {"id": 1, "title": "Tell Your World", "publishedAt": 1},
                {"id": 2, "title": "ロキ", "publishedAt": 1},
                {"id": 3, "title": "future", "publishedAt": 9999999999999},
            ],
            [
                {"id": 1, "aliases": ["告诉你的世界", "shared"]},
                {"id": 2, "aliases": ["洛基", "shared", "Tell Your World"]},
                {"id": 999, "aliases": ["日服独占"]},
            ],
        )

    def test_original_chinese_alias_and_id(self):
        for query, expected in [
            ("１", 1),
            ("告诉你的世界", 1),
            ("ロキ", 2),
            ("洛基", 2),
        ]:
            result, mode = self.index.search(query)
            self.assertEqual((result[0]["id"], mode), (expected, "exact"))

    def test_title_priority_and_ambiguous_alias(self):
        self.assertEqual(self.index.search("Tell Your World")[0][0]["id"], 1)
        self.assertEqual(self.index.search("shared")[1], "ambiguous")

    def test_fuzzy_limits_dedup_and_unreleased(self):
        result, mode = self.index.search("Tlel Your Wrold")
        self.assertEqual(mode, "suggested")
        self.assertEqual([r["id"] for r in result], [1, 2])
        self.assertEqual(len(self.index.search("nonsense", 1)[0]), 1)
        self.assertNotIn(3, self.index.songs)
        self.assertNotIn(999, self.index.names)

    def test_difficulty_full_and_short_names(self):
        for suffix, expected in [
            ("master", "master"),
            ("mas", "master"),
            ("EX", "expert"),
            ("expert", "expert"),
            ("apd", "append"),
            ("hard", "hard"),
            ("nm", "normal"),
            ("ez", "easy"),
        ]:
            self.assertEqual(
                parse_chart("Tell Your World " + suffix), ("Tell Your World", expected)
            )
        self.assertEqual(parse_chart("Tell Your World"), ("Tell Your World", "master"))

    def test_bad_alias_payload_is_rejected(self):
        with self.assertRaises(ValueError):
            clean_aliases({"wrong": []})
        with self.assertRaises(TypeError):
            clean_aliases({"musics": [{"music_id": 1, "aliases": "bad"}]})

    def test_display_aliases_keep_spelling_punctuation_and_long_values(self):
        long_alias = "很长的歌曲别名" * 30
        records = clean_aliases(
            {
                "musics": [
                    {
                        "music_id": 1,
                        "aliases": ["TYW", "tyw", "t.y.w", "TYW", long_alias],
                    }
                ]
            }
        )
        index = SongIndex([{"id": 1, "title": "song", "publishedAt": 1}], records)
        self.assertEqual(index.display_aliases[1], ["TYW", "tyw", "t.y.w", long_alias])

    def test_details_and_candidates_render_every_alias_inside_image(self):
        import astrbot_plugin_pjsk.rendering.song_ui as ui

        aliases = [f"别名 {i:03d}" for i in range(120)] + ["LAST_ALIAS_UNIQUE"]
        index = SongIndex(
            [{"id": 1, "title": "song", "publishedAt": 1}],
            [{"id": 1, "aliases": aliases}],
        )
        renderer = Renderer()
        for mode in ("exact", "suggested"):
            with patch.object(ui, "text", wraps=ui.text) as draw_text:
                data = song_image(
                    renderer, list(index.songs.values()), index, [], [None], mode
                )

            values = [call.args[3] for call in draw_text.call_args_list]
            self.assertTrue(all(alias in values for alias in aliases))
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                self.assertTrue(
                    all(
                        call.args[2][1] + call.args[4] < image.height
                        for call in draw_text.call_args_list
                    )
                )

    def test_alias_ink_is_centered_for_cjk_latin_and_multiline(self):
        from astrbot_plugin_pjsk.rendering.help_ui import text

        renderer = Renderer()
        for lines in (["火锅"], ["Agy"], ["!!!"], ["Hello", "国服别名"]):
            canvas = Image.new("RGB", (360, 180), "white")
            draw = ImageDraw.Draw(canvas)
            box = (20, 20, 320, 140)
            for cx, ty, line in alias_text_positions(renderer, box, lines):
                text(renderer, draw, (cx, ty), line, 23, center=True)
            ink = ImageChops.difference(
                canvas, Image.new("RGB", canvas.size, "white")
            ).getbbox()
            self.assertIsNotNone(ink)
            self.assertAlmostEqual((ink[0] + ink[2]) / 2, 180, delta=1)
            self.assertAlmostEqual((ink[1] + ink[3]) / 2, 90, delta=1)

    def test_alias_rows_have_shared_height_and_balanced_margins(self):
        cells, height = alias_layout(
            Renderer(), ["a", "国服", "Agyp", "多行别名" * 40, "末行"], width=300
        )
        rows = {}
        for x, y, width, h, _ in cells:
            rows.setdefault(y, []).append((x, width, h))
            self.assertLessEqual(y + h, height)
        for row in rows.values():
            self.assertEqual(len({r[2] for r in row}), 1)
            self.assertAlmostEqual(row[0][0], 300 - row[-1][0] - row[-1][1])


class ChartTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_alias_failure_uses_cdn_without_adding_jp_only_songs(self):
        from astrbot_plugin_pjsk.services.service import DataUnavailable
        from astrbot_plugin_pjsk.services.songs import ALIASES, ALIASES_CDN

        seen = []

        async def load(url, ttl, age, cleaner):
            seen.append(url)
            if url == ALIASES:
                raise DataUnavailable("offline")
            if url == ALIASES_CDN:
                data = {"musics": [{"music_id": 1, "aliases": ["告诉你的世界"]}]}
            else:
                data = [{"id": 1, "title": "Tell Your World", "publishedAt": 1}]
            return cleaner(data), 123, False

        owner = SimpleNamespace(
            config={},
            master_base="https://example.com/jp",
            live=SimpleNamespace(
                master=lambda _: "https://example.com/cn",
                load=AsyncMock(side_effect=load),
            ),
        )
        index, _, stale = await SongService(owner).data()
        self.assertEqual(index.search("告诉你的世界")[1], "exact")
        self.assertIn(ALIASES_CDN, seen)
        self.assertFalse(stale)

    async def test_cn_source_cache_and_no_second_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = io.BytesIO()
            Image.new("RGB", (32, 32), "white").save(output, "PNG")
            requests = []

            def handler(request):
                requests.append(str(request.url))
                return httpx.Response(200, content=b"SUS fixture")

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ) as client:
                owner = SimpleNamespace(
                    config={},
                    asset_dir=Path(temporary),
                    render_dir=Path(temporary),
                    sem=asyncio.Semaphore(1),
                    client=client,
                    log=Mock(),
                )
                service = SongService(owner)
                with patch.object(
                    service, "render_chart", return_value=output.getvalue()
                ) as render:
                    for _ in range(2):
                        self.assertEqual(
                            await service.chart(
                                {"id": 1, "title": "test"}, "master", 26, "font"
                            ),
                            output.getvalue(),
                        )
                    self.assertEqual(render.call_count, 1)
                self.assertEqual(len(requests), 1)
                self.assertIn(
                    "sekai-cn-assets/music/music_score/0001_01/master.txt", requests[0]
                )

    async def test_cn_catalog_does_not_include_jp_only_song(self):
        async def load(url, ttl, age, cleaner):
            if url.endswith("musicDifficulties.json"):
                data = [{"id": 1, "musicId": 1, "musicDifficulty": "master"}]
            elif url.endswith("aliases.json"):
                data = {"musics": [{"music_id": 999, "aliases": ["JPonly"]}]}
            else:
                data = [{"id": 1, "title": "CN title", "publishedAt": 1}]
                if "/jp/" in url:
                    data += [{"id": 999, "title": "JPonly", "publishedAt": 1}]
            return cleaner(data), 123, False

        owner = SimpleNamespace(
            config={},
            master_base="https://example.com/jp/master",
            live=SimpleNamespace(
                master=lambda _: "https://example.com/cn/master",
                load=AsyncMock(side_effect=load),
            ),
        )
        index, _, _ = await SongService(owner).data()
        self.assertEqual(set(index.songs), {1})
