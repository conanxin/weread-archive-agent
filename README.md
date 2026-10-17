# WeRead Archive Agent

面向个人学习、检索与归档的 **微信读书本地电子书导出工作流**。把现有开源的章节提取实现封装为稳定的 CLI，供 Windows 双击运行，也可由 Hermes / OpenClaw 调用。这个仓库开源的是**任务编排、格式转换、校验和 Agent 接口**；不会提交微信登录凭证、个人书库内容或提取引擎的第三方源码。

> 当前 CLI 编号仍为 **v0.1.0**。个人授权环境已完成两部不同 EPUB 书籍的整书结构/机器 QA（共 22 章和 66 章），并有分布式章节文字来源抽查与私人云盘读回证据；**出版社底本、图文版式与全书逐页的人为终审仍未通过，不宣称 `FULL_BOOK_CONFIRMED`**。正式发布版本编号需另行评审。

## 为什么采用这个结构

- 优先调用 [finlater/weread.koplugin](https://github.com/finlater/weread.koplugin) 独立 Python EPUB 提取脚本（AGPL-3.0 项目，不复制其源码）。其作者曾验证过 134 章及 282 张插图的 EPUB 导出实例。
- 以后追加 [lbq110/weread-exporter](https://github.com/lbq110/weread-exporter) Canvas 适配器作为独立替代。网页端不可读的书籍无法保证提取；不处理人机验证规避。
- Agent 只传书籍 URL、格式和目标目录；浏览器登录留在本地，命令不接受会话令牌字符串，也不把 Cookie 上传到云端。

## 立即使用（Windows 11）

环境：Python 3.10+、Git。生成 PDF 另需 [Calibre](https://calibre-ebook.com/)；Markdown 和 TXT 使用项目内置转换器，**无需 Pandoc**。

**方法 A：双击 `start.cmd`**，首次弹出浏览器扫码登录，随后粘贴微信读书网页版阅读地址。首次登录时会按需安装 Playwright / Chromium，安装过程需要网络连接和可交互的 Windows 桌面。

**方法 B：命令行 / Agent**。下面使用交互提示，避免误把示例 URL 当作真实书籍地址：

1. 在浏览器进入 [微信读书网页版](https://weread.qq.com/)，打开书架里一本可以阅读的书，**点击「阅读」后**复制地址栏中完整的 `https://weread.qq.com/web/reader/...` 链接。
2. 在 PowerShell 执行以下命令，粘贴链接时只需输入一次（不要粘贴中文占位文字）。

```powershell
python wereadlab.py doctor --json
# 如果之前已完成扫码登录，下一行无需重复运行
# python wereadlab.py login
$readerUrl = Read-Host "请粘贴从微信读书阅读页复制的完整 URL"
python wereadlab.py export $readerUrl --sample 2 --format epub --format md --json
python wereadlab.py inspect --latest --json
# 如果前两章只有扉页、版权页，可额外抽查目录第 5、6 个可读章节（先跳过 4 章）：
# python wereadlab.py export $readerUrl --sample 2 --skip 4 --format epub --format md --json
# 两章验证成功后，才运行全书导出：
# python wereadlab.py export $readerUrl --full --format epub --format pdf --format md --format txt --json
python wereadlab.py status --json
```

也可以先复制浏览器地址栏，再直接执行 `python wereadlab.py export (Get-Clipboard) --sample 2 --format epub --format md --json`。**详情页 `/web/bookDetail/...` 与实际阅读页 `/web/reader/...` 不应混用。**

`SESSION_SAVED` 表示 Cookie 已保存在本机，不代表已经确认能读取目标书籍；真实可用性要由后续试导出来验证。

- `login` 首次安装 Python Playwright（需要联网）并打开本地浏览器供本人扫码；未装 Chromium 时依提示安装一次。**无人值守 Agent 不应尝试自动扫码。**
- `export` 首次自动浅克隆上游仓库至 `.local/upstream/`。上游不在每次运行时自动更新，保持版本可复现。需要更新时执行 `python wereadlab.py upstream --update`。
- 默认执行 **2 章试导出**，即目录中前两个被识别为可读的章节，可能只是扉页/版权页。可以传 `--sample 2 --skip 4` 抽查目录中第 5、6 个可读章节；两次抽查结果会分开保存，避免误用缓存。传 `--full` 才取当前账号实际可读的整书章节。
- `inspect --latest --json` 在本地逐章列出标题、文字字符数和图片引用数，**不再联网抓书**。看到 `STRUCTURE_PASS_COMPLETENESS_UNVERIFIED` 只表示结构正常，不证明全文齐全或文字完全正确。
- 若章节正文已取得但返回 `IMAGE_ASSETS_INCOMPLETE`（CDN 插图未下载、注释图标缺失），**不要先重新抓全书**。程序在新导出时会自动尝试图片修复；旧版留下的 `*.partial.epub` 可独立修复，不再发起章节正文请求：

```powershell
cd D:\CodexData\weread-archive-agent
python wereadlab.py repair --latest --format epub --format md --format pdf --json
python wereadlab.py inspect --latest --json
```

图片修复只请求白名单 `https://res.weread.qq.com/` 的图片，将可下载资源写入 EPUB 并更新清单；重复 URL 只下载一次。原书缺失的 `Images/note.png` 用明显的文字注释标记 `〔注〕` 替代，不声称还原原图。无法下载的图片仍会导致 `IMAGE_ASSETS_INCOMPLETE`，不被静默跳过。修复文件另存为 `*.repaired.epub`，原始 `*.partial.epub` 保留。
- 默认若 EPUB 已存在会直接复用，避免重复请求。需要重试传 `--force`。
- 可用 `--expected-chapters N` 指定经过人工核对的**应有章节数**；结构检查不满足时不进行下一步转换。
- 用 `--output-dir D:\Books\SomeBook` 指定输出目录；否则使用 `.local/library/<reader-id>/`。
- 支持 `--format epub|pdf|md|txt`（可以重复使用）。缺少 Calibre 时仍保留 EPUB 和 Markdown，状态为 `FORMAT_PARTIAL`。

## P2-A｜只读取目录，不启动整书导出

```powershell
cd D:\CodexData\weread-archive-agent
$readerUrl = Read-Host "粘贴微信读书阅读地址"
python wereadlab.py catalog $readerUrl --json
```

- `catalog` 调用已固定 SHA 的上游阅读状态及 `chapterInfos` 目录接口；**只获取书目和章节目录元数据**，不会下载章节正文/插图。
- 结果写入私有 `.local/library/<reader-id>/catalog.json` 和 `catalog.report.json`。包含原目录顺序、章节 UID、标题、提供方字数统计、是否会被当前上游导出器选中；封面或零字数条目不直接计入可导出条数。
- 仅有 `CATALOG_READY` 不代表实际已完成一本书的正文、图片或 EPUB/PDF；下一阶段开发章节级检查点和可恢复的任务队列。
- GitHub 测试使用合成目录；真实数据和登录凭证不得提交仓库。

## P2-B1｜持久化章节任务队列（只建队，不下载正文）

```powershell
# 已有 catalog.json 后，在本地保存 22 条或其他真实数量的可导出章节任务
python wereadlab.py queue init --latest --json
python wereadlab.py queue status --latest --json
```

队列保存在该书的私有 `.local/library/<reader-id>/chapters.sqlite`，记录章节 UID、目录次序、提供方字数、PENDING / RUNNING / FAILED / COMPLETE、尝试次数和后续文件校验字段。重复初始化不会重置已有章节状态；目录章 ID / 次序改变则停止并请求显式校准。**此阶段只实现建队和状态查询；还没有章节执行 worker，也不能将 `QUEUE_READY` 视为整书下载完成。**

## P2-B2｜逐章提取与断点恢复（小批次）

```powershell
cd D:\CodexData\weread-archive-agent
python wereadlab.py queue status --latest --json
# 默认只处理一章：需要已有 catalog.json 与 chapters.sqlite
python wereadlab.py queue run --latest --limit 1 --json
# 只有确有 FAILED/INTERRUPTED 且已调查原因时，才显式允许重试：
# python wereadlab.py queue run --latest --limit 1 --retry-failed --json
python wereadlab.py queue status --latest --json
```

- 从本地保存的真实阅读器 ID 与正式 bookId 获取章节，启动时重新对照已冻结目录；目录顺序或上游 SHA 变化会停止执行。
- 每一章先生成 `chapters/0001.partial.epub`，修复其图片和注释，再生成 `chapters/0001.epub`；通过结构与基本截断门禁后写入文件 SHA-256，SQLite 状态才更新为 `COMPLETE`。
- 若图像修复失败，正文半成品仍保留。显式 `--retry-failed` 后，优先在本地修复图片，**不会重新下载已保存的章节正文**。
- 单本书 OS 文件锁防止并发 Worker；上次崩溃的 `RUNNING` 标为 `FAILED/INTERRUPTED`，供审查后重试；已有完成文件 SHA 不符会停止而非自动覆盖。
- `--limit` 范围为 1–10，默认 1；每次最多运行指定章节数，遇到权限、登录、章节或图片错误就停。不启动整书合并/上传；`WORKER_PROGRESS` 或 `CHAPTERS_FETCHED_PENDING_FULL_QA` **不等于最终完整电子书**。

## P2-B3｜处理内容过短的特殊 EPUB 章节

- 当目录预计有明显正文（500 字及以上），但 EPUB 中得到的正文少于预计的 10%，保持 `CONTENT_SUSPICIOUS` 判断，不接受残缺图像版内容。
- 小范围真实验证表明个别附录/后记 EPUB 只含少量装饰图片，但同一书的 TXT 文本通道有完整段落。新 Worker 在此类异常时可**自动尝试一次 TXT 通道**，并验证正文达到目录字数估算的至少 60%。
- 成功则保存 `chapters/NNNN.txt-fallback.partial.epub`，原来的 `NNNN.partial.epub` 和 `NNNN.images.partial.epub` 保留为独立证据；最终章节采用经验证的文本备用版本。
- 返回 `txt_fallback_ordinals` 用来报告内容恢复的章节序号。若 TXT 仍不完整，标记 `TXT_FALLBACK_INCOMPLETE` 并停止，不因图像 EPUB 可打开就冒称成功。合并成书时单独抽查这些章节版式/插图。
- 已有失败章节可用 `python wereadlab.py queue run --latest --limit 1 --retry-failed --json` 明确允许重试；优先复用已有本地 EPUB 半成品。

## P2-C｜合并已验收的章节（不访问微信读书）

所有目录中被选中的章节均已在 SQLite 标记 `COMPLETE`，并有通过 SHA256 的本地独立 EPUB 后，才能运行：

```powershell
cd D:\CodexData\weread-archive-agent
python wereadlab.py queue status --latest --json
python wereadlab.py book assemble --latest --format epub --format md --format pdf --json
```

- 若仍有待处理或失败章节，返回 `ASSEMBLY_NOT_READY`，不生成冒充完整的 EPUB。
- 合并前逐章复核文件 SHA256、目录 UID/排序和 EPUB 基本结构；各章同名插图使用独立目录，防止覆盖。
- CSS 里引用但未包含于原章包的装饰图资源会显式记录为 `CSS_DECORATION_UNAVAILABLE` 并在合并版用 `none` 降级，原始章 EPUB 保留。这意味着图文阅读能力可用，但部分视觉效果仍需原网页对照。
- 生成 `.local/library/<reader-id>/final/book.epub`、`book.pdf`、`book/fulltext.md` 和 `book.report.json`。状态 `BOOK_FILES_READY_COMPLETENESS_UNVERIFIED` 仍须人工抽查首章、中间章、末章及图文顺序，**不等于 `FULL_BOOK_CONFIRMED`**。
- 不会触发公开发布或自动 Drive 上传；后续单独执行私有传输与核验。

## P2-D2｜样式与整书保真审计（只读）

一次真实 22 章整书测试发现：合并器提示 19 项 CSS 装饰资源缺失。进一步去重后，它们实际是 **一个背景 PNG 在 19 章中被重复引用**；对应简单 CSS 类在这 19 个章节的静态 XHTML 中从未出现。这是低预期影响的未使用样式引用，不代表 19 张正文图片损失，也不等于原书网页排版已经逐页验证。

可复用的纯本地检查工具：

```powershell
python tools/fidelity_audit.py --book-dir '.local/library/实际书籍目录' --output '.local/css-fidelity-report.json'
```

审计结果只输出资源/选择器的摘要哈希、重复次数、CSS 属性名、选择器使用状态和章节序号，不输出正文、图片 URL 或 Cookie。`UNUSED_SIMPLE_CLASS` 与 `USED_SIMPLE_CLASS`、`UNKNOWN_OR_COMPLEX_SELECTOR` 必须分开处理；后两类不能直接按装饰资源忽略。

完整的真实故障、根因与复用规则见 [P2-D2 经验复盘](docs/LESSONS_LEARNED_2026-10-14.md)。目前全书文件可以私有阅读，但只达到 `BOOK_FILES_READY_COMPLETENESS_UNVERIFIED`，最终与源阅读页逐字/逐图对照仍待确认。

## P2-D3｜一句命令执行少量来源正文对照

整书 EPUB/PDF 生成成功后，使用 `source-audit` 在已获阅读权限的本地电脑上抽查来源。无需手工填写书籍 ID、上游脚本位置或 SHA，程序自动读取已有 `.local` 中的目录、会话和固定上游版本。

```powershell
cd D:\CodexData\weread-archive-agent
python wereadlab.py source-audit --latest --checks "19:txt,20:txt,21:txt" --live --json
```

- `--live` 必须显式给出；不传时不访问微信读书正文。最多校验六个指定章节，默认选择本书的三个 TXT 备用章节。独立入口 `tools/source_parity_audit.py` 仍可用于特别调试。
- 真实回执只在 `.local/library/<reader-id>/final/source_parity_audit.json` 中保存章节序号、数量、精确匹配状态、相似度，不含全文和 Cookie。
- 比较标准为 NFC Unicode、去空白、去导出器自动加的第一个章节标题，以及将可见注释标记和原始 alt 文本对齐。**标点和字词差异不能忽略**。
- `SOURCE_PARITY_EXACT_FOR_CHECKED_CHAPTERS` 仅说明指定章节的文本与同一服务重新获取的文本一致；不等于出版社母版校勘、图片/脚注保真，也不等于全书终验完成。

## P2-D4｜重复章节标题来源审计与独立候选版

上游 EPUB 生成器会在正文前添加无样式的 `<h1>章节标题</h1>`。若原始章节正文恰好也以同名 H1 开始，可能出现重复标题及独立空白标题页。此问题**不能**通过不分来源地删除所有重复 H1 解决。

```powershell
cd D:\CodexData\weread-archive-agent
# 只读审计（默认）；将路径替换为本机书籍私有目录
python -m tools.heading_fidelity --book-dir ".local/library/<reader-id>"

# 只有完成审计后才显式创建独立版本（原书不覆盖）
python -m tools.heading_fidelity --book-dir ".local/library/<reader-id>" --build-versioned
```

工具要求原始 EPUB 哈希与 QA 报告完全一致、所有目录章节独立文件 SHA 校验通过；仅删除已识别的上游**合成** H1，并原封不动保留来源正文、图片和其他章节。生成 `final/v2-headings/book.epub`，后续需要单独转换 PDF、完成视觉抽查和私有交付。真实样本 12 项匹配，Linux/Windows/实机各 54 项合成测试通过；详见 [P2-D4 实测报告](docs/P2D4_HEADING_FIDELITY_2026-10-15.md)。

**状态边界**：`P2D4_CANDIDATE_QA_PASS` 是候选版的机器质量门禁，并非已经逐页核对源阅读器，也不是自动发布或 `FULL_BOOK_CONFIRMED`。

## P3-E｜云盘私有交付的双重证明

完成本地 EPUB/PDF 质量报告后，**云端上传完成提示不能充当交付回执**。本项目新增纯离线工具，用已选择的文件生成 SHA256 清单，并在连接器提供实际云端元数据及下载文件 SHA256 后校验：云端真实 ID、大小、文件夹父目录、`shared=false` 和 owner-only 权限。

```powershell
# 示例为合成文件与占位符；清单及读取结果必须保存到 .local 私有路径
python -m tools.private_release_manifest --directory ".local/staged" `
  --files "book.epub" "book.pdf" `
  --target-folder-id "<private-folder-id>" `
  --output ".local/release-manifest.json"

python -m tools.private_release_verify `
  --manifest ".local/release-manifest.json" `
  --observed ".local/drive-observations.json" `
  --output ".local/release-receipt.json"
```

成功状态为 `PRIVATE_DELIVERY_PASS`；如存在同名多份、传错目录、权限异常、云端缺 SHA 或不一致，一律返回 `PRIVATE_DELIVERY_INCOMPLETE` 并提供机器可读失败原因。**此功能不执行上传/移动，也不读取 Google Cookie**。详细见 [P3-E 私人交付门禁](docs/P3E_PRIVATE_DELIVERY_GATE.md)。

## P3-H｜冻结章节与整书的图文保真校验

全书下载和 EPUB 合并完成之后，可以用**离线、只读**的源码到成品校验门禁，确保已保存的原始章节文本、正文图注、图片字节、alt 描述、图像资源及 spine 章节顺序不因合并/排版丢失：

~~~powershell
python -m tools.cached_source_parity --book-dir ".local/library/<reader-id>" --compiled ".local/library/<reader-id>/final/v3-headings/book.epub" --output ".local/parity-receipt.json"
~~~

状态为 `P3H_CACHED_SOURCE_PARITY_PASS` 或 `P3H_CACHED_SOURCE_PARITY_INCOMPLETE`（非零退出），JSON 不输出私人书籍正文与哈希。仅使用本地冻结缓存，不登录微信读书，不进行在线抓取或云盘上传。它**不是**出版社母版校勘或真人阅读器视觉终审。具体门禁和合成失败案例见 [P3-H 缓存来源保真说明](docs/P3H_CACHED_SOURCE_PARITY.md)，版权页合成标题修复见 [P3-F 视觉规则](docs/P3F_VISUAL_REVIEW_GATE.md)。

## P3-I｜原阅读器视觉抽查与严格 v4 标题修复

在线阅读器的 66 个目录与整书 PDF 66 条书签一一匹配。针对来源 XHTML 中 47 处“上游合成普通 H1 + 原始 secondTitle H2”的遗漏，本项目现在可在独立的 v4-headings 版本中，精确删除已证实的合成 H1；原版、v2 和 v3 均保留。

先运行只读审计，随后明确构建候选版，再用 --heading-policy v4 的缓存来源校验门禁核对 66 章文字、图片字节、资源完整性。统一 A4 PDF 规格，避免把排版页数变化误认为正文丢失。详细方法见 [P3-I 来源阅读器视觉门禁](docs/P3I_SOURCE_READER_VISUAL_FIDELITY.md)。**注释弹窗与阅读者最终签收依然待完成；不自动标记 FULL_BOOK_CONFIRMED。**

## P3-J｜注释文字和正文锚点的离线验收

保真不仅是图片与正文数量。微信读书的部分注释通过缺失的 Images/note.png 图标携带 alt 正文；修复后的 EPUB 改为可见的 `〔注：……〕` 文字。新增只读门禁，逐一核对来源注释的完整内容、段落位置以及 PDF 可检索性：

~~~powershell
python -m tools.note_fidelity --book-dir ".local/library/<reader-id>" --compiled ".local/library/<reader-id>/final/v4-headings/book.epub" --heading-policy v4 --pdf ".local/library/<reader-id>/final/v4-headings/book.pdf" --output ".local/note-fidelity-receipt.json"
~~~

这一步不会打开网页或读取 Cookie。**文字/锚点检查通过 ≠ 原阅读器点击弹窗样式通过**；网页注释浮层需单独抽样，真人阅读签收继续保持待确认。详细见 [P3-J 注释保真验收](docs/P3J_NOTE_FIDELITY.md)。

## 导出结果

```text
.local/
  session/                   # 本地浏览器资料及 Cookie（git 忽略）
  upstream/                  # 运行时取得的第三方引擎（git 忽略）
  library/reader-id/
    sample-2.epub
    sample-2.report.json
    sample-2.log
    sample-2/fulltext.md
    sample-2/images/*.jpg
    full.epub
    full.pdf
    full.report.json
    full/fulltext.md
    full/fulltext.txt
```

`*.report.json` 中包括上游 Commit SHA、书籍 URL、EPUB 章节/图片结构、输出格式及状态。默认不上传任何个人内容。`STRUCTURE_PASS_COMPLETENESS_UNVERIFIED` 意味着 ZIP/目录/本地图片引用符合检查要求，但**仍须对照原书目录核验首、中、末章节**。

## 自动化约束

通过 `AGENTS.md` 描述 Hermes、OpenClaw 的 JSON CLI 调用方式。Agent 可自动检测依赖、排队、调用已保存本地会话、转格式和检查；NAS 同步仍是后续功能；碰到 `LOGIN_REQUIRED`、`WEB_UNAVAILABLE`、`ACCESS_RESTRICTED` 或 `MANUAL_VERIFICATION_REQUIRED` 时应停止并通知用户，不尝试自动规避验证或扩大权限。

## 开发

```powershell
python -m unittest discover -s tests -v
python wereadlab.py doctor --json
```

测试只使用**合成 EPUB**，不调用微信读书，不需要账号或网络。持续更新计划见 [`docs/ROADMAP.md`](docs/ROADMAP.md)，研究依据见 [`docs/RESEARCH_LOG.md`](docs/RESEARCH_LOG.md)，经验教训与验收门禁见 [`docs/LESSONS_LEARNED_2026-10-14.md`](docs/LESSONS_LEARNED_2026-10-14.md)。

### 软件边界

此仓库的编排实现为 MIT。可选上游提取引擎为独立项目，按其各自许可证发布；当前不复制或再分发 AGPL 上游源码。请只处理自己有权限访问的阅读内容，避免把个人书籍文件、Cookie、登录日志提交到公开仓库。