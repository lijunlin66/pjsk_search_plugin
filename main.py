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

from .activity_ui import atlas, dossier, guide
from .catalog import trained
from .events import QueryError
from .render import Renderer
from .service import DataUnavailable, Service, atomic_write
from .transport import RETRY_BYTES, prepare_upload


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
        await self.help_image("card")
        await self.help_image("event")
        await self.help_image("card", True)
        await self.help_image("event", True)
        logger.info("pjsk查询工具 1.2.2 已加载；主数据在后台准备")

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
                    f"v1.2.2-upload|{self.service.revision}|{self.service.master_base}|{self.service.asset_base}|{query}|{self.renderer.font_path}|{self.config.get('character_aliases', '')}".encode()
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

    async def help_image(self, kind, failed=False):
        stamp = hashlib.sha256(
            f"1.2.2|{self.renderer.font_path}|{kind}|{failed}".encode()
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
                index = await self.service.activity_data()
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
                revision = hashlib.sha256(repr(records).encode()).hexdigest()
                key = hashlib.sha256(
                    f"event-1.2.2-layout2|{revision}|{query}|{self.service.asset_base}|{self.renderer.font_path}".encode()
                ).hexdigest()
                path = self.service.render_dir / (key + ".img")
                if path.exists() and time.time() - path.stat().st_mtime < 21600:
                    data = await asyncio.to_thread(path.read_bytes)
                else:
                    media = await self.service.activity_media(records, detail)
                    if detail:
                        data = await asyncio.to_thread(
                            dossier, self.renderer, records[0], media, index.catalog
                        )
                    else:
                        data = await asyncio.to_thread(
                            atlas, self.renderer, records, media, index.catalog, query
                        )
                    if media and all(media.values()):
                        await asyncio.to_thread(atomic_write, path, data)
                await self.deliver_image(event, data)
                if not detail:
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

    async def deliver_image(self, event, data):
        original_size = len(data)
        data = await asyncio.to_thread(prepare_upload, data)
        if len(data) != original_size:
            logger.info(f"查卡上传图片压缩：{original_size} -> {len(data)} bytes")
        try:
            await event.send(event.chain_result([Image.fromBytes(data)]))
        except Exception as exc:
            if "921" not in str(exc) and "highway upload" not in str(exc).lower():
                raise
            logger.warning("查卡图片上传被拒绝，保留完整长图并降低传输体积后重试一次")
            data = await asyncio.to_thread(prepare_upload, data, RETRY_BYTES, 20000)
            await event.send(event.chain_result([Image.fromBytes(data)]))
        return data

    @filter.command("查卡角色", alias={"pjsk角色"})
    async def characters(self, event: AstrMessageEvent):
        """列出角色、ID和内置别名。"""
        from .catalog import NAMES, UNITS

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
