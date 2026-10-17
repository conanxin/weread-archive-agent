# P5-B｜secondTitle-1 H2 标题的独立 v6 保真规则

## 来源结构与风险
新书来源 XHTML 的 body 起始处被固定上游追加一个无属性的 H1 标题；紧随其后的真正原书标题是 H2 class=secondTitle-1（没有 id）。此前 v4 的 secondTitle H2 必须有 id，v5 的 txtheading-1-15 H2 也有 id，因此不能直接套用旧版，否则 PDF 会重复显示章标题。

## 严格且版本化的修复
- 只在显式选择 v6-headings 的独立候选时启用；旧 v2/v3/v4/v5 默认行为与旧版交付文件不变。
- body 最前面的生成 H1 必须无属性、无嵌套内容，并与紧接着的原书 H2 class=secondTitle-1（无额外属性）标题文本完全相同。
- 两个标题必须与冻结 catalog 的当前章节名称一致，且节点之间只有空白。若存在正文或图片隔断、类名不符、标题异文、额外属性等，不得自动清理。
- 只删除合成的第一个 H1 节点，必须保留原书 H2、后续正文、图片、alt、注释和其它 ZIP 成员字节。
- 源单章及原始整书 EPUB 完全保留，所有 v6 成品独立存档。完成修改后执行逐章 cached_source_parity v6 来源文字和图片 SHA 检查。

## 通用命令
~~~powershell
python -m tools.heading_fidelity --book-dir "<new-book-dir>" --output-version v6-headings
python -m tools.heading_fidelity --book-dir "<new-book-dir>" --output-version v6-headings --build-versioned
python -m tools.cached_source_parity --book-dir "<new-book-dir>" --compiled "<new-book-dir>/final/v6-headings/book.epub" --heading-policy v6 --output ".local/v6-parity.json"
~~~

必须先完成冻结目录、章节队列 SHA、原始整书 EPUB SHA 和书内标题溯源证据，不得对任意书自动强制 v6。

## 匿名真实证据
授权私人第五本74有效章节中，20处原 H1/H1 或版权页结构、54处原 H2 secondTitle-1 结构。v6 仅删除74处严格证明为导出器添加的标题，保留真正的原书标题。来源→v6 本地QA：74/74章归一化正文一致、297/297实际图片字节和 alt 相同、298/298图片资源多重哈希一致、297种不同图像内容，异常0。所有源文件、私人书名、reader ID、图片、账号和SHA保持在本地忽略目录。

## 证据边界
冻结本地来源对成品的技术一致性不代表出版社母版逐字校勘、当前在线阅读器像素级一致或用户整本阅读签收；最终人工验收仍是独立门禁。