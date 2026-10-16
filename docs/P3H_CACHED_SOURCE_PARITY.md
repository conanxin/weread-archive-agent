# P3-H｜缓存来源 EPUB → 整书 EPUB 图文保真门禁

此工具把一次性个人书籍对账实验变成**离线、可复用的校验命令**。只读取冻结的 catalog.json、chapters.sqlite、单章 EPUB 和指定的整书 EPUB；不会访问微信读书、浏览器、Cookie 或 Google Drive。

## 运行方式（Windows）

在仓库根目录执行，输出 JSON 放到不上传 GitHub 的 .local 下：

~~~powershell
python -m tools.cached_source_parity --book-dir ".local/library/<reader-id>" --compiled ".local/library/<reader-id>/final/v3-headings/book.epub" --output ".local/cached_source_parity_receipt.json"
~~~

默认向终端输出 JSON。成功退出码 0；有任何检查失败退出码 1。参数中的实际目录仅留在本机，公开仓库不记录书籍 ID、来源正文、图片、私人哈希或云盘链接。CLI 仅报告聚合数量、错误类型及章节序号。

## 验证门禁

1. **来源冻结**：目录与 SQLite 快照 SHA 一致、选中的章节已 COMPLETE、每章源文件 SHA 与队列匹配。
2. **整书结构**：EPUB 可读、ZIP CRC、spine 数量和顺序与冻结章节一致。
3. **逐章正文**：仅清理来源可证明的合成 H1；比较正文文本经 Unicode NFC 与去空白后的字符，标点和字词不会忽略。图注与正文注释参与文字对账。
4. **被实际引用的图片**：比较引用次数、alt 描述和逐个图像的原始字节 SHA-256。组装器改名不会造成误判。
5. **整个图片资源包**：根据来源与最终 EPUB 的 OPF image/* manifest 计算 SHA-256 多重集合，保留所有重复图片的出现次数。

## 版本化标题规则与 P3-I v4

旧版本维持默认 heading_policy=v3 的生成标题识别口径。对于经过原阅读器验证的 v4-secondTitle 结构，显式增加 --heading-policy v4 才会将来源可证明的普通 H1 + 原始 secondTitle H2 归为合成标题；标题和来源类名必须完全符合严格判据。不要让未来的规则升级自动改变已验收 v2/v3 的比较语义。

## 输出状态

- **P3H_CACHED_SOURCE_PARITY_PASS**：上述离线门禁全部通过。
- **P3H_CACHED_SOURCE_PARITY_INCOMPLETE**：存在缺失或不同的证据，issue_codes 解释失败类别。
- **SOURCE_OR_EPUB_EVIDENCE_INVALID**：来源或 EPUB 无法验证，命令非零退出。

## 合成故障样本

- 来源章节的 SQLite SHA 改变；spine 章节顺序错误。
- 正文字符变化、图注文字变化。
- 图片 alt 被修改、图片引用消失、图片二进制被替换。
- 图片 manifest 缺少资源或图片哈希重复次数发生变化。
- 版权页包裹式源标题能够正确保留，仅删除明确属于导出器的合成 H1。

测试文件：tests/test_cached_source_parity.py，仅使用合成章节和模拟图片。

## 结论边界与后续

- 这不是新的 66 章微信读书在线抓取；只检查**本机冻结章节快照**到整书转换的完整性。
- 此工具不确认字体、分页、图像摆放、CSS 背景、可视脚注位置等阅读器视觉保真。
- 原阅读器并排检查和用户签收仍属于独立门禁；离线通过不等于 FULL_BOOK_CONFIRMED。
- 云盘实际上传、父目录和所有者权限，仍由 private_release_verify 等独立工具验收。

前序视觉规则见 docs/P3F_VISUAL_REVIEW_GATE.md，私人真实测试回执只保存在本地 .local 与 Notion 项目研究记录中。
