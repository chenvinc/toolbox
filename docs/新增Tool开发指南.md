# 新增 Tool 开发指南

> 面向：有一定 Python / PyQt 基础、但不熟悉本仓库的新贡献者。
> 本文所有路径、类名、函数名、配置项均来自对当前代码库的实地调研（见文末「参考资料」）。
> ⚠️ 标注「⚠️ 待确认」之处表示无法从现有代码确定，请勿凭空假设。

---

## 0. 先理解三件事

1. **本项目的 "Tool" 是什么？**
   工具箱里的每一个功能面板（如「📑 题库转PPT」「🔍 试题查重」）在代码里就是被注册到左侧导航栏的一个 **`BaseView` 子类**，由对应的 **`ViewModel`**（胶水层）持有一个 **`core` 层的 Service**（纯业务逻辑）。
   换句话说，"新增一个 Tool" = "新增一条 契约 → Service → ViewModel → View → 注册" 的链路。

2. **分层是硬约束，不是建议。**
   - `shared/`：前后端共享契约（Pydantic 模型）+ 统一异常。**零 Qt 依赖。**
   - `core/`：纯 Python 后端业务。**零 Qt 依赖**（禁止 `import PySide6` / `Qt*`）。所有文件 IO、线程、UI 副作用都通过 **端口（Protocol）注入**。
   - `ui/`：PySide6 前端。其中 `ui/infra/` 是端口的 Qt 实现（如 `QtTaskRunner` / `QtEventEmitter`），`ui/viewmodels/` 是胶水层，`ui/views/` 只负责渲染。

3. **数据流是单向的。**
   - UI → core：UI 构造一个 `Request`（Pydantic 模型）交给 ViewModel，ViewModel 经 `@async_task` 把同步 service 方法丢到后台线程。
   - core → UI：core 通过 `EventEmitter.emit(DomainEvent)` 推送事件；ViewModel 把事件翻译为 Qt 信号供 View 绑定。
   - **core 绝不持有、绝不返回任何 QWidget / QPixmap / Signal。**

权威的内部设计说明见 `docs/architecture.md`，其中第 8 节「新增功能开发指南」已概述三步流程，本文是对它的可执行展开。

---

## 1. 前置准备

### 1.1 技术栈约束（从真实配置提取）

| 项目 | 约束 | 来源 |
|------|------|------|
| Python 版本 | **3.13** | `mypy.ini` 的 `python_version = 3.13`；现有 `.venv` 基于 miniconda 3.13.12 构建 |
| 依赖管理 | `requirements.txt`，**固定次版本** | `python-docx==1.2.0`、`python-pptx==1.0.2`、`PySide6==6.11.1`、`pydantic>=2.5` |
| 类型检查 | **mypy `--strict`**（核心项全开） | `mypy.ini`：`disallow_untyped_defs`、`disallow_incomplete_defs`、`no_implicit_optional`、`warn_return_any`、`no_implicit_reexport` 等 |
| 契约载体 | Pydantic `BaseModel`（唯一新增依赖） | `shared/contracts.py` 顶部说明 |
| 测试框架 | `unittest` 风格用例 + `pytest` 运行器 | 全部测试文件均为 `unittest.TestCase`，根目录无 `pytest.ini`/`pyproject.toml`，直接用 `pytest` 收集 |

> ⚠️ 待确认：仓库根目录**未找到** `README.md` / `CONTRIBUTING.md` / `Makefile` / CI 工作流文件。若团队已有 onboarding 文档或 CI，请补充并链接到本文。

### 1.2 环境搭建（从真实文件提取，未臆造）

```bash
# 1) 用 Python 3.13 建虚拟环境（命令为通用标准，与 mypy.ini 的版本号一致）
python3 -m venv .venv

# 2) 安装依赖（版本号来自 requirements.txt）
.venv/bin/pip install -r requirements.txt

# 3) 类型检查（core/ + shared/ 必须零报错，已实地验证通过）
.venv/bin/mypy --strict shared core

# 4) 跑测试（详见第 4 节；集成测试需 offscreen 平台）
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --import-mode=importlib -q
```

> 注意：本仓库当前的 `.venv/bin/pytest` 的 shebang 指向一个已不存在的旧路径（`quiz2slide/.venv`）。**不要**直接执行 `.venv/bin/pytest`，请统一用 `.venv/bin/python -m pytest` 调用（已验证可运行）。

### 1.3 目录结构与职责

```
toolbox/
├── shared/
│   ├── contracts.py   # Request / Response / Event 定义（Pydantic），前后端唯一通信契约
│   └── errors.py      # ToolboxError 统一异常体系（core 抛、ui 捕获）
├── core/               # 纯 Python 后端，零 Qt
│   ├── ports/         # Protocol 端口：services / events / tasks / io
│   ├── services/      # 业务实现：slide_builder / similarity_service / _scorer / _question_parser
│   ├── adapters/      # 外部依赖适配：docx_loader / pptx_writer（python-docx / python-pptx 封装）
│   ├── models/        # 领域模型：question.py（Question dataclass）
│   └── di.py         # Container：极简依赖注入容器
├── ui/                # PySide6 前端
│   ├── views/         # BaseView（抽象基类）+ SlideView / SimilarityView
│   ├── viewmodels/    # SlideViewModel / SimilarityViewModel（QObject + Signal + @async_task）
│   └── infra/        # 端口的 Qt 实现：qt_task_runner / qt_event_emitter / preview_escape
├── tests/
│   ├── unit/core/          # core 纯逻辑单测（无 Qt、无 offscreen）
│   ├── integration/        # 前后端接线（ViewModel 层，需要 QApplication）
│   └── test_*.py          # 根级回归（如 test_p2_tech_debt、test_generate_pptx）
├── app.py              # 入口：Container.build → ViewModels → Views 注册到导航栏
├── theme.py / theme.qss / widgets.py  # 主题与基础控件（前端辅助，允许 Qt）
├── requirements.txt / mypy.ini
└── docs/             # architecture.md 等架构/整改报告
```

---

## 2. 新建 Tool 标准流程（Step-by-Step）

> 以新增一个「文本字数统计」Tool 为例（最小可运行，基于真实代码简化）。
> 每个真实构建块都标注了「参考自 …」，可直接对照源码。

### Step 1 — 定义契约（`shared/contracts.py`）

前后端只通过 Pydantic 模型通信，**禁止裸 dict**。

```python
# 在 shared/contracts.py 末尾追加
from typing import Literal
from pydantic import BaseModel, Field

class WordCountRequest(BaseModel):
    """统计一段文本的字符或词数。"""
    text: str = Field(..., min_length=1, description="待统计文本")
    count_type: Literal["char", "word"] = Field("char", description="char=字符数, word=词数")

class WordCountResult(BaseModel):
    """统计结果。"""
    count: int = Field(ge=0, description="统计值")
    count_type: Literal["char", "word"] = "char"
```

> 参考自 `shared/contracts.py` 的 `SimilarityRequest` / `GeneratePptxResult`：`Field(..., ge=0.0, le=1.0)` 等约束会在运行时自动校验，越界即抛 `ValidationError`。

如果你的 Tool 需要向 UI 推送新类型的事件，还需：
1. 在 `EventType`（同文件）新增枚举值；
2. 新增一个事件类（继承 `_BaseEvent`）；
3. 把事件类加入 `DomainEvent` 联合类型（按 `type` 判别）。

```python
class WordCountCompletedEvent(_BaseEvent):
    type: Literal[EventType.WORD_COUNT_COMPLETED] = EventType.WORD_COUNT_COMPLETED
    result: WordCountResult
# 并把 WordCountCompletedEvent 加进文件底部的 DomainEvent 联合类型
```

### Step 2 —（可选）声明端口（`core/ports/services.py`）

如果 Tool 是新的一类业务能力，用 `@runtime_checkable Protocol` 声明端口：

```python
# core/ports/services.py 末尾追加
@runtime_checkable
class WordCountService(Protocol):
    """文本统计服务。"""
    def count(self, request: WordCountRequest) -> WordCountResult: ...
```

> 参考自 `core/ports/services.py` 的 `SimilarityService` / `ExtractionService` / `PptxService`。
> 该 Protocol 仅用于类型约束与可替换性；core 内部通过鸭子类型调用，**不强制继承**。

### Step 3 — 实现 Service（`core/services/`）

新建 `core/services/word_count_service.py`。**纯 Python，零 Qt，依赖通过构造器注入。**

```python
# core/services/word_count_service.py
from __future__ import annotations
from shared.contracts import EventType, WordCountRequest, WordCountResult, WordCountCompletedEvent
from core.ports.events import EventEmitter

class WordCountServiceImpl:
    """文本统计服务实现。"""
    def __init__(self, emitter: EventEmitter) -> None:
        self._emitter = emitter

    def count(self, request: WordCountRequest) -> WordCountResult:
        if request.count_type == "word":
            value = len([w for w in request.text.split() if w.strip()])
        else:
            value = len(request.text)
        result = WordCountResult(count=value, count_type=request.count_type)
        # 可选：推送完成事件（core → UI 的单向通道）
        self._emitter.emit(WordCountCompletedEvent(result=result))
        return result
```

> 参考自 `core/services/slide_builder.py`（`ExtractionServiceImpl` / `PptxServiceImpl`）：
> - 构造器只接收**端口**（`DocumentLoader`、`PptxWriter`、`EventEmitter`），不直接 `import python-docx` / `python-pptx`（那些被限制在 `core/adapters/`）。
> - 凡涉及文件写入（如 PPT 生成），先校验路径再操作；`PptxServiceImpl.generate` 在 `output_path == template_path` 时抛 `OutputOverwriteError`，避免覆盖源文件。
> 若你的 Tool 要读 Word 文档，复用 `DocumentLoader` 端口 + `core/adapters/docx_loader.py` 的 `DocxLoaderAdapter`，解析交给 `core/services/_question_parser.py:parse_questions`。

### Step 4 — 实现 ViewModel（`ui/viewmodels/`）

新建 `ui/viewmodels/word_count_viewmodel.py`。它是胶水层：持有 service，把 `DomainEvent` 桥接为 Qt 信号。

```python
# ui/viewmodels/word_count_viewmodel.py
from __future__ import annotations
from typing import Any
from PySide6.QtCore import QObject, Signal
from core.ports.events import EventEmitter
from core.ports.services import WordCountService
from core.ports.tasks import TaskRunner
from shared.contracts import DomainEvent, EventType, WordCountRequest
from ui.infra.qt_task_runner import async_task

class WordCountViewModel(QObject):
    completed = Signal(object)   # WordCountResult
    failed = Signal(str)

    def __init__(self, svc: WordCountService, task_runner: TaskRunner, event_emitter: EventEmitter) -> None:
        super().__init__()
        self._svc = svc
        self._task_runner = task_runner
        self._emitter = event_emitter
        event_emitter.on_event(self._on_event)

    # 后台异常回调（由 @async_task 触发，必须定义，否则异常被吞）
    def on_async_error(self, exc: Exception) -> None:
        self.failed.emit(str(exc))

    # 供主窗口 closeEvent 清理后台线程
    def cancel_current(self) -> None:
        handle = getattr(self, "_current_task", None)
        if handle is not None:
            handle.cancel()

    def _on_event(self, event: DomainEvent) -> None:
        if event.type == EventType.WORD_COUNT_COMPLETED:
            self.completed.emit(event.result)

    @async_task
    def count(self, request: WordCountRequest) -> Any:
        return self._svc.count(request)
```

> 参考自 `ui/viewmodels/similarity_viewmodel.py` 与 `ui/viewmodels/slide_viewmodel.py`：
> - 必须定义 `on_async_error(self, exc)`，`@async_task` 在后台抛异常时会回调它。
> - 必须定义 `cancel_current()`，供 `app.py` 的 `closeEvent` 关闭孤儿线程。
> - 命令转发方法用 `@async_task` 装饰，签名与 service 方法一致。

### Step 5 — 实现 View（`ui/views/`）

新建 `ui/views/word_count_view.py`，继承 `BaseView`，实现 `get_name` / `get_nav_title` / `get_description`，并在 `__init__` 中接收 ViewModel。

```python
# ui/views/word_count_view.py（仅示意核心骨架）
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QLabel, QPushButton
from ui.views.base_view import BaseView
from ui.viewmodels.word_count_viewmodel import WordCountViewModel

class WordCountView(BaseView):
    def get_name(self) -> str:
        return "WordCount"
    def get_nav_title(self) -> str:
        return "🔢 字数统计"
    def get_description(self) -> str:
        return "统计文本字符数或词数。"

    def __init__(self, view_model: WordCountViewModel) -> None:
        super().__init__()
        self._vm = view_model
        self._setup_ui()
        self._connect_view_model()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        self._input = QTextEdit()
        self._output = QLabel("")
        self._btn = QPushButton("开始统计")
        self._btn.clicked.connect(self.on_count)
        root.addWidget(self._input)
        root.addWidget(self._btn)
        root.addWidget(self._output)

    def _connect_view_model(self):
        self._vm.completed.connect(lambda r: self._output.setText(f"结果：{r.count}"))
        self._vm.failed.connect(lambda m: self._output.setText(f"失败：{m}"))

    def on_count(self):
        # 构造 Request 交给 ViewModel（UI → core 单向数据流）
        from shared.contracts import WordCountRequest
        self._vm.count(WordCountRequest(text=self._input.toPlainText(), count_type="char"))

    def stop_worker(self):
        """供主窗口 closeEvent 调用。"""
        self._vm.cancel_current()
```

> 参考自 `ui/views/base_view.py`（`BaseView` 抽象基类：约定 `get_name` / `get_description` 必须实现，`get_nav_title` 可重写，`on_activate` 可选重写）与 `ui/views/slide_view.py`（完整的 View 范例：模块卡片 `_make_module_card`、主题重绘 `_restyle_all`、QSettings 持久化）。

---

## 3. 注册与集成

> 本仓库**没有自动发现（auto-discovery）机制**。新 Tool 需要手动：
> 1. 在 DI 容器注册 service；
> 2. 在 `app.py` 实例化 ViewModel + View 并加入导航栏。

### 3.1 在 `core/di.py` 注册 service

```python
# core/di.py —— 在 build() 内新增
from core.services.word_count_service import WordCountServiceImpl

class Container:
    @classmethod
    def build(cls, *, task_runner, event_emitter):
        ...
        word_count = WordCountServiceImpl(event_emitter)   # 按构造器注入端口
        c.register("word_count", word_count)
        ...
```

> 参考自 `core/di.py` 的 `Container.build`：生产环境由 `app.py` 传入 `QtTaskRunner()` / `QtEventEmitter()`；测试环境用 `SyncTaskRunner` / `CollectingEmitter` 替身。

### 3.2 在 `app.py` 接线并注册

```python
# app.py —— 顶部新增 import
from ui.viewmodels.word_count_viewmodel import WordCountViewModel
from ui.views.word_count_view import WordCountView

# 在 ToolboxApp.__init__ 内，仿照 slide_vm / sim_vm：
wc_vm = WordCountViewModel(
    container.resolve("word_count"),
    self._task_runner,
    self._event_emitter,
)

# 在 _register_tools 内追加：
def _register_tools(self, slide_vm, sim_vm, wc_vm):
    self._add_tool(SlideView(slide_vm))
    self._add_tool(SimilarityView(sim_vm))
    self._add_tool(WordCountView(wc_vm))   # 新工具出现于导航栏
```

> 参考自 `app.py`：`_register_tools` → `_add_tool` 会把 View 加入左侧 `QListWidget` 导航栏与 `QStackedWidget` 主区，`nav_list.currentRowChanged` 触发 `_on_nav_changed` → 调用 `view.on_activate()`。
> `closeEvent` 会遍历 `self._tools` 调 `stop_worker`（若存在），因此每个启动后台任务的 View 必须实现 `stop_worker()`。

### 3.3 需要同步更新的元数据 / 文档字段

| 位置 | 动作 |
|------|------|
| `shared/contracts.py` | 新增 `XxxRequest` / `XxxResult`；若新增事件，改 `EventType` + 事件类 + `DomainEvent` |
| `core/ports/services.py` | 若为新业务类，新增 `XxxService(Protocol)` |
| `core/di.py` | `Container.build` 内 `register("xxx", ...)` |
| `app.py` | import + `_register_tools` 内 `_add_tool(XxxView(vm))` |
| `ui/viewmodels/` + `ui/views/` | 新增 ViewModel / View 文件 |
| `tests/unit/core/` + `tests/integration/` | 新增对应单测 / 集成测试（见第 4 节） |
| `docs/architecture.md` §8 | ⚠️ 待确认：是否在此同步记录新 Tool；建议补充以便后人追溯 |

> ⚠️ 待确认：仓库根目录无 `README.md` / `CONTRIBUTING.md`，没有统一的「已实现 Tool 清单」文档。如有，请在此处登记新 Tool 名称与职责。

---

## 4. 测试与验证

### 4.1 单元测试规范（core 层，无 Qt、无 offscreen）

core 逻辑测试的核心是**用替身（fake）注入端口**，不碰真实文件系统与 GUI。项目里有两个现成范式：

**范式 A — 纯 service 测试**（`tests/unit/core/test_similarity_service.py`）：
- 用 `PathMapLoader`（实现 `DocumentLoader` 端口，按路径返回预设段落）替代 `DocxLoaderAdapter`；
- 用 `CollectingEmitter`（实现 `EventEmitter` 端口，收集所有事件）替代 `QtEventEmitter`；
- 断言服务返回值（如 `OneToManyResult.main_count`）与推送的事件类型（`CHECK_STARTED` / `CHECK_PROGRESS` / `CHECK_COMPLETED`）；
- 断言异常路径（如 `NoQuestionsExtracted`）。

```python
# 真实用例节选（来自 tests/unit/core/test_similarity_service.py）
class PathMapLoader:
    def __init__(self, mapping):
        self._mapping = {k: list(v) for k, v in mapping.items()}
        self.calls = []
    def load_paragraphs(self, path):
        self.calls.append(path)
        return list(self._mapping[path])

class CollectingEmitter:
    def __init__(self):
        self.events = []
        self._handlers = []
    def emit(self, event):
        self.events.append(event)
        for h in self._handlers:
            h(event)
    def on_event(self, handler):
        self._handlers.append(handler)

def test_detects_duplicate_across_secondary(self):
    svc = SimilarityServiceImpl(
        PathMapLoader({"main.docx": MAIN_PARA, "dup.docx": DUP_PARA}),
        CollectingEmitter(),
    )
    res = svc.check(SimilarityRequest(mode=SimilarityMode.ONE_TO_MANY, ...))
    self.assertIsInstance(res, OneToManyResult)
    self.assertEqual(res.duplicate_count, 1)
```

**范式 B — DI 容器测试**（`tests/unit/core/test_slide_builder.py`）：
- 直接 `Container.build(task_runner=SyncTaskRunner(), event_emitter=CollectingEmitter())` 验证 `resolve("extraction")` 返回正确的 `ExtractionServiceImpl` 实例。

### 4.2 集成测试规范（ViewModel 接线，需 QApplication）

参考 `tests/integration/test_similarity_viewmodel.py`：
- `setUp` 内 `self._app = QApplication.instance() or QApplication(sys.argv)`；
- 用 `SyncTaskRunner`（同步立即执行，便于断言）+ `CollectingEmitter` + `FakeDocumentLoader` 组装；
- `vm.started.connect(...)` / `vm.completed.connect(...)` / `vm.failed.connect(...)` 订阅信号；
- 断言「UI 命令 → service → 事件 → Qt 信号」单向链路，以及异常经 `on_async_error` 桥接为 `failed` 信号。

### 4.3 本地调试 / 运行命令（已实地验证）

```bash
# 跑全部测试（集成测试需 offscreen 平台；--import-mode=importlib 见下方坑点）
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --import-mode=importlib -q

# 只跑某个 core 单测（无需 offscreen）
.venv/bin/python -m pytest tests/unit/core/test_similarity_service.py -q

# 只跑某个集成测试
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/integration/test_similarity_viewmodel.py -q

# 类型检查（core/ + shared/ 必须零报错）
.venv/bin/mypy --strict shared core

# 启动工具箱本体做手动验证
.venv/bin/python app.py
```

> 本机**实地验证结果**：`mypy --strict shared core` → `Success: no issues found in 20 source files`。
> `pytest --import-mode=importlib` → **53 passed, 2 failed**（2 个失败均为测试文件自身的既有 bug，见第 5 节，非源码问题）。

### 4.4 CI / Lint 检查要求（从真实代码与测试反推）

| 规则 | 来源 / 验证方式 |
|------|------------------|
| `core/` 与 `shared/` **零 Qt 导入** | `docs/architecture.md` 反复强调；可用 `grep -rE "PySide|Qt" core shared` 复查 |
| mypy `--strict` 对 `shared` + `core` 零报错 | `mypy.ini` 已开启 strict 核心项；已验证 20 文件通过 |
| `core/` + `ui/` 源码**不得残留 `print(`** | 由 `tests/test_p2_tech_debt.py::test_no_print_calls_remain_in_core_and_ui` 强制，业务日志统一走 `logging` |
| 前后端只经 `shared/contracts.py` 通信，禁止裸 dict | `shared/contracts.py` 文件头注释 + 全仓实践 |
| 业务异常统一继承 `ToolboxError` | `shared/errors.py`；service 抛异常，由 ViewModel 桥接为 failed 信号 |
| UI 样式统一复用 `Theme` / `widgets.py`，禁止硬编码颜色 | `docs/全局UI规范整改报告.md`；`Theme.qss_*` 片段语义由 `test_p2_tech_debt.py` 校验 |

---

## 5. 常见坑点与 FAQ

### Q1. 为什么我的 `QtXxxEmitter` 一继承 `EventEmitter` 就报错？
`EventEmitter` 是 `@runtime_checkable Protocol`，而 `QObject`（Qt 基类）有不同元类，二者**不能同时作为基类**（元类冲突）。项目里 `QtEventEmitter` 的做法是**结构实现**：只继承 `QObject`，按规定提供 `emit(event)` 与 `on_event(handler)` 两个方法即可满足端口（见 `ui/infra/qt_event_emitter.py` 注释）。**新写 UI 侧的端口实现时，不要写 `class XxxEmitter(EventEmitter, QObject)`。**

### Q2. 持久化（QSettings）时为什么把已存值覆盖了？
`SlideView._load_settings()` 在加载期间用 `blockSignals(True)` 屏蔽了控件的 change 信号，加载完再 `blockSignals(False)`。原因：若不屏蔽，部分字段尚未载入时就触发 `_save_settings`，会把「半载状态」（如空字符串 `opt_prefix=""`）写回，覆盖已存值。**你新增带持久化的控件时务必复制这一模式**：先 `blockSignals(True)` → 设值 → `blockSignals(False)`。

### Q3. `@async_task` 装饰的方法为什么异常没反应 / 任务取消不了？
`ui/infra/qt_task_runner.py:async_task` 依赖两件事：
- ViewModel 必须有 `self._task_runner`（否则装饰器退化为同步直调）；
- ViewModel 必须定义 `on_async_error(self, exc)`，后台异常才会被桥接为失败信号，**否则异常被静默吞掉**；
- 装饰器会把 `self._current_task` 设为 `TaskHandle`，`cancel_current()` 正是靠它取消。

### Q4. 关闭窗口时程序崩溃（SIGABRT）？
`QtTaskRunner` 持有 `_active` 强引用集合，并在 `finished` 时 `deleteLater`，避免后台线程仍在运行时 worker 被析构触发 SIGABRT（见 `qt_task_runner.py` 注释）。`QtTaskHandle.cancel()` 会 `quit()` + `wait()` **阻塞**等待线程终止。`app.py` 的 `closeEvent` 会遍历所有 Tool 调 `stop_worker()` → `cancel_current()`。**任何启动后台任务的 View 都必须实现 `stop_worker()`，否则关闭窗口可能留下孤儿线程或崩溃。**

### Q5. 写文件时为什么抛 `OutputOverwriteError`？
`PptxServiceImpl.generate` 在校验阶段用 `_same_path()`（规范化大小写与绝对路径后比较）判断 `output_path == template_path`，若相等直接抛 `OutputOverwriteError`。该异常**同时继承 `ValueError`**，以兼容旧契约/旧测试。涉及写文件的新 Tool 也请用这一模式保护源文件。

### Q6. 枚举字符串对不上，逻辑失效？
UI 用枚举成员（如 `SimilarityMode.ONE_TO_MANY`），其 `.value` 才是契约字符串 `"1_to_many"`；`LineSpacingType` 的 `"1 倍"` / `"1.5 倍"` / `"自定义"` 等字符串必须与 `core/adapters/pptx_writer.py:_resolve_line_spacing` 中的字面量**严格一致**，否则解析分支走错。

### Q7. 全局 UI 配色 / 间距有什么规矩？
所有颜色来自 `Theme._set_colors`，所有几何/排版来自 `_set_tokens`（`radius=6`、`spacing=16`/`8`、`page_pad=24/20`、字号 `14/13/12`）。新 View 的 QSS 应通过 `t.qss_card()` / `t.qss_progress_bar()` 等 `Theme` 片段与 `widgets.py` 复用，**禁止硬编码颜色**（由 `docs/全局UI规范整改报告.md` 与 `test_p2_tech_debt.py` 约束）。

### Q8. 已知既有测试回归问题（非源码 bug，提交前请知悉）
以下两个失败在当前 `main` 已存在，**与新增 Tool 无关**，但会让你本地 `pytest` 显示 2 failed：
1. `tests/test_p1_settings_and_threads.py:222` 在 `test_check_button_text_recovers_after_completion` 中使用了 `QtTaskRunner()`，但**该文件未导入** `QtTaskRunner`（`NameError: name 'QtTaskRunner' is not defined`）。需补 `from ui.infra.qt_task_runner import QtTaskRunner`。
2. `tests/unit/core/test_scorer.py:41` 断言 `self.assertIn("reason", result.reason)` 语义错误——把字段名当子串去匹配中文 reason（如 `"高度相似"`），应改为 `self.assertTrue(hasattr(result, "reason"))` 或检查 `result.reason` 非空。

> ⚠️ 待确认：`docs/architecture.md` 声称「38 测试全绿（offscreen）」，但当前套件用 `--import-mode=importlib` 收集到 **55** 个测试且 2 个失败。文档计数与现状可能已过时，建议核实后更新。

### Q9. 为什么不能直接跑 `pytest`，会报 collection error？
当前 `tests/unit/core/__init__.py` 存在、但 `tests/__init__.py` / `tests/unit/__init__.py` 缺失，导致默认 `prepend` 导入模式下 pytest 把单测模块误判为 `core.test_xxx` 而收集失败。**已验证可行的调用是加 `--import-mode=importlib`**（见第 4.3 节命令）。⚠️ 待确认：团队 CI 是否用其它机制（如根 `conftest.py` 或补 `__init__.py`）——若有，请优先遵循团队命令。

---

## 参考资料（本文调研所读取的真实文件）

- `docs/architecture.md` —— 分层架构、契约/端口设计、第 8 节「新增功能开发指南」
- `shared/contracts.py` —— Request / Response / Event 契约定义
- `shared/errors.py` —— `ToolboxError` 统一异常体系
- `core/di.py` —— `Container` 依赖注入
- `core/ports/services.py` / `events.py` / `tasks.py` / `io.py` —— 四个端口 Protocol
- `core/models/question.py` —— `Question` 领域模型
- `core/services/slide_builder.py` / `similarity_service.py` / `_scorer.py` / `_question_parser.py` —— 业务实现
- `core/adapters/docx_loader.py` / `pptx_writer.py` —— 外部依赖适配
- `ui/viewmodels/slide_viewmodel.py` / `similarity_viewmodel.py` —— ViewModel 胶水层
- `ui/views/base_view.py` / `slide_view.py` —— View 基类与范例
- `ui/infra/qt_task_runner.py` / `qt_event_emitter.py` —— 端口的 Qt 实现（`@async_task`、结构实现 EventEmitter）
- `app.py` —— 入口与 Tool 注册（`_register_tools` / `_add_tool` / `closeEvent`）
- `tests/unit/core/test_similarity_service.py` / `test_slide_builder.py` / `test_scorer.py` —— core 单测范式
- `tests/integration/test_similarity_viewmodel.py` —— ViewModel 集成测试范式
- `tests/test_p2_tech_debt.py` —— 无 `print(`、QSS 语义等价等 Lint 回归
- `tests/test_p1_settings_and_threads.py` / `tests/unit/core/test_scorer.py` —— 第 5 节 Q8 所述既有测试 bug 出处
- `requirements.txt` / `mypy.ini` / `.gitignore` —— 依赖与类型检查约束
