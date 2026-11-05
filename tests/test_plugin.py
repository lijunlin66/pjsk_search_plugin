"""Run: python -m unittest discover -s tests -v (no AstrBot or network needed)."""

import asyncio
import importlib
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from astrbot_plugin_pjsk.catalog import Catalog, skill_text, trained, trained_only
from astrbot_plugin_pjsk.render import Renderer
from astrbot_plugin_pjsk.service import DataUnavailable, Service, validate_table


def tables():
    return {
        "cards": [
            {
                "id": 100 + i,
                "characterId": 5 if i < 2 else 21,
                "cardRarityType": "rarity_4",
                "releaseAt": 1,
                "assetbundleName": f"res005_no00{i}",
                "attr": "cute",
                "prefix": "测试卡",
                "skillId": 1,
                "supportUnit": "idol" if i == 2 else "none",
            }
            for i in range(3)
        ],
        "gameCharacters": [
            {
                "id": 5,
                "givenName": "みのり",
                "firstName": "花里",
                "givenNameEnglish": "MINORI",
                "firstNameEnglish": "HANASATO",
                "unit": "idol",
            },
            {"id": 21, "givenName": "ミク", "firstName": "初音", "unit": "piapro"},
        ],
        "skills": [
            {
                "id": 1,
                "description": "{{1;d}}秒 {{1;v}}%",
                "skillEffects": [
                    {
                        "id": 1,
                        "skillEffectDetails": [
                            {
                                "level": 1,
                                "activateEffectDuration": 5,
                                "activateEffectValue": 80,
                            }
                        ],
                    }
                ],
            }
        ],
        "cardRarities": [
            {
                "cardRarityType": "rarity_4",
                "maxLevel": 50,
                "trainingMaxLevel": 60,
                "maxSkillLevel": 4,
            }
        ],
    }


class Log:
    def info(self, *_):
        pass

    def warning(self, *_):
        pass

    def exception(self, *_):
        pass


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog(tables())

    def test_all_character_spellings(self):
        for q in (
            "花里实乃里",
            "实乃里",
            "mnr",
            "MINORI",
            "花里みのり",
            "Hanasato Minori",
            "Minori Hanasato",
        ):
            self.assertEqual({c["id"] for c in self.catalog.search(q)}, {100, 101}, q)

    def test_team_includes_support_singers(self):
        for q in ("MMJ", "MORE MORE JUMP!", "moremorejump"):
            self.assertEqual(len(self.catalog.search(q)), 3)

    def test_numeric_id_and_missing(self):
        self.assertEqual(self.catalog.search("100")[0]["id"], 100)
        self.assertEqual(self.catalog.search("99999"), [])

    def test_unreleased_filtered(self):
        t = tables()
        t["cards"][0]["releaseAt"] = 9_999_999_999_999
        self.assertEqual(len(Catalog(t).search("mnr")), 1)

    def test_custom_alias(self):
        self.assertEqual(len(Catalog(tables(), "小实=5").search("小实")), 2)

    def test_training_states(self):
        self.assertFalse(trained({"cardRarityType": "rarity_birthday"}))
        c = {"cardRarityType": "rarity_4", "initialSpecialTrainingStatus": "done"}
        self.assertTrue(trained_only(c))
        self.assertFalse(trained(c))

    def test_skills_and_unknown(self):
        self.assertEqual(skill_text(tables()["skills"][0], 1), "5秒 80%")
        self.assertIn(
            "未解析", skill_text({"description": "{{999;v}}", "skillEffects": []}, 1)
        )

    def test_bad_master_schema(self):
        for value in ({}, [], [{"id": 1}]):
            with self.assertRaises(DataUnavailable):
                validate_table("cards", value)


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_page_deadline_cancels_slow_downloads(self):
        self.service.config["image_budget"] = 3

        async def handler(request):
            await asyncio.sleep(30)
            return httpx.Response(200, content=self.webp)

        self.mock(handler)
        result = await asyncio.wait_for(
            self.service.images(["https://example.com/slow"]), timeout=4
        )
        self.assertEqual(result, [None])
        self.assertEqual(self.service.pending, {})

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = Service(self.temp.name, {}, Log())
        await self.service.client.aclose()
        im = Image.new("RGB", (24, 16), "red")
        out = io.BytesIO()
        im.save(out, "WEBP")
        self.webp = out.getvalue()

    async def asyncTearDown(self):
        await self.service.close()
        self.temp.cleanup()

    def mock(self, handler):
        self.service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def test_successful_atomic_snapshot(self):
        t = tables()
        self.mock(lambda r: httpx.Response(200, json=t[r.url.path.split("/")[-1][:-5]]))
        await self.service.refresh()
        self.assertTrue(self.service.snapshot.exists())
        self.assertEqual(len(self.service.catalog.cards), 3)

    async def test_refresh_keeps_metadata_until_reader_releases_lock(self):
        t = tables()
        self.mock(lambda r: httpx.Response(200, json=t[r.url.path.split("/")[-1][:-5]]))
        self.service.extra_cache["events"] = (1, [{"id": 1}])
        written = asyncio.Event()
        loop = asyncio.get_running_loop()
        from astrbot_plugin_pjsk.service import atomic_write

        def save(path, data):
            atomic_write(path, data)
            loop.call_soon_threadsafe(written.set)

        with patch("astrbot_plugin_pjsk.service.atomic_write", side_effect=save):
            async with self.service.extra_lock:
                task = asyncio.create_task(self.service.refresh())
                await asyncio.wait_for(written.wait(), 3)
                self.assertFalse(task.done())
                self.assertIn("events", self.service.extra_cache)
            await asyncio.wait_for(task, 3)
        self.assertNotIn("events", self.service.extra_cache)

    async def test_failure_preserves_old_snapshot(self):
        self.service.catalog = Catalog(tables())
        old = self.service.catalog
        self.mock(lambda r: httpx.Response(503))
        with self.assertRaises(httpx.HTTPError):
            await self.service.refresh()
        self.assertIs(self.service.catalog, old)

    async def test_disk_image_cache_and_dedup(self):
        hits = []

        async def handler(r):
            hits.append(1)
            await asyncio.sleep(0.02)
            return httpx.Response(200, content=self.webp)

        self.mock(handler)
        url = "https://example.com/test.webp"
        a, b = await asyncio.gather(self.service.image(url), self.service.image(url))
        self.assertEqual(a, b)
        self.assertEqual(len(hits), 1)
        self.assertEqual(await self.service.image(url), a)
        self.assertEqual(len(hits), 1)

    async def test_bad_image_and_negative_cache(self):
        hits = []

        def handler(r):
            hits.append(1)
            return httpx.Response(200, content=b"not an image")

        self.mock(handler)
        self.assertIsNone(await self.service.image("https://example.com/x"))
        self.assertIsNone(await self.service.image("https://example.com/x"))
        self.assertEqual(len(hits), 1)

    async def test_partial_failure_does_not_break_gallery(self):
        self.mock(
            lambda r: (
                httpx.Response(200, content=self.webp)
                if r.url.path == "/ok"
                else httpx.Response(404)
            )
        )
        a, b = await self.service.images(
            ["https://example.com/ok", "https://example.com/bad"]
        )
        self.assertTrue(a)
        self.assertIsNone(b)

    async def test_concurrency_is_bounded(self):
        active = peak = 0

        async def handler(r):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1
            return httpx.Response(200, content=self.webp)

        self.mock(handler)
        await self.service.images([f"https://example.com/{i}" for i in range(18)])
        self.assertLessEqual(peak, 6)
        self.assertGreater(peak, 1)

    async def test_trained_only_uses_existing_art(self):
        c = tables()["cards"][0]
        c["initialSpecialTrainingStatus"] = "done"
        self.assertIn("after_training", self.service.image_url(c, thumb=True))


class EntryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Only the framework boundary is mocked. Network/cache/layout are tested separately.
        def deco(*a, **k):
            return lambda fn: fn

        api = types.ModuleType("astrbot.api")
        api.AstrBotConfig = dict
        api.logger = Log()
        event = types.ModuleType("astrbot.api.event")
        event.AstrMessageEvent = object
        event.filter = types.SimpleNamespace(
            command=deco,
            permission_type=deco,
            PermissionType=types.SimpleNamespace(ADMIN=1),
        )
        components = types.ModuleType("astrbot.api.message_components")
        components.Image = types.SimpleNamespace(fromBytes=lambda b: b)
        star = types.ModuleType("astrbot.api.star")
        star.Context = object
        star.Star = type("Star", (), {})
        paths = types.ModuleType("astrbot.core.utils.astrbot_path")
        paths.get_astrbot_data_path = lambda: "."
        self.saved = {}
        for name, value in {
            "astrbot.api": api,
            "astrbot.api.event": event,
            "astrbot.api.message_components": components,
            "astrbot.api.star": star,
            "astrbot.core.utils.astrbot_path": paths,
        }.items():
            self.saved[name] = sys.modules.get(name)
            sys.modules[name] = value
        self.main = importlib.import_module("astrbot_plugin_pjsk.main")
        self.plugin = self.main.PjskPlugin.__new__(self.main.PjskPlugin)
        self.plugin.config = {}
        self.plugin.busy = False
        self.plugin.query_lock = asyncio.Lock()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.plugin.renderer = types.SimpleNamespace(
            font_path="test", gallery=Mock(return_value=b"image")
        )
        self.plugin.service = types.SimpleNamespace(
            ensure=AsyncMock(return_value=Catalog(tables())),
            revision="fixture",
            master_base="https://example.com/master",
            asset_base="https://example.com/assets",
            render_dir=Path(self.temp.name),
            stale=False,
            updated_at=1,
            gallery_images=AsyncMock(
                side_effect=lambda cards: [(None, None) for _ in cards]
            ),
            prune=lambda: None,
        )

    async def asyncTearDown(self):
        for name, value in self.saved.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value
        sys.modules.pop("astrbot_plugin_pjsk.main", None)

    async def run_event(self, text):
        event = types.SimpleNamespace(
            get_message_str=lambda: text,
            plain_result=lambda t: t,
            chain_result=lambda chain: chain,
            send=AsyncMock(),
        )
        results = [r async for r in self.plugin.lookup(event)]
        return [call.args[0] for call in event.send.await_args_list] + results

    async def test_normal_lookup_command(self):
        self.assertIn("共 2 张", (await self.run_event("查卡 mnr"))[1])

    async def test_live_prefix_handlers_select_correct_server_and_mode(self):
        seen = []

        async def capture(event, region, borders=False):
            seen.append((region, borders))
            yield "ok"

        self.plugin.live_lookup = capture
        for name in ("current_cn", "current_jp", "borders_cn", "borders_jp"):
            self.assertEqual(
                [r async for r in getattr(self.plugin, name)(object())], ["ok"]
            )
        self.assertEqual(
            seen, [("cn", False), ("jp", False), ("cn", True), ("jp", True)]
        )

    async def test_upload_921_retries_once(self):
        output = io.BytesIO()
        Image.new("RGB", (32, 48), "blue").save(output, "JPEG")
        event = types.SimpleNamespace(
            chain_result=lambda chain: chain,
            send=AsyncMock(
                side_effect=[RuntimeError("highway upload error_code=921"), None]
            ),
        )
        result = await self.plugin.deliver_image(event, output.getvalue())
        self.assertEqual(event.send.await_count, 2)
        self.assertLess(len(result), 4 * 1024 * 1024)

    async def test_unrelated_send_failure_is_not_retried(self):
        event = types.SimpleNamespace(
            chain_result=lambda chain: chain,
            send=AsyncMock(side_effect=RuntimeError("connection closed")),
        )
        with self.assertRaisesRegex(RuntimeError, "connection closed"):
            await self.plugin.deliver_image(event, b"small")
        self.assertEqual(event.send.await_count, 1)

    async def test_failed_image_send_does_not_claim_success(self):
        output = io.BytesIO()
        Image.new("RGB", (32, 48), "blue").save(output, "JPEG")
        self.plugin.renderer.gallery.return_value = output.getvalue()
        event = types.SimpleNamespace(
            get_message_str=lambda: "查卡 mnr",
            plain_result=lambda text: text,
            chain_result=lambda chain: chain,
            send=AsyncMock(side_effect=RuntimeError("highway upload error_code=921")),
        )
        results = [r async for r in self.plugin.lookup(event)]
        self.assertEqual(event.send.await_count, 2)
        self.assertTrue(any("发送失败" in r for r in results))
        self.assertFalse(any("已全部合成" in r for r in results))

    async def test_help_without_parameters(self):
        self.plugin.help_image = AsyncMock(return_value=b"help-image")
        self.assertEqual((await self.run_event("pjsk"))[0], [b"help-image"])

    async def test_unified_help_command_returns_one_image_without_loading_data(self):
        self.plugin.help_image = AsyncMock(return_value=b"complete-guide")
        event = types.SimpleNamespace(chain_result=lambda chain: chain)
        self.assertEqual(
            [r async for r in self.plugin.query_help(event)], [[b"complete-guide"]]
        )
        self.plugin.help_image.assert_awaited_once_with("all")
        self.plugin.service.ensure.assert_not_awaited()

    async def test_help_entrances_share_persistent_cache_and_failures_stay_distinct(
        self,
    ):
        self.plugin.service.root = Path(self.temp.name)
        with patch.object(self.main, "guide", return_value=b"cached-guide") as render:
            for kind in ("all", "card", "event"):
                self.assertEqual(await self.plugin.help_image(kind), b"cached-guide")
            self.assertEqual(render.call_count, 1)
            await self.plugin.help_image("card", True)
            await self.plugin.help_image("event", True)
            self.assertEqual(render.call_count, 3)
            self.assertEqual(len(list(Path(self.temp.name).glob("guide-*.jpg"))), 3)
        # Reading a warmed cache must work even when rendering is unavailable.
        with patch.object(self.main, "guide", side_effect=RuntimeError("no render")):
            self.assertEqual(await self.plugin.help_image("all"), b"cached-guide")

    async def test_live_help_returns_unified_image_without_requesting_live_data(self):
        self.plugin.help_image = AsyncMock(return_value=b"complete-guide")
        event = types.SimpleNamespace(
            get_message_str=lambda: "/cn榜线 帮助",
            chain_result=lambda chain: chain,
        )
        self.assertEqual(
            [r async for r in self.plugin.live_lookup(event, "cn", True)],
            [[b"complete-guide"]],
        )

    async def test_team_with_spaces_returns_all(self):
        self.assertIn(
            "共 3 张，已全部", (await self.run_event("pjsk MORE MORE JUMP!"))[1]
        )

    async def test_legacy_page_suffix_still_returns_all(self):
        self.assertIn(
            "共 2 张，已全部", (await self.run_event("pjsk查询 mnr 第2页"))[1]
        )

    async def test_more_than_old_page_size_is_never_sliced(self):
        data = tables()
        data["cards"] = [dict(data["cards"][0], id=1000 + i) for i in range(54)]
        self.plugin.config["page_size"] = 4
        self.plugin.service.ensure.return_value = Catalog(data)
        results = await self.run_event("pjsk mnr")
        self.assertIn("共 54 张，已全部", results[1])
        self.assertEqual(len(self.plugin.renderer.gallery.call_args.args[0]), 54)
        self.assertEqual(self.plugin.renderer.gallery.call_args.args[0][-1]["id"], 1000)
        self.assertNotIn("下一页", results[1])

    async def test_busy_has_immediate_feedback(self):
        self.plugin.busy = True
        self.assertIn("稍后", (await self.run_event("pjsk mnr"))[0])


class RenderTests(unittest.TestCase):
    def test_unicode_layout_and_missing_image(self):
        renderer = Renderer()
        catalog = Catalog(tables())
        cards = list(catalog.cards.values())
        outputs = [
            renderer.gallery(cards, [None] * 3, catalog, "花里实乃里", "缓存"),
            renderer.detail(cards[0], [None, None], catalog, {}, "缓存"),
        ]
        for output in outputs:
            with Image.open(io.BytesIO(output)) as im:
                self.assertGreaterEqual(im.width, 1000)
                self.assertGreater(im.height, 300)
                im.verify()


if __name__ == "__main__":
    unittest.main()
