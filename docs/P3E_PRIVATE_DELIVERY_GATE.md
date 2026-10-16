# P3-E｜私有云盘交付状态机（第一阶段：离线验收）

此阶段将第二本《燕辽古道与部族方国研究》的真实交付经验提炼为**不触碰登录凭证的离线文件验收工具**。

## 背景与边界

- 已验证的个人案例：第二本已生成 66 章完整 EPUB/PDF、18 处重复合成 H1 排版修复版本；七份云端成品均仅所有者可见，并从 Google Drive 再次下载，**7/7 完整 SHA-256 与家中 Windows 文件一致**。
- 文件上传最初落在非预期目录、出现异步同名确认弹窗，不能用网页提示或文件名搜索推断“上传成功”。
- 本次只做两种**本地且确定性**动作：列出允许发布的文件和本地 SHA；读取外部可信 Drive 连接器提供的元数据与下载后 SHA，判定是否完成。**不实现网络上传、云端目录移动、凭证读取或用户权限变更。** 仍见 [Issue #28](https://github.com/conanxin/weread-archive-agent/issues/28)。

## 用法（在本机项目目录）

创建独立的私有文件清单：

```powershell
python -m tools.private_release_manifest `
  --directory ".local/p3e-staged" `
  --files "book.epub" "book.pdf" "qa.json" `
  --target-folder-id "<your-private-drive-folder-id>" `
  --output ".local/private_release_manifest.json"
```

外部连接器把实际云端返回值写入私有 `.local/private_drive_observation.json`，需要包含：

```json
{
  "folder": {"id": "fake-folder-123", "shared": false,
             "permissions": [{"type": "user", "role": "owner"}]},
  "files": [
    {"name": "synthetic.epub", "id": "fake-cloud-id",
     "bytes": 123, "parent_ids": ["fake-folder-123"],
     "shared": false, "permissions": [{"type": "user", "role": "owner"}],
     "downloaded_sha256": "<SHA256 computed from cloud-downloaded bytes>"}
  ]
}
```

**示例均是合成字段，不是可使用的真实账号/书籍 ID。** 下载云端原文件并计算 SHA256 必须由可信的远端数据访问操作完成；仅返回文件 ID 或大小不足以判断 `DELIVERED`。

```powershell
python -m tools.private_release_verify `
  --manifest ".local/private_release_manifest.json" `
  --observed ".local/private_drive_observation.json" `
  --output ".local/private_release_receipt.json"
```

校验可能输出 `PRIVATE_DELIVERY_PASS`、`PRIVATE_DELIVERY_INCOMPLETE`；差异类别包括 `WRONG_CLOUD_PARENT`、`CLOUD_BYTE_COUNT_MISMATCH`、`CLOUD_HASH_NOT_PROVEN`、`OWNER_ONLY_NOT_PROVEN`、`AMBIGUOUS_SAME_NAME`。任何失败均返回非零退出码；重复执行同样内容幂等，不覆盖不一致的旧回执。

## 质量规则

1. `STAGED` 仅表示指定本地文件存在，类型允许，内容哈希已冻结；不是云端成功。
2. `PRIVATE_DELIVERY_PASS` 只在每个文件的真实 ID、目标父目录、文件名、字节数、owner-only ACL 与云端下载 SHA256 全匹配才出现。
3. 旧版和 v2 单独保存，不以合成文件名覆盖真实上传结果；遇同名多个云端 ID 必须停止人工核对。
4. 公开 GitHub 不保存实际目录 ID、原书/图片、Cookie、真实 SHA、私人共享链接。
5. 后续真正的私有云盘上传适配器独立开发并在授权环境验证，需支持任务断点、真实 ID 调和和明确的用户允许范围。

## 阶段验收

- 合成测试涵盖：同名多份、上传至根目录、大小不同、缺少下载哈希、权限变成公开、完成后重跑、路径穿越、已修改的本地文件。
- Windows / Linux GitHub CI 应双平台 PASS。
- **不称此模块已实现自动 Google Drive 上传。** 它是交付流程的安全判定核心，为 Hermes/OpenClaw Agent 后续集成预留可靠 JSON 接口。
