# P8-A｜Google Drive 显式父目录上传适配器

这是第六、第七本个人私有交付反复出现的「浏览器看起来在子目录上传，实际上文件落在 Drive 根目录」问题的最小修复方向。纯合成测试不会上传任何图书。

## 已实现

- tools/drive_upload_adapter.py 使用官方 Google Drive v3 resumable upload，请求开始时在 metadata 中**直接给出 parents: [target_folder_id]**，不以浏览器 UI 的当前文件夹作为上传位置。
- 每个文件开始前，查找精确同名对象；同名多个、已有文件大小/MD5不同、非owner-only或多父目录，则立即停止，不凭名称冒险覆盖。
- 只有确切无同名对象时才新上传；已存在正确文件直接复用；在错误父目录但大小/MD5一致且owner-only的文件则**移动原文件 ID**，而非重传。
- 操作后再次获取真实云端元数据，验证 ID、name、parent、size、md5Checksum、shared及permissions。
- 默认计划模式不会写云端；显式提供 --execute 才允许创建/移动。UPLOAD_PLACEMENT_VERIFIED **仅证明云端放置位置与MD5等元数据**，不代表PRIVATE_DELIVERY_PASS。
- 每本交付仍须独立下载云端全部字节并验证SHA-256，原图 ZIP 还需 CRC；最终只能使用原有 tools.private_release_verify，不另造一套通过标准。

## 本机最小用法

此前 private_release_manifest 生成的真实manifest放在个人书籍 .local 下，不能提交到公开GitHub。

需要**官方 Google Drive OAuth access token**，并授予对应文件权限的 Drive scope。浏览器Google登录Cookie与ChatGPT Drive连接器认证状态不会自动成为这种token。用户自行在本地配置短期token，不应在聊天发送明文。

~~~powershell
cd D:\CodexData\weread-archive-agent
# 首先自行配置本地进程环境变量 GOOGLE_DRIVE_ACCESS_TOKEN
python -m tools.drive_upload_adapter --manifest '.local\PRIVATE_RELEASE_MANIFEST.json' --receipt '.local\drive-placement-plan.json'
# 查看计划，确认后才显式执行；另用一个私有回执文件名
python -m tools.drive_upload_adapter --manifest '.local\PRIVATE_RELEASE_MANIFEST.json' --receipt '.local\drive-placement-executed.json' --execute
~~~

没有token时程序停止并不会修改云端，更不会宣称验证通过。**本轮尚未配置可用OAuth token，也尚未真实运行过新适配器**；不会改动已完成的前七本成品。

## 三种必须分开的状态

| 输出 | 能证明什么 | 不能证明什么 |
| --- | --- | --- |
| PLACEMENT_PLAN_ONLY | 实际元数据支持拟创建/拟移动计划 | 无上传、无移动 |
| UPLOAD_PLACEMENT_VERIFIED | 已创建/复用/移动到真实父目录，size/MD5/owner-only通过 | 未完成独立下载云端SHA |
| PRIVATE_DELIVERY_PASS | 现有独立验证器比较全部云端字节SHA/权限后通过 | 不等于G7人类实际阅读签收 |

## 测试与边界

~~~powershell
python -m unittest discover -s tests -p test_drive_upload_adapter.py -v
~~~

用内存FakeDrive测试显式父目录创建、错误根目录移动原ID、重复调用复用、重复同名阻断、字节/MD5不一致拒绝、非owner-only拒绝、本地文件变更拒绝、计划模式无副作用等。

HTTP上传的断流跨进程session恢复、OAuth刷新与独立cloud SHA/CRC下载属于下一阶段，未假定已完成。当前原有独立验收器仍是唯一完整交付判断依据。

## 下一步 P8-B

- 把来源严格证明的无id secondTitle H2 独立 v7 规则加入主程序与合成测试，不改变v2-v6输出。
- 增加真实注释锚点与PDF四类页面（文字、图片、矢量分隔、纯空白）分类测试。
- 用户在自己环境配置合法OAuth token后，再使用**合成文件**做一次真实Google Drive上传/移动/完整回读闭环，不能使用已经交付的七本真书作新模块首测。
