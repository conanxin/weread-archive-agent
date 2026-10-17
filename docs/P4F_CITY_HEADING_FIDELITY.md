# P4-F｜原始城市章节 H2 与导出器新增 H1 的严格保真

此版本用于新的书籍源排版结构：固定导出器在真实章节 HTML 的正文开头增加一个**没有属性**的 H1；原书紧接着已经有 `h2 class="txtheading-1-15" id="..."`。不能把前一个 H1 和原始 H2 全部保留为重复可见标题。

## 不破坏旧版本的 v5 规则

- 原书 XHTML body 的首个元素必须是导出器生成的 `<h1>目录标题</h1>`，无任何属性或嵌套节点。
- 紧随其后的源节点必须是完整的 `<h2 class="txtheading-1-15" id="非空值">同目录标题</h2>`；两节点之间只能有空白。
- 两个可见标题必须与已冻结的 catalog 标题完全相等（使用现有实体、Unicode 空白归一化定义）。不能删除源 H2，也不能改动后续正文、图片或注释。
- 若 class 不符、ID 缺失、标题不同、存在正文/图片隔断，返回未匹配，不自动处理。
- 此规则仅在明确选择 `v5-headings` 时启用；旧的 `v2/v3/v4` 默认规则和已经交付的成果均不改变。

## 全量缓存完成后执行

~~~powershell
python -m tools.heading_fidelity --book-dir ".local/library/<this-reader-id>" --output-version v5-headings
python -m tools.heading_fidelity --book-dir ".local/library/<this-reader-id>" --output-version v5-headings --build-versioned
python -m tools.cached_source_parity --book-dir ".local/library/<this-reader-id>" --compiled ".local/library/<this-reader-id>/final/v5-headings/book.epub" --heading-policy v5 --output ".local/v5-parity.json"
~~~

只有全部单章 COMPLETE、冻结章 SHA、原始整书 EPUB 和其 `fullbook_QA_report.json` 均通过后，才能执行上述命令。创建另存版而非覆盖源 EPUB。

## 真实案例的证据边界

在新的已授权私人书籍前 35 个章节样本中，既观察到了原 H1 类型，也观察到了大量 `<h2 class="txtheading-1-15">`。工具原 v4 规则只能严格处理之前的 secondTitle H2 类型，本次才新增独立规则。样本里的新 H2 原节点确实有 class 和非空 ID，合成 H1 与原 H2 都匹配冻结目录。

公开单元测试用合成 EPUB 验证 v4 保持不变、v5 才对新 H2 执行严格删除，并拒绝异文、缺 ID、错 class、夹杂正文/图片的假匹配。真实书籍、图片、账号、reader ID 和章节截图仍只存放在私人 `.local` / owner-only Drive。

## 不可混淆的质量门禁

标题去重只说明一个特定可证明的导出器生成 H1 被移除；不能替代所有来源文字或图片 SHA 的全书对照，也不能自动把内容标记为人工视觉认可。默认注释仍是全文内联，不制作弹窗专版。