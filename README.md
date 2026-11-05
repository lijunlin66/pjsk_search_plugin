# pjsk查询工具

<img src="logo.png" width="128" height="128" alt="pjsk查询工具图标">

适用于 AstrBot 4.29.1–4.x 的世界计划日服卡面查询插件。插件标识为 `astrbot_plugin_pjsk`，展示名为 **pjsk查询工具**。作者：lijunlin66，版本：1.2.2。

## 数据来源

**使用日服游戏数据的社区镜像，不是 SEGA 官方开放 API，也不是官方合作插件。** 默认 master 和卡图来自 Sekai-World；可配置兼容的 Haruki 日服 master 镜像。 未找到可直接用于此插件的官方公开卡片数据库接口。镜像更新可能滞后、暂时不可用；查询仅显示已到 `releaseAt` 的卡片。管理员可配置兼容相同 JSON 结构的数据源和图片根地址。

- [Haruki 日服 master 镜像](https://sekai-master-cdn.haruki.seiunx.com/haruki-sekai-master/master/cards.json)
- [日服 master 数据仓库](https://github.com/Sekai-World/sekai-master-db-diff)
- [Sekai Viewer](https://github.com/Sekai-World/sekai-viewer)：用于核实图片路径与技能占位符含义；本插件独立实现查询和渲染，没有复制上游代码。
- [游戏官方角色介绍](https://pjsekai.sega.jp/character/index.html)

## 安装

在 AstrBot WebUI 插件管理中选择从链接安装，填写：

```text
https://github.com/lijunlin66/pjsk_search_plugin
```

也可上传 `astrbot_plugin_pjsk-1.2.2.zip`，然后启用。也可将此目录放入 `AstrBot/data/plugins/astrbot_plugin_pjsk` 后重载。依赖由 `requirements.txt` 声明：HTTPX、Pillow。Python 需 3.10 或以上，以所用 AstrBot 版本的 Python 要求为准。

默认无需密钥、游戏账号、浏览器或额外渲染服务。附带 Noto CJK 中日文字体及 OFL 许可证，Linux 容器也可直接绘图。需能访问 `sekai-world.github.io` 与 `storage.sekai.best`。当前声明和验证目标为 OneBot v11（`aiocqhttp`）；其他平台未做实际适配器验证。

源码仓库：[lijunlin66/pjsk_search_plugin](https://github.com/lijunlin66/pjsk_search_plugin)，默认分支 `main`。`metadata.yaml` 已填写实际仓库地址，可通过仓库链接安装；尚未提交 AstrBot 插件市场。插件图标由维护者提供，按官方建议缩放为 256×256 PNG，保留原图内容。

## 指令

默认唤醒前缀为 `/`，若 AstrBot 修改了前缀，使用相应前缀。

| 指令 | 作用 |
| --- | --- |
| `/查卡` | 帮助 |
| `/查卡 花里实乃里` | 中文全名搜索 |
| `/查卡 实乃里`、`/查卡 mnr` | 名字、缩写搜索 |
| `/查卡 Hanasato Minori` | 英文全名，兼容姓在前或名在前 |
| `/查卡 MMJ`、`/查卡 MORE MORE JUMP!` | 团队搜索，支持带空格全名 |
| `/查卡 1441` | 卡片 ID 精确查询 |
| `/查卡角色` | 列出全部 26 位角色、别名及团队别名 |
| `/查卡更新` | AstrBot 管理员手动刷新主数据 |

主指令为 `/查卡`；兼容 `/pjsk`、`/pjsk查询`、`/pjsk查卡`、`/查卡牌`。`/查卡角色`、`/查卡更新` 也分别兼容 `/pjsk角色`、`/pjsk更新`。还可搜索日文原始卡名片段。纯数字优先作为卡片 ID；25 时团可用 `n25` 或 `25时`，初音未来可用 `miku` 或中文姓名。

团队包括 Leo/need（ln）、MORE MORE JUMP!（mmj）、Vivid BAD SQUAD（vbs）、Wonderlands×Showtime（wxs/ws）、25時、ナイトコードで。（n25）、VIRTUAL SINGER（vs）。团队检索也包含支援该团队的虚拟歌手卡；单查 `vs` 则匹配虚拟歌手本身。

## 活动查询（1.2.0）

| 指令 | 说明 |
| --- | --- |
| `/查活动`、`/查活动 帮助` | 本地缓存的图片指引 |
| `/活动列表`、`/活动图鉴` | 所有已开启活动，合成一张图 |
| `/查活动 mnr` | 有实乃里活动关联卡的活动，包含报酬卡 |
| `/查活动 205` | 编号详情：标题横幅、时间、类型、属性、加成角色、关联卡片、首发卡池 |
| `/查活动 cute 心羽` | 同时满足属性与角色条件 |
| `/查活动 mmjrin` | 活动卡含 MMJ 支援的镜音铃 |
| `/查活动 mmj len` | MMJ 箱活且活动卡含镜音连 |
| `/查活动 vbs ws` | 加成真人团队恰好为这两团 |
| `/查活动 vbs rui` | 加成含 VBS 和类所属团，且活动卡有类 |
| `/查活动 25h混`、`/查活动 25h加成` | 加成团队包含 25 时，不限定是否还有其他团队 |
| `/查活动 箱活 蓝星`、`/查活动 混活 5v5` | 团队范围、属性与活动类型组合 |

`/查询活动`、`/pjsk活动` 也是查询别名。条件用空格隔开；支持马拉松/普通、5v5/嘉年华、WL；属性支持英文和粉花、紫月、蓝星、橙心、绿草及颜色单字；角色复用查卡别名（包括自定义别名），团队额外支持 `25h`。两个角色须同时有活动关联卡。纯数字表示活动编号，连请用 len，团队 ln 优先表示 Leo/need。

箱活/混活按加成中的真人团队数区分，早期活动缺少明确 unit 时从加成表推导；World Link 可能包含跨团加成或没有固定属性，不强行标注单一属性。角色检索依据 eventCards，加成角色来自 eventDeckBonuses，均不等同于全部剧情登场角色。卡池匹配活动期间开池且 pickup 含本期活动卡的记录，不把后续复刻计为本期首发。暂无关联记录时明确显示缺失。

只展示已经开启的日服活动（包括进行中和已结束），列表时间按 UTC+8，结束取 aggregateAt 结算时间。列表与查询结果均完整合图；超大图沿用流式编码和发送体积控制。资源缺失时保留文字和占位，缺图结果不进入成图缓存。

查卡和查活动无参数/帮助、无匹配结果均返回重新设计的图片指引；帮助图在启动时生成并保存到插件数据目录，再次使用只读本地文件。活动成图完整时缓存 6 小时，数据内容变化自动换键；活动表分源持久缓存，复用现有异步下载、并发限制与失败降级。网络故障会给出故障说明，避免误认为条件不匹配。

## 展示内容

多卡结果按实装时间和 ID 倒序排列，**全部匹配卡片一次合成一张长图，不分页、不截断**，显示花前花后头像、ID、卡名、稀有度、属性、限定角标与技能类型。图鉴仅取轻量头像并复用本地缓存。输入图中的 ID 可查详情。

单卡显示完整花前、花后卡图，以及所属/支援团队、属性、稀有度、实装时间、供给类型、等级上限、抽卡台词、满级综合力及其口径、综合力成长、技能名、技能 Lv.1–4 与效果条件、特训消耗、专精解锁、关联剧情、剧情加成、专精奖励及对应服装。首发关联卡池、活动与歌曲另外展示横幅、封面及关键资料；衣装缩略图按本卡及所属团队模型匹配。生日/周年卡、不可特训卡、初始已特训且仅有花后的特殊卡会明确标注。

数值口径是**无专精、无剧情加成**；特训后数值包含固定特训加成。剧情加成和奖励另列。技能原文保持日文，效果参数和常见条件以中文显示；随角色等级变化的技能展示区间，通过技能原文显示条件区间。遇到未来新增、尚不支持的公式时明确保留占位符并提示，避免编造数值。

“完整资料”指当前卡片主数据、技能及上述关联培养记录；不提供账号持有信息、实时卡池概率、历史卡池全量归档（仅匹配本卡首发 pickup）或剧情正文。主数据没有的内容不会编造。扩展表失败时显示“无关联记录 / 主数据未提供”，核心卡面查询仍可使用。

## 性能和故障处理

- 复用异步 HTTP 客户端和连接池；不在消息回调中同步请求网络。
- 图鉴下载 `thumbnail/chara` 轻量头像，每个可特训卡取花前花后两个资源；单卡才取 `member` 完整图。卡框、星级、属性图标随插件本地提供。
- 全局图片并发默认 6，上限 8；单卡图片基础时限默认 12 秒，全量图鉴按图片数量扩展等待时限，最多 180 秒，失败或超时只占位，成功图片继续展示。
- 发送前对大图自适应编码，目标不超过 6 MiB；此目标不保证所有 QQ 会话都能直接上传。QQ 仍返回 921/highway 错误时，以 4 MiB、最大边 20000 的完整等比图重试一次，不裁掉卡片、不分页。
- 图片通过官方 `event.send` 发送，成功后才回复卡数；失败时报告发送失败，不返回成功说明。
- 同一 URL 同时请求合并；图片落盘缓存，失败 URL 短时负缓存。成图成功后缓存 5 分钟，不缓存含失败占位图的成图。
- 关联数据按源地址分别持久缓存，精简卡池大表和衣装模型字段；重启可复用，刷新失败保留最近的关联记录。
- 长图逐行绘制，超过常规画布预算或 JPEG 高度限制时使用流式 PNG 编码，避免建立巨大画布。
- 默认图片及成图缓存上限 256 MB，按最近使用时间清理；主数据快照单独保存。
- 主数据首次后台加载；默认每 6 小时检查更新。完整核心表全部成功并通过结构验证后才替换快照；失败保留旧数据并标注。过期缓存可先返回，后台更新。
- 同一实例一次生成一张图，其他查询立即提示稍后重试，避免消息堆积和内存压力。
- 绘图、JSON 解析及大文件操作放入工作线程；插件卸载时取消后台任务并关闭客户端。

持久化文件全部位于 `data/plugin_data/astrbot_plugin_pjsk/`，不会写进插件源码目录。图片和成图缓存可在停用插件后删除以重建；删除主数据快照则下次必须联网准备数据。更换地址和字体后重载插件。

## 配置

在 AstrBot 插件配置页面修改，更换数据地址或字体后重载插件。

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| master_base | Sekai-World GitHub Pages | 日服 master JSON 根地址；兼容镜像可使用 `https://sekai-master-cdn.haruki.seiunx.com/haruki-sekai-master/master` |
| asset_base | `https://storage.sekai.best/sekai-jp-assets` | 日服卡图根地址 |
| image_concurrency | 6 | 下载并发，范围 1–8 |
| image_budget | 12 | 基础时限秒数，范围 3–30；全量图鉴最多扩展至 180 秒 |
| master_ttl_hours | 6 | 主数据检查间隔小时，范围 1–168 |
| cache_mb | 256 | 图片与成图磁盘缓存 MB，范围 64–2048 |
| font_path | 空 | 自定义中日文字体绝对路径；空值自动选择字体 |
| character_aliases | 空 | 每行 `别名=角色ID`，如 `小实=5` |

## 官方规范对应

依照 [AstrBot 官方插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)、[最小实例](https://docs.astrbot.app/dev/star/guides/simple.html)、[消息事件](https://docs.astrbot.app/dev/star/guides/listen-message-event.html)、[插件配置](https://docs.astrbot.app/dev/star/guides/plugin-config.html) 和 [存储规范](https://docs.astrbot.app/dev/star/guides/storage.html) 实现：

- 入口 `main.py`，插件继承 `Star`，构造函数接收 `Context`、`AstrBotConfig`。
- `metadata.yaml` 提供唯一英文插件名、中文展示名、作者、版本和兼容范围；使用当前官方支持的 metadata 自动发现机制，无需旧版 `@register`。
- Handler 全部位于插件类中，前两个参数为 `self`、`event`；命令及管理员权限使用官方 `filter`。
- 日志仅通过 `from astrbot.api import logger`；依赖和后台配置分别放在 `requirements.txt`、`_conf_schema.json`。
- 消息通过 `event.send`、`event.plain_result`、`event.chain_result`、`Image.fromBytes` 输出；实现 `initialize` / `terminate` 生命周期。

## 验证

开发时建议将仓库克隆为插件标识对应的目录名：

```text
git clone https://github.com/lijunlin66/pjsk_search_plugin.git astrbot_plugin_pjsk
cd astrbot_plugin_pjsk
python -m pip install -r requirements.txt ruff
```

然后在插件目录运行：

```text
python -m unittest discover -s tests -v
python -m ruff check .
python -m ruff format --check .
```

自动测试覆盖别名、团队支援卡、数字 ID、未实装过滤、特训状态、技能参数、主数据原子替换、失败保留缓存、图片合并请求、负缓存、并发限制、单图失败、命令正文解析及中文字形渲染。入口测试模拟 AstrBot 边界，不等同于已在真实 QQ 会话发送成功。

已验证环境：AstrBot 4.29.1、Python 3.12.15、HTTPX 0.28.1、Pillow 13.0.0。2026-11-01 快照共 1,472 张卡；实乃里 54 张、MMJ 271 张均完成单张长图生成。实际 QQ 日志已确认 MMJ 上传失败后的降级重试成功。数据会继续增长，网络与平台状态会影响延迟。

维护方法见 [MAINTENANCE.md](MAINTENANCE.md)，版本变更见 [CHANGELOG.md](CHANGELOG.md)。

代码采用 MIT 许可证；附带字体采用 SIL OFL，见 `fonts/OFL.txt`。图标、游戏数据与卡图版权属于 SEGA、Colorful Palette、Crypton 等权利人；代码许可不覆盖游戏素材。随插件的游戏 UI 素材来源见 `assets/SOURCES.md`。
