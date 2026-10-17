# P8-B｜v7 标题、学术注释与 PDF 分隔页：统一的离线保真门禁

更新：2026-10-17。把第七本学术注释样本验证过的结构规则加入公共工作流，保留此前v2–v6各规则与七本历史成品不变。本文只展示合成案例，不包含真实书籍来源或私人文件ID。

## 1. v7 标题识别是显式选择，不是通用删除H2

来源HTML的一种新形态是上游生成的无属性H1紧挨真正的无id H2：

~~~html
<body><h1>合成章节</h1><h2 class="secondTitle">合成章节</h2><p>示例正文。</p></body>
~~~

v7规则只删除经确认属于导出器生成的第一个H1，必须同时满足：
1. H1是body起始的精确无属性H1。
2. 后继紧邻的真正来源标签为无其它属性的H2 class="secondTitle"，不接受id、其它class、段落或图片介入。
3. 两个标题与冻结目录的真实章节标题完全一致（归一化空白后比较）。
4. 明确启用v7或v7-headings。旧v2–v6不启用。

版本构建输出单独位于 final/v7-headings/book.epub，不修改历史目录、正文、图片资源与原始章节checkpoint；缓存来源全文和图片对账仍单独执行。

## 2. 学术注释保护：三层证据，而非把旧半成品全文与新版强制相等

合法TXT回退可能补回原始EPUB漏掉的出版字段/附录正文。旧注释QA使用原始partial直接比较最终全文，会错误拒绝有来源支持的正文扩充。

改为三层对照：
- 原始partial：保存原始注释图alt及标记位置，证明注释来源。
- SQLite实际选中章：带校验SHA的完整候选，允许经过来源验证的正文恢复；注释文字与原始partial逐条匹配。
- 最终EPUB：与选中章逐字、逐注释锚点及相对区块位置比对；若生成PDF，则核对注释文字在PDF中的出现次数，而非只统计独立文本数。

RAW_SELECTED_NOTE_MISMATCH、NOTE_COUNT_MISMATCH、BODY_OR_NOTE_ANCHOR_MISMATCH和NOTE_TEXT_MISMATCH均属于阻断性问题。学术注释的原页面弹窗视觉仍需单独的人工G7签收，不能自动记完成。

## 3. PDF真空白和矢量章节分隔页应分开

新增离线工具 tools/pdf_page_audit.py，页面分为TEXT、TEXT_WITH_IMAGES、IMAGE_ONLY、VECTOR_ONLY和TRUE_BLANK。
- VECTOR_ONLY代表没有提取到文字/位图，但至少有矢量绘制对象；**只标成待人工视觉确认，不自动断定是章节分隔页**。
- TRUE_BLANK代表文字、位图、矢量对象均未发现；不能把此类页混进分隔页通过。
- 仅人工已看过确实是分隔页的页号，才能逐页提供 --reviewed-separator-page。技术报告仍保留whole_book_human_signoff=PENDING。
- 未审查的VECTOR_ONLY及TRUE_BLANK都会产生PDF_PAGE_AUDIT_REVIEW_REQUIRED，复核后才可能成为PDF_PAGE_AUDIT_PASS。

## 4. 工作示例（针对将来的独立书籍候选）

~~~powershell
python -m tools.heading_fidelity --book-dir '.local\library\NEW_READER' --output-version v7-headings
python -m tools.heading_fidelity --book-dir '.local\library\NEW_READER' --output-version v7-headings --build-versioned
python -m tools.cached_source_parity --book-dir '.local\library\NEW_READER' --compiled '.local\library\NEW_READER\final\v7-headings\book.epub' --heading-policy v7 --output '.local\v7_parity.json'
python -m tools.note_fidelity --book-dir '.local\library\NEW_READER' --compiled '.local\library\NEW_READER\final\v7-headings\book.epub' --heading-policy v7 --pdf '.local\library\NEW_READER\final\v7-headings\book.pdf' --output '.local\v7_note_report.json'
python -m tools.pdf_page_audit --pdf '.local\library\NEW_READER\final\v7-headings\book.pdf' --output '.local\pdf_review.json'
# 下行只能在确实人工看过这两页之后使用：
python -m tools.pdf_page_audit --pdf '.local\library\NEW_READER\final\v7-headings\book.pdf' --reviewed-separator-page 22 --reviewed-separator-page 150 --output '.local\pdf_review_after_visual.json'
~~~

本项目只创建隔离的v7候选和私有QA JSON；未改变七本历史交付，也不将合成测试通过误报成真实原网页逐页确认。

## 5. 离线验证与后续

CI覆盖v7规则、旧规则隔离、缓存全文/图像来源严格校验、经过来源支持的TXT版权字段恢复、原始注释不得被改写、PDF矢量页不自动误标真正空白等。测试样本不包含真实书名、reader ID、图片、Cookie或个人Drive链接。

下一阶段可使用**已冻结私有原始章节**仅做只读回归审计，不重新导出或覆盖已交付版本；首次真实Drive API OAuth测试属于P8-A另一个尚未完成的验收事项。
