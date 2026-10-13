# WeRead Archive Agent

面向个人学习、检索与归档的 **微信读书本地电子书导出工作流**。把现有开源的章节提取实现封装为稳定的 CLI，供 Windows 双击运行，也可由 Hermes / OpenClaw 调用。这个仓库开源的是**任务编排、格式转换、校验和 Agent 接口**；不会提交微信登录凭证、个人书库内容或提取引擎的第三方源码。

> 当前版本 **v0.1.0（P0 可运行原型）**，尚未在维护者的真实微信读书账号上完成整书验收。状态 `FILES_READY_COMPLETENESS_UNVERIFIED` 仅证明输出文件通过结构检查，**不证明正文没有缺页或漏章**。

## 为什么采用这个结构

- 优先调用 [finlater/weread.koplugin](https://github.com/finlater/weread.koplugin) 独立 Python EPUB 提取脚本（AGPL-3.0 项目，不复制其源码）。其作者曾验证过 134 章及 282 张插图的 EPUB 导出实例。
- 以后追加 [lbq110/weread-exporter](https://github.com/lbq110/weread-exporter) Canvas 适配器作为独立替代。网页端不可读的书籍无法保证提取；不处理人机验证规避。
- Agent 只传书籍 URL、格式和目标目录；浏览器登录留在本地，命令不接受会话令牌字符串，也不把 Cookie 上传到云端。

## 立即使用（Windows 11）

环境：Python 3.10+、Git。生成 PDF 另需 [Calibre](https://calibre-ebook.com/)；Markdown 和 TXT 使用项目内置转换器，**无需 Pandoc**。

**方法 A：双击 `start.cmd`**，首次弹出浏览器扫码登录，随后粘贴微信读书网页版阅读地址。首次登录时会按需安装 Playwright / Chromium，安装过程需要网络连接和可交互的 Windows 桌面。

**方法 B：命令行 / Agent**：

```powershell
python wereadlab.py doctor --json
python wereadlab.py login
python wereadlab.py export "https://weread.qq.com/web/reader/实际阅读器ID" --sample 2 --format epub --format md --json
python wereadlab.py export "https://weread.qq.com/web/reader/实际阅读器ID" --full --format epub --format pdf --format md --format txt --json
python wereadlab.py status --json
```

- `login` 首次安装 Python Playwright（需要联网）并打开本地浏览器供本人扫码；未装 Chromium 时依提示安装一次。**无人值守 Agent 不应尝试自动扫码。**
- `export` 首次自动浅克隆上游仓库至 `.local/upstream/`。上游不在每次运行时自动更新，保持版本可复现。需要更新时执行 `python wereadlab.py upstream --update`。
- 默认执行 **2 章试导出**；传 `--full` 才取当前账号实际可读的整书章节。
- 默认若 EPUB 已存在会直接复用，避免重复请求。需要重试传 `--force`。
- 可用 `--expected-chapters N` 指定经过人工核对的**应有章节数**；结构检查不满足时不进行下一步转换。
- 用 `--output-dir D:\Books\SomeBook` 指定输出目录；否则使用 `.local/library/<reader-id>/`。
- 支持 `--format epub|pdf|md|txt`（可以重复使用）。缺少 Calibre 时仍保留 EPUB 和 Markdown，状态为 `FORMAT_PARTIAL`。

## 导出结果

```text
.local/
  session/                   # 本地浏览器资料及 Cookie（git 忽略）
  upstream/                  # 运行时取得的第三方引擎（git 忽略）
  library/reader-id/
    sample-2.epub
    sample-2.report.json
    sample-2.log
    sample-2/fulltext.md
    sample-2/images/*.jpg
    full.epub
    full.pdf
    full.report.json
    full/fulltext.md
    full/fulltext.txt
```

`*.report.json` 中包括上游 Commit SHA、书籍 URL、EPUB 章节/图片结构、输出格式及状态。默认不上传任何个人内容。`STRUCTURE_PASS_COMPLETENESS_UNVERIFIED` 意味着 ZIP/目录/本地图片引用符合检查要求，但**仍须对照原书目录核验首、中、末章节**。

## 自动化约束

通过 `AGENTS.md` 描述 Hermes、OpenClaw 的 JSON CLI 调用方式。Agent 可自动检测依赖、排队、调用已保存本地会话、转格式、检查、同步 NAS；碰到 `LOGIN_REQUIRED`、`WEB_UNAVAILABLE`、`ACCESS_RESTRICTED` 或 `MANUAL_VERIFICATION_REQUIRED` 时应停止并通知用户，不尝试自动规避验证或扩大权限。

## 开发

```powershell
python -m unittest discover -s tests -v
python wereadlab.py doctor --json
```

测试只使用**合成 EPUB**，不调用微信读书，不需要账号或网络。持续更新计划见 [`docs/ROADMAP.md`](docs/ROADMAP.md)，研究依据见 [`docs/RESEARCH_LOG.md`](docs/RESEARCH_LOG.md)。

### 软件边界

此仓库的编排实现为 MIT。可选上游提取引擎为独立项目，按其各自许可证发布；当前不复制或再分发 AGPL 上游源码。请只处理自己有权限访问的阅读内容，避免把个人书籍文件、Cookie、登录日志提交到公开仓库。