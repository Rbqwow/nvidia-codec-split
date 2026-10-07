# NVIDIA App 新版适配流程

本文记录 11.0.9.251 版本的定位依据，以及为本公开项目增加新版配置的方法。原始本机脚本已重构为 `src/nvidia_codec_split` 包；下面的路径、接口和偏移仅代表已验证版本，不能直接套用到更新后的文件。

## 1. 基线与源码入口

| 项目 | 已验证值 |
| --- | --- |
| NVIDIA App | `11.0.9.251` |
| Overlay 文件版本 | `128.4.13.34` |
| 录制 DLL 版本 | `11.0.9.251` |
| 验证 GPU / 驱动 | RTX 4060 Laptop GPU / `616.92` |
| 录制模块 | `ShadowPlay/NVSPCAPS/_nvspcaps64.dll` |
| 浮窗入口 | `osc/index.html` |
| 主脚本 | `osc/main.cb3bd1642c6faf80.js` |
| 原版录制 DLL SHA-256 | `097f45f1ac2bc4c88d55062ea12f137738a8b16c68952bc921669f7a24d7537a` |
| 原版主脚本 SHA-256 | `7b9d4c59e46d2a229fe1640c5252fddbf2b29460273741b444ea18c1ad3cb30b` |
| 公开版生成的主脚本 SHA-256 | `88d0828f8c5afd8a6a30d5a5c071719179f9f0018f407916dded6d8bf7e460ab` |

完整校验值和原始/新字节见 [版本配置](../src/nvidia_codec_split/profiles/11.0.9.251.json)。公开版保留原脚本行尾；早期本机生成器曾重复转换 CRLF，其生成哈希作为迁移兼容值保留，需要真正的原版备份才能重新准备。

| 代码 | 职责 |
| --- | --- |
| [core.py](../src/nvidia_codec_split/core.py) | 配置验证、路径约束、本机资源生成、文件校验、安装/还原及回滚 |
| [memory.py](../src/nvidia_codec_split/memory.py) | 模块发现、进程创建时间、字节校验、暂停/写入/恢复和写入回滚 |
| [watcher.py](../src/nvidia_codec_split/watcher.py) | 按本机状态目录区分单实例，检测新进程、定期检查版本、响应停止事件 |
| [legacy.py](../src/nvidia_codec_split/legacy.py) | 从旧助手或旧项目清单迁移已校验的原始备份及启动项记录 |
| [cli.py](../src/nvidia_codec_split/cli.py) | prepare/import-legacy/check/check-restore/status 与运行时命令 |
| [Install.ps1](../Install.ps1) | 普通用户管理备份与 HKCU，UAC 仅执行安装目录写入及服务重启 |
| [tools/cdp.mjs](../tools/cdp.mjs) | 临时连接实际浮窗、执行诊断 JavaScript |

## 2. 更新后取得原版基线

首先检查新版是否已经原生提供独立 HEVC，并录制实际视频确认。如果原生功能已满足需求，停用旧助手即可。

适配前保存录制参数、结束正在录制的内容、关闭即时重放，停掉旧助手。公开版可用 `python run.py stop-watch`；完整卸载通过 `Restore.cmd`。助手停止后，已加载进程中的补丁可能仍存在；需要原版基线时重启 `NvContainerLocalSystem`，重新加载签名模块。

公开版还原会跳过已被新版替换的界面文件，不把旧资源覆盖到新版。0.1.1 起，`Restore.cmd` 也能迁移早期本机脚本的原始备份，不要求预先运行公开版 `Apply.cmd`，也不依赖旧补丁生成物。旧运行时目录已删除时，会查找本仓库旁的 `nvidia_codec_patch`；其他位置用 `Restore.cmd -LegacyRoot <旧项目目录>` 指定。保留旧项目的 `native_manifest.json`、原始 `osc` 备份和 `helper-startup.json`，不要删除校验来强行套用旧备份。

还原前可用 `python run.py check-restore --state-dir <旧状态目录>` 只读校验。完整流程先验证原始备份，再停助手；旧助手的内存写入子进程必须正常完成，不能一起强制终止。UAC 步骤完成界面还原与服务重启后，普通用户步骤才恢复自己的 HKCU 登录启动项。受支持版本用 `status` 确认录制模块六处原始字节、零处补丁字节；缺失备份应在 UAC 前报错。

读取版本与文件信息：

```powershell
$nvAppRoot = Join-Path $env:ProgramFiles 'NVIDIA Corporation\NVIDIA App'
$nvCodecDll = Join-Path $nvAppRoot 'ShadowPlay\NVSPCAPS\_nvspcaps64.dll'
(Get-Item -LiteralPath (Join-Path $nvAppRoot 'CEF\NVIDIA Overlay.exe')).VersionInfo |
    Select-Object FileVersion,ProductVersion
(Get-Item -LiteralPath $nvCodecDll).VersionInfo | Select-Object FileVersion,ProductVersion
Get-FileHash -LiteralPath $nvCodecDll -Algorithm SHA256
Get-AuthenticodeSignature -LiteralPath $nvCodecDll | Select-Object Status,StatusMessage
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
$nvIndex = Get-Content -LiteralPath (Join-Path $nvAppRoot 'osc\index.html') -Raw
[regex]::Matches($nvIndex,'<script[^>]+src="([^"]+\.js)"') |
    ForEach-Object { $_.Groups[1].Value }
```

原版资源和完整 DLL 只在本机保存，不提交到仓库。为每个版本使用独立的本机状态目录和原始文件备份，保留旧版回退资料。

## 3. 临时诊断接口

本次有效方法是在 `%LOCALAPPDATA%\NVIDIA Corporation\NVIDIA Overlay\overrides.json` 的 `switches` 数组临时加入 `nv-remote-debugging-port=9227`，然后重启浮窗。先单独备份本次开始前的配置，不覆盖之前的快照；结束后撤掉调试开关。

```powershell
Get-Process -Name 'NVIDIA Overlay' -ErrorAction SilentlyContinue | Stop-Process
Start-Process -FilePath (Join-Path $nvAppRoot 'CEF\NVIDIA Overlay.exe') -WindowStyle Hidden
node .\tools\cdp.mjs targets
node .\tools\cdp.mjs evaluate .\tools\probe.js
```

确认调试仅监听 `127.0.0.1`。使用其他端口时，通过当前终端的 `NV_CODEC_DEBUG_PORT` 指定相同端口。

已验证的 CEF 原生请求格式：

```javascript
window.cefQuery({
  request: JSON.stringify({
    command: 'QUERY_IPC_EXTENSION_MESSAGE', system: 'CrimsonNative',
    module: 'ShareServer', method: 'GetSupportedBitratesFramerates',
    payload: {quality:'VeryGood',resolution:'In-game',codec:'H265',framerate:60}
  }),
  persistent: false,
  onSuccess: text => {
    const message = JSON.parse(text);
    const result = message.payload || message;
    if (result._return_code || result._return_internal < 0) console.error(result);
    else console.log(result);
  },
  onFailure: (code,message) => console.error({code,message})
});
```

参数在 `payload`，返回值通常也包装在 `payload`。`_return_code=0` 不足以证明保存成功；负的 `_return_internal` 仍可能表示失败。本次成功值出现过 0 和 1，新版需按接口定义确认。

`tools/probe.js` 读取状态，不启动录像。若另写设置/录制探测，保存原始参数、检查活动录制状态、在 `finally` 中停止由测试启动的捕获，并恢复原始参数。

## 4. 重新定位界面层

```powershell
rg -l 'H264_HEVC|convertCodec|GetInstantReplaySettings|CodecHelp1HEVC|recCodec' `
    (Join-Path $nvAppRoot 'osc') -g '*.js'
```

同一个主脚本还包含 GFN、直播及其他编码器代码。沿 `Share.Shareserver`、`ShadowPlayService` 和视频录制页面定位，避免按 HEVC 字符串全局替换。

11.0.9.251 中需要修改的七项：

1. `convertCodec` 单独保留 H265，避免把非 AV1 值都变成合并项。
2. 初始化时检查 `GetHevcSupportedState`，并探测 H265 的码率/帧率查询。
3. 两项检查成功时，在后端合并项旁加入 H265，保留 AV1。
4. 显示 H.264、HEVC (H.265)、AV1 三个名称。
5. 切换时给 HEVC 显示正确帮助，避免落入 AV1 的播放提示。
6. 重新打开页面时读回相同选择和帮助。
7. G-Assist 的 `hevc`/`h265`/`h.265` 输入映射到 H265。

更新新配置中 `frontend.edits` 的匹配片段和变量别名。每个片段都应有明确的匹配数量。更新主脚本文件名、原始哈希、生成哈希以及语言资源的哈希。新版已有独立 HEVC 时，重新判断哪些修改仍有必要。

语言键为 `capture.CodecH264`、`capture.CodecHEVC`，并更新 HEVC 与 HDR/8K 说明。生成代码位于 `transform_main`、`transform_locale`；主脚本按字节保留行尾。

本版使用 Angular 命名路由出口，诊断页面为 `#/(igo:sidebar/settings/video)`。普通 `#/settings/video` 路由不匹配。用 webpack 注入诊断回调时，每次使用不同的块 ID，避免已加载块不再执行回调。

## 5. 原生后端定位

| 界面 | 本版桥接字符串 | 本版录制原生枚举 |
| --- | --- | --- |
| H.264 | `H264/HEVC` | 2 |
| HEVC | `H265` | 1 |
| AV1 | `AV1` | 3 |

这是 ShadowPlay 的映射，不能沿用主脚本中其他组件的枚举。

关键发现：`ShareServer.dll` 的接口定义允许 H265，但原版后端参数范围查询拒绝它，设置时报 `ShadowPlay: Invalid property value`。实际设置路径把 H265 转成了原生空字符串；只补字面 H265 的比较仍失败。最终本版 setter 接受这个桥接生成的空字符串和严格以 NUL 结尾的 H265，写入枚举 1。新版必须重新检查实参，不能默认仍使用空字符串。

| 文件 | 定位锚点 |
| --- | --- |
| `CEF/plugins/NVIDIA Overlay/ShareServer.dll` | Codec 接口定义、H264/HEVC、H265、GetSupportedResolutionsCodecs、SetInstantReplaySettings |
| `ShadowPlay/NVSPCAPS/_nvspcaps64.dll` | rhvyeiok、CSettings::SetProperty、getCustomCodec、getBitrateFPSRange、EvaluateVideoCaptureSettings、Auto changing codec to HEVC |
| `ShadowPlay/capcore64.dll` | CVideoCapture::Initialize、CH265EncodeVideo、CH264EncodeVideo |

用 `pefile` 读取 PE 节区、函数范围，以 `capstone` 反汇编字符串引用和调用链。使用模块实际基址加 RVA；文件偏移需通过节区转换，旧进程绝对地址不能复用。

本版六处区域：

| 配置名 | RVA | 文件偏移 | 长度 | 作用 |
| --- | --- | --- | --- | --- |
| HEVC setter | `0x1151c0` | `0x1145c0` | 37 | 在填充区加入 HEVC 设置分支 |
| HEVC setter branch | `0x1107a5` | `0x10fba5` | 6 | 设置失败路径转入新增判断 |
| HEVC bitrate range | `0x114ff0` | `0x1143f0` | 29 | H265 复用合并项的参数范围 |
| HEVC bitrate branch | `0x11574f` | `0x114b4f` | 6 | 查询失败路径加入 H265 判断 |
| HEVC settings getter | `0x116c90` | `0x116090` | 94 | 原生枚举 1 读回 H265 |
| Explicit H.264 for SDR | `0x100206` | `0x0ff606` | 7 | 跳过普通 SDR 的自动 HEVC 条件 |

其他本版位置：H265 字符串文件偏移 `0x2e0348`；合并项字符串 RVA `0x2fe8f0`；AV1 字符串 RVA `0x2fe8e8`；字符串比较函数 RVA `0x13940`；编码字段位于 `CSettings+0x1b38`。setter 的失败/正常路径为 `0x11083d`/`0x1107b0`；范围查询的失败/正常路径为 `0x115b0a`/`0x115755`；SDR 自动转换后的路径为 `0x100297`。

逐项确认函数边界、寄存器、字段偏移、栈空间、返回约定、条件和跳转目的地。连续 `0xCC` 只是填充区候选，必须检查引用与后一个函数，确保新增代码不跨边界。保留更早的 HDR、8K 和硬件能力保护。

公开版配置直接保存经过审核的原始与新字节。`validate_profile` 拒绝重叠和不同长度区域；内存工具在首次写入之前验证全部区域，不依赖可被 `python -O` 关闭的断言。不要为接受新版而修改校验值来“绕过”拒绝。

## 6. 生成配置、部署和测试

新配置放在 `src/nvidia_codec_split/profiles/<版本>.json`，结构以现有配置为准。原版 DLL 必须保持磁盘内容不变。前端准备在本机完成，原版与生成后的完整文件进入私有状态目录，不提交 Git。

```powershell
python .\run.py prepare --profile <已适配版本> --state-dir <新版私有状态目录>
python .\run.py check --state-dir <新版私有状态目录>
node --check <状态目录中的prepared主脚本>
powershell.exe -NoProfile -File .\Install.ps1 -Action Apply `
    -Profile <已适配版本> -StateDir <新版私有状态目录>
```

尖括号内容是维护者需要替换的参数，不是可直接执行的命令。使用新增配置之前，确保原版哈希和各处字节/语义都已审核。

助手以状态目录派生互斥锁与停止事件，记录 PID 加进程创建时间。每次扫描检查磁盘哈希；版本变化后退出。停止命令等待当前事务结束，安装器不强行杀死可能暂停了录制进程的助手。

本版曾直接替换 DLL 后被 NVIDIA 签名加载拒绝，错误为 `2148098064`（`0x80096010`）。最终方案始终保留原版签名 DLL，仅在加载后的进程内存修改。

验收包含：

- 独立选项、实际设置读回、重新打开页面、帮助文案。
- 手动 HEVC 的 2K SDR 录像。
- 即时重放开启、保存、关闭与有效文件。
- H.264 高帧率录像仍为 H.264。
- AV1 实际短片兼容性。
- 录制服务重启后自动重新应用。
- 还原后启动项、界面、录制设置、模块加载状态恢复。

```powershell
ffprobe -v error -select_streams v:0 `
    -show_entries stream=codec_name,profile,width,height,pix_fmt,r_frame_rate,color_transfer `
    -show_entries format=duration -of json '本次录像.mp4'
```

本次 SDR 证据包括 `yuv420p`、`bt709` 与日志 `m_bHDRCapture[0]`，不能只看显示器 HDR 状态。原实现验证结果见 [VALIDATION.md](VALIDATION.md)，其中明确列出尚未做实际录制验证的项目。

## 7. 常见问题与日志

| 现象 | 本次原因 / 检查 | 处理 |
| --- | --- | --- |
| 独立 HEVC 缺失 | 硬件状态、H265 参数查询或助手未生效 | 看 watcher.log 与原生返回码，再检查界面注入条件 |
| H265 设置失败 | 允许的接口枚举与实际原生字符串不同 | 重新跟踪实参，不能假设新版仍为空字符串 |
| 重开页面变回合并项 | getter 或 convertCodec 仍归并 H265 | 同时修正原生读回和界面转换 |
| 单独重启 SPUser 后浮窗退出 | m_pSPServer not initialized、查询 EK 失败 | 重启 NvContainerLocalSystem，让服务重新初始化录制模块 |
| 自定义复制的界面空白 | file:// 模块 CORS | 本项目沿用原安装目录的入口及资源加载方式 |
| 保存失败但视频编码器正确 | 音频初始化或样本时间范围不足 | 延长采样时间，检查音频日志和实际返回值 |
| 未知字节拒绝写入 | 布局变化或其他修改 | 保留拒绝、停助手、重新定位，必要时重载原版模块 |

本次 3 秒手动录制曾因音频轨没有样本而被删除；8.5 秒重放返回 `0x8000000B`，音频缓存时间不足；等待 20 秒后按原录音设置成功保存。短片启动失败不能单独证明编码补丁有误。

```text
%PROGRAMDATA%\NVIDIA Corporation\ShadowPlay\CaptureCore.log
%PROGRAMDATA%\NVIDIA Corporation\NVIDIA App\NvContainer\*SPUser.log
%LOCALAPPDATA%\NVIDIA Corporation\NVIDIA Overlay\console.log
%LOCALAPPDATA%\NVIDIA Corporation\NVIDIA Overlay\debug.log
%LOCALAPPDATA%\NVIDIA Corporation\NVIDIA Overlay\CxNative_NVIDIA Overlay.log
%LOCALAPPDATA%\NVIDIA Codec Split\watcher.log
```

`CaptureCore.log` 中 HEVC 对应本版 `customCodec:1 vCodec:1`、`m_eVideoCodec[1]`、`CH265EncodeVideo`；H.264 对应枚举 2 和 `CH264EncodeVideo`。最终仍以保存文件的实际视频流为准。

结束后恢复诊断前配置、撤掉调试端口，恢复录制参数与原启用状态。保留新版原始备份、定位依据、配置与测试结果在本机；只提交补丁定义、源代码、通用文档和不含用户信息的验证事实。
