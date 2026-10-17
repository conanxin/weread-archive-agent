# P8-C｜Google Drive 合成文件真实云端闭环与本地 OAuth 启用

本阶段必须区分两种验证：
- **连接器实测完成**：使用已授权的ChatGPT Google Drive连接器，对91字节纯合成文本真实上传、云端全字节SHA-256及同ID错目录移动进行校验。
- **本地Python适配器未实测完成**：本机没有Google REST API OAuth token、ADC、gcloud或rclone。过去的离线合成测试并不能证明新Python模块已能向真实云端写文件。

## 1. 已通过的连接器实测

通过已连接的Google Drive，在独立私人测试文件夹中创建合成来源：四行不含个人信息的TXT。原生Google Doc导出完整91字节TXT后，以文件引用通过upload_file明确指定目标 parent_folder_id 上传。

- 云端实际文件ID、指定单一父目录、91字节文件大小、shared=false、唯一owner权限均通过真实Google元数据查询。
- 实际云端完整回下载文件与本地来源逐字节一致，SHA-256为82929997e57c419cdfed4d8443aa364c6516bf3bbc5cca5e2d6a7f6196a3c288。
- 将该**合成**文件以同一file ID移至My Drive根目录，再移回目标私人子目录：ID未变、大小和权限未变。

这是Google Drive连接器接口的真实闭环，**不是本地Python新适配器的真实OAuth验证**。测试完成后可以删除临时合成文件与文件夹，不碰前七本书。

## 2. 新增本地OAuth helper

tools/drive_oauth_bootstrap.py 使用本人自己的Google Cloud Desktop OAuth客户端JSON。默认没有交互，只有显式传 --authorize 才在本机127.0.0.1临时回调开启浏览器申请用户本人同意。认证结果作为可刷新缓存留在被gitignore的.local，不会打印token内容；缓存到期且存在refresh token时自动刷新，否则明确失败。

tools/drive_upload_adapter.py继续优先接受本地GOOGLE_DRIVE_ACCESS_TOKEN环境变量。未设置时可以读取 --oauth-token-cache；首次可传 --oauth-client-json 和 --authorize。默认仍只展示计划，必须显式 --execute 才对云端创建或移动文件。上传元数据通过后依然要执行独立云端下载SHA+ZIP CRC，并调用原有 private_release_verify 取得唯一G6最终成功状态。

## 3. 用户仅需完成一次的准备

1. 打开自己的Google Cloud Console，选择个人项目并启用Google Drive API。
2. 在Google Auth Platform的Branding/Audience页面配置OAuth同意页，Testing应用需将自己的Google账号添加为测试用户。在Clients创建Desktop app OAuth客户端并下载JSON到本机项目私有的.local目录。必须是JSON顶层含installed的桌面类型。
3. 在自己的Windows浏览器中完成首次OAuth同意。由于需要访问本人此前通过浏览器上传的已有文件，工具申请完整Google Drive scope（https://www.googleapis.com/auth/drive）。这不是第三方共享授权，也不会在聊天传递凭证。Google如显示尚未验证应用，由本人确认后才能继续。

~~~powershell
cd D:\CodexData\weread-archive-agent
python -m pip install google-auth-oauthlib
# 自己下载的Desktop OAuth JSON保存为：
# .local\google_drive_desktop_client.json
python -m tools.drive_oauth_bootstrap --client-json '.local\google_drive_desktop_client.json' --authorize
~~~

授权成功后私有缓存默认保存在.local\google_drive_oauth_user.json。该步骤本身不会上传图书。

## 4. 本地Python模块的正式在线验收（仍待授权）

获得OAuth后，用小型合成文本先生成private_release_manifest。执行下面的计划/实施两个步骤：

~~~powershell
python -m tools.drive_upload_adapter --manifest '.local\p8c_synthetic_manifest.json' --receipt '.local\p8c_placement_plan.json'
python -m tools.drive_upload_adapter --manifest '.local\p8c_synthetic_manifest.json' --receipt '.local\p8c_placement_executed.json' --execute
~~~

然后基于实际Google Drive对象ID、父目录、唯一owner ACL、大小、完整云端独立下载SHA，运行既有private_release_verify。此项只有完成后才能标记本地适配器 LIVE_PASS。目前仍为 LOCAL_ADAPTER_LIVE_PENDING_OAUTH。

## 5. 测试与后续边界

新增纯合成测试覆盖：缺少用户批准必须拒绝、缓存使用、过期token刷新、撤销刷新、scope不匹配停止、desktop client JSON格式、首次交互式授权缓存写入。不使用真实账号或图书。

真实连接器实测与Python适配器首次OAuth验证必须分开留证。七本已交付文件、对应Notion技术验收以及G7人工阅读签收状态均保持原样。后续可继续研究长时间上传时的token更新与真正断点续传。


## 6. 推荐的一条命令真实测试（完成OAuth准备后）

无需手动创建manifest或私有测试文件，直接运行本次新增的合成真实云端验证入口：

~~~powershell
cd D:\CodexData\weread-archive-agent
python -m tools.drive_live_smoke --oauth-client-json '.local\google_drive_desktop_client.json' --authorize
~~~

该命令使用本机已批准的OAuth（首次带 --authorize 才请求本人许可），按以下顺序执行：
创建随机命名的临时私人Drive文件夹 → 冻结合成TXT原始SHA → 默认计划模式确认拟创建 → 通过本地P8-A上传适配器请求真实Google Drive上传且指定parent → 第二次运行适配器确认复用原ID → 将同一文件ID移动到Drive根目录 → 再经适配器把同一ID恢复到测试文件夹 → 独立Drive API下载全部字节计算SHA-256 → 交给现有private_release_verify总验收 → 清理临时合成文件及文件夹。

只有所有条件都通过且清理成功，才输出 P8C_LOCAL_ADAPTER_REAL_API_PASS。若中途网络/API/权限失败，程序应失败且不得冒称成功；隐私与授权信息不会打印。私人执行回执保留在 .local\p8c_google_drive_rest_live_smoke.json；不要提交这个文件。

此命令**尚未执行真实REST云端测试**，因为本地仍缺用户自己的Desktop OAuth client JSON。GitHub CI测试中模拟整条流程，不会登录任何Google账号。
