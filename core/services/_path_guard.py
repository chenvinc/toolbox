"""路径守卫 / 行距解析纯函数（零 Qt、零第三方依赖）。

P0 整改：从 ``core/adapters/pptx_writer`` 下沉至此，适配器不再承担
「共享工具库」角色（services 不应 import 适配器的私有符号）：

- ``same_path``：服务层「输出路径 ≠ 模板 / 源文件」防覆盖校验共用；
- ``resolve_line_spacing``：把 ``LineSpacingType`` 的枚举字符串值解析为行距
  数值，服务（PptxServiceImpl）与 UI 预览（SlideView）共用。

新增工具 / 服务如需同类校验，一律从本模块取用。
"""
from __future__ import annotations

import os


def same_path(a: str, b: str) -> bool:
    """判断两个路径是否指向同一文件（规范化大小写与绝对路径后比较）。"""
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def resolve_line_spacing(line_spacing_type: str, line_spacing_value: float) -> float:
    """根据行间距类型解析为实际的行间距数值。"""
    if line_spacing_type == "1.5 倍":
        return 1.5
    if line_spacing_type == "自定义":
        return line_spacing_value
    return 1.0
