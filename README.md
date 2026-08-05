# Icon Crop Studio

最快制作 Windows ICO 的批量裁切工具（开发中）。

## 运行（Windows 10/11）

```bat
pip install -r requirements.txt
python main.py
```

调试模式：`python main.py --debug`

## 测试

```bat
pip install pytest
python -m pytest
```

## 当前进度

- [x] Phase 1 项目初始化：包结构、config.json 管理、logging（控制台 + 滚动文件）、JSON i18n（简中/英文，运行时切换）
- [x] Phase 2 主窗口：菜单栏、工具栏、20/60/20 三栏 QSplitter、状态栏、窗口几何记忆、语言菜单实时切换
- [x] Phase 3 图片加载：目录扫描、分页（默认20/页）、异步缩略图（QThreadPool + LRU缓存）、状态角标、拖放（文件/多文件/文件夹）、可点击的输入/输出目录、工具栏快捷键提示、记忆上次目录、临时中央预览
- [x] Phase 4 裁切组件：正方形裁切框（拖动/角点/边缘缩放、不越界）、Ctrl+滚轮缩放、中键平移、双击适应窗口、WASD/QE 键控（Shift 加速/Ctrl 微调）、Esc 重置、Ctrl+Z/Y 撤销重做、裁切框位置跨图片按比例继承；缩略图页自适应容量（永不滚动）
- [x] Phase 5 快捷键系统：集中式 action_id→QAction 注册表、默认值+用户覆盖合并（`core/shortcuts.py`，Qt-free）、空串=禁用、设置对话框内冲突检测与恢复默认；`action_reset_crop`（Esc，可重绑定）
- [x] Phase 6 导出系统：单ICO多尺寸帧（LANCZOS）、PNG/JPG按尺寸分文件、异步导出（边导出边处理下一张）、Ctrl+S 导出、Space 导出并下一张、状态角标变色（蓝→绿/红）、不覆盖时自动改名、导出选项即时持久化
- [x] Phase 7 实时预览：`core/preview_service.py`（QRunnable 池 + generation 丢弃过期）+ 右栏棋盘格 `CropPreview`（各选中尺寸缩略块+标签），裁切框拖动/尺寸切换防抖刷新
- [x] Phase 8 多语言完善：中英双语 key 全量对齐（65/65）
- [x] Phase 9 文件夹监听：`core/folder_watcher.py`（QFileSystemWatcher + 快照 diff + 轮询兜底），新增/删除图片实时增删列表项，`ImageCollection.remove/index_of`
- [x] Phase 10 设置对话框：语言/主题/缩略图大小/监听/记住裁切/覆盖/快捷键编辑（副本编辑，OK 才回写）；主题 system/light/dark（`ui/theme.py`，暗色走 Fusion+palette）
- [x] Phase 11 性能优化：工具栏标准主题图标（TextUnderIcon）、导出完成状态用 O(1) `index_of` 定位
- [x] Phase 12 测试完善：shortcuts / folder diff / preview / collection.remove 等新增单测
- [x] Phase 13 输出尺寸 DIY：自定义尺寸（如 800*800、100*200）添加/删除与输入校验；同比例尺寸才可同时选中（比例互斥）；裁切框支持任意宽高比（整数精确缩放）；裁切框位置跨图片按比例继承并跨会话保存（`last_crop_relative`）
- [x] Phase 14 导出文件名模板（`core/naming.py`，占位符 `{name}`/`{format}`/`{size}`/`{size_}`/`$yyyy-MM-dd$` 时间）与工具栏亮度调整（QGraphicsEffect，-100~100，滑块+还原，不修改原图）

## 架构

- `core/` 全部 Qt-free，可独立单测；GUI 层（`ui/`）保持薄。
- i18n 采用 JSON 目录 + 订阅回调（非 Qt Linguist），新增语言只需在
  `resources/i18n/` 放一个 JSON 并在 `core/localization.py` 的
  `AVAILABLE_LANGUAGES` 注册。
- 配置为 dataclass `AppConfig`，未知键忽略、缺失键取默认，升级兼容。
- 配置/日志存放于 `%APPDATA%/IconCropStudio/`。
