# P3-J｜注释文字、正文锚点与在线弹窗的分层校验

## 背景与原理
部分微信读书章节的注释文字在 Images/note.png 图标的 alt 属性里。原 EPUB 缺少可用的图标本地资源；tools/repair_epub_images.py 将它变成显示完整文字的「〔注：……〕」标记。这样保全注释内容，但与原网页版点击橙色标记弹窗的样式不同。

## 本地、离线、可复用的检验命令
~~~powershell
python -m tools.note_fidelity --book-dir ".local/library/<reader-id>" --compiled ".local/library/<reader-id>/final/v4-headings/book.epub" --heading-policy v4 --pdf ".local/library/<reader-id>/final/v4-headings/book.pdf" --output ".local/note-fidelity-receipt.json"
~~~
本命令只读冻结 catalog、SQLite 队列、原始 partial.epub、完成的单章 EPUB 和最终 EPUB；指定 --pdf 时才读取 PDF（需安装 PyMuPDF）。不联网，不读取账号 Cookie，不上传 Drive。

## 质量门禁
1. 先验证冻结目录与 SQLite 快照哈希、单章 EPUB 完成状态和各章 SHA、原始 partial EPUB 的 ZIP CRC。
2. 按被冻结目录逐章剔除有来源证据的导出器合成 H1，对比原始 note.png 图标与已修复 EPUB 注释标记。
3. 从原始图标的 alt 按上游转换器相同规则保留全文、处理首尾空白和可见占位符，逐项核对注释文字顺序。
4. 比较正文的 Unicode NFC/去空白文本、注释锚点及段落、标题、列表、引文等块级边界，检测“文字尚在但挪到别处”的情况。
5. 可选检查 PDF 中所有不同注释标签的可检索性；未提供 PDF 则状态为 NOT_REQUESTED，不声称通过。
6. 遇缺失、异文或锚点位置不符时状态 P3J_NOTE_TEXT_ANCHOR_INCOMPLETE、退出码非零；全部通过才 P3J_NOTE_TEXT_ANCHOR_PASS。只输出匿名统计、章节序号和失败类别，不输出原文、注释全文、私人标识或凭证。

## 私人第二本真实回执（不进入公开代码）
48 个章节含注释，原始 partial EPUB 共 193 个 note.png 引用，v4 EPUB 有 193 条带文字的对应标记。193/193 注释文本精确匹配，66/66 章正文及块级锚点对应。不同注释标签 170 项，v4 PDF 可检索 170/170；没有发现离线文字或锚点异常。

## 原阅读器现场核验
在用户已授权的原网页，点击橙色注释标记后，浮层 reader_footerNote_bubble / reader_footerNote_text 显示内容。
第 43 章 11/11 在线弹窗文字内容多重集合与保存的注释一致；网页 DOM 顺序与 EPUB 顺序有局部互换（第 2/3 项及第 10/11 项），不能仅比较 nth(index)。第 17 章 14 个标记中有 13 个点击成功，均与该章存档注释内容匹配；另一个 UI 点击超时，不能报告 14/14 通过。没有进行全书 193 个在线弹窗的逐一对照。

## 阅读格式取舍与阶段边界
当前 v4 EPUB / PDF 保全注释文字并可搜索，但 PDF 将注释内嵌于正文，与在线阅读器的点击浮层存在真实样式和交互差异。是否另做“交互式 EPUB 脚注候选版”应以阅读器兼容性及用户阅读体验决定，当前不覆盖原始、v2、v3、v4，也不宣称已经还原弹窗。

内容保存、锚点对应、PDF 可检索、在线弹窗抽样、人工阅读签收是不同证据层级。最终状态依然 HUMAN_VISUAL_FIDELITY_PENDING / FULL_BOOK_CONFIRMED=false。

## P3-K 补充：内联注释默认接受与重复次数核验

阅读方式已确定：注释完整地内联显示即可，不要求与来源在线弹窗交互一致；现有已交付版本作为首选候选，不创建专门恢复弹窗的 v5。指定 PDF 时，tools.note_fidelity 现在除确认每种注释可搜索外，还逐种核对全文出现**次数**，对同样文字重复标注采取计数方式，若缺失或多出则报 PDF_NOTE_OCCURRENCE_MULTIPLICITY_MISMATCH。内容、锚点、原版保存、用户全书阅读签收仍独立评估。更多见 docs/P3K_INLINE_NOTE_READING_POLICY.md。

## 合成回归测试
tests/test_note_fidelity.py 使用纯合成 EPUB 验证正常注释、通用占位、错字、错位、缺失原始文件与不安全标题策略等情况；GitHub 不包含私人书籍文件、截图、Cookie、真实正文或原始图片。