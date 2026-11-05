import io
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from astrbot_plugin_pjsk.activity_ui import atlas, dossier, guide
from astrbot_plugin_pjsk.catalog import Catalog
from astrbot_plugin_pjsk.events import EventIndex, QueryError
from astrbot_plugin_pjsk.render import Renderer


class ActivityTests(unittest.TestCase):
    def setUp(self):
        chars = [
            {"id": cid, "givenName": str(cid), "unit": u}
            for cid, u in [
                (5, "idol"),
                (9, "street"),
                (16, "theme_park"),
                (23, "piapro"),
            ]
        ]
        cards = [
            {
                "id": cid,
                "characterId": cid,
                "cardRarityType": "rarity_2",
                "assetbundleName": "fixture",
                "releaseAt": 0,
                "attr": "cute",
                "supportUnit": "idol" if cid == 23 else "none",
            }
            for cid in [5, 9, 16, 23]
        ]
        self.catalog = Catalog(
            {"cards": cards, "gameCharacters": chars, "skills": [], "cardRarities": []}
        )
        tables = {
            "events": [
                {
                    "id": i,
                    "name": "测试活动",
                    "startAt": 1 if i != 4 else 9999999999999,
                    "aggregateAt": 1000,
                    "unit": "none",
                    "eventType": "marathon" if i != 3 else "cheerful_carnival",
                    "assetbundleName": "fixture",
                }
                for i in [1, 2, 3, 4]
            ],
            "eventCards": [
                {"eventId": i, "cardId": cid}
                for i, ids in [(1, [5, 23]), (2, [5, 9]), (3, [9, 16]), (4, [5])]
                for cid in ids
            ],
            "gameCharacterUnits": [
                {
                    "id": c["id"],
                    "gameCharacterId": c["id"],
                    "unit": "idol" if c["id"] == 23 else c["unit"],
                }
                for c in chars
            ],
            "eventDeckBonuses": [
                {
                    "eventId": i,
                    "gameCharacterUnitId": cid,
                    "cardAttr": "cute",
                    "bonusRate": 25,
                }
                for i, ids in [(1, [5, 23]), (2, [5, 9]), (3, [9, 16])]
                for cid in ids
            ],
        }
        self.index = EventIndex(self.catalog, tables)

    def ids(self, query):
        return {r["event"]["id"] for r in self.index.search(query)}

    def test_team_exact_and_inclusion(self):
        self.assertEqual(self.ids("mmj"), {1})
        self.assertEqual(self.ids("mmj混"), {1, 2})
        self.assertEqual(self.ids("mmj加成"), {1, 2})
        self.assertEqual(self.ids("vbs ws"), {3})

    def test_roles_must_all_have_cards(self):
        self.assertEqual(self.ids("mnr"), {1, 2})
        self.assertEqual(self.ids("mnr khn"), {2})
        self.assertEqual(self.ids("mnr rui"), set())

    def test_team_role_mixed_and_unit_event(self):
        self.assertEqual(self.ids("vbs rui"), {3})
        self.assertEqual(self.ids("mmj len"), {1})
        self.assertEqual(self.ids("ws rui"), set())

    def test_scoped_virtual_singer(self):
        self.assertEqual(self.ids("mmjlen"), {1})
        self.assertEqual(self.ids("vbslen"), set())

    def test_type_attr_and_shape(self):
        self.assertEqual(self.ids("箱活 粉花"), {1})
        self.assertEqual(self.ids("混活 5v5 cute"), {3})
        self.assertEqual(self.ids("马拉松 蓝星"), set())

    def test_numeric_and_unreleased(self):
        self.assertEqual(self.ids("1"), {1})
        self.assertEqual(self.ids("4"), set())
        self.assertEqual(self.ids("全部"), {1, 2, 3})

    def test_unknown_condition_is_not_ignored(self):
        with self.assertRaises(QueryError):
            self.index.search("mnr invalid-filter")

    def test_images_are_valid_and_have_content(self):
        renderer = Renderer()
        record = self.index.records[0]
        for data in [
            guide(renderer, "event", True),
            guide(renderer, "card"),
            atlas(renderer, self.index.records, {}, self.catalog, "测试"),
            dossier(renderer, record, {}, self.catalog),
        ]:
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                self.assertGreater(image.height, 500)
                self.assertGreater(image.width, 1000)


if __name__ == "__main__":
    unittest.main()
