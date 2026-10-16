# P3-I｜原阅读器视觉保真抽检与 v4 标题修复

## 目标与证据分层

以已经获得阅读权限的在线微信读书阅读器作视觉参考，建立原阅读器、冻结目录、缓存来源 EPUB、最终 EPUB 和 PDF 之间的章节身份对照，并单独核对真正显示的插图、图片裁切、注释标记和正文标题。

- 章节身份：在线阅读器的 66 个目录项，与冻结的 66 个可选章节一一对应；PDF 的 66 个书签标题也各匹配一次。
- 抽查页面：版权页、作者简介/照片、两个有重复器物图的章节、中部长章的注释处、后记。真实截图仅保留在个人机器的 .local 下。
- 在线原图：作者照片及两处器物图，从个人授权阅读器重读原图，3/3 字节 SHA 和解码后像素与已缓存来源图片一致；不代表已查出版社全套图版。
- 注释表现：在线原阅读器有橙色注释标记，PDF 中保留注释文字，但变成正文中的文本；弹窗、脚注位置和动态交互尚未证实一致。

## 第二层合成标题根因

v3 已识别 19 处“普通生成 H1 与原书 H1 相邻/版权页特殊包裹”问题。本轮原阅读器逐章对照发现另外 47 处：

- 第一节点为固定导出器加上的无属性 H1；紧接来源原有的 H2 class=secondTitle，且两个可见标题与冻结目录完全一致。
- 修复只删除第一个来源可证明的合成 H1；绝不删除原书 H2、正文或插图。
- v4 独立匹配要求原书 H2 具有 secondTitle 类和非空 id，且两者与目录标题在 HTML 实体/空白规范化后完全一致。任一条件缺失、标题不等或中间有正文都拒绝修改。
- 新版作为独立 v4 候选版，保留原版、v2、v3，不覆盖旧文件。

## 可复用的本地命令

在授权 Windows 电脑仓库根目录执行：

~~~powershell
python -m tools.heading_fidelity --book-dir ".local/library/<reader-id>" --output-version v4-headings
python -m tools.heading_fidelity --book-dir ".local/library/<reader-id>" --output-version v4-headings --build-versioned
python -m tools.cached_source_parity --book-dir ".local/library/<reader-id>" --compiled ".local/library/<reader-id>/final/v4-headings/book.epub" --heading-policy v4 --output ".local/v4-source-parity.json"
ebook-convert ".local/library/<reader-id>/final/v4-headings/book.epub" ".local/library/<reader-id>/final/v4-headings/book.pdf" --paper-size a4
~~~

先做只读审计和冻结来源校验，再显式构建。PDF 统一使用 A4，避免不同纸张尺寸造成虚假的页数差异。

## 真实个人案例结果

- v4 从冻结原始 EPUB 仅删除了 66 处来源可证明的合成 H1；相对 v3，只有 47 个章节 XHTML 成员发生变化，其余 ZIP 内容一致。
- 66/66 章正文归一化一致；11/11 实际图片引用与 alt 完整一致；70/70 图片资源 SHA 多重集合不变；issue_count=0。
- PDF v3 为 228 页，v4 为 219 页；219/219 均可检索，66/66 章 PDF 标题都只出现一次，11 个含图片页、2 种内嵌图片对象保留，0 替代乱码和文字越界。
- 本地合成测试增加 H1/H2 正例、防误删反例和版本策略检查；GitHub CI 由 PR 审核流程独立验证。

## 仍待人工判断的边界

- 浏览器是可变宽、可切换主题和字体的动态版面，PDF 不应被要求与网页逐像素一致。
- 图片的原始字节相同不代表图片显示尺寸、位置、裁切一定完全一样。
- 原网页橙色动态注释标记与 PDF 文字注释之间存在样式差异；尚未验证动态注释弹窗和原文位置，不报告注释全面视觉通过。
- 能打开并截图特定章节，不意味着全书逐页视觉验收通过。
- 只有用户明确签收阅读体验，才考虑 HUMAN_VISUAL_FIDELITY_PENDING 的升级；此前 FULL_BOOK_CONFIRMED=false。

## 私有档案与可复用工程

公开 GitHub 只保留严格转换规则、合成测试、使用方法和匿名统计。实际书籍、截图、完整图像、账号凭证、私人文件哈希和个人阅读记录只放在个人授权电脑或 owner-only 私人云盘，不写入公开仓库。
