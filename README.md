# Paul工作台

面向视频创作者的 macOS 内容工作台，把素材获取、本地转录、文案精选与组稿、配音放在同一个应用里。

当前源码版本：**4.3.4 / 构建 20261115.3**。基于 [Lulu](https://github.com/AidenXu-1/Lulu) 开发，沿用 [MIT 许可证](LICENSE)，原始版权声明与第三方许可完整保留。

## 当前功能

| 环节 | 能力 |
| --- | --- |
| 素材获取 | 音视频链接下载、主页采集、封面保存、直播录制与画质选择 |
| 转录 | SenseVoice Q8、Whisper、Whisper 4bit、MOSS；长录音恢复与说话人处理 |
| 文案 | 文稿库、同题候选对比、用户指定模型评分、精选片段与组稿 |
| 配音与资料 | 本地配音、音频库、Obsidian 与飞书集成 |
| 自动化与外观 | 随 App 提供的 Agent CLI、五套可替换配色、统一导航与列表对比度 |

文案评分需要使用者主动选择已配置的模型连接。仅添加候选文案不会调用模型；原始文稿保留，候选副本可以单独整理。

选题研究、拍摄管理和后期剪辑属于后续规划，尚未作为完整制作链路接入。

## 本版更新：文案并排对比

「文案精选」默认同时展示勾选文案的全文，各篇独立滚动；篇数较多时可横向查看。可以直接从任意一篇选段加入精选，保留片段来源，也可以切换到单篇编辑。精选与组稿面板按需展开。

本版同时更新了「创作中枢」应用与工作台图标。组稿目前支持选段、排序和继续编辑；根据多篇文案整合生成新稿的操作体验仍待改进。

## 新增：候选文案 CLI

`20261115.1` 新增 `editorial.list`、`editorial.show`、`editorial.candidate`、`editorial.create` 和 `editorial.add-candidate`。可以查询与新建选题，直接添加正文，或把版本匹配的现有文稿复制进「文案精选 → 候选文案」。

写入使用版本检查与持久化请求回执，重复请求不会重复添加。界面自动同步新增内容，并保留本地正在编辑的正文、精选片段和组稿。

调用前按 [独立 Agent Skill](agent-skill/README.md) 校验实际安装，再查询 `capabilities` 和 `workspace tools catalog`；只有已安装 App 返回可用的接口才能执行。详细参数见 [文案精选调用说明](agent-skill/lulu-agent/references/workspace.md)。

## 运行与构建

目标环境：Apple Silicon、macOS 15 或更新版本。完整依赖、构建入口和校验流程见 [BUILDING.md](BUILDING.md)。

源码目录：`app/src` 为产品实现，`app/native` 为原生通信，`app/packaging` 为构建和包体校验，`app/tests` 为测试，`agent-skill` 为独立技能。

应用显示名称为「Paul工作台」；内部包路径保留 `/Applications/Lulu.app`，CLI 入口为 `/Applications/Lulu.app/Contents/MacOS/lulu-agent-cli`，以兼容安装校验、数据和现有调用方。

当前提交提供源码。本次本地构建通过 1,577 项完整产品检查，另有 29 项文案对比、候选接口与界面同步相关测试通过。安装包以本仓库实际发布的 Release 为准；上游 Lulu 安装包不包含这里新增的定制功能。

## 数据与许可

本地模型独立安装，用户文稿、录音、模型权重、配置密钥和应用备份不属于本仓库。云端 AI、链接采集和同步按使用者选择执行。

第一方代码沿用 [MIT 许可](LICENSE)；第三方组件、工具和模型按各自许可使用，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
