# Icon Crop Studio

Windows ICO 的批量裁切工具。批量导入、逐个裁切、一键导出 16–256 任意尺寸的 ICO / PNG / JPG。全程本地运行，图片与设置不出本机。

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
