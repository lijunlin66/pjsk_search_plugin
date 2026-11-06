import asyncio
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from astrbot_plugin_pjsk.rendering.live_ui import live_image
from astrbot_plugin_pjsk.rendering.render import Renderer
from astrbot_plugin_pjsk.services.live import (
    LiveService,
    active_event,
    normalize_ranking,
    validate_ranking,
)
from astrbot_plugin_pjsk.services.service import DataUnavailable


def event(now):
    return {
        "id": 10,
        "name": "测试活动",
        "startAt": now - 1000,
        "aggregateAt": now + 86400000,
        "eventType": "marathon",
        "assetbundleName": "fixture",
    }


def ranking(now):
    e = event(now)
    return {
        "region": "cn",
        "event_id": 10,
        "start_at": e["startAt"],
        "end_at": e["aggregateAt"],
        "updated_at": now,
        "rankings": [
            {
                "rank": 1000,
                "score": 123456,
                "name": "not-stored",
                "userId": "not-stored",
            }
        ],
    }


class LivePureTests(unittest.TestCase):
    def test_current_bounds_and_gap(self):
        e = event(10000)
        self.assertIsNone(active_event([e], e["startAt"] - 1))
        self.assertEqual(active_event([e], e["startAt"]), e)
        self.assertIsNone(active_event([e], e["aggregateAt"]))
        with self.assertRaises(DataUnavailable):
            active_event([e, dict(e, id=11)], 10000)

    def test_score_normalization_drops_player_profiles(self):
        data = normalize_ranking(ranking(10000))
        self.assertEqual(data["rankings"], [{"rank": 1000, "score": 123456}])

    def test_wrong_region_event_and_dates_are_rejected(self):
        now = 10000000
        e, data = event(now), normalize_ranking(ranking(now))
        validate_ranking(data, "cn", e, now)
        for change in [
            {"region": "jp"},
            {"event_id": 11},
            {"end_at": 0},
            {"updated_at": now - 900001},
            {"updated_at": now + 300001},
        ]:
            with self.subTest(change=change), self.assertRaises(DataUnavailable):
                validate_ranking(data | change, "cn", e, now)

    def test_current_and_border_images(self):
        now = int(time.time() * 1000)
        value = {
            "region": "cn",
            "event": event(now),
            "fetched_at": now / 1000,
            "participants": ["花里实乃里"],
            "cards": [1, 2],
            "attrs": ["cute"],
            "ranking": normalize_ranking(ranking(now)),
        }
        for borders in [False, True]:
            with Image.open(
                io.BytesIO(live_image(Renderer(), value, borders=borders))
            ) as im:
                im.load()
                self.assertEqual(im.width, 1200)
                self.assertGreater(im.height, 600)


class LiveCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.hits = 0
        self.fail = False

        async def handler(request):
            self.hits += 1
            await asyncio.sleep(0.005)
            return httpx.Response(
                503 if self.fail else 200, json={"value": request.url.path}
            )

        self.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.owner = SimpleNamespace(
            root=Path(self.temp.name), config={}, client=self.client
        )
        self.live = LiveService(self.owner)

    async def asyncTearDown(self):
        await self.client.aclose()
        self.temp.cleanup()

    async def test_concurrent_requests_share_cache_and_regions_stay_separate(self):
        jp, cn = "https://example.com/jp/latest", "https://example.com/cn/latest"
        await asyncio.gather(
            *(self.live.load(jp, 60, 900, lambda d: d) for _ in range(3))
        )
        other = await self.live.load(cn, 60, 900, lambda d: d)
        self.assertEqual(self.hits, 2)
        self.assertEqual(other[0]["value"], "/cn/latest")

    async def test_disk_cache_and_expired_fallback(self):
        url = "https://example.com/jp/latest"
        await self.live.load(url, 60, 900, lambda d: d)
        self.live = LiveService(self.owner)
        self.fail = True
        cached = await self.live.load(url, 60, 900, lambda d: d)
        self.assertFalse(cached[2])
        fallback = await self.live.load(url, 0, 900, lambda d: d)
        self.assertTrue(fallback[2])
        self.assertEqual(self.hits, 2)
        for p in self.live.root.glob("*.json"):
            data = json.loads(p.read_bytes())
            data["fetched_at"] = time.time() - 1000
            p.write_text(json.dumps(data))
        self.live = LiveService(self.owner)
        with self.assertRaises(DataUnavailable):
            await self.live.load(url, 0, 900, lambda d: d)

    async def test_jp_default_line_falls_back_on_wrong_event(self):
        now = int(time.time() * 1000)

        async def handler(request):
            data = ranking(now) | {"region": "jp"}
            if request.url.host == "rks-n.pjsk.moe":
                data["event_id"] = 99
            return httpx.Response(200, json=data)

        await self.client.aclose()
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.owner.client = self.client
        result = await self.live.ranking({"region": "jp", "event": event(now)})
        self.assertEqual(result["ranking"]["event_id"], 10)
        self.assertEqual(result["ranking_source"], "rks-n.exmeaning.com")

    async def test_streamed_card_metadata_handles_split_unicode_and_drops_growth(self):
        payload = json.dumps(
            [
                {
                    "id": 5,
                    "assetbundleName": "card5",
                    "attr": "cute",
                    "prefix": "测试卡面",
                    "cardParameters": [100] * 500,
                }
            ],
            ensure_ascii=False,
        ).encode()

        class Chunks(httpx.AsyncByteStream):
            async def __aiter__(self):
                for offset in range(0, len(payload), 7):
                    yield payload[offset : offset + 7]

        await self.client.aclose()
        self.client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    stream=Chunks(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )
            )
        )
        self.owner.client = self.client
        rows = await self.live.stream_card_metadata("https://example.com/cards.json")
        self.assertEqual(rows[0]["prefix"], "测试卡面")
        self.assertNotIn("cardParameters", rows[0])

    async def test_incomplete_card_stream_is_rejected(self):
        await self.client.aclose()
        self.client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, content=b'[{"id":5,"assetbundleName":"card5","attr":"cute"}'
                )
            )
        )
        self.owner.client = self.client
        with self.assertRaises(ValueError):
            await self.live.stream_card_metadata("https://example.com/cards.json")


if __name__ == "__main__":
    unittest.main()
