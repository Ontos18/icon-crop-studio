# Icon Crop Studio

Windows ICO 的批量裁切工具。批量导入、逐个裁切、一键导出 16–256 任意尺寸的 ICO / PNG / JPG。全程本地运行，图片与设置不出本机。

## 特性

- **批量 ICO**：单个 ICO 内嵌多尺寸帧（LANCZOS 高质量缩放），或导出多尺寸 PNG/JPG 分文件
- **实时预览**：导出前预览每个尺寸的裁切效果，棋盘格显示透明区域
- **灵活裁切**：拖动 / 角点边缘缩放、WASD 微调、Shift+滚轮缩放裁切框、Ctrl+滚轮缩放画布、双击适应窗口
- **等比缩放**：与裁切平行的完整图片缩放模式，指定目标宽度或高度，另一边按原图比例自动计算
- **越界裁切**：裁切框可超出图片边界，超出区域按透明/白导出
- **显示亮度**：实时亮度调整，仅影响显示，不修改原图
- **高效加载**：异步解码、缩略图 LRU 缓存、文件夹自动监听（新增/删除实时同步）
- **高度自定义**：任意输出尺寸、文件名模板（时间戳/尺寸占位符）、全部快捷键可重绑
- **双语界面**：简体中文 / English，运行时即时切换
- **三套主题**：跟随系统 / 浅色 / 深色

## 运行（Windows 10/11）

需要 Python 3.10+：

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

## 快捷键

| 操作 | 快捷键 |
|------|--------|
| 打开目录 | Ctrl+O |
| 导出 | Ctrl+S |
| 导出并下一张 | Space |
| 上一张 / 下一张 | ← / → |
| 撤销 / 重做 | Ctrl+Z / Ctrl+Y |
| 重置裁切框 | Esc |
| 越界裁切 | M |
| 设置 | Ctrl+, |

画布操作：**Ctrl+滚轮** 缩放画布，**Shift+滚轮** 缩放裁切框，**中键拖动** 平移，**双击** 适应窗口，**WASD** 微调裁切框（Shift 加速 / Ctrl 微调）。完整清单可在应用内「帮助 → 快捷键一览」查看。

批量等比缩放：在右侧「处理方式」选择「等比缩放」，选择按宽度或按高度并输入目标像素。随后可继续使用 **Ctrl+S** 导出，或连续按 **Space** 导出并切换到下一张。

## 架构

- `core/` 全部 Qt-free，可独立单测；GUI 层（`ui/`）保持薄。
- i18n 采用 JSON 目录 + 订阅回调，新增语言只需在 `resources/i18n/` 放一个 JSON 并在 `core/localization.py` 注册。
- 配置为 dataclass，未知键忽略、缺失键取默认，兼容升级。
- 配置/日志存放于 `%APPDATA%/IconCropStudio/`。

## 许可

MIT License，见 [LICENSE](LICENSE)。第三方依赖许可见 [NOTICE.md](NOTICE.md)。
