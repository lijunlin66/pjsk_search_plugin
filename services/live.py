"""Region-isolated current events and public cutoff snapshots; no game credentials."""

import asyncio
import hashlib
import json
import time
from urllib.parse import urlparse

import httpx

from ..domain.catalog import ATTRS, NAMES
from ..domain.presentation import compact_table
from .service import DataUnavailable, atomic_write

REGIONS = {"jp": "日服", "cn": "国服"}
JP_RANK = "https://rks-n.pjsk.moe/api/public/v2"
CN_RANK = "https://rks-n-cn.exmeaning.com/api/public/v2"
CN_MASTER = "https://sekai-master-cdn.haruki.seiunx.com/haruki-sekai-sc-master/master"
CN_ASSET = "https://storage.exmeaning.com/sekai-cn-assets"
TIERS = {
    1,
    10,
    50,
    100,
    200,
    300,
    400,
    500,
    1000,
    1500,
    2000,
    2500,
    3000,
    4000,
    5000,
    10000,
    20000,
    30000,
    40000,
    50000,
    100000,
    200000,
    300000,
}


def active_event(events, now):
    active = [
        e
        for e in events
        if isinstance(e.get("startAt"), (int, float))
        and isinstance(e.get("aggregateAt"), (int, float))
        and e["startAt"] <= now < e["aggregateAt"]
    ]
    if len(active) > 1:
        raise DataUnavailable("活动时间表存在重叠，暂时无法确定当前活动。")
    return active[0] if active else None


def normalize_ranking(data):
    if not isinstance(data, dict) or not isinstance(data.get("rankings"), list):
        raise TypeError("Invalid ranking response")
    rows = {}
    for row in data["rankings"]:
        if not isinstance(row, dict):
            continue
        rank, score = row.get("rank"), row.get("score")
        if isinstance(rank, bool) or isinstance(score, bool):
            continue
        if isinstance(rank, int) and isinstance(score, int) and rank > 0 and score >= 0:
            rows[rank] = {"rank": rank, "score": score}
    return {
        k: data.get(k)
        for k in ("event_id", "region", "start_at", "end_at", "updated_at")
    } | {"rankings": sorted(rows.values(), key=lambda r: r["rank"])}


def validate_ranking(data, region, event, now):
    if data.get("region") != region or data.get("event_id") != event["id"]:
        raise DataUnavailable("榜线尚未同步至所选服的当前活动，请稍后重试。")
    for key, field in (("start_at", "startAt"), ("end_at", "aggregateAt")):
        value = data.get(key)
        if not isinstance(value, (int, float)) or abs(value - event[field]) > 1000:
            raise DataUnavailable("榜线活动时间与主数据不一致，暂不展示。")
    stamp = data.get("updated_at")
    if (
        not isinstance(stamp, (int, float))
        or stamp > now + 300000
        or now - stamp > 900000
    ):
        raise DataUnavailable("榜线数据已超过 15 分钟未更新或时间异常，请稍后重试。")
    if not data.get("rankings"):
        raise DataUnavailable("当前活动暂时没有可用榜线。")


class LiveService:
    def __init__(self, owner):
        self.owner = owner
        self.root = owner.root / "live"
        self.root.mkdir(exist_ok=True)
        self.memory, self.locks, self.failures = {}, {}, {}

    async def load(self, url, ttl, max_age, cleaner, stream_cards=False):
        if not url.startswith("https://"):
            raise DataUnavailable("实时查询数据地址必须使用 HTTPS。")
        key = hashlib.sha256(url.encode()).hexdigest()
        async with self.locks.setdefault(key, asyncio.Lock()):
            path = self.root / (key + ".json")
            if key not in self.memory and path.exists():
                try:
                    saved = await asyncio.to_thread(
                        lambda: json.loads(path.read_bytes())
                    )
                    self.memory[key] = (saved["fetched_at"], saved["data"])
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            now = time.time()
            cached = self.memory.get(key)
            if cached and 0 <= now - cached[0] < ttl:
                return cached[1], cached[0], False
            try:
                if self.failures.get(key, 0) > now:
                    raise ValueError("Recent request failed")
                if stream_cards:
                    data = await self.stream_card_metadata(url)
                else:
                    response = await self.owner.client.get(url, timeout=8)
                    response.raise_for_status()
                    data = await asyncio.to_thread(lambda: cleaner(response.json()))
                self.memory[key] = (now, data)
                await asyncio.to_thread(
                    atomic_write,
                    path,
                    json.dumps(
                        {"fetched_at": now, "data": data}, ensure_ascii=False
                    ).encode(),
                )
                return data, now, False
            except (ValueError, TypeError, KeyError, OSError) as exc:
                return self.fallback(key, cached, now, max_age, exc)
            except httpx.HTTPError as exc:
                return self.fallback(key, cached, now, max_age, exc)

    async def stream_card_metadata(self, url):
        # Decode one record at a time instead of retaining all card growth data.
        keep = {
            "id",
            "characterId",
            "prefix",
            "attr",
            "cardRarityType",
            "cardSupplyId",
            "assetbundleName",
            "releaseAt",
            "initialSpecialTrainingStatus",
        }
        decoder = json.JSONDecoder()
        rows, buffer, started, ended, expect_value = [], "", False, False, True
        size = 0
        async with self.owner.client.stream("GET", url, timeout=25) as response:
            response.raise_for_status()
            async for chunk in response.aiter_text(chunk_size=65536):
                size += len(chunk)
                if size > 120_000_000:
                    raise ValueError("Card table too large")
                buffer += chunk
                while True:
                    buffer = buffer.lstrip()
                    if not buffer:
                        break
                    if not started:
                        if buffer[0] != "[":
                            raise ValueError("Invalid card table")
                        started, buffer = True, buffer[1:]
                        continue
                    if ended:
                        raise ValueError("Unexpected trailing card data")
                    if not expect_value:
                        if buffer[0] == ",":
                            buffer, expect_value = buffer[1:], True
                            continue
                        if buffer[0] != "]":
                            raise ValueError("Invalid card separator")
                    if buffer[0] == "]":
                        if expect_value and rows:
                            raise ValueError("Trailing card separator")
                        buffer, ended = buffer[1:], True
                        continue
                    try:
                        value, offset = decoder.raw_decode(buffer)
                    except json.JSONDecodeError:
                        break
                    if (
                        not isinstance(value, dict)
                        or not {"id", "assetbundleName", "attr"} <= value.keys()
                    ):
                        raise ValueError("Invalid card record")
                    rows.append({k: v for k, v in value.items() if k in keep})
                    buffer, expect_value = buffer[offset:], False
                    if len(rows) > 10000:
                        raise ValueError("Too many card records")
        if not ended or buffer.strip() or not rows:
            raise ValueError("Incomplete card table")
        return rows

    async def card_records(self, current):
        ids = set(current["cards"])
        catalog = getattr(self.owner, "catalog", None)
        if current["region"] == "jp" and catalog and ids <= catalog.cards.keys():
            records = [catalog.cards[cid] for cid in current["cards"]]
        else:
            records, _, stale = await self.load(
                f"{self.master(current['region'])}/cards.json",
                21600,
                86400,
                lambda data: data,
                stream_cards=True,
            )
            current["extras_stale"] = current.get("extras_stale", False) or stale
            records = [r for r in records if r.get("id") in ids]
        now = int(time.time() * 1000)
        return sorted(
            (r for r in records if r.get("releaseAt", 0) <= now), key=lambda r: r["id"]
        )

    async def card_thumbnails(self, current):
        cards = current.get("card_details", [])
        urls = []
        base = (
            self.owner.asset_base
            if current["region"] == "jp"
            else self.owner.config.get("cn_asset_base", CN_ASSET).rstrip("/")
        )
        for card in cards:
            bundle = card.get("assetbundleName", "")
            if not bundle or not all(
                c.isascii() and (c.isalnum() or c in "_-") for c in bundle
            ):
                urls.append(None)
                continue
            state = (
                "after_training"
                if card.get("initialSpecialTrainingStatus") == "done"
                else "normal"
            )
            urls.append(f"{base}/thumbnail/chara/{bundle}_{state}.webp")
        images = iter(await self.owner.images([url for url in urls if url], budget=15))
        return {
            card["id"]: next(images) if url else None for card, url in zip(cards, urls)
        }

    def fallback(self, key, cached, now, max_age, exc):
        self.failures[key] = now + 15
        if cached and 0 <= now - cached[0] <= max_age:
            return cached[1], cached[0], True
        raise DataUnavailable("实时活动数据源暂不可用，请稍后重试。") from exc

    def master(self, region):
        return (
            self.owner.master_base
            if region == "jp"
            else self.owner.config.get("cn_master_base", CN_MASTER).rstrip("/")
        )

    async def table(self, region, name, required=False):
        def clean(data):
            if (
                not isinstance(data, list)
                or not data
                or not all(isinstance(r, dict) for r in data)
            ):
                raise ValueError("Invalid master table")
            if name == "events" and any(
                not {"id", "startAt", "aggregateAt", "name"} <= r.keys() for r in data
            ):
                raise ValueError("Invalid events")
            return compact_table(name, data)

        try:
            return await self.load(
                f"{self.master(region)}/{name}.json",
                300 if required else 21600,
                86400,
                clean,
            )
        except DataUnavailable:
            if required:
                raise
            return [], 0, True

    async def current(self, region):
        events, fetched, stale = await self.table(region, "events", True)
        now = int(time.time() * 1000)
        event = active_event(events, now)
        if not event:
            if stale:
                raise DataUnavailable(
                    "活动时间表更新失败，无法确认当前活动，请稍后重试。"
                )
            future = sorted(
                (e for e in events if e.get("startAt", 0) > now),
                key=lambda e: e["startAt"],
            )
            return {
                "region": region,
                "event": None,
                "next": future[0] if future else None,
                "fetched_at": fetched,
                "stale": False,
            }
        return {"region": region, "event": event, "fetched_at": fetched, "stale": stale}

    async def enrich(self, current):
        region, event = current["region"], current["event"]
        results = await asyncio.gather(
            *(
                self.table(region, name)
                for name in ("eventDeckBonuses", "gameCharacterUnits", "eventCards")
            )
        )
        bonuses, units, cards = (r[0] for r in results)
        units = {r["id"]: r for r in units if "id" in r}
        deck = [
            r
            for r in bonuses
            if r.get("eventId") == event["id"] and r.get("bonusRate", 0) > 0
        ]
        ids = {
            units[r["gameCharacterUnitId"]]["gameCharacterId"]
            for r in deck
            if r.get("gameCharacterUnitId") in units
        }
        current.update(
            attrs=sorted({r["cardAttr"] for r in deck if r.get("cardAttr") in ATTRS}),
            participants=[
                NAMES.get(cid, str(cid)).split("|")[0] for cid in sorted(ids)
            ],
            cards=sorted(
                {
                    r["cardId"]
                    for r in cards
                    if r.get("eventId") == event["id"]
                    and isinstance(r.get("cardId"), int)
                }
            ),
            extras_stale=any(r[2] for r in results),
        )
        try:
            current["card_details"] = await self.card_records(current)
        except DataUnavailable:
            current["card_details"] = []
            current["extras_stale"] = True
        current["card_images"] = await self.card_thumbnails(current)
        return current

    async def ranking(self, current):
        region, event = current["region"], current["event"]
        base = self.owner.config.get(
            "ranking_jp_base" if region == "jp" else "ranking_cn_base",
            JP_RANK if region == "jp" else CN_RANK,
        ).rstrip("/")
        bases = [base]
        if region == "jp" and base == JP_RANK:
            bases.append("https://rks-n.exmeaning.com/api/public/v2")
        last_error = None
        for source in bases:
            try:
                data, fetched, stale = await self.load(
                    f"{source}/{region}/latest", 60, 900, normalize_ranking
                )
                now = int(time.time() * 1000)
                validate_ranking(data, region, event, now)
                current.update(
                    ranking=data,
                    ranking_fetched=fetched,
                    ranking_stale=stale or now - data["updated_at"] > 300000,
                    ranking_clock_skew=data["updated_at"] > now + 60000,
                    ranking_source=urlparse(source).hostname,
                )
                return current
            except DataUnavailable as exc:
                last_error = exc
        raise last_error

    async def banner(self, current):
        bundle = current["event"].get("assetbundleName", "")
        if not bundle or not all(
            c.isascii() and (c.isalnum() or c in "_-") for c in bundle
        ):
            return None
        base = (
            self.owner.asset_base
            if current["region"] == "jp"
            else self.owner.config.get("cn_asset_base", CN_ASSET).rstrip("/")
        )
        try:
            return await asyncio.wait_for(
                self.owner.image(f"{base}/home/banner/{bundle}/{bundle}.webp"),
                timeout=8,
            )
        except TimeoutError:
            return None
