"""AstrBot entry point; all message handlers stay on the Star class."""

import asyncio
import hashlib
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .domain.catalog import trained
from .domain.events import QueryError
from .rendering.activity_ui import atlas, atlas_batches, dossier
from .rendering.help_ui import GUIDE_REVISION, guide
from .rendering.live_ui import live_image
from .rendering.render import Renderer, local_date
from .rendering.song_ui import song_image
from .services.live import REGIONS
from .services.service import DataUnavailable, Service, atomic_write
from .services.songs import parse_chart
from .services.transport import RETRY_BYTES, UPLOAD_BYTES, prepare_upload


class PjskPlugin(Star):
    """日服卡面查询、全量长图图鉴和完整卡片资料。"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        root = Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_pjsk"
        self.service = Service(root, config, logger)
        self.renderer = Renderer(config.get("font_path", ""))
        self.query_lock = asyncio.Lock()
        self.busy = False

    async def initialize(self):
        await self.service.start()
        await self.help_image("all")
        await self.help_image("card", True)
        await self.help_image("event", True)
        logger.info("pjsk查询工具 1.6.0 已加载；主数据在后台准备")

    def status(self):
        stamp = datetime.fromtimestamp(
            self.service.updated_at, timezone(timedelta(hours=8))
        ).strftime("%m-%d %H:%M CST")
        return f"数据检查于 {stamp}" + (
            " · 更新失败，当前使用缓存" if self.service.stale else ""
        )

    @filter.command("查卡", alias={"pjsk", "pjsk查询", "pjsk查卡", "查卡牌"})
    async def lookup(self, event: AstrMessageEvent):
        """输入卡片ID、角色或团队名字查询；多卡全部合成一张长图。"""
        # The framework has already matched and removed the wake prefix.
        # Read the remainder intact so team names containing spaces work.
        parts = event.get_message_str().strip().split(maxsplit=1)
        query = parts[1].strip() if len(parts) > 1 else ""
        if not query or query in {"帮助", "help"}:
            yield event.chain_result([Image.fromBytes(await self.help_image("card"))])
            return
        if len(query) > 150:
            yield event.plain_result("关键词过长，请使用卡片ID、角色名或团队名。")
            return
        # Accept old pagination suffixes, always returning the full result now.
        match = re.search(r"\s+(?:第\s*(\d+)\s*页|--page\s+(\d+))$", query)
        if match:
            query = query[: match.start()].strip()
        if not query:
            yield event.chain_result([Image.fromBytes(await self.help_image("card"))])
            return
        if self.busy:
            yield event.plain_result("正在生成另一张图，请稍后重试。")
            return
        self.busy = True
        try:
            async with self.query_lock:
                catalog = await self.service.ensure()
                cards = await asyncio.to_thread(catalog.search, query)
                if not cards:
                    yield event.chain_result(
                        [Image.fromBytes(await self.help_image("card", True))]
                    )
                    return
                detail = len(cards) == 1
                cache_key = hashlib.sha256(
                    f"v1.6.0-upload|{self.service.revision}|{self.service.master_base}|{self.service.asset_base}|{query}|{self.renderer.font_path}|{self.config.get('character_aliases', '')}".encode()
                ).hexdigest()
                path = self.service.render_dir / (cache_key + ".img")
                complete = True
                # Short cache avoids freezing temporary placeholders and stale labels.
                if (
                    path.exists()
                    and time.time() - path.stat().st_mtime < 300
                    and not self.service.stale
                ):
                    data = await asyncio.to_thread(path.read_bytes)
                else:
                    if detail:
                        card = cards[0]
                        urls = [self.service.image_url(card)]
                        if trained(card):
                            urls.append(self.service.image_url(card, after=True))
                        images, extras = await asyncio.gather(
                            self.service.images(urls), self.service.extras(card)
                        )
                        media = await self.service.detail_media(card, extras)
                        data = await asyncio.to_thread(
                            self.renderer.detail,
                            card,
                            images,
                            catalog,
                            extras,
                            self.status(),
                            media,
                        )
                    else:
                        images = await self.service.gallery_images(cards)
                        data = await asyncio.to_thread(
                            self.renderer.gallery,
                            cards,
                            images,
                            catalog,
                            query,
                            self.status(),
                        )
                    complete = all(images) and (
                        detail or all(all(pair) for pair in images)
                    )
                    complete = complete and (not detail or all(media.values()))
                data = await self.deliver_image(event, data)
                if complete:
                    await asyncio.to_thread(atomic_write, path, data)
                if not detail:
                    yield event.plain_result(
                        f"共 {len(cards)} 张，已全部合成一张长图。详情：/查卡 {cards[0]['id']}"
                    )
                await asyncio.to_thread(self.service.prune)
        except DataUnavailable as exc:
            yield event.plain_result(str(exc))
        except Exception as exc:  # noqa: BLE001 - isolate plugin failures at the message boundary
            logger.exception(f"PJSK 查询失败：{type(exc).__name__}")
            yield event.plain_result(
                "查卡图片生成或发送失败，请稍后重试；管理员可在 AstrBot 日志中查看原因。"
            )
        finally:
            self.busy = False

    @filter.command("pjsk查询帮助")
    async def query_help(self, event: AstrMessageEvent):
        """一张图片查看查卡、活动、当前活动与榜线的全部用法。"""
        yield event.chain_result([Image.fromBytes(await self.help_image("all"))])

    async def help_image(self, kind="all", failed=False):
        # Normal help entrances share one pre-rendered local file.
        if not failed:
            kind = "all"
        stamp = hashlib.sha256(
            f"{GUIDE_REVISION}|{self.renderer.font_path}|{kind}|{failed}".encode()
        ).hexdigest()
        path = self.service.root / f"guide-{stamp}.jpg"
        if path.exists():
            return await asyncio.to_thread(path.read_bytes)
        data = await asyncio.to_thread(guide, self.renderer, kind, failed)
        await asyncio.to_thread(atomic_write, path, data)
        return data

    @filter.command("查活动", alias={"查询活动", "pjsk活动", "活动列表", "活动图鉴"})
    async def activities(self, event: AstrMessageEvent):
        """活动编号详情或空格分隔的多条件活动筛选。"""
        parts = event.get_message_str().strip().split(maxsplit=1)
        query = parts[1].strip() if len(parts) > 1 else ""
        if (
            query in {"帮助", "help"}
            or not query
            and parts[0].lstrip("/") not in {"活动列表", "活动图鉴"}
        ):
            yield event.chain_result([Image.fromBytes(await self.help_image("event"))])
            return
        if len(query) > 150:
            yield event.plain_result("条件过长，请缩短关键词。")
            return
        if self.busy:
            yield event.plain_result("正在生成另一张图，请稍后重试。")
            return
        self.busy = True
        try:
            async with self.query_lock:
                index = await self.service.activity_data(detail=query.isdigit())
                try:
                    records = await asyncio.to_thread(index.search, query)
                except QueryError as exc:
                    yield event.plain_result(str(exc))
                    records = []
                if not records:
                    yield event.chain_result(
                        [Image.fromBytes(await self.help_image("event", True))]
                    )
                    return
                detail = query.isdigit()
                # Card records include large growth tables. Never stringify those
                # just to name a list image: the existing core revision covers them.
                signatures = [
                    (
                        record["event"],
                        [card.get("id") for card in record["cards"]],
                        sorted(record.get("attrs", [])),
                        sorted(record.get("participants", [])),
                        sorted(record.get("units", [])),
                        record.get("teams", []),
                        [
                            {
                                key: g.get(key)
                                for key in ("id", "name", "startAt", "endAt")
                            }
                            for g in record.get("gachas", [])
                        ],
                    )
                    for record in records
                ]
                revision = hashlib.sha256(
                    (self.service.revision + repr(signatures)).encode()
                ).hexdigest()
                batches = [records] if detail else atlas_batches(records)
                paths = []
                for i in range(len(batches)):
                    key = hashlib.sha256(
                        f"event-1.6.0-batch2-14mp|{revision}|{query}|{i}|{len(batches)}|{self.service.asset_base}|{self.renderer.font_path}".encode()
                    ).hexdigest()
                    paths.append(self.service.render_dir / (key + ".img"))
                images = []
                for i, (batch, path) in enumerate(zip(batches, paths)):
                    if path.exists() and time.time() - path.stat().st_mtime < 21600:
                        data = await asyncio.to_thread(path.read_bytes)
                    else:
                        # Download and draw one bounded batch at a time.
                        media = await self.service.activity_media(batch, detail)
                        if detail:
                            data = await asyncio.to_thread(
                                dossier, self.renderer, batch[0], media, index.catalog
                            )
                        else:
                            page = (
                                (i + 1, len(batches), len(records))
                                if len(batches) > 1
                                else None
                            )
                            data = await asyncio.to_thread(
                                atlas,
                                self.renderer,
                                batch,
                                media,
                                index.catalog,
                                query,
                                page,
                                True,
                            )
                        if media and all(media.values()):
                            await asyncio.to_thread(atomic_write, path, data)
                        del media
                    images.append(data)
                await self.deliver_images(event, images, bounded=True)
                if not detail and len(images) == 1:
                    yield event.plain_result(
                        f"共 {len(records)} 项，已合为一张图。详情：/查活动 {records[0]['event']['id']}"
                    )
                await asyncio.to_thread(self.service.prune)
        except DataUnavailable as exc:
            yield event.plain_result(str(exc))
            yield event.chain_result(
                [Image.fromBytes(await self.help_image("event", True))]
            )
        except Exception as exc:  # noqa: BLE001 - isolate failures at the message boundary
            logger.exception(f"PJSK 活动查询失败：{type(exc).__name__}")
            yield event.plain_result("活动图片生成或发送失败，请稍后重试。")
        finally:
            self.busy = False

    @filter.command("cn当前活动")
    async def current_cn(self, event: AstrMessageEvent):
        """查询国服正在进行的活动。"""
        async for result in self.live_lookup(event, region="cn"):
            yield result

    @filter.command("jp当前活动")
    async def current_jp(self, event: AstrMessageEvent):
        """查询日服正在进行的活动。"""
        async for result in self.live_lookup(event, region="jp"):
            yield result

    @filter.command("cn榜线")
    async def borders_cn(self, event: AstrMessageEvent):
        """查询国服当前活动综合榜线。"""
        async for result in self.live_lookup(event, region="cn", borders=True):
            yield result

    @filter.command("jp榜线")
    async def borders_jp(self, event: AstrMessageEvent):
        """查询日服当前活动综合榜线。"""
        async for result in self.live_lookup(event, region="jp", borders=True):
            yield result

    @filter.command("cn时速")
    async def speed_cn(self, event: AstrMessageEvent):
        """查询国服当前活动综合榜最近一小时涨分。"""
        async for result in self.live_lookup(event, region="cn", speed=True):
            yield result

    @filter.command("jp时速")
    async def speed_jp(self, event: AstrMessageEvent):
        """查询日服当前活动综合榜最近一小时涨分。"""
        async for result in self.live_lookup(event, region="jp", speed=True):
            yield result

    async def live_lookup(self, event, region, borders=False, speed=False):
        parts = event.get_message_str().strip().split(maxsplit=1)
        query = parts[1] if len(parts) > 1 else ""
        if query:
            yield event.chain_result([Image.fromBytes(await self.help_image("all"))])
            return
        if self.busy:
            yield event.plain_result("正在生成另一张图，请稍后重试。")
            return
        self.busy = True
        try:
            async with self.query_lock:
                current = await self.service.live.current(region)
                if not current["event"]:
                    message = f"{REGIONS[region]}当前没有正在进行的活动。"
                    if current.get("next"):
                        following = current["next"]
                        message += f"\n下期：{following['name']}（ID {following['id']}）\n开始：{local_date(following['startAt'])} UTC+8"
                    yield event.plain_result(message)
                    return
                current = await (
                    self.service.live.ranking(current, speed=speed)
                    if borders or speed
                    else self.service.live.enrich(current)
                )
                banner = await self.service.live.banner(current)
                data = await asyncio.to_thread(
                    live_image, self.renderer, current, banner, borders or speed, speed
                )
                await self.deliver_image(event, data)
        except DataUnavailable as exc:
            yield event.plain_result(str(exc))
        except Exception as exc:  # noqa: BLE001 - isolate failures at the message boundary
            logger.exception(f"PJSK 当前活动查询失败：{type(exc).__name__}")
            yield event.plain_result("当前活动、榜线或时速查询失败，请稍后重试。")
        finally:
            self.busy = False

    async def deliver_image(self, event, data):
        return (await self.deliver_images(event, [data]))[0]

    async def deliver_images(self, event, images, bounded=False):
        if not 1 <= len(images) <= 3:
            raise ValueError("图片数量必须在 1–3 之间")
        budget = UPLOAD_BYTES // len(images)
        prepared = []
        for data in images:
            prepared.append(
                await asyncio.to_thread(
                    prepare_upload,
                    data,
                    budget,
                    16000 if bounded else None,
                    18_000_000 if bounded else None,
                )
            )
        logger.info(
            f"PJSK 图片消息：{len(prepared)} 张，同一消息发送，共 {sum(map(len, prepared))} bytes"
        )
        try:
            await event.send(
                event.chain_result([Image.fromBytes(data) for data in prepared])
            )
        except Exception as exc:
            # A timeout has unknown delivery status; retry only an explicit rejection.
            if "921" not in str(exc) and "highway upload" not in str(exc).lower():
                raise
            logger.warning("PJSK 图片上传被拒绝，降低整条消息的体积后重试一次")
            prepared = [
                await asyncio.to_thread(
                    prepare_upload,
                    data,
                    RETRY_BYTES // len(images),
                    12000 if bounded else 20000,
                    12_000_000 if bounded else None,
                )
                for data in images
            ]
            await event.send(
                event.chain_result([Image.fromBytes(data) for data in prepared])
            )
        return prepared

    @filter.command("song")
    async def song_lookup(self, event: AstrMessageEvent):
        """查询国服歌曲 ID、原名、译名或社区别名。"""
        async for result in self.music_lookup(event):
            yield result

    @filter.command("谱面查询")
    async def chart_lookup(self, event: AstrMessageEvent):
        """国服谱面图片，默认 MASTER；支持 mas、ex 等难度缩写。"""
        async for result in self.music_lookup(event, chart=True):
            yield result

    async def music_lookup(self, event, chart=False):
        parts = event.get_message_str().strip().split(maxsplit=1)
        query = parts[1].strip() if len(parts) > 1 else ""
        if not query or query.lower() in {"help", "帮助"}:
            yield event.chain_result([Image.fromBytes(await self.help_image("all"))])
            return
        if len(query) > 150:
            yield event.plain_result("关键词过长，请使用歌曲名或歌曲 ID。")
            return
        if self.busy:
            yield event.plain_result("正在生成另一张图，请稍后重试。")
            return
        self.busy = True
        try:
            async with self.query_lock:
                difficulty = "master"
                if chart:
                    query, difficulty = parse_chart(query)
                index, levels, stale = await self.service.songs.data()
                matches, mode = await asyncio.to_thread(
                    index.search, query, self.config.get("song_suggestion_count", 2)
                )
                if not matches:
                    yield event.plain_result(
                        "请输入有效的歌曲名字或 ID；暂时没有可匹配的国服歌曲。"
                    )
                    return
                if chart and mode == "exact" and len(matches) == 1:
                    level = next(
                        (
                            r
                            for r in levels
                            if r.get("musicId") == matches[0]["id"]
                            and r.get("musicDifficulty") == difficulty
                        ),
                        None,
                    )
                    if not level:
                        yield event.plain_result(
                            f"国服暂无 {difficulty.upper()} 难度记录，或难度资料暂不可用。可用 /song {matches[0]['id']} 查看已收录难度。"
                        )
                        return
                    data = await self.service.songs.chart(
                        matches[0],
                        difficulty,
                        level["playLevel"],
                        self.renderer.font_path,
                    )
                else:
                    covers = await self.service.images(
                        [self.service.songs.jacket(music) for music in matches]
                    )
                    data = await asyncio.to_thread(
                        song_image,
                        self.renderer,
                        matches,
                        index,
                        levels,
                        covers,
                        mode,
                        stale,
                    )
                await self.deliver_image(event, data)
                await asyncio.to_thread(self.service.prune)
        except DataUnavailable as exc:
            yield event.plain_result(str(exc))
        except Exception as exc:  # noqa: BLE001 - isolate at the message boundary
            logger.exception(f"PJSK 歌曲查询失败：{type(exc).__name__}")
            yield event.plain_result("歌曲或谱面图片生成/发送失败，请稍后重试。")
        finally:
            self.busy = False

    @filter.command("查卡角色", alias={"pjsk角色"})
    async def characters(self, event: AstrMessageEvent):
        """列出角色、ID和内置别名。"""
        from .domain.catalog import NAMES, UNITS

        lines = ["角色ID用于配置自定义别名；查卡请使用名字，纯数字表示卡片ID。"]
        lines.extend(f"{cid}: {names}" for cid, names in NAMES.items())
        lines.extend(f"{name}: {aliases}" for name, aliases in UNITS.values())
        yield event.plain_result("\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("查卡更新", alias={"pjsk更新"})
    async def refresh(self, event: AstrMessageEvent):
        """管理员刷新日服主数据；失败保留最后完整快照。"""
        try:
            await self.service.refresh()
            yield event.plain_result("日服数据更新完成。" + self.status())
        except Exception as exc:  # noqa: BLE001 - report failure without replacing valid snapshots
            logger.exception(f"PJSK 手动更新失败：{type(exc).__name__}")
            self.service.stale = True
            yield event.plain_result(
                "更新失败，已保留原有完整缓存。请检查网络与数据地址。"
            )

    async def terminate(self):
        await self.service.close()
