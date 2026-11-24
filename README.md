# zcode-adb-patch · ZCode 引擎 adb 直连补丁

解除 ZCode 客户端（Bash 工具）对直接 `adb` 命令的拦截。补丁对象：`E:\ZCode\resources\glm\zcode.cjs`。有两种用法，改的是同样三处：

| 形态 | 适合 | ZCode 升级后 |
| --- | --- | --- |
| **插件** `plugins/zcode-adb-patch`（推荐） | 装一次就不用管 | 新会话启动时自动重打 |
| **脚本** `re-patch-adb.sh` | 不想装插件，或插件失效时兜底 | 手动跑一次 |

与 [zcode-auto-compact](../zcode-auto-compact)（自动上下文压缩，另一独立项目）改的是**同一个引擎文件**的不同位置，可以共存，先后顺序无关（见文末）。

## 背景：官方策略变更时间线

| 时间 | ZCode 版本 | 官方行为 |
| --- | --- | --- |
| ~2026-10 及以前 | 3.18.x | Bash 工具里 `adb` / `adb shell` 随便用（会话库里有 10 月 558 次、10-14 后 1025 次 getprop 等真实使用记录） |
| 11-19 | **3.19.0.10774** | Bash 处理器里**无条件**调用 `assertAdbUsesMcp`（压缩后 `pHa`）：按最终可执行名匹配 `adb/.exe/.com/.cmd/.bat`，穿透 `command/exec/call` 包装，命中即 PermissionDenied（reason `android-adb-requires-mcp`），强制收口到 android-emulator MCP 工具。无任何配置开关 |
| 11-23 | **3.19.1.10833** | 软化：裸 `adb` 若能在 SDK 目录或 PATH 解析到 → **改写为该 adb 的绝对路径后照常执行**；仅三种情况拒绝：① 解析到的 adb 在工作区内 ② 哪里都找不到 ③ 执行适配器不支持解析。Bash 工具描述同步写明「工作区内 adb 被禁止」 |
| 11-23 | **4.0.0.10870** | 拦截/改写逻辑未变（只是去掉了 `legacy-shell` 方言分支），但压缩变量名全换：同一条语句里解析结果 `S` → `v`、解析器 `v` → `_`，引擎里也开始出现 `$` 开头的标识符。含变量名的字面量锚点因此失效，锚点改为正则捕获变量名 |

## 补丁内容

### 3.19.0 版（已归档，`archive/*.3.19.0.sh`）

三处修改：① `pHa(o.command,t)` 调用 → `void 0`（移除唯一调用点）；② 删除 Bash 工具描述里的 adb 禁令文案整条（否则模型看到文案仍自我设限）；③ 识别正则 `/^adb(?:\.(?:exe|com|cmd|bat))?$/` → `/\u0000/`（保险层）。**不适用于 3.19.1**：新版的识别正则负责「找到 adb 以改写绝对路径」，废掉它会失去自动改写。

### 3.19.1 起（现行；插件与脚本改的是这三处）

锚点只认每版不变的文字（文案、报错消息）；语句里的压缩变量名每版会变，用正则捕获出来并要求同一条语句里前后一致。三处必须要么都是原文、要么都已打过，任何一处找不到、出现多次或被别的补丁改过，整体拒绝改动：

| # | 官方逻辑 | 改为 |
| --- | --- | --- |
| 1 | 工具描述「Workspace-controlled adb executables are blocked…」 | 「adb commands are allowed, including workspace-controlled adb executables; bare adb…」 |
| 2 | 解析不到（工作区内 / 找不到）→ `throw PermissionDenied/ConfigurationError` | `continue`（跳过改写，命令原样交给 shell） |
| 3 | 执行适配器不支持解析 → `throw ConfigurationError` | `continue` |

效果：能解析到 SDK adb 时保留官方的绝对路径改写；解析不到时不再拒绝，直接放行原命令。**2026-11-23 实测（3.19.1）**：补丁后 Bash 里 `adb version` 正常执行（RockChip adb @ `E:\adb`），新会话系统提示里的工具描述即为改后文案。

## 安装插件

**前提**：ZCode 桌面版 + Python 3.8+（`python3` / `python` / `py -3` 任一可用）。

1. 插件市场 → **添加** → **添加插件市场**：
   - 从 GitHub 装：粘贴 `1473166814/zcode-adb-patch`（走 HTTPS）
   - HTTPS 克隆被网络重置时：粘贴 `git@github.com:1473166814/zcode-adb-patch.git`（走 SSH，需本机有可用的 GitHub SSH key）
   - 从本地装：粘贴本仓库根目录 `F:\Workspace\Projects\zcode-adb-patch`
2. **个人** → `zcode-adb-patch` → 「adb 直连补丁」→ **安装**
3. 开一个新会话：钩子在这一步给引擎打补丁
4. 之后新开的会话生效

安装后可以在 ZCode 的 **设置 → 插件** 里管理。更新插件：改源码并升 `plugin.json` 与 `marketplace.json` 里的版本号 → 市场页齿轮「市场源」→ 刷新该市场 → 个人 → 插件详情 → 更新（从 GitHub 装的，刷新时宿主会重新 clone 仓库）。

**发给别人**：把 `1473166814/zcode-adb-patch` 发给对方，对方在 插件市场 → 添加 → 添加插件市场 里粘贴即可（公开仓库，不需要给任何 key）。对方网络到不了 GitHub 时，把 [`dist/zcode-adb-patch-v0.2.0.zip`](dist/zcode-adb-patch-v0.2.0.zip) 发过去：解压到固定目录 → 把该目录作为本地插件市场添加 → 安装。对方需要 Python 3.8+。

### 用法

| 命令 | 作用 |
| --- | --- |
| `/adb-patch` | 查看状态：`state`（`clean` 未打 / `patched` 已打 / `foreign` 形状不符 / `missing` 找不到引擎）、三处各自的状态、`patchEnabled` |
| `/adb-patch restore` | 只把这三处改动还原为原文，并停止自动打补丁 |
| `/adb-patch config --patch on\|off` | 打开 / 关闭自动打补丁 |
| `/adb-patch config --auto-update on\|off` | 打开 / 关闭插件的自动更新 |

设置在 `~/.zcode/zcode-adb-patch/config.json`（`patchEnabled`、`autoUpdate`、`autoUpdateIntervalMinutes`）。同目录的 `patch-record.json` 是补丁记录：打补丁时记下三处原文，`restore` 靠它逐字节放回。

### 生效时机

- **安装后**：开一个新会话（钩子打补丁）→ 再新开的会话生效。
- **ZCode 升级后**：第一次启动时钩子自动重打 → 之后新开的会话生效，不用再跑脚本。
- 已在运行的会话保持原样（引擎代码在进程启动时就加载了）。

### 插件比脚本多做的保护

- 打补丁时记下三处原文，`restore` 只还原这三处，不动同一文件里的其它补丁（`restore-adb.sh` 是整文件还原）。
- 用 ZCode 自带的运行时对副本做语法检查，通过才替换。
- 替换前确认引擎没被别的进程改过，替换后回读确认；发现被改就重读重打（zcode-auto-compact 也会改同一个文件）。
- 自动更新走 ZCode 官方 CLI（`plugins marketplace update` + `plugins update`）：新会话检查、每小时限频、安装前语法预检、坏版本拒装；记录在 `update.json`。
- 钩子模式标准输出为空、任何异常都不外泄，不干扰会话。

## 手动脚本（兜底）

**live 工作副本在 `%USERPROFILE%\.zcode\patches\`**（备份也在那里）；本仓库是版本化记录——以后改动 live 脚本后记得同步到这里再提交。脚本里的备份目录默认取 `%USERPROFILE%\.zcode\patches`（非 Windows 或自定义位置可设 `ZCODE_PATCH_DIR`）。

```bash
# ZCode 更新后重打（先试打副本+语法检查，通过才替换引擎；已打过则退出 0）
bash ~/.zcode/patches/re-patch-adb.sh
# 只在指定副本上试打，不动已安装引擎
bash ~/.zcode/patches/re-patch-adb.sh <某份zcode.cjs>
# 还原当前版本的原版引擎（撤掉 adb 补丁；整文件还原，会连带撤掉 zcode-auto-compact 的引擎补丁）
bash ~/.zcode/patches/restore-adb.sh
```

脚本内建的安全措施：先在副本上改，锚点计数断言（≠1 即中止）、`node --check` 全文件语法检查（失败不替换），通过后才替换；替换前自动备份；显式传入空路径会报错，不会回落到已安装的引擎。注意补丁后**新开会话**才生效。

脚本和插件可以并存：两者认同样的「已打过」形状，谁先打都行，另一个会判定无需修改。区别在还原——用脚本打的补丁没有插件的补丁记录，要还原得用 `restore-adb.sh`。

### 脚本的备份（`~/.zcode/patches/`）

| 文件 | 含义 |
| --- | --- |
| `zcode.cjs.orig-<版本>` | 该版本的**厂商原版**（首次打补丁时保存；引擎若已带 zcode-auto-compact 补丁则不保存，避免污染）。已有 3.19.0.10774 / 3.19.1.10833 / 4.0.0.10870 三份。SHA256：3.19.1.10833 `4b90ae046753be9f5ba63dee14b8fd2cdb07b5540e9bfe348ba127504b8cf8da`，4.0.0.10870 `0de95ddd65d7712a3beeccc8ee6de53ea0ce96338eb427e52b2717ba2f3afe19` |
| `zcode.cjs.pre-patch.<时间戳>` | 每次打补丁前的即时快照 |

## 验证记录

**2026-11-23（4.0.0.10870，脚本）**：相对原版恰好只有这三处不同、其余字节逐一相同（仅带 adb 补丁时 SHA256 `0de95ddd…` → `44448463…`），`node --check` 通过，官方 CLI 能正常启动；在 3.19.1 原版上新旧脚本的产物逐字节相同。

**2026-11-23（插件 0.1.0）**：只在引擎副本上测，共 47 项全过——

- 4.0.0 / 3.19.1 原版打补丁后的产物与脚本产物逐字节相同；还原后与厂商原版逐字节相同
- 形状不符、补丁记录被篡改、语法检查不通过时都拒绝改动，且不留临时文件
- 模拟「替换前被别的进程改」「替换后被盖掉」，都能发现并重打
- 与 zcode-auto-compact 1.0.2 的钩子真实并发（6 种启动时序）：两处补丁都在，其余字节不变
- 钩子模式标准输出为空；宿主不关闭钩子 stdin 时也能正常退出
- 官方 `zcode plugins validate` 通过

**2026-11-23（插件 0.2.0）**：新增自动更新（复用 zcode-auto-compact 已在用的官方 CLI 命令链）。已验证 `status` / `config --patch` / `config --auto-update` 输出、钩子模式标准输出为空、对真实引擎只读不改（SHA256 不变）；更新链路要等装到真实市场后才跑得到。

**尚未实测**：安装后由真实钩子触发打补丁与自动更新，以及 Bash 里实际执行 `adb`（要新开会话）。

## 与 zcode-auto-compact（另一项目）的关系

- 两者是独立项目，改同一个文件 `zcode.cjs` 的不同位置，锚点互不重叠，**已验证共存**。
- 两个都用插件形态时先后顺序无关：zcode-adb-patch 替换前后会确认文件有没有被别的进程改过；zcode-auto-compact 从 1.0.2 起，`restore-engine` 只校验目标函数及紧邻上下文，不再被别处的改动误伤。
- 若用的是脚本：`restore-adb.sh` 要有该版本的原版备份才能还原，而脚本只在引擎还没带 zcode-auto-compact 补丁时才保存原版。所以**先跑脚本，再开新会话**。
- zcode-auto-compact 低于 1.0.2 时，先让它打、后打 adb 补丁会让它的 `restore-engine` 因整文件哈希不一致而拒绝写入；升级到 1.0.2 即可。
- 4.0.0 的桌面端代码里有一个 `ZCODE_DESKTOP_AGENT_BYTECODE=1` 开关：开启后桌面会话改跑字节码版引擎 `zcode.bytecode.cjs`，两处源码补丁都不会生效。当前版本默认不开（安装目录里也没有该文件）；若某次升级后补丁「打上了却不生效」，先查这个。

## 目录结构

```
marketplace.json              插件市场清单（必须在仓库根：GitHub 源的宿主只认根目录的 marketplace.json）
zcode-adb-patch/              插件源码
  .zcode-plugin/plugin.json     插件清单
  hooks/adb_patch.py            主逻辑：引擎补丁 / 还原 / 状态 / CLI
  hooks/hooks.json              SessionStart 钩子
  commands/adb-patch.md         /adb-patch 命令
re-patch-adb.sh               手动脚本（现行）
restore-adb.sh                手动还原（整文件）
archive/                      3.19.0 版脚本归档
```

`marketplace.json` 里的 `source` 是相对仓库根的路径，插件目录必须和它同级或在其下；ZCode 添加市场时会 clone 整个仓库（GitHub 源）或复制整个目录（本地目录源）。

## License

MIT（见 [LICENSE](LICENSE)）
