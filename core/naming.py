"""Export filename templating (Qt-free, fully unit-testable).

The user customises ``config.filename_template`` in the settings dialog.
Supported placeholders:

===========  ==============================================
``{name}``   source file name without extension, e.g. ``logo``
``{format}`` output format, e.g. ``png`` / ``ico`` / ``jpg``
``{size}``   size as ``800x800`` / ``100x200``
``{size_}``  size with underscore, ``800_800`` / ``100_200``
``{w}``      output width
``{h}``      output height
``$pat$``    strftime pattern, e.g. ``$yyyy-MM-dd_HH-mm-ss$``
===========  ==============================================

Example template::

    {format}_比例（{size_}）_$yyyy-MM-dd_HH-mm-ss$.png
"""
from __future__ import annotations

import re
from datetime import datetime

#: 默认模板：保留旧行为（方形输出 <stem>_16.png，非方形 <stem>_100x200.png）。
DEFAULT_TEMPLATE = "{name}_{size}.{format}"

# 顺序重要：{size_} 必须先于 {size} 替换（{size} 是 {size_} 的前缀）。
_TIME_RE = re.compile(r"\$([^$]*)\$")

#: Java/常见习惯写法的日期 token -> Python strftime。长 token 在前。
_STRFTIME_TOKENS = (
    ("yyyy", "%Y"), ("yy", "%y"), ("MM", "%m"), ("dd", "%d"),
    ("HH", "%H"), ("hh", "%I"), ("mm", "%M"), ("ss", "%S"),
)


def _to_strftime(pattern: str) -> str:
    """把 ``$yyyy-MM-dd_HH-mm-ss$`` 之类转换为 strftime 格式。"""
    for token, replacement in _STRFTIME_TOKENS:
        pattern = pattern.replace(token, replacement)
    return pattern


def render_filename(template: str, *, name: str, fmt: str,
                    size: tuple[int, int],
                    when: datetime | None = None) -> str:
    """Render ``template`` with the given values into an output file name.

    ``name`` is the source stem (no extension). ``size`` is the output
    (width, height). ``when`` defaults to ``datetime.now()``.
    """
    w, h = size
    size_text = f"{w}x{h}"
    size_underscore = f"{w}_{h}"
    text = (template
            .replace("{name}", name)
            .replace("{format}", fmt)
            .replace("{size_}", size_underscore)
            .replace("{size}", size_text)
            .replace("{w}", str(w))
            .replace("{h}", str(h)))
    if when is None:
        when = datetime.now()
    text = _TIME_RE.sub(lambda m: when.strftime(_to_strftime(m.group(1))), text)
    return text
