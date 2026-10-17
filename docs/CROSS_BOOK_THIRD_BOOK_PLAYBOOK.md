# WeRead Archive Agent｜双书经验教训与第三本标准作业流程

状态：2026-10-17。范围：个人授权的本地电子书阅读归档、质量验证、私人交付。本文不包含真实书名、reader ID、书籍正文、图像、账号凭证、私人 Google Drive 文件 ID 或链接。真实证据记录于个人 Notion 和 .local。

## 一、前两本在技术上的已验证事实（匿名）

案例 A｜22 个有效章节（源目录 23 条）
- 早期仅抓取 2 个目录项可能全是版权、前言等极短篇章，不能作为真实长章节可靠性样本。
- 章 19—21 的 EPUB 路线存在明显短文缺字，TXT 后备恢复后，按固定归一化做了真实来源 5/5 抽样匹配（包含两章正常 EPUB）。
- 首版 EPUB 22 章、PDF 275 页；后续识别 12 处导出器追加的重复 H1，另存候选版 PDF 263 页。174 处 Markdown 图片引用、图片修复和样本显示另有各自独立证据。
- CSS warning 19 次实际聚合为一项未使用的装饰背景 PNG，不得报告为 19 张插图缺失。
- XHTML head 的 title 曾混入 Markdown 正文；body-only 修复后还需按 LF/CRLF 标准化比较，不能把 Windows 换行造成的字节增减当成正文丢失。
- 公共项目技术验收完成，但完整原网页逐页视觉与真人整书签收仍未取得。

案例 B｜66 个有效章节（源目录 67 条）
- 导出器在真实源标题前自动加 H1；细分 H1/H1、特殊版权页 wrapper、原始 H2.secondTitle 三类。前两轮仅修 18+1 处，真实浏览器对照后又发现 47 处，共 66 个有来源证据的合成标题；另存 v4 219 页 PDF（先前 228 页），不覆盖任何旧版。
- 冻结来源到 v4：66/66 章节的规范化可见正文、11/11 使用中的图片引用及 alt、70/70 全部 OPF 图片资源多重哈希一致；源平台实物图片抽样字节/像素 3/3 相同。
- 从 48 章识别 193 次注释，完整文本及块级正文锚点 193/193、66/66；不同注释全文 170 种，在 PDF 中按每一种的出现次数核对后，总计 193/193，无多出或漏项。
- 原微信读书注释是橙色标记点击浮层；个人阅读偏好已确认为“注释全文直接内联正文即可”。不为重现浮层再制造 v5。样式接受不等于全书人工签收。
- 私有交付必须看实际云端 ID、真实父目录、owner-only 权限及全量文件下载 SHA-256。浏览器提示“上传完成”有时实际上写进 Drive 根目录，需以独立云端元数据为准，必要时将真实文件移动至指定私人子目录。
- 现有 v4 EPUB/PDF 已作为首选阅读候选；全部以前版本与私人回执保留。

**共同结论**：结构完整性、来源文本一致性、图片字节一致性、注释语义锚点、PDF 视觉显示、云端真实交付和真人认可，是彼此独立的验收层。不得互相替代。

## 二、第三本启动前的真实阻塞

- 当前本地 library 中只有上述两本冻结书籍；第三本尚未明确目标书目与合法的 https://weread.qq.com/web/reader/... 阅读页 URL。
- 检查环境 doctor --json = READY 仅表示运行依赖与保存的会话文件存在，不能据此声称已获得第三本的在线访问。
- 在第三本 reader URL 到达前，只进行文档与程序预检，不读取书架、不得把前一本 ID 当成第三本，不进行内容抓取。
- 明确第三本阅读页后，验证目录返回的实际书名和数量，才能新建独立 book directory。

## 三、从第三本开始固定的八道门禁

### G0｜目标和环境（不抓正文）
- 必须获得用户给出的**真实微信读书阅读页** URL；从 bookDetail 路径或展示页 ID 猜测 reader ID 一律不通过。
- python wereadlab.py doctor --json，记录状态、Playwright/Calibre 是否可用及固定 upstream SHA。COOKIE_FILE_EXISTS ≠ LOGGED_IN。

### G1｜冻结目录（仅元数据）
- python wereadlab.py catalog "<real-reader-url>" --json
- 核对真实书名、全目录项数、有效章节数、编号/排序和章节 wordCount 等预估量（预估字数不等于已采集字符）。
- 只有返回 CATALOG_READY、且具备相应的授权访问时才能进行后续章节小样。冻结 catalog 与章 UID/ordinal，不允许混书。保存实际返回的第三本私有 book directory，后续用明确的 --catalog/--db 路径指定它，避免 --latest 在两本旧书间误选。

### G2｜选择有代表性的章节小样
- python wereadlab.py queue init --catalog "<third-private-book-dir>/catalog.json" --json
- python wereadlab.py queue status --db "<third-private-book-dir>/chapters.sqlite" --json
- python wereadlab.py queue run --db "<third-private-book-dir>/chapters.sqlite" --limit 1 --json
- 若第一章太短、只有页头或装饰图，不能误判为正文正常；另用 export --sample 2 --skip N --format epub --format md --json 选择一处真正的中段长章节。
- 至少取前（非仅封面）、中、后/最长章节的代表性样本；核对可见正文字符、图像资源、引用、注释、样式和可打开性。任一异常先停，不要立刻跑全书。

### G3｜有界采集和局部修复
- 首次小样验收后，才用 queue run --db "<third-private-book-dir>/chapters.sqlite" --limit 4 --json 按有限批次继续，直到所指定的第三本队列 status 全部 COMPLETE；仍是顺序有界处理，不启动激进并发。
- CONTENT_SUSPICIOUS（例如预期长文但 EPUB 只有极少字符）：保留原始 .partial，先按实际证据尝试 TXT 后备，再复核长文正文，而不是把极短结果写 COMPLETE。
- 图片来源 CDN 出现可信跳转，只在限定域名、文件头、大小和 MIME 条件内修复；图片缺失的修复不应再次下载已有正文。
- 对 Images/note.png 且文字在 alt 的注释，保留完整内联文字；绝不截断，不强制模拟在线点击浮层。
- 错误类别 LOGIN_REQUIRED / ACCESS_RESTRICTED / MANUAL_VERIFICATION_REQUIRED 等需停，并向用户报告，不绕过阅读权限。

### G4｜全书合并和内容保真
- 先确认冻结目录与队列覆盖一致，单章 SHA 均通过，再执行 book assemble --db "<third-private-book-dir>/chapters.sqlite" --format epub --format md --format pdf --format txt --json。
- 只对发现有来源证据的合成标题执行 heading_fidelity；不能不管来源就强套第二本的 H1/H2 修复。原始、修订版另存，文本和图片字节应保持。
- 对适用的独立修订 EPUB 运行 tools.cached_source_parity。严格核对每章正文 NFC/空白定义下的字符、spine 顺序、图片字节、alt 和完整图片哈希多重集合；有差异必须报告。
- 若原始 partial EPUB 中有 note.png 注释，则用 tools.note_fidelity 的适当 heading-policy 复核注释正文、段落位置和 PDF 检索/重复次数；无适用的注释结构则明确报告不适用，不能凭空填 193/193。
- 至少做头、中、后以及有图与有注释章节的真实来源文本/网页对照，记录抽样范围，不声称全集出版社母版校对完成。

### G5｜PDF 和 Markdown 排版
- 手工再次生成 PDF 必须固定 --paper-size a4；整书前后版本页数不作为内容删改证据。
- PDF 核对全页是否可搜索、书签总数、内容乱码/越界、实际含图片页、图片裁切样本和重复标题。Markdown/TXT 必须只取 XHTML body，排除 head/script/style。
- 比较 Windows 与 Linux 输出时说明 CRLF 和 LF 的差异；统一换行后再讨论真实文本内容差异。
- 对正文 note 做内联全文即可；没有经过用户明确改变偏好时不制作弹窗专版。

### G6｜私有交付（不把本地文件写入公共 GitHub）
- 为第三本建立独立 owner-only Drive 子目录，不复用前两本的真实文件 ID 或文件夹。
- 生成 allowlisted manifest，上传经检验的 EPUB、A4 PDF、Markdown/TXT/图像 ZIP、QA 摘要（仅私人目录）。
- 只在实际云端文件 ID、指定父目录、权限为 owner-only 且完整云端字节重新下载 SHA-256 均与本地一致时报告 PRIVATE_DELIVERY_PASS。
- 上传提示或文件名/大小相似不足以证明成功；检查确实不是错在 Drive 根目录或同名旧文件。

### G7｜用户可读性决定与最终状态
- 以 EPUB 可重排和 A4 PDF 为主要私人阅读成果，并给出打开链接；优先保持注释内联全文。
- 技术状态“BOOK_FILES_READY / PRIVATE_DELIVERY_PASS”与真人“FULL_BOOK_CONFIRMED”分开。
- 没有用户明确签收全书之前，依旧标记 HUMAN_READING_SIGNOFF_PENDING；别为了升级状态重复导出同一整书。

## 四、Hermes/OpenClaw 单消息任务协议

第三本目标 URI 到达后向已配置 Agent 发送一次任务消息即可，指令需同时具备：
- Context：仓库、既有第一/二本经验、默认内联注释、避免混书。
- Target：用户确认的真实第三本 reader URL（仅发给已授权的私人 Agent）。
- Gates：G0→G1→G2，先返回真实第三本书名、冻结目录条数、小样字符/图片/注释结果。
- Scope：经第一轮 pilot 自动验收再逐批采集；任何登录/内容不完整/人工验证阻塞立即停。
- Deliverable：EPUB/PDF/MD/TXT 与私人云端交付，以实际父目录/权限/完整云端 SHA 为准。
- Privacy：Cookie、正文与原图只放个人 .local / owner-only Drive；公共 GitHub 只可写匿名方法及合成测试。
- Return：状态 JSON，包含已完成与未完成的门禁、源证据类型和文件实际路径，不能声称凭网页目录已经导完书。

## 五、不要重新发生的七种失败

| 失败模式 | 原因 | 第三本阻断动作 |
| --- | --- | --- |
| 把两页小样当正文 | 首目录是封面/版权/短前言 | 中段实质长章节必须复测 |
| 极短 EPUB 标完成 | 长章节仅抓到装饰或空白 | CONTENT_SUSPICIOUS → TXT fallback 后复测 |
| 图片告警当丢图 | CSS 背景资源重复 | 按实际使用、哈希与正文位置分类 |
| 两个章节标题 | 导出器增加 H1，源已有 H1/H2 | 按来源结构识别，只删可证明节点 |
| 注释丢字或位置变 | note.png alt 被忽略/截断 | 完整内联 + 锚点与重复次数门禁 |
| PDF 页数变化当缺文 | 纸张尺寸和标题排版不同 | 固定 A4 + 逐章正文/图片对账 |
| Drive 显示上传成功 | 实际写入错误目录、旧文件或权限不符 | 云端 ID/parent/ACL/full-download SHA |

## 六、第三本当前状态

THIRD_BOOK_TARGET_PENDING；ENVIRONMENT_DOCTOR_READY；NO_CATALOG_YET；NO_CAPTURE_YET。
明确书名与阅读链接是唯一的入口缺口；在缺口被填补前，不会承诺第三本已经开始正文导出。
