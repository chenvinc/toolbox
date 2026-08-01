# 新增 Tool 开发指南（v4.0）

> 配套文档：[项目架构书（v4.0）](./architecture.md)
> 本文以「新增一个 `Demo` 工具」为例，给出从契约到注册的**全链路步骤、可复制代码模板与避坑清单**。所有 API 名、信号、方法签名均与 v4.0 真实代码一致。

---

## 0. 一句话流程

```
shared/contracts.py   Request / Result / EventType / 事件模型
        ↓
core/ports/          （可选）新增 Service / IO Protocol
        ↓
core/adapters/       封装第三方库（如需）
        ↓
core/services/        业务编排 + emitter.emit(进度/完成)
        ↓
core/services/__init__  补导出
core/di.py            注册到容器
        ↓
ui/viewmodels/        ViewModel 胶水（命令转发 + 事件→信号）
        ↓
ui/views/             View 渲染（BaseView 子类 + 统一样式模式）
        ↓
app.py                装配 VM + 注册 View
```

> 重要前提：**`core` / `shared` 零 Qt 依赖**。在 `core` 里 `import PySide6` 即为架构违规。

---

## 1. 后端契约（`shared/contracts.py`）

在 `class EventType` 中新增**专属**三个成员（共用 emitter，必须唯一，否则串台）：

```python
class EventType(str, Enum):
    # ...既有...
    DEMO_PROGRESS = "demo_progress"
    DEMO_COMPLETED = "demo_completed"
    DEMO_FAILED = "demo_failed"
```

新增 Request / Result（Pydantic `BaseModel`）：

```python
class DemoRequest(BaseModel):
    input_path: str
    output_path: str
    threshold: float = 0.8


class DemoResult(BaseModel):
    output_path: str
    item_count: int
```

新增事件模型（失败事件建议**单独建类**，避免与 `FailedEvent` 的 `Literal` 冲突）：

```python
class DemoCompletedEvent(_BaseEvent):
    type: Literal[EventType.DEMO_COMPLETED] = EventType.DEMO_COMPLETED
    result: DemoResult


class DemoFailedEvent(_BaseEvent):
    type: Literal[EventType.DEMO_FAILED] = EventType.DEMO_FAILED
    message: str
```

并把它们追加进 `DomainEvent` 的 `Union`（以 `type` 判别）：

```python
DomainEvent = Annotated[
    Union[
        # ...既有...
        DemoCompletedEvent, DemoFailedEvent,
        ProgressEvent,          # 进度复用通用 ProgressEvent，需把 DEMO_PROGRESS 加进其 Literal
    ],
    Field(discriminator="type"),
]
```

若 `ProgressEvent` 的 `Literal` 未包含 `DEMO_PROGRESS`，请补上：

```python
class ProgressEvent(_BaseEvent):
    type: Literal[
        EventType.CHECK_PROGRESS, EventType.PPTX_PROGRESS,
        EventType.EXAM_PROGRESS, EventType.PDF_PROGRESS,
        EventType.DEMO_PROGRESS,
    ] = EventType.CHECK_PROGRESS
```

> 若需 UI 按异常类型分流，在 `shared/errors.py` 新增继承 `ToolboxError` 的异常（如 `DemoReadError`）。

---

## 2. 端口（`core/ports/`）（如需要）

**业务端口**（`services.py`）：新增 `@runtime_checkable Protocol`。

```python
@runtime_checkable
class DemoService(Protocol):
    def run(self, request: DemoRequest) -> DemoResult: ...
```

**IO 端口**（`io.py`，仅当要封装第三方库时）：

```python
@runtime_checkable
class DemoWriter(Protocol):
    def build(self, request: DemoRequest,
              on_progress: Callable[[int, int], None]) -> DemoResult: ...
```

> Protocol 用结构化子类型，**适配器不继承任何基类**，仅方法签名匹配即可。`TaskHandle` / `TaskRunner` / `EventEmitter` 端口已存在，无需新增。

---

## 3. 适配器（`core/adapters/xxx.py`）（如需要）

```python
"""Demo 适配器：封装第三方库（零 Qt）。"""
from __future__ import annotations
from core.ports.io import DemoWriter
from shared.contracts import DemoRequest, DemoResult


class DemoWriterAdapter:
    """实现 DemoWriter 端口。"""
    def build(self, request: DemoRequest,
              on_progress: Callable[[int, int], None]) -> DemoResult:
        # TODO: 调用第三方库（如 docx/pptx/pymupdf）
        on_progress(1, 1)
        return DemoResult(output_path=request.output_path, item_count=0)
```

---

## 4. 服务（`core/services/demo_service.py`）

```python
"""Demo 服务实现（零 Qt）。"""
from __future__ import annotations
from core.ports.events import EventEmitter
from core.ports.io import DemoWriter
from shared.contracts import (
    DemoCompletedEvent, DemoRequest, DemoResult, EventType, ProgressEvent,
)


class DemoServiceImpl:
    def __init__(self, writer: DemoWriter, emitter: EventEmitter) -> None:
        self._writer = writer
        self._emitter = emitter

    def run(self, request: DemoRequest) -> DemoResult:
        total = 1
        self._emitter.emit(ProgressEvent(
            type=EventType.DEMO_PROGRESS, message="准备中...", current=0, total=total))
        result = self._writer.build(request, self._on_progress)
        self._emitter.emit(ProgressEvent(
            type=EventType.DEMO_PROGRESS, message="完成", current=total, total=total))
        self._emitter.emit(DemoCompletedEvent(result=result))
        return result

    def _on_progress(self, cur: int, tot: int) -> None:
        self._emitter.emit(ProgressEvent(
            type=EventType.DEMO_PROGRESS,
            message=f"处理 {cur}/{tot}", current=cur, total=tot))
```

> 失败以业务异常形式抛出（由 VM 的 `on_async_error` 桥接为失败信号），不要在服务里吞异常或重复发失败事件。
> 路径保护类服务请校验「输出 ≠ 模板/源」，抛 `OutputOverwriteError`。

### 4.1 补齐导出
`core/services/__init__.py` **务必补导出**（现存两个服务已遗漏，别再漏）：

```python
from .demo_service import DemoServiceImpl
__all__ = [..., "DemoServiceImpl"]
```

### 4.2 注册到容器（`core/di.py`）
在 `Container.build` 中实例化并 `register`：

```python
from core.adapters.demo_writer import DemoWriterAdapter
from core.services.demo_service import DemoServiceImpl
# ...
demo_writer = DemoWriterAdapter()
c.register("demo", DemoServiceImpl(demo_writer, event_emitter))
```

> `register` 是裸 `dict` 查表，key 用约定字符串（如 `"demo"`）。

---

## 5. ViewModel（`ui/viewmodels/demo_viewmodel.py`）

> **继承 `BaseViewModel`**（v4.0 抽取，见 `ui/viewmodels/base_viewmodel.py`）。基类已提供：构造时持有 `task_runner`/`event_emitter` 并订阅事件、`cancel_current()`、`_on_event` 模板方法（**内置 `_WATCHED` 串台防护**）。子类只需：① 声明类属性 `_WATCHED`；② 实现 `_dispatch` 与 `on_async_error`；③ 把业务 `service` 存到 `self._service`，并把 `_current_task` 存到 `self._current_task`。

```python
from __future__ import annotations
from PySide6.QtCore import Signal
from core.ports.services import DemoService
from core.ports.tasks import TaskHandle
from shared.contracts import (
    DemoCompletedEvent, DemoFailedEvent, DemoRequest, DomainEvent, EventType,
    ProgressEvent,
)
from ui.infra.qt_task_runner import async_task
from ui.viewmodels.base_viewmodel import BaseViewModel


class DemoViewModel(BaseViewModel):
    # _WATCHED 声明本 VM 关心的事件类型；基类按它过滤，避免与其它工具串台
    _WATCHED = frozenset({
        EventType.DEMO_PROGRESS,
        EventType.DEMO_COMPLETED,
        EventType.DEMO_FAILED,
    })

    progress = Signal(str, int, int)       # message, current, total
    completed = Signal(object)             # DemoResult
    failed = Signal(object)                # 抛异常本体，供视图 isinstance 分流

    def __init__(self, service: DemoService,
                 task_runner,
                 event_emitter) -> None:
        # 基类负责：持有 task_runner/event_emitter、订阅事件、提供 cancel_current
        super().__init__(event_emitter, task_runner)
        self._service = service
        self._task_runner = task_runner    # ⚠️ 字段必须叫 _task_runner（@async_task 用 getattr 找）
        self._current_task: TaskHandle | None = None

    def on_async_error(self, exc: Exception) -> None:
        # 后台异常（@async_task 触发）桥接为失败信号；建议发异常本体
        self.failed.emit(exc)

    def _dispatch(self, event: DomainEvent) -> None:
        # 基类已按 _WATCHED 过滤，这里只处理本工具关心的事件
        if event.type == EventType.DEMO_PROGRESS:
            self.progress.emit(event.message, event.current, event.total)
        elif event.type == EventType.DEMO_COMPLETED:
            self.completed.emit(event.result)
        elif event.type == EventType.DEMO_FAILED:
            self.failed.emit(event.message)

    @async_task
    def run(self, request: DemoRequest) -> DemoResult:
        return self._service.run(request)
```

> ⚠️ `failed` 统一用 `Signal(object)`、`on_async_error` 发异常本体，供视图 `isinstance` 分流（以 `JsonExamViewModel` 为范本）。
> ⚠️ 所有 VM 共用同一个 `QtEventEmitter`；基类 `_on_event` 已按 `_WATCHED` 过滤、只把关心的事件分发到 `_dispatch`。因此 §1 的专属 `EventType` 务必新增且唯一——配错 `_WATCHED` 会漏收或误收事件。

---

## 6. View（`ui/views/demo_view.py`）

继承 `BaseView`，严格遵循统一构造与样式模式（以 `SimilarityView` 为范本，其 `_restyle_all` 最完整）。

```python
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea, QVBoxLayout, QWidget
from PySide6.QtGui import QPalette
from ui.views.base_view import BaseView
from ui.infra.preview_escape import escape_preview_line  # 需要预览 HTML 时
from widgets import AppButton, AnimatedButton, AnimatedProgressBar, ToastNotification
from theme import get_theme


class DemoView(BaseView):
    def get_name(self) -> str:
        return "Demo"

    def get_nav_title(self) -> str:
        return "🧩 Demo 示例"          # "<emoji> <中文>"

    def get_description(self) -> str:
        return "演示新增 Tool 的标准骨架。"   # 一句话，以 。结尾

    def __init__(self, view_model) -> None:
        super().__init__()
        self._vm = view_model
        self.theme = get_theme()                  # 全局单例（推荐），或 Theme()
        # 业务状态字段 ...
        self.settings = QSettings("Demo", "Demo")   # 两参数同名；键名集中到 ui/infra/settings_keys.py 的 DemoKeys 常量
        self._field_labels: list = []
        self._section_labels: list = []
        self._module_cards: list = []
        self._setup_ui()
        self._connect_view_model()
        self._load_settings()
        # 集中刷新：app.py 保留唯一 colorSchemeChanged 接线触发 theme.refresh()，
        # refresh() 会广播 Theme.theme_changed，各 View 订阅它即可（无需各自连 OS 信号）
        self.theme.theme_changed.connect(self._on_theme_changed)

    # ---- UI 构建 ----
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(self.theme.page_pad_x, self.theme.page_pad_y,
                                self.theme.page_pad_x, self.theme.page_pad_y)
        root.setSpacing(0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        root.addWidget(self._scroll)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(self.theme.spacing)
        self._scroll.setWidget(content)

        self._make_module_card("模块")            # 复制标准实现
        self.progress_bar = AnimatedProgressBar()
        self.toast = ToastNotification(self, theme=self.theme)
        self._update_demo_state()
        self._restyle_all()

    def _make_module_card(self, title: str):
        # 与既有 4 个 View 逐字相同：QFrame(objectName=module_card) + QVBoxLayout
        # setContentsMargins(theme.page_pad_y, theme.spacing, theme.page_pad_y, theme.spacing)
        # + QLabel(title, objectName=card_title)
        # 追加到 _section_labels 与 _module_cards，return card, layout
        ...

    def _make_labeled_field(self, label_text, widget):
        # 透明 QWidget + QVBoxLayout(0,2) + label(入 _field_labels) + widget
        ...

    # ---- 信号绑定 ----
    def _connect_view_model(self) -> None:
        self._vm.progress.connect(self._on_progress)
        self._vm.completed.connect(self._on_completed)
        self._vm.failed.connect(self._on_failed)

    # ---- 主题热切换（订阅 theme_changed，禁止在此调 refresh()，否则自触发死循环） ----
    def _on_theme_changed(self) -> None:
        self._restyle_all()

    def _restyle_all(self) -> None:
        t = self.theme
        pal = self.palette()
        pal.setColor(QPalette.Window, t.window_solid_bg)
        self.setPalette(pal)
        self.setAutoFillBackground(True)
        for card in self._module_cards:
            card.setStyleSheet(t.qss_card())
        for lbl in self._field_labels:
            lbl.setStyleSheet(f"font-size:12px;color:{t.text_secondary};margin-bottom:2px;")
        for lbl in self._section_labels:
            lbl.setStyleSheet(t.qss_section_header())
        self.progress_bar.setStyleSheet(t.qss_progress_bar())
        # 所有 AppButton.set_theme(t)（按钮须存成实例属性！）
        # 所有 StepperInput.set_theme(t)
        # DropZone: dz._theme = t; dz._apply_style()   ← 别忘了
        self._scroll.setStyleSheet(   # 复制既有 4 份逐字相同的滚动条样式块
            f"QScrollBar:vertical{{width:6px;background:transparent;}}"
            f"QScrollBar::handle:vertical{{background:{t.scrollbar_handle};"
            f"border-radius:3px;min-height:30px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}")

    # ---- 持久化 ----
    def _load_settings(self) -> None:
        # blockSignals(True) 包裹全部 setText/setValue/setChecked，避免半载写回
        ...

    def _save_settings(self) -> None:
        # 键名用 ui/infra/settings_keys.py 的常量；布尔直接存真 bool，勿存 "true"/"false" 字符串
        self.settings.setValue(DemoKeys.THRESHOLD, self._threshold_spin.value())

    # ---- 命令入口 ----
    def on_run(self) -> None:
        if self._run_btn._loading:
            return
        self._update_demo_state()
        self._vm.run(DemoRequest(input_path=..., output_path=...))

    def _update_demo_state(self) -> None:
        self._run_btn.set_actionable(bool(self._input_path), "请先选择输入文件")

    # ---- 事件处理 ----
    def _on_progress(self, msg, cur, tot): ...
    def _on_completed(self, result): ...
    def _on_failed(self, msg):
        # failed 载荷可能是 str（领域失败事件 message）或 Exception（on_async_error 透传）
        text = msg if isinstance(msg, str) else str(msg)
        self.toast.show_message(text, success=False)

    # ---- 必须实现 stop_worker ----
    def stop_worker(self) -> None:
        self._vm.cancel_current()
```

### View 避坑清单
1. **按钮必须存成实例属性**再 `set_theme`，否则 `_restyle_all` 刷不到（`SlideView.change_btn` 的教训）。
2. **DropZone 的 `theme` 必传**：`theme=None` 会 `AttributeError`。
3. **`StepperInput` 在 `QSpinBox` 模式下 `valueChanged` 不发射**，需手动把 ± 按钮 `clicked` 接到保存逻辑。
4. **`AppButton.setEnabled` 被重写**为 `set_actionable(enabled, "")`，会清空已设禁用原因——禁用提示请用 `set_actionable(False, reason)`。
5. 颜色/圆角一律走 `self.theme.*`，**禁止硬编码色值**（字号可保留 12/13px 现状）。
6. 需要预览 HTML 时，正文用 `escape_preview_line()`，CSS 字体名用 `sanitize_font_name()`。
7. **「打开文件夹」**统一用富文本链接，并在 `linkActivated` 回调里调用 `ui.infra.open_folder.open_folder(path)`（自动剥离 `folder:` 前缀、跨平台派发、不阻塞、失败仅 warning）：
   `<a href="folder:{folder}" style="color:{theme.accent};text-decoration:underline;">打开文件夹</a>`，配合 `label.setTextFormat(Qt.RichText)` + `linkActivated.connect(self._open_output_folder)`。

---

## 7. 注册（`app.py`）

```python
from ui.viewmodels.demo_viewmodel import DemoViewModel
from ui.views.demo_view import DemoView

# 在 _apply_global_font 中造 VM：
demo_vm = DemoViewModel(container.resolve("demo"), self._task_runner, self._event_emitter)

# 在 _register_tools 中注册：
self._add_tool(DemoView(demo_vm))
```

`_add_tool` 自动用 `get_nav_title()` 作导航项、`f"{get_name()}\n{get_description()}"` 作 tooltip；切换时调 `on_activate()`（如需初始化可重写，否则空实现即可）。
`closeEvent` 会通过 `getattr(tool, 'stop_worker', None)` 鸭子类型调用你的 `stop_worker()`，**必须实现**。

---

## 8. 端到端自检清单

- [ ] `EventType` 新增 `DEMO_PROGRESS/COMPLETED/FAILED`，且唯一
- [ ] `DomainEvent` 与 `ProgressEvent.Literal` 已纳入新类型
- [ ] `core/ports` 新增 Protocol（如需要）
- [ ] `core/adapters` 仅封装第三方库，零 Qt
- [ ] `core/services/demo_service.py` 内 `emitter.emit(进度/完成)`
- [ ] `core/services/__init__.py` 已补导出
- [ ] `core/di.py` 已 `register("demo", ...)`
- [ ] `ui/viewmodels` 继承 `BaseViewModel`，声明 `_WATCHED`，实现 `_dispatch` / `on_async_error` 与 `@async_task` 命令（`cancel_current` 已继承）
- [ ] `ui/views` 继承 `BaseView`，含三列表、`_restyle_all`、`_load_settings(blockSignals)`、`stop_worker`
- [ ] `app.py` 装配 VM + `_add_tool`
- [ ] `pytest` 通过（core 层可脱离 Qt 单测）

---

## 9. 常见错误（来自真实代码库）

| 错误 | 现象 | 修正 |
| --- | --- | --- |
| 忘记给新服务补 `__init__.py` 导出 | `di.py` 仅能从子模块 import，易漏 | 同步 `core/services/__init__.py` 的 import 与 `__all__` |
| 复用既有 `EventType` | 多个 VM 串台、信号错乱 | 每个工具用专属 `EventType` |
| VM 字段不叫 `_task_runner` | `@async_task` 退化成同步执行 | 固定命名为 `self._task_runner` |
| 漏写 `on_async_error` | 后台异常被静默吞掉 | 必须实现，转成 `failed` 信号 |
| View 按钮未存实例属性 | 主题切换后按钮不变色 | 存 `self._btn` 并在 `_restyle_all` 调 `set_theme` |
| DropZone 传 `theme=None` | 构造即 `AttributeError` | 必传 theme |
| 在 `core` 里 import PySide6 | 架构违规、无法脱离 Qt 单测 | 第三方库只放 `core/adapters` |
