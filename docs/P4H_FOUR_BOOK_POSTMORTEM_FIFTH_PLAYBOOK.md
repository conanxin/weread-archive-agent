# P4-H｜四本电子书导出复盘与第五本标准流程

日期：2026-10-17。仅供个人已授权阅读归档使用。公共 GitHub 只保存匿名技术方法和合成测试；真实书籍正文、图像、reader ID、账号 Cookie、云盘文件和 SHA 留在私有 .local/Notion/Drive。

## 四本工程案例（技术交付已通过；人工整书签收另计）

| 案例 | 有效条目 | 真正出现的缺陷 | 可复用的修复证据 |
| --- | ---: | --- | --- |
| A | 22 | 中后段 EPUB 缺字、Markdown head 污染、CSS 假缺图、重复 H1 | TXT 后备、body-only、装饰资源分类、来源证明去掉12处生成H1；独立263页PDF候选 |
| B | 66 | H1/H1、版权页wrapper、H1/H2 secondTitle 复合标题、网页弹窗注释 | 删除66处已证明合成H1；章节/图片来源 SHA 与193次内联注释验证；v4 PDF219页 |
| C | 602 | 11个路线图实际在资源包却未被正文引用，后记 EPUB 只有6字，Calibre长时间渲染，Drive上传错父目录 | 11个地图章节+后记共12处图文融合；589处生成H1去重；A4 PDF814页；9/9私有云端回读 |
| D | 146 | 原H2新类 txtheading-1-15、351张插图、120MB PDF、EPUB被上传至Drive根目录、TXT首次下载非200 | 独立v5去掉145处来源证明生成H1；351/351原图SHA；A4 PDF634页；10/10私有云端完整SHA |

所有通过结论的来源范围是用户已授权的冻结缓存、导出成品及真实私人云盘读回，不是出版社母版逐字校勘。12页或其他样本视觉对照不能替代整书阅读签收，FULL_BOOK_CONFIRMED 保留 false。

## 第四本新增的六项关键经验

1. **标题必须依照原书 XHTML 来源而非只根据是否重复。** 第四本特有的 H2 class=txtheading-1-15 带非空 ID，紧邻导出器添加的无属性 H1；两个标题必须与冻结 catalog 完全一致才能删除那个合成 H1。真实 H2、日期/城市标题、图像和正文不动。v5 标题规则独立显式启用，v2/v3/v4 完全不变。
2. **插图数量应报告不同分母。** 第四本有351次正文图片引用、351份manifest图片资源、351种唯一内容SHA、PDF有332页带图片及351个嵌入对象。资源存在不代表其被正文正确引用：第三本11张地图已证明这类风险，合并前必须运行 preassembly_risk_audit。
3. **前中后小样与整书来源对账不能互相替代。** 第四本前、中、后 EPUB/MD 小样正常，才按每批≤4章顺序采集到146/146，0失败；合并前146/146章节风险0，再做146/146正文和351/351图片来源SHA对账，0异常。
4. **PDF要等待真实Calibre子进程。** 远程shell返回不保证 ebook-convert.exe 已完成。第四本A4 PDF 634页，约120MB；必须确认实际进程退出、文件能打开、日志中PDF写出完成、目录146条、正文检索/嵌图/乱码/越界检查通过，不重复启动昂贵转换。
5. **Drive网页上传完成不等于放对位置或SHA相同。** 第四本10份文件最初实际只有9份位于目标目录，EPUB错在Drive根目录；通过准确文件ID移动回新书专属owner-only文件夹，并独立查10/10 ID、父目录、权限、大小、全字节SHA。9份首次下载正确，TXT旧下载接口返回非200，换用户内容下载地址重试完整字节成功，最终10/10。不能因为某一下载入口失败就直接判文件已损坏，更不能只看文件大小。
6. **注释呈现默认全文内联，但未出现特殊注释时不可编造通过数。** 用户明确选择注释直接放正文。第四本没有前两本那种 Images/note.png 标记，不应把第二、三本的193/15项注释数复制到新书。只有确实存在注释时才运行 note_fidelity 检查文字、锚点、PDF重复次数。

## 把临时脚本变成真正可复用的验收

已有通用工具 tools.private_release_manifest 与 tools.private_release_verify，**不再为第五本写另一套私人上传/交付门禁**。本轮把第四本10个真实云端对象的重新读取metadata、9份首次成功的实际下载哈希及TXT完整重试哈希交给 generic verifier，再次得到 PRIVATE_DELIVERY_PASS 10/10。它只读证据，不上传、不暴露账号，也不读取书籍正文。

以后每个新书发布前：先冻结allowlist manifest；上传后按真实ID重新读取parent、shared=false、唯一owner、大小，再从云端下载完整文件计算SHA256；组装observed JSON给通用verify执行。若传错父目录，只按精确ID移动，随后重新检查所有门禁。绝不以浏览器toast或同名文件数量推断成功。

### 关键命令

~~~powershell
python -m tools.private_release_manifest --directory "<private-stage-dir>" --files <allowlisted-filenames> --target-folder-id "<owner-only-folder-id>" --output ".local/fifth-manifest.json"
python -m tools.private_release_verify --manifest ".local/fifth-manifest.json" --observed ".local/fifth-cloud-observed.json" --output ".local/fifth-delivery-qa.json"
~~~

observed 文件必须来自**真正的云端元数据与完整下载SHA**，不能把本地文件hash直接伪装成云端hash。它们只保存在私有 .local。

## 第五本 G0—G7 主线

| 阶段 | 必须通过后才能继续 |
| --- | --- |
| G0 | 用户提供确切 https://weread.qq.com/web/reader/... 阅读页；Windows doctor=READY。无目标不猜书 |
| G1 | 真实 catalog 中确认书名、目录、章节UID和访问状态；建立本书独立catalog.json/chapters.sqlite，不用此前书的--latest |
| G2 | 前、中、后含实质正文、图片/注释代表小样；检查正文字符、资源引用、页面样式；不能仅导版权页 |
| G3 | 初始--limit 1，小样合格后每批≤4顺序续传；保存partial和单章SHA；遇登录、权限或疑似缺文立即停/局部恢复 |
| G3.5 | 在采集过程中执行 preassembly_risk_audit，检查很短的正文与未引用大图；风险须审阅，平台估字偏差本身不等于已证缺文 |
| G4 | 全部章COMPLETE、冻结来源SHA通过；按该书实际H1/H2严格标题规则生成独立候选；cached_source_parity及适用的note_fidelity全章通过 |
| G5 | 生成EPUB、MD/TXT、固定A4 PDF；等待真实Calibre结束，查书签、全文可搜索、实际图片、注释重复次数、乱码越界与代表性视觉 |
| G6 | 新书专属private Drive文件夹、allowlist manifest、真实文件ID/parent/owner-only ACL、完整重新下载SHA，经generic verifier为PRIVATE_DELIVERY_PASS |
| G7 | 提供私人文件链接，保留用户全书阅读签收为独立待办；不为阶段编号重复导出整书 |

示例（把真实URL和本书目录替换后，且由用户明确指定第五本目标才执行）：

~~~powershell
python wereadlab.py doctor --json
python wereadlab.py catalog "<fifth-reader-url>" --json
python wereadlab.py queue init --catalog "<fifth-book-dir>/catalog.json" --json
python wereadlab.py queue run --db "<fifth-book-dir>/chapters.sqlite" --limit 1 --json
python -m tools.preassembly_risk_audit --book-dir "<fifth-book-dir>" --output ".local/fifth-preassembly.json"
~~~

## 当前第五本的严格边界

截至本阶段，用户已要求复盘第四本并继续第五本，但没有明确给出**第五本书名或真实reader链接**。不能从前四本的reader ID、书架或推荐书单中猜测下一本，更不能抓取旧书冒充新书。仅完成文档、环境预检、用户Agent任务交接；获得确切reader URL后再执行G1目录及G2实质样本，然后自动有界续传。

状态：FOUR_BOOK_TECHNICAL_DELIVERY_PASS / FOURTH_GENERIC_DELIVERY_10_OF_10_PASS / FIFTH_BOOK_TARGET_REQUIRED / FIFTH_BOOK_CAPTURE_NOT_STARTED。
