# P8-E｜Windows Remote Desktop Commander 退出码1的有界恢复

本方案针对Windows登录自启动任务已经触发，但固定版本 Remote Agent 随后退出、计划任务 LastTaskResult=1 且无真实 Remote node.exe的情况。它不把 Online UI、443端口可达、或日志没有error误判为远程工具已成功。

## 已证事实与未证原因

- 之前从 npx @latest 切换为固定本地0.3.0，解决了约24分钟的启动延迟。
- 用户提供的Windows/WSL实际诊断：最后任务结果为1，Remote进程已消失；日志只有启动banner，未能捕获退出根因。
- 官方相关但不等同的缺陷：[持久化会话与Refresh Token](https://github.com/wonderwhy-er/DesktopCommanderMCP/issues/661) 和 [Online状态但不能执行命令](https://github.com/wonderwhy-er/DesktopCommanderMCP/issues/798)。不能因其他案例就删除本机设备凭据。

## 默认只读诊断

在Windows PowerShell或者之前已授权且Windows interop可用的WSL/Hermes执行：

~~~powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File 'D:\CodexData\weread-archive-agent\tools\windows\dc_remote_recover.ps1' -Mode Diagnose
~~~

报告包括任务状态/最后退出码、固定程序文件和会话文件是否存在、实际Remote进程数/TCP数、遗留NPX数量、脱敏日志的事件分类计数。**不读取会话JSON内容、不输出完整日志或设备登录码、不修改任何Windows配置。**

## 限次单次恢复（必须显式批准）

仅在任务Ready、没有实际Remote或遗留NPX进程、固定程序入口与保存的会话文件存在、日志未显示重新授权问题时才可请求启动：

~~~powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File 'D:\CodexData\weread-archive-agent\tools\windows\dc_remote_recover.ps1' -Mode RecoverOnce -Apply
~~~

每小时最多2次，至少间隔300秒；脚本只请求启动原 DesktopCommanderRemote 任务，不停止进程、修改计划任务、清理缓存或登出账号。START_REQUESTED_NOT_YET_VERIFIED表示已提交启动请求，**不是云端联通的PASS**。如发现认证问题或任务状态不明确，会按安全守卫直接跳过。

## 最新P8-F4证据：已有Watchdog及自然自愈成功

2026-10-19当天下午的私有Notion P8-F3/P8-F4记录提供了更新事实：用户级 DesktopCommanderRemoteWatchdog **已经安装并每5分钟检查**，14:42的一次自然退出后由它自动拉起原 Remote 任务，14:46 ChatGPT 的 ping 和只读echo均通过。**这意味着无需第二个恢复/看门狗任务**。

19:26又出现了Online列表与实际ping超时的不同症状，此时不应无证据地重新启动设备。脚本因此新增对现有 DesktopCommanderRemoteWatchdog 的只读识别：如果这个Watchdog已经启用，即使显式运行RecoverOnce -Apply，也会返回 SKIP_EXISTING_WATCHDOG_MANAGES_RECOVERY，**不会插入竞争性重启**。

在用户不在电脑旁的条件下，优先借Hermes/WSL跑 Diagnose 查看两个任务状态、真实进程/TCP、日志事件计数，再由ChatGPT单独验ping。只有明确证明已经存在的Watchdog不能覆盖目标故障，并经过单独维护审批，才考虑下一版改造。

## 用户不在Windows旁边时给Hermes/WSL的命令

用户先前已通过WSL Windows interop完成只读诊断。如果该通道现在仍可用，可将下方一条命令发给有权访问Windows的Hermes Agent：

~~~bash
cd /mnt/d/CodexData/weread-archive-agent && git pull --ff-only origin main && powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File 'D:\CodexData\weread-archive-agent\tools\windows\dc_remote_recover.ps1' -Mode Diagnose
~~~

如果Git不能快进，停止而不执行reset/clean。只回传机读的非敏感状态码与事件分类，不回传缓存会话、cookie、token、设备验证码或原始日志。由用户确认门禁后才进入RecoverOnce。

## 当前不做的事情

- 不建立第二个Windows自启动任务，也不部署无限循环自动重启。若授权已失效，这可能反复产生无法完成的人工验证码请求。
- 不再修改七本私人图书，不清除Remote配对凭据。
- 不把纯结构CI测试冒称Windows真机恢复成功。
- 真正完成的门禁为ChatGPT端新鲜pong、只读命令实际成功，且后续一次冷启动后持续正常。
