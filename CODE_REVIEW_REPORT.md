# 代码审查报告 — ppt_maker/toolbox

> 审查范围：`app.py` / `base_tool.py` / `similarity_checker.py` / `theme.py` / `utils.py` / `widgets.py` / `word_2_slide_tool.py`
> 审查基准：Bug 风险与边界条件 · Python 语言特性与规范 · 架构与代码质量 · 性能与资源管理 · 安全性与数据验证
> 审查假设：单用户桌面应用（PySide6 + python-docx + python-pptx），输入为本地 `.docx` / `.pptx` 文件。

---

## 🔴 严重问题（必须修改）

### 1. 相似度检测（1对多模式）参数类型错误，导致评分失真且两种模式结果不一致
**位置**：`similarity_checker.py:210`（数据准备）+ `:254-256`（`_preprocess`）+ `:228`（调用 `score_question_pair`）

`CheckerWorker.run` 把副文档题目做成了**规范化字符串**，但 `score_question_pair` 的契约是「题目行列表（`List[str]`）」：

```python
# 当前代码（错误）
secondary_data[fname] = [self._preprocess(q) for q in qs]   # _preprocess 返回 str
...
result = score_question_pair(q_lines, s_text)               # s_text 是 str，不是 list
```

`score_question_pair` 内部会 `"\n".join(q_lines_b)`，当 `q_lines_b` 是字符串时，**按字符展开**；`_split_question_parts` 也会把字符串当可迭代对象逐字符处理，最终 `option_b_norm` 恒为空、受保护的选项加权分支（`if option_a_norm and option_b_norm:`）被跳过，`option_ratio` 退化为 `1.0`。

**后果**：
- 选项相似度分支失效，题目匹配分数与文档真实内容脱节，易产生**漏报（false negative）**；
- 更关键的是：**多对多模式**传入的是正确的行列表，**1对多模式**传入的是字符串，同一道题在两种模式下分数不同 → 结果不可复现、不可解释。

**修复**：1对多模式应与多对多模式保持一致，直接保留行列表，删掉 `_preprocess` 这个“兼容旧接口”的损坏封装：

```python
# 修改后
secondary_data[fname] = [list(q) for q in qs]   # 保留 List[str] 结构
...
result = score_question_pair(q_lines, s_text)   # s_text 此时是 list，契约一致
```

如确需预规范化，应在 `score_question_pair` **内部**统一处理，而不是在调用方破坏入参类型。

---

### 2. 题目预览 HTML 未转义 —— 内容注入（HTML Injection）
**位置**：`word_2_slide_tool.py:606-616`（`on_convert` 构建预览 HTML）

用户 Word 文档的原文被**未经 `html.escape` 直接拼接进 HTML**，且字体名被拼进 `<style>`：

```python
for line in q:
    parts.append(f"<div class='q'>{line}</div>")          # line 未转义
...
f"body {{ margin: 24px; font-family: '{font_name}'; ... }}"  # font_name 未转义
```

**后果**：虽然 `QTextBrowser` 不执行 JavaScript（不是传统 XSS），但：
- 题目文本中的 `<`、`>`、`&`、`</div>`、`</style>` 会**破坏预览布局**或意外闭合标签；
- `<img src="...">`、`<a href="...">` 会被 Qt 富文本渲染（可加载外部/本地资源、产生可点击链接），属于内容注入；
- `font_name` 若含单引号会破坏 CSS（轻则样式失效，重则可注入额外 CSS 规则）。

**修复**：

```python
import html as _html

safe_font = _html.escape(font_name, quote=True)
for i, q in enumerate(questions, 1):
    parts.append(f"<div class='q-header'>第 {i} 题</div>")
    for line in q:
        parts.append(f"<div class='q'>{_html.escape(line)}</div>")
...
f"body {{ ... font-family: '{safe_font}'; ... }}"
```

同理，`_on_finished` 中插入 `folder` 路径的 `<a href="folder:{folder}">` 也应做 `_html.escape(folder, quote=True)`。

---

### 3. 输出路径可与模板路径相同 → 文件损坏风险；且删除首页使用私有 API 不够健壮
**位置**：`utils.py:266-276`（`generate_pptx`）+ `word_2_slide_tool.py:663-675`（调用）

- `generate_pptx` 以 `template_path` 打开 `Presentation` 并保存到 `output_path`。若用户把“输出路径”选成与模板同一文件，会在读同一 zip 的同时写同一文件，**可能损坏 PPTX**。
- 删除模板首页依赖私有 API：`prs.slides._sldIdLst[0].get(qn('r:id'))` 取到的 `rId` 若为 `None`（极个别模板），`prs.part.drop_rel(None)` 会抛 `KeyError`，直接让整个转换线程崩溃。

**修复**：

```python
def generate_pptx(template_path, questions, ...):
    if os.path.abspath(template_path) == os.path.abspath(output_path):
        raise ValueError("输出路径不能与模板路径相同")
    prs = Presentation(template_path)
    if prs.slides:
        first = prs.slides[0]
        rId = first._element.get(qn('r:id'))   # 注意是从 slide 元素取，不是从 sldIdLst
        if rId is not None:
            prs.part.drop_rel(rId)
        # 用公开方式移除：prs.slides 没有 remove，但可通过 _sldIdLst 删除
        sldIdLst = prs.slides._sldIdLst
        for i, sldId in enumerate(sldIdLst):
            if sldId.get(qn('r:id')) == rId:
                del sldIdLst[i]
                break
    ...
```

建议长期用 `python-pptx` 的公开 API 或封装一个 `remove_slide()` 工具函数，避免直接操作 `_sldIdLst`。

---

### 4. 相似度工具硬编码题号/选项格式与阈值，忽略文档真实排版
**位置**：`similarity_checker.py:592-598`（`_start_one_to_many`）+ `:612-617`（`_start_many_to_many`）

```python
self._worker = CheckerWorker(
    self._main_path, self._secondary_paths,
    "1.",   # 硬编码题号格式
    "A.",   # 硬编码选项前缀
    0.8,    # 硬编码阈值
)
```

`SimilarityCheckerTool` 根本没有暴露题号格式、选项前缀、匹配阈值的输入控件。对于使用「`1、`」「`(1)`」「`一、`」或中文选项「A．」的文档，`extract_questions` 会退回内置宽泛正则，但**阈值不可调**，且无法像 `Quiz2SlideTool` 那样指定精确格式 → 大量漏检/误检。

**修复**：复用 `Quiz2SlideTool` 已有的「题号格式 / 选项前缀」输入控件，并增加一个阈值 `QDoubleSpinBox`（如 0.6–0.95，默认 0.8），把它们透传给 `CheckerWorker`。

---

### 5. 后台 Worker 线程未被管理 —— 重复点击会 orphan 线程、信号可能重复触发
**位置**：`similarity_checker.py:592-601 / 612-620`（每次新建 `self._worker`）+ `word_2_slide_tool.py:663-675`

每次点击「开始检测 / 开始转换」都新建一个线程并覆盖 `self._worker`：
- 上一个仍在运行的线程变成“孤儿”继续跑，两个 `finished` 信号可能都打到 `_on_finished`（`similarity_checker.py:625`），导致 UI 被覆盖/重复导出；
- 没有 `quit()` / `wait()`，存在线程与对象生命周期隐患。

**修复**（以相似度工具为例，转换工具同理）：

```python
def _start_one_to_many(self):
    ...
    if getattr(self, '_worker', None) and self._worker.isRunning():
        self._worker.quit()
        self._worker.wait()
    self._worker = CheckerWorker(...)
    self._worker.log.connect(self._on_log)
    self._worker.finished.connect(self._on_finished)
    self._worker.start()
```

并建议用 `self._worker.finished.connect(self._worker.deleteLater)` 释放资源。

---

## 🟡 建议优化（推荐修改）

### A. 类型提示普遍缺失
`utils.py` 的所有公开函数（`extract_questions`、`generate_pptx`、`_resolve_line_spacing` 等）和大量方法（如 `Quiz2SlideTool.get_name` 重写时丢了 `-> str`、`on_convert`、`_build_main` 等）都没有参数/返回值注解。建议：

```python
from typing import List

def extract_questions(doc_path: str, num_pattern: str, opt_prefix: str) -> List[List[str]]: ...
def generate_pptx(template_path: str, questions: List[List[str]], font_name: str,
                  font_size: int, output_path: str, line_spacing_type: str = "1 倍",
                  line_spacing_value: float = 1.0, first_line_indent: bool = True,
                  progress_cb=None) -> None: ...
```

`progress_cb` 可用 `Callable[[int, int], None] | None`。

### B. DRY 严重违规：QSS 样式字符串在 3 个文件中重复
卡片、进度条、分隔线、section 标题、输入框聚焦样式等在 `widgets.py`、`similarity_checker.py`、`word_2_slide_tool.py` 中**逐字复制**。主题切换时三处都要改，极易不一致。

**建议**：在 `theme.py` 的 `Theme` 上提供方法式属性，例如：
```python
@property
def qss_progress_bar(self) -> str:
    return (f"QProgressBar {{ border: none; background: {self.progress_bg}; "
            f"border-radius: 3px; height: 6px; }}"
            f"QProgressBar::chunk {{ background: {self.progress_chunk}; border-radius: 3px; }}")
```
各工具只调用 `t.qss_progress_bar`，样式集中维护。

### C. 主题刷新/重绘逻辑重复 → 抽到 `BaseTool`
`_setup_background` / `_on_theme_changed` / `_restyle_all` 在 `app.py`、`similarity_checker.py`、`word_2_slide_tool.py` 中结构雷同。建议在 `BaseTool` 中提供默认实现：
```python
class BaseTool(QWidget):
    def _on_theme_changed(self):
        self.theme.refresh()
        self._restyle_all()
    def _restyle_all(self):
        """子类重写以应用自身样式。"""
        ...
```
子类只实现 `_restyle_all`，消除重复。

### D. `on_convert` 过长（约 120 行），违反「单函数 ≤ 50 行」
`word_2_slide_tool.py:559-675` 把校验、提取、构建 HTML、弹窗、启动线程全塞在一个方法里。建议拆出：
- `_extract_and_preview(questions) -> bool`（构建并展示识别结果对话框）
- `_build_preview_html(questions, font_name, ...) -> str`
- `_start_convert(...)`（启动 `ConvertWorker`）

### E. 题目提取在 GUI 主线程同步执行
`word_2_slide_tool.py:570` 的 `extract_questions(...)` 直接跑在界面线程，大文档会造成短暂卡顿（相似度工具已放入 `QThread`，此处却没放）。建议把「提取 + 预览」也放进 `ConvertWorker` 之前的准备线程，或至少用 `QApplication.processEvents()` + 进度提示。

### F. 文件句柄未用上下文管理器释放
`Document(doc_path)` / `Presentation(template_path)` 均未 `close()`（python-docx / python-pptx 底层 `ZipFile` 依赖 GC 关闭）。在批量/循环场景下可能堆积句柄。建议对只读场景用 `with` 或在完成后显式释放（若库支持）。至少应在 `extract_questions` 入口做文件存在性/可读性校验，避免 `Document` 抛未分类异常被 `except Exception` 吞成模糊字符串。

### G. 相对路径资源脆弱
- `app.py:25`：`QApplication.setWindowIcon(QIcon("./assets/images/logo.png"))` 依赖进程 cwd；
- `word_2_slide_tool.py:789`：`get_resource_path` 用 `os.path.abspath('.')` 而非脚本目录。

建议统一用 `os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "images", "logo.png")`，并复用已有的 `get_resource_path`。

### H. 控制台 `print` 混用
`word_2_slide_tool.py:576/705/708` 在 GUI 程序里用 `print` 输出进度与结果。建议改走 `ToastNotification` / 日志文件 / `logging`，避免终端噪声且便于排查。

### I. 状态残留
`SimilarityCheckerTool._on_check` 启动新检测前未清空 `self._last_result`；若新检测出错提前返回，`_last_result` 仍是上一次成功结果，用户可能导出陈旧报告。建议在 `_on_check` 开头 `self._last_result = None`。

### J. `setCurrentText` 默认值在非目标平台可能失效
`_load_settings` 默认字体 `"微软雅黑"` 在 macOS 上不存在，`setCurrentText` 只是把文本设成该字面值，`generate_pptx` 会用不存在的字体名（回退渲染）。建议从 `system_fonts[0]` 取默认值，或校验字体是否存在。

---

## 🟢 亮点（值得保持）

- **后台计算与 UI 解耦做得好**：相似度检测（`CheckerWorker` / `ManyToManyWorker`）与 PPT 生成（`ConvertWorker`）都用 `QThread` + `Signal` 把进度/结果抛回主线程，主界面不阻塞。
- **信号/槽职责清晰**：`log` / `finished` / `progress_text` 分层，线程安全（跨线程信号由 Qt 排队派发）。
- **主题抽象到位**：`Theme` 集中管理深/浅色配色，并监听系统 `colorSchemeChanged` 自动切换，思路正确。
- **正则构建策略巧妙**：`_build_num_regex` / `_build_opt_regex` 自动区分「格式示例 / 原始正则 / 兜底」，对中文试卷的 `1.` `1、` `1．` 等变体兼容性好，是本项目最有价值的设计。
- **行内多选项拆分**：`_split_inline_options` 正确处理了「`A. xxx B. xxx`」同行选项，边界考虑细致。
- **题目有效性双重校验**：`_finish_question` 要求题干非空且至少 2 个选项，过滤噪声可靠。
- **可复用控件库**：`AppButton` / `AnimatedButton` / `AnimatedProgressBar` / `ToastNotification` / `DropZone` 接口一致、带主题驱动，工程质量不错。
- **异常兜底合理**：Worker 内 `try/except` 把错误收敛为 `{"error": ...}` 回传，避免线程静默崩溃。
- **用户偏好持久化**：`QSettings` 保存题号格式/字体/字号，体验友好。
- **f-string 使用一致**，字符串格式化规范。

---

## 总结

整体架构清晰、职责划分合理，后台线程与主题系统是亮点；**核心风险集中在「相似度检测 1对多模式的入参类型错误（#1）」和「预览 HTML 未转义（#2）」**——前者会直接导致查重结果不可信、两种模式不一致，后者存在内容注入与布局破坏，二者都应在合入前修复；其余多为可维护性（DRY/类型提示/长函数）与健壮性（线程管理/路径/资源释放）层面的改进，建议排入后续迭代。
