"""One local, reusable guide for all public query commands."""

from PIL import ImageDraw

from .render import GRAY, INK

GUIDE_REVISION = "1.6.0-speed-1"
ACCENT = "#078e86"

# Commands and descriptions occupy fixed columns; long values wrap within a cell.
SECTIONS = [
    (
        "歌曲与谱面 · 国服曲库",
        "完整指令 / 输入示例",
        "查询内容",
        [
            ("/song 歌曲名或ID", "支持日文原名、中文译名、社区别名与俗称。"),
            (
                "/song 告诉你的世界",
                "歌曲封面、标题、创作者、上线时间、难度等级与音符数。",
            ),
            ("/谱面查询 1", "返回一张国服谱面图片，默认 MASTER 难度。"),
            ("/谱面查询 1 ex", "指定难度；也可使用 expert 全称。"),
            (
                "难度全称 / 缩写",
                "easy / ez、normal / nm、hard / hd、expert / ex、master / mas、append / apd。",
            ),
        ],
        [
            "没有精确匹配时显示最接近的候选歌曲；默认 2 首，管理员可在插件设置中调整。",
            "重名或别名冲突时请用歌曲 ID 确认；难度与歌名之间用空格。",
            "只检索国服已上线歌曲；谱面从国服原始数据绘制，本地缓存复用。",
        ],
    ),
    (
        "查卡 · 日服卡面",
        "指令 / 输入示例",
        "查询内容",
        [
            ("/查卡 mnr", "按角色缩写搜索，也可用实乃里、花里实乃里。"),
            ("/查卡 Hanasato Minori", "支持中日英文姓名，英文姓名顺序均可。"),
            ("/查卡 MMJ", "按团队检索，也支持 MORE MORE JUMP! 全名。"),
            ("/查卡 1395", "按卡片 ID 查看花前花后、技能、属性与培养资料。"),
            ("/查卡 卡名片段", "按日文原始卡名中的文字搜索。"),
        ],
        [
            "多卡结果全部合成一张长图；输入图中卡片 ID 可查看单卡详情。",
            "角色或团队整体输入；查卡不使用活动的多条件组合语法。",
            "兼容 /pjsk、/pjsk查询、/pjsk查卡、/查卡牌；只显示已实装卡片。",
        ],
    ),
    (
        "查活动 · 日服活动图鉴",
        "指令 / 输入示例",
        "查询内容",
        [
            ("/查活动 mnr", "检索有实乃里活动关联卡的活动，包含报酬卡。"),
            ("/查活动 205", "按活动 ID 查看横幅、卡池、加成角色、属性与时间。"),
            (
                "/活动列表  或  /活动图鉴",
                "浏览全部已开启活动；极大结果分 2–3 张，在同一条消息中发送。",
            ),
            ("/查活动 标题片段", "按活动原始标题搜索，标题片段作为一个条件。"),
        ],
        [
            "支持类型、属性、团队和角色筛选；多个条件用空格隔开，同时生效。",
            "纯数字是活动 ID；角色按活动关联卡检索，不代表全部剧情登场角色。",
            "只展示已经开启的日服活动；兼容 /查询活动、/pjsk活动。",
        ],
    ),
    (
        "活动筛选 · 关键词速查",
        "筛选类别",
        "可用关键词与规则",
        [
            ("活动类型", "马拉松 / 普通；5v5 / 嘉年华；WL。"),
            (
                "属性 · 粉 / 蓝 / 橙",
                "cute / 粉花；cool / 蓝星；happy / 橙心（也可用黄）。",
            ),
            ("属性 · 绿 / 紫", "pure / 绿草；mysterious / 紫月；支持颜色单字。"),
            ("团队", "ln、mmj、vbs、ws / wxs、25h / n25、vs。"),
            ("角色", "姓名、英文名、缩写和自定义别名；镜音连请用 len。"),
            ("箱活 / 混活", "按活动加成中的真人团队数区分单团与多团。"),
        ],
        [
            "单写 mmj 匹配 MMJ 箱活；vbs ws 要求加成中的真人团队恰好为这两团。",
            "25h混 / 25h加成：加成团队包含 25 时即可；不限制还有其他团队。",
            "mmjrin 指 MMJ 支援的镜音铃；miku 不限制支援团。多个角色须同时有活动卡。",
            "World Link 可能没有固定属性；团队缩写 ln 优先表示 Leo/need。",
        ],
    ),
    (
        "组合示例 · 可以直接照着查",
        "完整指令",
        "匹配范围",
        [
            ("/查活动 cute 心羽", "粉花属性，且活动关联卡中有心羽。"),
            ("/查活动 马拉松 橙心", "橙心属性的马拉松活动。"),
            ("/查活动 knd hnm", "活动关联卡同时有奏与穗波。"),
            ("/查活动 mmj len", "MMJ 箱活，且活动关联卡中有镜音连。"),
            ("/查活动 vbs rui", "加成包含 VBS 和类所属团，且活动关联卡中有类。"),
            ("/查活动 箱活 蓝星", "蓝星属性的箱活；也可试 /查活动 混活 5v5。"),
        ],
        [],
    ),
    (
        "当前活动、榜线与时速 · 国服 / 日服",
        "完整指令",
        "查询内容",
        [
            ("/cn当前活动", "国服当前活动：横幅、时间、加成角色、卡面缩略图与属性。"),
            ("/jp当前活动", "日服当前活动，展示内容与国服一致。"),
            ("/cn榜线", "国服当前活动综合榜线：档位、积分与上游更新时间。"),
            ("/jp榜线", "日服当前活动综合榜线。"),
            ("/cn时速", "国服当前活动十个指定档位的积分与一小时时速。"),
            ("/jp时速", "日服当前活动时速，档位与国服相同。"),
        ],
        [
            "cn 表示国服，jp 表示日服；上述指令无需再填写服别或活动编号。",
            "活动间歇期会提示暂无进行中活动；榜线不包含 WL 角色单榜或预测分数。",
            "榜线有采样与缓存延迟，以图中上游更新时间为准；时间统一使用 UTC+8。",
            "时速档位：T1 / T10 / T50 / T100 / T500 / T1000 / T5000 / T10000 / T20000 / T30000。",
            "≈ 表示按历史采样间隔折算 PT/h；缺样本显示暂无数据，不代表零涨分。",
        ],
    ),
    (
        "帮助与辅助指令",
        "完整指令",
        "作用",
        [
            ("/pjsk查询帮助", "查看本张完整帮助图。"),
            ("/查卡角色", "列出全部角色、角色 ID、别名与团队别名。"),
            ("/查卡更新", "手动刷新日服主数据，仅 AstrBot 管理员可用。"),
        ],
        [
            "/查卡、/查活动不带参数或加“帮助”，均可查看本图；无匹配时也会附上指引。",
            "查卡与历史活动使用日服数据；当前活动、榜线按 cn / jp 分服查询。",
            "使用社区数据镜像，资源或更新可能滞后；若多次失败，请联系管理员检查日志。",
        ],
    ),
]


def text(renderer, draw, xy, value, size=25, color=INK, bold=False, center=False):
    """Align by visible glyph bounds; a small outline gives portable bold CJK."""
    stroke = 1 if bold else 0
    font = renderer.font(size)
    left, top, right, _ = draw.textbbox((0, 0), value, font=font, stroke_width=stroke)
    draw.text(
        (xy[0] - left - ((right - left) / 2 if center else 0), xy[1] - top),
        value,
        font=font,
        fill=color,
        stroke_width=stroke,
        stroke_fill=color,
    )


def guide(renderer, kind="all", failed=False):
    width, margin, inset, divider = 1440, 44, 76, 616
    key_width, value_width = divider - inset - 40, width - inset - divider - 36
    layouts = []
    for heading, first, second, rows, notes in SECTIONS:
        wrapped = [
            (renderer.wrap(key, 26, key_width), renderer.wrap(value, 25, value_width))
            for key, value in rows
        ]
        heights = [max(len(k), len(v)) * 36 + 24 for k, v in wrapped]
        tips = [renderer.wrap(note, 23, width - inset * 2 - 30) for note in notes]
        height = 170 + sum(heights) + sum(len(n) * 34 + 10 for n in tips)
        layouts.append((heading, first, second, wrapped, heights, tips, height))

    height = 248 + sum(item[-1] + 24 for item in layouts) + 94
    canvas = renderer.background(width, height)
    draw = ImageDraw.Draw(canvas)
    text(renderer, draw, (76, 34), "PJSK  /  QUERY GUIDE", 21, ACCENT, bold=True)
    text(renderer, draw, (76, 84), "世界计划 · 查询使用指南", 43, bold=True)
    notice = (
        f"{'活动' if kind == 'event' else '卡面'}暂未匹配到结果，请参考下面的用法调整条件。"
        if failed
        else "查卡面、找活动、看榜线，一张图掌握全部查询用法。"
    )
    text(renderer, draw, (76, 157), notice, 26, GRAY)
    text(
        renderer,
        draw,
        (76, 202),
        "查卡 / 历史活动：日服     当前活动 / 榜线：国服与日服",
        23,
        ACCENT,
    )

    y = 248
    for number, (heading, first, second, rows, heights, tips, box_height) in enumerate(
        layouts, 1
    ):
        draw.rounded_rectangle(
            (margin, y, width - margin, y + box_height),
            24,
            fill="white",
            outline="#d5e7e7",
            width=2,
        )
        draw.rounded_rectangle((inset, y + 26, inset + 58, y + 78), 14, fill="#e0f7f3")
        text(
            renderer,
            draw,
            (inset + 29, y + 40),
            f"{number:02}",
            25,
            ACCENT,
            bold=True,
            center=True,
        )
        text(renderer, draw, (inset + 82, y + 39), heading, 30, bold=True)
        draw.rounded_rectangle(
            (inset, y + 100, width - inset, y + 146), 10, fill="#edf8f7"
        )
        text(renderer, draw, (inset + 18, y + 112), first, 23, ACCENT, bold=True)
        text(renderer, draw, (divider + 24, y + 112), second, 23, ACCENT, bold=True)
        row_y = y + 146
        for (keys, values), row_height in zip(rows, heights):
            for lines, x, size, color in (
                (keys, inset + 18, 26, INK),
                (values, divider + 24, 25, GRAY),
            ):
                # Both columns share the same vertical center, including wrapped rows.
                bounds = [
                    draw.textbbox((0, 0), line, font=renderer.font(size))
                    for line in lines
                ]
                ink_height = max(bottom - top for _, top, _, bottom in bounds)
                line_y = row_y + (row_height - ((len(lines) - 1) * 36 + ink_height)) / 2
                for line in lines:
                    text(renderer, draw, (x, line_y), line, size, color)
                    line_y += 36
            row_y += row_height
            draw.line(
                (inset + 18, row_y, width - inset - 18, row_y), fill="#e7eeee", width=1
            )
        draw.line((divider, y + 110, divider, row_y), fill="#dceae9", width=1)
        row_y += 18
        for lines in tips:
            draw.ellipse((inset + 8, row_y + 10, inset + 14, row_y + 16), fill=ACCENT)
            for line in lines:
                text(renderer, draw, (inset + 30, row_y), line, 23, GRAY)
                row_y += 34
            row_y += 10
        y += box_height + 24
    text(
        renderer,
        draw,
        (width / 2, y + 12),
        "再次查看：/pjsk查询帮助",
        26,
        ACCENT,
        bold=True,
        center=True,
    )
    text(
        renderer,
        draw,
        (width / 2, y + 58),
        "默认指令前缀为 /；若机器人修改了前缀，请使用对应前缀。",
        21,
        GRAY,
        center=True,
    )
    return renderer.encode(canvas)
