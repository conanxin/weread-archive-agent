# P5-C｜五本跨书籍导出复盘与第六本准入清单

更新：2026-10-17。公开仓库仅保留匿名方法、合成测试与工程经验。真实书名、正文、图片、reader ID、个人云端链接、账号和私人哈希只在受控个人存储中。

## 五本跨书测试的可证结论

| 样本 | 有效章节/条目 | 典型实测失败类型 | 已验证的修复边界 |
| --- | ---: | --- | --- |
| A | 22 | EPUB个别后部章节只返回装饰而非实质正文；CSS装饰图虚警；Windows SQLite清理失败 | 已授权TXT备选通道、逐章短文门禁；区分CSS与XHTML正文图片；显式close连接 |
| B | 66 | H1/H2生成标题重复；正文注释与弹窗锚点 | 根据来源逐章精确清理生成H1；对应文本/图片/注释全量对账 |
| C | 602 | 11幅地图存在于资源包但未被正文引用；后记假完整 | 检查引用关系而非只看资源数；章节级局部恢复，不强制整书重抓 |
| D | 146 | 新H2类名带id、长耗时PDF、Drive错父目录、小TXT下载入口非200 | 独立v5标题策略；等待真实转换子进程；云端实际ID/parent/ACL/完整SHA门禁 |
| E | 74 | 新H2类名不带id、版权信息平台估字数偏差、Drive错父目录及大ZIP确认页 | 独立v6来源标题策略；TXT来源核对估字例外；实际ID搬移、全文件下载SHA及ZIP CRC |

本表的章节数是各自**冻结来源目录中有效条目数**，不是统一平台「字数」。对齐范围仅为授权冻结本地章节来源、EPUB等构建结果及私人交付证据；不等于出版社底本逐字校对。

第五本E实际通过：74/74来源章节归一化正文、297/297正文图片引用及alt、298/298 manifest图片条目多重哈希；A4 PDF 627页/74书签/所有627页可检索；10/10私人云端完整下载字节SHA门禁。独立v6的 H2.secondTitle-1（无id）修复在 [PR #39](https://github.com/conanxin/weread-archive-agent/pull/39)，106/106合成测试通过。没有修改A—D历史成品。

## 为什么不能定义「导出成功」为一个布尔值

| Gate | 观察对象 | PASS的最低证据 | 不能推断 |
| --- | --- | --- | --- |
| G0 身份/环境 | 用户指定的当前阅读页与本机doctor | 实际URL及账号授权环境可用 | 章节真实完整 |
| G1 目录/队列 | catalog、UID、chapter order、SQLite | 冻结目录SHA，建立独立队列 | 只导了封面也算整书 |
| G2 实质小样 | 首中尾，长文/插图/注释 | 原正文非空且图片引用可追溯 | 小样通过便代表全章 |
| G3/G3.5 有界采集 | 每章源文件、局部SHA、TXT后备 | 全部chapter COMPLETE，疑似短章/大图未引用警示逐一分类 | 以平台估字强行补写真实文本 |
| G4 来源保真 | 真实XHTML标题、正文、alt、图片hash、内联注释 | 全部章节来源对账，无未解释的正文图片缺失 | 将v4/v5/v6无条件应用于新书 |
| G5 阅读文件 | EPUB/MD/TXT/PDF | 目录/书签、A4页数、可检索、图片、缺字乱码/越界检测及视觉抽样 | 缩略图12页通过等于全书肉眼校勘 |
| G6 私人交付 | 真实云端对象 | allowlist + 实际ID + 正确parent + owner-only ACL + 完整独立下载SHA/必要ZIP CRC + generic verifier PASS | 浏览器toast或文件名出现即成功 |
| G7 阅读者签收 | 真人在实际阅读器的体验和来源抽核 | 手动核查记录与明确签收 | 机器QA/云端PASS能代替 |

最终状态只可逐项记为 `G0_G6_PASS`、`G7_HUMAN_READING_SIGNOFF_PENDING` 和 `FULL_BOOK_CONFIRMED=false`，不得默默提升状态。

## 第五本新增五条经验

1. **H2无id不意味着噪声。** 来源真实H2.secondTitle-1无id，邻接导出器插入的无属性H1，且两节点和冻结目录标题完全相同，才允许在显式v6候选里移除合成H1。只删除生成节点，不重写来源正文或v2—v5。
2. **平台estimated wordCount是线索，不是逐字标准。** 版权信息平台估字较高，但已授权TXT与EPUB可见正文高度一致；分类为证据支持的估值口径差异，而不是编造丢失正文或放松整书所有短章门禁。
3. **图片至少核四类分母。** XHTML真正引用数、EPUB manifest资源数、不同内容SHA数、PDF页内图像对象数可能不等。只有全部相关引用逐章字节与alt对账通过才宣布图片保真。
4. **Drive错误可能发生在上传之后。** 即使UI显示当前子目录和完成toast，PDF/TXT也可能落到root。应精确定位云端对象ID、确认实际parent、移动同一ID并重新验证权限与完整下载SHA；不因UI消息重复上传。
5. **大ZIP下载确认页≠ZIP损坏。** 若返回Google安全确认HTML，应通过授权客户端在允许的Google域名流程完成实际下载，再检查完整大小、SHA及ZIP CRC。错误HTML不能作为成功云端哈希。

现有 [Issue #28](https://github.com/conanxin/weread-archive-agent/issues/28) 已包含相关复发证据，不重复创建每书专用issue或新的私人交付验证器。 `tools.private_release_manifest` 与 `tools.private_release_verify` 的本地证据来自真正云端回读，严禁把本地source hash伪装为云端下载hash。

## 第六本执行前的唯一外部输入

**必须由用户明确提供第六本真实 `https://weread.qq.com/web/reader/...` 页面。** 无此URL时只保持 `SIXTH_READER_URL_REQUIRED`，不读取任何旧书作为第六本，不猜reader ID，也不因自动化而从书架随机选书。

收到URL后执行以下最小流程：

1. Windows授权环境 `wereadlab.py doctor --json`；读取并冻结本书catalog + UID/order + SQLite队列（**新书独立目录**）。
2. `--limit 1` 验证，再抽首/中/末有实质文字和图片的章节；合格后有界串行批次最多4章，失败停下而非跳过，保留partial/SHA。
3. 每批运行 `preassembly_risk_audit`；风险优先本书局部检查TXT后备和真实图像引用，明确记录受证据支持的异常例外。
4. 只有全章COMPLETE时合并原始EPUB；**根据本书XHTML证据**选用v2—v6或受控新策略，保留独立候选，执行`cached_source_parity`和适用的`note_fidelity`（注释默认全文内联）。
5. 生成PDF/MD/TXT、真正图片ZIP，等待Calibre结束，实际检查书签、可检索页面、乱码/溢出和首中尾/图像密集版式。
6. 新建本书私人owner-only文件夹，按真实allowlist交付；实际文件ID、父目录、owner ACL、云端下载完整SHA通过既有generic gate才宣布`PRIVATE_DELIVERY_PASS`。
7. 提供人工G7抽读清单，但仅有用户明确签收后才可写`FULL_BOOK_CONFIRMED=true`。

如果遇到授权过期、验证码、访问权限异常或实质正文无法核对，应停在准确门禁并请求人工处理；不要把任务成功和内容成功混同。五本已通过的旧成品及冻结来源无需重新抓取或覆盖。

## 交接状态

`FIVE_BOOKS_TECHNICALLY_DELIVERED / FIFTH_G7_PENDING / SIXTH_READER_URL_REQUIRED`

详细历史方案在 [P4-H四本复盘](P4H_FOUR_BOOK_POSTMORTEM_FIFTH_PLAYBOOK.md)、[P5-B v6标题规则](P5B_SECOND_TITLE_DASH_ONE_H2.md)。本页不包含任何私人文件或来源URL。
