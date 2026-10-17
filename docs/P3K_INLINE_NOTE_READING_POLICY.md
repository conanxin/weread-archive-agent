# P3-K｜内联全文注释成为默认阅读方式

## 决策

个人阅读项目已确认：将来源注释的**全部文字直接显示在正文中**即可，不要求模拟原在线阅读器的点击浮层。当前已经完成验收的 v4 成品继续作为首选私人阅读候选，不因这一阅读偏好产生新的 v5 文件，也不更改已交付 EPUB/PDF 字节。

这项决定只代表 **ANNOTATION_PRESENTATION_ACCEPTED / INLINE_FULLTEXT**，不自动升级全书的人工阅读签收。书籍正文与图片的来源验证、云端交付、读者实际阅读均是独立门禁。

## 未来新书的默认实现

1. 若上游注释保存在缺失资源 Images/note.png 的 alt 中，保留完整文字并输出清晰的“〔注：……〕”内联标签，不截断或吞并注释。
2. 保留该标签所在的正文位置，不能把所有注释移动到章节末尾；在文字/段落锚点维度使用离线校验。
3. 导出的 EPUB 允许重排文本；打印型 PDF 的字体与分页可以与动态网页不同，但注释必须完整、可选择、可检索。
4. 无需调用个人登录会话重现交互浮层；除非用户以后明确提出新的阅读偏好，否则不制造仅为弹窗服务的新整书版本。
5. 仍可保留源网页浮层样本作为归档研究证据，不把“样式不同”再当作当前阅读目标的验收阻塞项。

## 工程验证命令

~~~powershell
python -m tools.note_fidelity --book-dir ".local/library/<reader-id>" --compiled ".local/library/<reader-id>/final/v4-headings/book.epub" --heading-policy v4 --pdf ".local/library/<reader-id>/final/v4-headings/book.pdf" --output ".local/note-reading-qa.json"
~~~

从 P3-K 起，指定 PDF 时，除了原有的注释全文、正文锚点、不同注释文字是否可检索之外，新增**带重复次数的全文出现数量核验**。例如同一注释正文出现两次，就必须在 PDF 文本中完整匹配两次；重复多/少都返回非零失败状态 `PDF_NOTE_OCCURRENCE_MULTIPLICITY_MISMATCH`。实现函数 `pdf_note_multiplicity` 和合成测试不需要个人书籍，公开安全。

## 当前私人书籍的实证边界（公开文档不包含原书文件）

- 冻结来源注释数、EPUB 转换结果与 PDF 可搜索次数一致：193/193 次。
- PDF 中不同全文注释标签 170 项：170/170 项都可检索；重复内容的总出现次数也与原来源完全一致，未发现多出/少掉。
- 66 个章节的正文、块级段落注释锚点都通过缓存来源对账，219 页 PDF 和 66 个书签不变。
- 私人已交付 v4 EPUB 和 PDF 的本地字节哈希仍与冻结的私有交付清单相同，未生成或上传新的电子书文件。
- 已保留原在线网页少量浮层交互抽检，但不要求 PDF 拥有同样的弹窗。

## 应用状态

- `INLINE_FULLTEXT_ACCEPTED`：用户已明确认可目前的注释显示形式。
- `P3K_INLINE_NOTE_PDF_OCCURRENCES_PASS`：已导出 PDF 的注释总次数与 EPUB 来源标签一致。
- `PREFERRED_READING_EDITION=v4-headings`：将已经验证并私有交付的 v4 作为当前优先阅读文件。
- `HUMAN_FULL_BOOK_READING_SIGNOFF=PENDING`：尚未取得“整本书的最终阅读体验全部通过”的明确结论；不得自动提升至 `FULL_BOOK_CONFIRMED`。

原始版本、v2、v3 和 v4 的文件及历史研究回执继续保留；本阶段不重复导书、不创建新的版本。
