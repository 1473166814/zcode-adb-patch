---
description: 查看 zcode-adb-patch 的引擎补丁状态，或把它还原（例：/adb-patch restore）
---
管理 zcode-adb-patch（ZCode 引擎的 adb 直连补丁）。插件根目录 = 本命令文件所在目录的上一级。Windows 用 `python`。

- 没给参数或给 `status`：`python "<插件根目录>/hooks/adb_patch.py" status`，
  转述返回 JSON 的 `state`（clean=未打 / patched=已打 / foreign=形状不符 / missing=找不到引擎）、`patchEnabled`、
  `edits` 里每一处的状态、`hasRecord`；有 `error` 或 `note` 原样转述。
- 给 `restore`：`python "<插件根目录>/hooks/adb_patch.py" restore`，转述返回的 JSON。
  它只把引擎里三处改动还原为原文，并停止自动打补丁。
- 给 `config --patch on|off`：`python "<插件根目录>/hooks/adb_patch.py" config --patch <参数>`，
  打开或关闭自动打补丁，转述返回 JSON 的 `engine.state` 与 `engine.patchEnabled`；有 `error` 原样转述。
- 给 `config --auto-update on|off`：`python "<插件根目录>/hooks/adb_patch.py" config --auto-update <参数>`，
  打开或关闭插件的自动更新，转述返回 JSON 的 `autoUpdate` 与 `autoUpdateIntervalMinutes`；有 `error` 原样转述。

用户附加要求：$ARGUMENTS
