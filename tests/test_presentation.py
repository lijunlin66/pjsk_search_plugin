import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from astrbot_plugin_pjsk.domain.presentation import compact_table, related, variants
from astrbot_plugin_pjsk.services.service import (
    DataUnavailable,
    Service,
    validate_table,
)


class RelatedTests(unittest.TestCase):
    def setUp(self):
        self.card = {"id": 1395, "releaseAt": 1000}
        self.tables = {
            "gachas": [
                {
                    "id": 1,
                    "startAt": 1000,
                    "gachaPickups": [],
                    "gachaDetails": [{"cardId": 1395}],
                },
                {"id": 952, "startAt": 990, "gachaPickups": [{"cardId": 1395}]},
                {"id": 999, "startAt": 99999, "gachaPickups": [{"cardId": 1395}]},
            ],
            "events": [{"id": 205, "startAt": 1000}, {"id": 218, "startAt": 999}],
            "eventCards": [
                {"cardId": 1395, "eventId": 205, "isDisplayCardStory": True},
                {"cardId": 1395, "eventId": 218, "isDisplayCardStory": False},
            ],
            "eventMusics": [{"eventId": 205, "musicId": 743}],
            "musics": [{"id": 743}, {"id": 999}],
            "cardCostume3ds": [{"cardId": 1395, "costume3dId": 23}],
            "costume3ds": [{"id": 23, "partType": "hair"}],
            "costume3dModels": [
                {
                    "id": 1,
                    "costume3dId": 23,
                    "unit": "piapro",
                    "thumbnailAssetbundleName": "wrong",
                },
                {
                    "id": 2,
                    "costume3dId": 23,
                    "unit": "idol",
                    "thumbnailAssetbundleName": "correct",
                },
            ],
        }

    def test_initial_pickup_not_normal_pool_or_rerun(self):
        self.assertEqual(
            related(self.card, self.tables, "idol")["gachas"][0]["id"], 952
        )

    def test_story_event_not_later_bonus_event(self):
        links = related(self.card, self.tables, "idol")
        self.assertEqual([e["id"] for e in links["events"]], [205])
        self.assertEqual([m["id"] for m in links["musics"]], [743])

    def test_costume_model_uses_correct_unit(self):
        costume = related(self.card, self.tables, "idol")["costumes"][0]
        self.assertEqual(costume["thumbnailAssetbundleName"], "correct")

    def test_compact_gacha_keeps_pickups_and_drops_pool(self):
        row = compact_table("gachas", self.tables["gachas"])[0]
        self.assertNotIn("gachaDetails", row)
        self.assertIn("gachaPickups", row)

    def test_relation_tables_without_id_are_valid(self):
        validate_table("cardCostume3ds", self.tables["cardCostume3ds"])
        validate_table("eventMusics", self.tables["eventMusics"])

    def test_nontrainable_has_no_redundant_image(self):
        self.assertEqual(variants({"cardRarityType": "rarity_birthday"}), [False])
        self.assertEqual(variants({"cardRarityType": "rarity_4"}), [False, True])
        self.assertEqual(
            variants(
                {"cardRarityType": "rarity_4", "initialSpecialTrainingStatus": "done"}
            ),
            [True],
        )


class CacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_expired_disk_metadata_survives_network_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            log = type(
                "Log", (), {"warning": lambda *a: None, "exception": lambda *a: None}
            )()
            service = Service(temp, {}, log)
            try:
                saved = {
                    "updated_at": time.time() - 22000,
                    "rows": [{"id": 3, "cardId": 1395, "title": "已缓存剧情"}],
                }
                (
                    service.master_dir / f"extra-{service.source_key}-cardEpisodes.json"
                ).write_text(json.dumps(saved))
                service._json = AsyncMock(side_effect=DataUnavailable("offline"))
                extras = await service.extras(
                    {"id": 1395, "cardSupplyId": 3, "releaseAt": 1}
                )
                self.assertEqual(
                    extras["卡片剧情 / 解锁条件 / 剧情加成"][0]["title"], "已缓存剧情"
                )
                self.assertEqual(extras["_related"]["musics"], [])
            finally:
                await service.close()


if __name__ == "__main__":
    unittest.main()
