# P6-G｜六本跨书导出复盘与第七本执行手册

更新：2026-10-17。第六本是**摄影图版密集型样本 F**，公开资料仅记录统计、故障类型、程序验证方法。原始书名、reader URL/ID、正文、图像、caption、私人云端URL/ID、文件hash、登录Cookie和具体个人凭据均只留在未提交的个人证据空间。

## 1. 第六本样本 F 的可核实技术结果

| 维度 | 技术结果 | 不可推断 |
| --- | --- | --- |
| 目录与采集 | 18项目录剔除封面后17个有效章；17/17工作队列COMPLETE，0 FAILED | 全章在出版社底本逐字校对完成 |
| 来源可追溯 | 17/17章节正文与冻结授权章来源一致，改正13处有证据的导出器额外H1 | 自动改名/删除任意源H1/H2都是安全的 |
| 摄影图像 | 328正文图片引用、638打包图像资源、多重集合 SHA 一致、321个不同内容SHA | `328 == 638 == 321`，不同分母无需相等 |
| Markdown附图 | 328图片引用对应322个路径/文件，322/322与原EPUB图像字节一致 | 每一次引用都必须保存重复的物理文件 |
| 阅读PDF | 511页A4，17书签标题一致，502页可检索，293页含图，321不同PDF图片对象，0完全空白/替代字符/正文越界 | 12页抽样即等于511页逐页人眼校勘 |
| 私人云交付 | 10/10真实云端对象、ID、parent、独占owner ACL、size、完整云端下载SHA256；ZIP另CRC；通用验收`PRIVATE_DELIVERY_PASS` | 仅浏览器显示文件名或toast就算交付 |

**严格状态**：`G0_G6_PASS / PRIVATE_DELIVERY_PASS_10_OF_10 / G7_HUMAN_READING_SIGNOFF_PENDING / FULL_BOOK_CONFIRMED=false`。

## 2. 新风险与对应工程教训

### 2.1 版权页内容不足 + 来源摄影图丢引用

- 初次来源单章 EPUB 仅约145可见字符，TXT来源约500可见字符；第1章XHTML内没有照片引用，尽管源EPUB包含5张大型真实照片。不能以平台字数或manifest有图判断正文完整。
- 按**同一章在线阅读截图 + 授权TXT文字 + 5张原始图片 + 图注身份/顺序**重建了独立text/image hybrid candidate，5/5来源照片字节SHA相同，原始EPUB和TXT候选都保留。
- 不照搬前一本“平台字数估算偏差即可例外”的分类：此处EPUB与TXT内容确实不同，必须先做实质恢复；恢复后仍把平台估字视为告警，不用估值去填补虚构正文。

### 2.2 图片资源存在但正文不引用；一次远端照片下载不全

- 分篇章节源照片在原阅读器能看见、ZIP中亦有文件，但XHTML正文没有相关引用。单靠文件数会漏图。
- 发生一次`IMAGE_ASSETS_INCOMPLETE`：采用单章有限重试修复远程资源，保留`.partial.epub`，再用来源hash精确插入一幅真实摄影图并保留历史版。
- 另有一次`UPSTREAM_ERROR`与两处TXT fallback（本样本的第8、17有效条目）。边界是**原子章节checkpoint + 单章定位恢复**，不重新采集已经COMPLETE的章；任何失败不可默认跳过。

### 2.3 13个生成H1与真实H1相邻重复

- 本书真实章节源头是有class与id的H1，普通导出器额外插入同名、无属性的H1。第六本不需要第五本H2.secondTitle-1规则。
- 本样本确证13章生成H1重复；使用**最小适用v2**规则另存候选，仅移除经目录同名与相邻原节点证明的生成H1。
- `cached_source_parity`对修订版17/17章文字和328/328图片引用及alt、638/638资源hash逐项比较，issue_count=0，仍留原始完整EPUB不覆盖。

### 2.4 15次缺失CSS背景图引用并非正文摄影漏图

- 静态源码中15个背景图引用去重只有一个resource，全部属于**当前章节XHTML未使用的简单CSS class**，与源正文图像引用缺失分开。
- CSS UNUSED并不严格证明在线视觉毫无影响；它只是经审计的低风险装饰例外，需要靠最终PDF视觉抽样验证版式。

### 2.5 近GB大文件上传：登录失效、超时与落错目录

- 私人交付清单有10份，总量约1.7GB。图片ZIP需长时上传；PDF首次上传器抛出`Locator.inner_text TimeoutError`，本地浏览器的旧登录Cookie此后把文件/目录访问重定向到Google账号登录页。
- Google连接器元数据仍可查，并不等于本地Playwright上传/下载会话仍有效。**登录态先实测Drive host与可用上传入口**，不能只以Cookie数、浏览器曾登入或connector访问成功为准。
- 用户重新授权本地浏览器后续传仅缺失文件；PDF虽从目录页上传却实际进入云端root。通过真实ID移动**原对象**到正确parent，再验`shared=false`、唯一owner、size、云端全下载SHA，无需重复上传。
- 大于连接器256MiB直取上限的图片ZIP先遭到登录页重定向，而非Google安全扫描表单；恢复授权后用**单文件流式**下载完整云端字节计算SHA256与ZIP CRC，PDF、EPUB同样做实际云端下载SHA。
- `LOGIN_REDIRECT`、`GOOGLE_CONFIRM_FORM`、`HTTP_RETRYABLE`、`SUCCESS_BINARY`必须分开处理。**HTML响应、只看文件字节数、Drive文件在列表里、或者本地SHA均不能冒充独立云端SHA证明**。

## 3. G0–G7标准工作流（七本及后续）

| Gate | 最小动作 | 通过证据 |
| --- | --- | --- |
| G0 | 本地doctor + 用户明确给出新reader URL | 登录/运行环境READY，确切书籍身份 |
| G1 | catalog冻结/章节UID及顺序SHA；每书独立SQLite | 目录与选章一致，封面单独排除 |
| G2 | 首中尾+版权页/分篇/长章/摄影密集章小样 | 原文实质非空，普通EPUB与授权TXT必要时核对 |
| G3 | 每批≤4章，限速、原始源checkpoint、异常停机、单章恢复 | 所有有效章COMPLETE，失败0，每批preassembly风险归类 |
| G4 | 来源XHTML标题画像，按证据选v2—v6或另开隔离候选；来源完整对账 | 正文、图片src/alt、manifest原图SHA一致、未解释风险为0 |
| G5 | EPUB+Markdown/TXT+原图ZIP+A4 PDF，实际完成转换 | TOC、索引、图注、可检索、乱码/越界/空页、抽样视觉QA |
| G6 | owner-only父目录 + allowlist；传前验Auth；云端ID/parent/ACL/size；实际下载所有字节SHA；ZIP CRC | **现有通用**`tools.private_release_verify`返回PRIVATE_DELIVERY_PASS |
| G7 | 实际阅读器中的人工来源视觉对照与明确签收 | 人工记录与用户确认；未签则`FULL_BOOK_CONFIRMED=false` |

不同图片数量必须分别计算：`BODY_IMAGE_REFS`（XHTML引用次数）、`MANIFEST_IMAGE_ENTRIES`（打包项）、`IMAGE_UNIQUE_SHA`（内容）、`MARKDOWN_IMAGE_FILES`（导出路径）、`PDF_IMAGE_OBJECTS`（嵌入对象）和`PDF_IMAGE_PAGES`（含图页数）。任何等号都需证明，不能从数字不同推断漏图。

## 4. 针对第七本的最小入口（无需重验已交付六本）

仅接受用户新提供、确实指向**第七本**的微信读书网页版reader URL；不得猜书架或继承第六本reader ID。Windows已授权环境下：

```powershell
python wereadlab.py doctor --json
python wereadlab.py catalog '<NEW_BOOK_READER_URL>' --json
python wereadlab.py queue init --catalog '<NEW_BOOK_CATALOG_JSON>' --json
python wereadlab.py queue run --db '<NEW_BOOK_SQLITE>' --limit 1 --json
python -m tools.preassembly_risk_audit --book-dir '<NEW_BOOK_DIRECTORY>' --output '<PRIVATE_RISK_JSON>'
```

确认首中尾小样后才做每批≤4章节继续；全部章完成后按书本真实结构另存标题候选、来源对账、制多格式及私人完整交付。若图/注/权限/验证码出现无法证明的异常，停在相应门禁，勿标全书通过。

## 5. 下次工程改进优先级（当前只是建议，尚未实现）

**P0 上传传输适配器（沿用现有单一校验器）：** 先查实际云端文件ID和正确parent以免重复；可用时通过provider API直接指定parent而非只靠UI当前目录；每一大文件有可续传/可确认状态；本地Auth可用性检测；出错应产出可重用receipt而非扔弃进度。

**P0 下载认证与大文件校验：** 登录重定向必须与Google大文件确认HTML区分；在允许Google域名流程中以本机授权会话流式下载SHA/ZIP CRC；断网或429只做有界重试，日志不包含cookie/下载token；成功最终仍调现有`private_release_manifest`、`private_release_verify`。

**P1 正文+原摄影图hybrid模板：** 基于来源图注锚点恢复图片，采用SHA逐图精确复制，不按文件排序臆造插图位置，TXT与EPUB原本均留证。

**P2 G7人工验收工作单：** 自动给出封面/版权/摄影最多/长章/含注释/参考文献样本和手工签收入口，记录章/页/图编号及阅读器，不因G6成功自动签收。

参照已合并的[前五本P5-C手册](P5C_FIVE_BOOK_RETROSPECTIVE_SIXTH_PLAYBOOK.md)、[上传错目录和云端校验跟踪Issue #28](https://github.com/conanxin/weread-archive-agent/issues/28)。此文档不修改原六本已冻结资料或代码，也不声称工程改进提案已经实现。