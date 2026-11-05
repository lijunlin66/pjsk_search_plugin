"""Bounded asynchronous downloads, persistent caches and atomic master snapshots."""

import asyncio
import hashlib
import io
import json
import time
from pathlib import Path

import httpx
from PIL import Image

from .catalog import Catalog, trained, trained_only
from .presentation import compact_table, related, variants


class DataUnavailable(Exception):
    pass


def atomic_write(path, content):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(content)
    temp.replace(path)


def validate_table(name, rows):
    if (
        not isinstance(rows, list)
        or not rows
        or not all(isinstance(r, dict) for r in rows)
    ):
        raise DataUnavailable(f"{name} 数据结构异常")
    required = {
        "cardCostume3ds": {"cardId", "costume3dId"},
        "eventMusics": {"eventId", "musicId"},
        "cards": {
            "id",
            "characterId",
            "assetbundleName",
            "cardRarityType",
            "releaseAt",
        },
        "gameCharacters": {"id", "givenName", "unit"},
        "skills": {"id", "skillEffects"},
        "cardRarities": {"cardRarityType", "maxLevel"},
    }.get(name, {"id"})
    if any(not required <= r.keys() for r in rows):
        raise DataUnavailable(f"{name} 缺少必要字段")
    return rows


class Service:
    CORE = ("cards", "gameCharacters", "skills", "cardRarities")

    def __init__(self, root, config, log):
        self.root = Path(root)
        self.config = config
        self.log = log
        self.master_base = config.get(
            "master_base", "https://sekai-world.github.io/sekai-master-db-diff"
        ).rstrip("/")
        self.asset_base = config.get(
            "asset_base", "https://storage.sekai.best/sekai-jp-assets"
        ).rstrip("/")
        if not all(
            base.startswith("https://") for base in (self.master_base, self.asset_base)
        ):
            raise ValueError("数据与图片地址必须使用 HTTPS")
        self.asset_dir = self.root / "images"
        self.render_dir = self.root / "renders"
        self.master_dir = self.root / "master"
        for p in (self.asset_dir, self.render_dir, self.master_dir):
            p.mkdir(parents=True, exist_ok=True)
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(25, connect=5),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=12, max_keepalive_connections=8),
            headers={
                "User-Agent": "astrbot_plugin_pjsk/1.3.0",
                "Accept-Encoding": "gzip, deflate",
            },
        )
        self.sem = asyncio.Semaphore(
            max(1, min(8, int(config.get("image_concurrency", 6))))
        )
        self.refresh_lock = asyncio.Lock()
        self.catalog = None
        self.revision = ""
        self.updated_at = 0
        self.retry_at = 0
        self.stale = False
        self.pending = {}
        self.negative = {}
        self.extra_cache = {}
        self.extra_lock = asyncio.Lock()
        self.refresh_task = None
        self.closed = False
        self.source_key = hashlib.sha256(self.master_base.encode()).hexdigest()[:12]
        self.snapshot = self.master_dir / f"snapshot-{self.source_key}.json"
        from .live import LiveService

        self.live = LiveService(self)

    async def start(self):
        if self.snapshot.exists():
            try:
                data = await asyncio.to_thread(
                    lambda: json.loads(self.snapshot.read_bytes())
                )
                for name in self.CORE:
                    validate_table(name, data["tables"][name])
                self.catalog = Catalog(
                    data["tables"], self.config.get("character_aliases", "")
                )
                self.updated_at = data["updated_at"]
                self.revision = data["revision"]
            except (OSError, ValueError, KeyError, TypeError, DataUnavailable):
                self.log.warning("PJSK 本地主数据缓存无效，将重新下载")
        self.queue_refresh()

    def queue_refresh(self):
        if not self.closed and (self.refresh_task is None or self.refresh_task.done()):
            self.refresh_task = asyncio.create_task(self._background_refresh())

    async def _background_refresh(self):
        try:
            await self.refresh()
        except Exception as exc:
            self.stale = True
            self.log.exception(f"PJSK 更新失败，保留已有缓存：{type(exc).__name__}")

    async def ensure(self):
        if self.catalog is None:
            if self.refresh_task:
                await self.refresh_task
            if self.catalog is None:
                raise DataUnavailable("日服数据暂时不可用，请稍后重试或检查数据地址")
        ttl = max(1, min(168, int(self.config.get("master_ttl_hours", 6)))) * 3600
        if time.time() - self.updated_at > ttl and time.time() > self.retry_at:
            self.queue_refresh()
        return self.catalog

    async def _json(self, name):
        response = await self.client.get(f"{self.master_base}/{name}.json")
        response.raise_for_status()
        return await asyncio.to_thread(
            lambda: compact_table(name, validate_table(name, response.json()))
        )

    async def refresh(self):
        async with self.refresh_lock:
            self.retry_at = time.time() + 300
            # Publish only after ALL core tables have been downloaded and validated.
            results = await asyncio.gather(*(self._json(n) for n in self.CORE))
            tables = dict(zip(self.CORE, results))
            raw = await asyncio.to_thread(
                lambda: json.dumps(
                    tables, ensure_ascii=False, separators=(",", ":")
                ).encode()
            )
            revision = hashlib.sha256(raw).hexdigest()[:16]
            updated = time.time()
            catalog = await asyncio.to_thread(
                Catalog, tables, self.config.get("character_aliases", "")
            )
            snapshot = await asyncio.to_thread(
                lambda: json.dumps(
                    {"tables": tables, "revision": revision, "updated_at": updated},
                    ensure_ascii=False,
                ).encode()
            )
            await asyncio.to_thread(atomic_write, self.snapshot, snapshot)
            async with self.extra_lock:
                self.catalog, self.revision, self.updated_at = (
                    catalog,
                    revision,
                    updated,
                )
                self.stale = False
                self.extra_cache.clear()

    async def load_extra_tables(self, names):
        now = time.time()
        for name in names:
            cache = self.master_dir / f"extra-{self.source_key}-{name}.json"
            if name not in self.extra_cache and cache.exists():
                try:
                    saved = await asyncio.to_thread(
                        lambda p=cache: json.loads(p.read_bytes())
                    )
                    self.extra_cache[name] = (saved["updated_at"], saved["rows"])
                except (OSError, ValueError, KeyError, TypeError):
                    pass
        missing = [
            n
            for n in names
            if n not in self.extra_cache or now - self.extra_cache[n][0] > 21600
        ]
        results = await asyncio.gather(
            *(asyncio.wait_for(self._json(n), timeout=8) for n in missing),
            return_exceptions=True,
        )
        for n, value in zip(missing, results):
            if isinstance(value, Exception):
                self.log.warning(f"PJSK 扩展表 {n} 暂不可用")
                # Negative cache prevents repeated failed requests.
                self.extra_cache[n] = (
                    now - 21300,
                    self.extra_cache.get(n, (0, []))[1],
                )
            else:
                self.extra_cache[n] = (now, value)
                await asyncio.to_thread(
                    lambda name=n, rows=value: atomic_write(
                        self.master_dir / f"extra-{self.source_key}-{name}.json",
                        json.dumps(
                            {"updated_at": now, "rows": rows}, ensure_ascii=False
                        ).encode(),
                    )
                )

    async def extras(self, card):
        # Linked data is fetched only for details, never on the gallery hot path.
        async with self.extra_lock:
            names = (
                "cardEpisodes",
                "costume3ds",
                "masterLessonRewards",
                "resourceBoxes",
                "cardCostume3ds",
                "costume3dModels",
                "gachas",
                "events",
                "eventCards",
                "eventMusics",
                "musics",
            )
            await self.load_extra_tables(names)
            episodes = self.extra_cache.get("cardEpisodes", (0, []))[1]
            rewards = [
                r
                for r in self.extra_cache.get("masterLessonRewards", (0, []))[1]
                if r.get("cardId") == card["id"]
            ]
            box_ids = {r.get("resourceBoxId") for r in rewards}
            boxes = [
                r
                for r in self.extra_cache.get("resourceBoxes", (0, []))[1]
                if r.get("id") in box_ids
                and r.get("resourceBoxPurpose") == "master_lesson_reward"
            ]
            links = await asyncio.to_thread(
                related,
                card,
                {n: self.extra_cache.get(n, (0, []))[1] for n in names},
                self.catalog.unit(card) if self.catalog else "none",
            )
        return {
            "卡片剧情 / 解锁条件 / 剧情加成": [
                e for e in episodes if e.get("cardId") == card["id"]
            ],
            "专精奖励 / 服装解锁": rewards + boxes,
            "_related": links,
        }

    async def activity_data(self):
        from .events import EventIndex

        catalog = await self.ensure()
        names = (
            "events",
            "eventCards",
            "eventDeckBonuses",
            "gameCharacterUnits",
            "gachas",
            "eventMusics",
            "musics",
            "cheerfulCarnivalTeams",
        )
        async with self.extra_lock:
            await self.load_extra_tables(names)
            tables = {n: self.extra_cache.get(n, (0, []))[1] for n in names}
            if any(not tables[n] for n in names[:4]):
                raise DataUnavailable(
                    "活动资料暂不可用，请稍后重试；已有卡面查询仍可使用。"
                )
            return await asyncio.to_thread(EventIndex, catalog, tables)

    async def activity_media(self, records, detail=False):
        urls = {}
        for record in records:
            e = record["event"]
            bundle = e["assetbundleName"]
            if not bundle or any(
                c
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                for c in bundle
            ):
                continue
            urls[f"event:{e['id']}"] = (
                f"{self.asset_base}/home/banner/{bundle}/{bundle}.webp"
            )
            for card in record["cards"]:
                urls[f"card:{card['id']}"] = self.image_url(card, thumb=True)
            if detail:
                for g in record["gachas"]:
                    urls[f"gacha:{g['id']}"] = (
                        f"{self.asset_base}/home/banner/banner_gacha{g['id']}/banner_gacha{g['id']}.webp"
                    )
        budget = min(180, max(12, len(urls) / 2))
        values = await self.images(list(urls.values()), budget=budget)
        return dict(zip(urls, values))

    async def gallery_images(self, cards):
        urls = [
            self.image_url(c, after=after, thumb=True)
            for c in cards
            for after in variants(c)
        ]
        base = max(3, min(30, int(self.config.get("image_budget", 12))))
        budget = min(180, base * max(1, (len(urls) + 23) // 24))
        images = iter(await self.images(urls, budget=budget))
        return [tuple(next(images) for _ in variants(c)) for c in cards]

    async def detail_media(self, card, extras):
        links = extras.get("_related", {})
        urls = {}
        for i, after in enumerate(variants(card)):
            urls[f"thumb:{i}"] = self.image_url(card, after=after, thumb=True)
        for kind, template in (
            ("gachas", "home/banner/banner_gacha{id}/banner_gacha{id}.webp"),
            ("events", "home/banner/{assetbundleName}/{assetbundleName}.webp"),
            ("musics", "music/jacket/{assetbundleName}/{assetbundleName}.webp"),
            ("costumes", "thumbnail/costume/{thumbnailAssetbundleName}.webp"),
        ):
            for i, record in enumerate(links.get(kind, [])):
                if kind == "costumes" and not record.get("thumbnailAssetbundleName"):
                    continue
                path = template.format(**record)
                if ".." not in path and all(
                    c.isascii() and (c.isalnum() or c in "_-/.") for c in path
                ):
                    urls[f"{kind}:{i}"] = f"{self.asset_base}/{path}"
        values = await self.images(list(urls.values()))
        return dict(zip(urls, values))

    def image_url(self, card, after=False, thumb=False):
        bundle = card["assetbundleName"]
        if (
            not isinstance(bundle, str)
            or not bundle
            or any(
                c
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                for c in bundle
            )
        ):
            raise DataUnavailable("卡图资源名异常")
        suffix = (
            "after_training"
            if (after and trained(card)) or trained_only(card)
            else "normal"
        )
        path = (
            f"thumbnail/chara/{bundle}_{suffix}.webp"
            if thumb
            else f"character/member/{bundle}/card_{suffix}.webp"
        )
        return f"{self.asset_base}/{path}"

    async def image(self, url):
        path = self.asset_dir / (hashlib.sha256(url.encode()).hexdigest() + ".webp")
        if path.exists():
            try:
                data = await asyncio.to_thread(path.read_bytes)
                await asyncio.to_thread(path.touch)
                return data
            except OSError:
                pass
        if self.negative.get(url, 0) > time.time():
            return None
        if url not in self.pending:
            self.pending[url] = asyncio.create_task(self._download_image(url, path))
        task = self.pending[url]
        try:
            return await task
        finally:
            if task.done() and self.pending.get(url) is task:
                self.pending.pop(url, None)

    async def _download_image(self, url, path):
        try:
            async with self.sem:
                async with self.client.stream(
                    "GET", url, timeout=httpx.Timeout(8, connect=4)
                ) as response:
                    response.raise_for_status()
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 8 * 1024 * 1024:
                            raise ValueError("图片过大")
                data = bytes(data)
                await asyncio.to_thread(self._verify_image, data)
                await asyncio.to_thread(atomic_write, path, data)
                return data
        except (httpx.HTTPError, OSError, ValueError, Image.DecompressionBombError):
            if len(self.negative) > 2048:
                self.negative.clear()
            self.negative[url] = time.time() + 60
            return None

    @staticmethod
    def _verify_image(data):
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > 12_000_000:
                raise ValueError("图片尺寸过大")
            im.verify()

    async def images(self, urls, budget=None):
        if not urls:
            return []
        tasks = [asyncio.create_task(self.image(url)) for url in urls]
        try:
            done, pending = await asyncio.wait(
                tasks,
                timeout=budget
                if budget is not None
                else max(3, min(30, int(self.config.get("image_budget", 12)))),
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            return [
                task.result()
                if task in done and not task.cancelled() and task.exception() is None
                else None
                for task in tasks
            ]
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def prune(self):
        limit = max(64, min(2048, int(self.config.get("cache_mb", 256)))) * 1024 * 1024
        files = []
        for directory in (self.asset_dir, self.render_dir):
            for path in directory.iterdir():
                if path.is_file() and path.suffix != ".tmp":
                    stat = path.stat()
                    files.append((stat.st_mtime, stat.st_size, path))
        total = sum(row[1] for row in files)
        for _, size, path in sorted(files):
            if total <= limit:
                break
            path.unlink(missing_ok=True)
            total -= size

    async def close(self):
        self.closed = True
        tasks = list(self.pending.values())
        if self.refresh_task and not self.refresh_task.done():
            tasks.append(self.refresh_task)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.client.aclose()
