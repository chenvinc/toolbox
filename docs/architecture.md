# Toolbox 前后端分离架构重构 — 设计文档

> 阶段定位：**阶段1-4 全部落地**（契约层设计 + Word→Slide 样板 + 相似度检测迁移 + 遗留清理与界面重建）。全部回归测试通过（55 测试全绿，offscreen），`core/`+`shared/` mypy `--strict` 零报错。
> 作者视角：项目首席架构师
> 依据：现有 `similarity_checker.py` / `word_2_slide_tool.py` / `utils.py` / `base_tool.py` 真实代码

---

## 0. 目标与约束

| 目标 | 实现手段 |
|------|----------|
| 后端零 UI 依赖 | `core/` 禁止 import 任何 `PySide6`/`Qt*`；所有外部副作用（文件IO、系统调用、线程）通过 **port（Protocol）注入** |
| 单向数据流 | UI → core 走 **Request 命令**；core → UI 走 **Event 事件**；core 永不直接触碰控件 |
| 契约优先 | 前后端交互全部用 `shared/contracts.py` 的 Pydantic 模型 / `core/ports/` 的 Protocol 约束，禁止裸 dict |
| 可测试性 | `core/services/` 在 pytest + offscreen 下零 Qt 依赖通过；文件IO/线程通过 mock 注入 |
| 渐进式（Strangler Fig） | 新旧并存，按模块迁移，每步可运行、回归不丢功能 |

**唯一新增依赖**：`pydantic`（用于契约校验与序列化）。`core/` 不依赖它做业务，仅 `shared/` 用它定义契约（pydantic 本身零 Qt 依赖，不影响"core 无 Qt 导入"验收项）。

---

## 1. 目标目录结构

```
project_root/
├── shared/                      # 前后端共享契约（零 Qt 依赖）
│   ├── __init__.py
│   ├── contracts.py             # Request/Response/Event 定义（Pydantic）
│   └── errors.py                # 统一异常体系
├── core/                        # 纯 Python 后端核心（零 Qt 依赖）
│   ├── __init__.py
│   ├── models/
│   │   ├── question.py          # Question 等领域模型
│   │   └── report.py            # 查重报告领域模型
│   ├── ports/                   # 对外接口（Protocol）
│   │   ├── services.py          # SimilarityService / ExtractionService / PptxService
│   │   ├── events.py            # EventEmitter（core→UI 推送端口）
│   │   ├── tasks.py             # TaskRunner（异步执行端口）
│   │   └── io.py                # DocumentLoader / PptxWriter（文件IO端口）
│   ├── services/                # 业务实现
│   │   ├── similarity_service.py        # SimilarityServiceImpl
│   │   └── slide_builder.py     # Extraction + Pptx 实现
│   ├── adapters/                # 外部依赖适配（python-docx / python-pptx 封装）
│   │   ├── docx_loader.py
│   │   └── pptx_writer.py
│   └── di.py                    # 依赖注入容器（纯 Python，无 Qt）
├── ui/                          # PySide6 前端层
│   ├── views/                   # 仅渲染 + 事件转发（零业务规则）
│   │   ├── base_view.py         # BaseView(QWidget)：get_name/get_description/on_activate
│   │   ├── slide_view.py        # Quiz2SlideView：提取→预览确认→生成 + QSettings 持久化
│   │   └── similarity_view.py   # SimilarityView：1对多/多对多查重 + 阈值持久化 + 报告导出
│   ├── viewmodels/              # 持有 core service，胶水逻辑，发射 Qt 信号
│   │   ├── similarity_viewmodel.py
│   │   └── slide_viewmodel.py
│   ├── infra/                   # Qt 版 port 实现
│   │   ├── qt_task_runner.py    # TaskRunner 的 QThread 实现 + @async_task + QtTaskHandle
│   │   ├── qt_event_emitter.py  # EventEmitter → Qt Signal 桥接（结构上实现 EventEmitter 端口）
│   │   └── preview_escape.py    # 预览 HTML 安全转义（纯函数，零 Qt）
│   └── app.py                   # 启动时用 di 组装 services→viewmodels→views
├── tests/
│   ├── unit/core/               # 后端纯逻辑（无 Qt）
│   ├── integration/             # 前后端集成（ViewModel 接线 / 端到端）
│   ├── test_preview_escape.py   # P0#2 预览注入防护回归
│   ├── test_p1_settings_and_threads.py  # P1#4 阈值接线 + P1#5 线程管理回归
│   ├── test_p2_tech_debt.py     # P2 技术债扫描（零 print / QSS 等价）
│   └── test_generate_pptx.py    # P0#3 生成 PPTX 场景回归
├── app.py                       # DI 接线入口（QtTaskRunner + QtEventEmitter → ViewModels → Views）
├── theme.py / widgets.py        # 主题与基础控件（前端辅助，允许 Qt）
```

> 注：阶段4 已**删除**遗留 `similarity_checker.py` / `word_2_slide_tool.py` / `base_tool.py` / `utils.py`，
> 其逻辑全部由 `core/` 后端 + `ui/views/` 新界面承接；旧测试 `test_similarity_logic.py` 与
> `test_similarity_legacy_parity.py` 一并下线（保真已由 `core` 单测 + 集成测试覆盖）。

---

## 2. shared/contracts.py — 完整接口定义（草案）

```python
"""前后端共享通信契约（零 Qt 依赖）。

所有 Request/Response 均为 Pydantic BaseModel，带完整类型提示与文档字符串。
前后端禁止直接传递裸 dict —— 一律通过本模块定义的模型。
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, List, Literal, Union

from pydantic import BaseModel, Field


# ────────────────────────────────────────────────────────────────────
# 枚举
# ────────────────────────────────────────────────────────────────────

class SimilarityMode(str, Enum):
    """查重模式。"""
    ONE_TO_MANY = "1_to_many"      # 主文档 vs 多个副文档
    MANY_TO_MANY = "many_to_many"  # 所有文档两两比对


class LineSpacingType(str, Enum):
    """行间距类型（与现有 UI 下拉一致）。"""
    SINGLE = "1 倍"
    ONE_HALF = "1.5 倍"
    CUSTOM = "自定义"


class EventType(str, Enum):
    """后端向前端推送的事件类型。"""
    CHECK_STARTED = "check_started"
    CHECK_PROGRESS = "check_progress"
    CHECK_COMPLETED = "check_completed"
    CHECK_FAILED = "check_failed"
    EXTRACT_COMPLETED = "extract_completed"
    EXTRACT_FAILED = "extract_failed"
    PPTX_PROGRESS = "pptx_progress"
    PPTX_COMPLETED = "pptx_completed"
    PPTX_FAILED = "pptx_failed"


# ────────────────────────────────────────────────────────────────────
# Request（UI → core 命令）
# ────────────────────────────────────────────────────────────────────

class SimilarityRequest(BaseModel):
    """发起一次题目查重。"""
    mode: SimilarityMode
    threshold: float = Field(0.8, ge=0.0, le=1.0, description="相似度判定阈值")
    num_pattern: str = Field("1.", description="题号格式示例或原始正则；空串启用内置宽泛匹配")
    opt_prefix: str = Field("A.", description="选项前缀示例或原始正则；空串启用内置宽泛匹配")
    main_path: str = Field("", description="1对多模式主文档路径")
    secondary_paths: List[str] = Field(default_factory=list, description="1对多模式副文档路径")
    all_paths: List[str] = Field(default_factory=list, description="多对多模式全部文档路径")


class ExtractQuestionsRequest(BaseModel):
    """从 Word 文档提取题目。"""
    doc_path: str
    num_pattern: str = "1."
    opt_prefix: str = "A."


class GeneratePptxRequest(BaseModel):
    """基于模板为题目生成 PPT。"""
    template_path: str
    questions: List[List[str]] = Field(description="每道题为行列表（题干+选项行）")
    font_name: str
    font_size: int = Field(18, ge=9, le=72)
    output_path: str
    line_spacing_type: LineSpacingType = LineSpacingType.SINGLE
    line_spacing_value: float = 1.0
    first_line_indent: bool = True


# ────────────────────────────────────────────────────────────────────
# Response（core → UI 结果，替代原裸 dict）
# ────────────────────────────────────────────────────────────────────

class QuestionScore(BaseModel):
    """单对题目的相似度评分（替代 score_question_pair 返回的裸 dict）。"""
    score: float = Field(..., ge=0.0, le=1.0)
    reason: str
    stem_ratio: float
    option_ratio: float
    full_ratio: float
    token_ratio: float
    bigram_ratio: float


class SimilaritySource(BaseModel):
    """1对多模式下，某题命中的副文档来源。"""
    file: str
    score: float
    reason: str


class SimilarityDetail(BaseModel):
    """1对多模式下，主文档中一道重复题及其来源。"""
    index: int
    text: List[str]
    sources: List[SimilaritySource]


class OneToManyResult(BaseModel):
    """1对多查重结果。"""
    mode: Literal[SimilarityMode.ONE_TO_MANY] = SimilarityMode.ONE_TO_MANY
    main_count: int
    duplicate_count: int
    details: List[SimilarityDetail]


class SimilarityPair(BaseModel):
    """多对多模式下的一对重复题。"""
    q1_file: str
    q1_index: int
    q1_text: List[str]
    q2_file: str
    q2_index: int
    q2_text: List[str]
    score: float
    reason: str
    pair_type: Literal["internal", "cross"]


class ManyToManyResult(BaseModel):
    """多对多查重结果。"""
    mode: Literal[SimilarityMode.MANY_TO_MANY] = SimilarityMode.MANY_TO_MANY
    total_questions: int
    document_count: int
    doc_questions: dict[str, int]
    duplicate_pairs: List[SimilarityPair]
    duplicate_rate: float


class ExtractQuestionsResult(BaseModel):
    """题目提取结果。"""
    questions: List[List[str]]


class GeneratePptxResult(BaseModel):
    """PPT 生成结果。"""
    output_path: str
    page_count: int


SimilarityResult = Annotated[
    Union[OneToManyResult, ManyToManyResult], Field(discriminator="mode")
]


# ────────────────────────────────────────────────────────────────────
# Event（core → UI 推送，统一事件通道）
# ────────────────────────────────────────────────────────────────────

class _BaseEvent(BaseModel):
    type: EventType


class ProgressEvent(_BaseEvent):
    """通用进度事件（查重/提取/PPT生成复用）。"""
    type: Literal[EventType.CHECK_PROGRESS, EventType.PPTX_PROGRESS] = EventType.CHECK_PROGRESS
    message: str = ""
    current: int = 0
    total: int = 0


class CheckStartedEvent(_BaseEvent):
    type: Literal[EventType.CHECK_STARTED] = EventType.CHECK_STARTED
    mode: SimilarityMode


class CheckCompletedEvent(_BaseEvent):
    type: Literal[EventType.CHECK_COMPLETED] = EventType.CHECK_COMPLETED
    result: SimilarityResult


class ExtractCompletedEvent(_BaseEvent):
    type: Literal[EventType.EXTRACT_COMPLETED] = EventType.EXTRACT_COMPLETED
    result: ExtractQuestionsResult


class FailedEvent(_BaseEvent):
    type: Literal[
        EventType.CHECK_FAILED, EventType.EXTRACT_FAILED, EventType.PPTX_FAILED
    ] = EventType.CHECK_FAILED
    message: str


class PptxCompletedEvent(_BaseEvent):
    type: Literal[EventType.PPTX_COMPLETED] = EventType.PPTX_COMPLETED
    result: GeneratePptxResult


# 事件联合类型（按 type 判别）
DomainEvent = Annotated[
    Union[
        CheckStartedEvent, CheckCompletedEvent, ExtractCompletedEvent,
        PptxCompletedEvent, ProgressEvent, FailedEvent,
    ],
    Field(discriminator="type"),
]
```

### 使用示例（契约层即可单测）

```python
from shared.contracts import SimilarityRequest, SimilarityMode

req = SimilarityRequest(
    mode=SimilarityMode.ONE_TO_MANY,
    threshold=0.8,
    main_path="main.docx",
    secondary_paths=["a.docx", "b.docx"],
)
assert req.threshold == 0.8          # 类型校验 + 范围约束
assert req.mode == SimilarityMode.ONE_TO_MANY
```

---

## 3. shared/errors.py — 统一异常体系

```python
"""统一异常体系。core 抛出这些异常，ui 层捕获并转换为 FailedEvent / Toast。"""
from __future__ import annotations


class ToolboxError(Exception):
    """所有业务异常的基类。"""


class DocumentReadError(ToolboxError):
    """Word/PPT 文档读取失败。"""


class NoQuestionsExtracted(ToolboxError):
    """未从文档中提取到任何题目。"""


class SimilarityThresholdError(ToolboxError):
    """阈值参数非法。"""


class OutputOverwriteError(ToolboxError):
    """输出路径与模板路径相同，拒绝以避免损坏模板。"""


class PptxGenerationError(ToolboxError):
    """PPT 生成失败。"""
```

---

## 4. core/ports/ — Protocol 设计草案

> 设计要点：core 仅依赖这些 Protocol，**绝不直接 import PySide6**。
> Qt 版实现（QThread/Signal 桥接）放在 `ui/infra/`，由 DI 注入。

```python
# core/ports/services.py
from __future__ import annotations
from typing import Protocol, runtime_checkable

from shared.contracts import (
    SimilarityRequest, SimilarityResult,
    ExtractQuestionsRequest, ExtractQuestionsResult,
    GeneratePptxRequest, GeneratePptxResult,
)


@runtime_checkable
class SimilarityService(Protocol):
    """题目查重服务。"""
    def check(self, request: SimilarityRequest) -> SimilarityResult:
        """同步执行查重，返回结构化结果。禁止返回任何 UI 对象。"""
        ...


@runtime_checkable
class ExtractionService(Protocol):
    """Word 题目提取服务。"""
    def extract(self, request: ExtractQuestionsRequest) -> ExtractQuestionsResult:
        ...


@runtime_checkable
class PptxService(Protocol):
    """PPT 生成服务。"""
    def generate(self, request: GeneratePptxRequest) -> GeneratePptxResult:
        ...
```

```python
# core/ports/events.py
from __future__ import annotations
from typing import Callable, Protocol, runtime_checkable

from shared.contracts import DomainEvent


@runtime_checkable
class EventEmitter(Protocol):
    """core → UI 的事件推送端口。core 只调用 emit()，不关心下游是 Qt 还是 CLI。"""
    def emit(self, event: DomainEvent) -> None:
        ...

    def on_event(self, handler: Callable[[DomainEvent], None]) -> None:
        """订阅事件（由具体实现注册到传输层）。"""
        ...
```

```python
# core/ports/tasks.py
from __future__ import annotations
from typing import Any, Callable, Generic, Optional, Protocol, TypeVar

T = TypeVar("T")


@runtime_checkable
class TaskRunner(Protocol):
    """异步执行端口。ViewModel 调用 submit() 把同步 service 方法放到后台线程，
    通过回调（普通 Callable，非 Qt Signal）回传进度/结果/错误，保持 core 无 Qt。"""

    def submit(
        self,
        func: Callable[..., T],
        *,
        args: tuple = (),
        kwargs: Optional[dict] = None,
        on_progress: Optional[Callable[[str, int, int], None]] = None,
        on_result: Optional[Callable[[T], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> "TaskHandle":
        ...


@runtime_checkable
class TaskHandle(Protocol):
    def cancel(self) -> None: ...
    def is_running(self) -> bool: ...
```

```python
# core/ports/io.py  —— 文件IO端口，便于 mock 注入
from __future__ import annotations
from typing import List, Protocol, runtime_checkable


@runtime_checkable
class DocumentLoader(Protocol):
    """加载 Word 文档段落文本（适配 python-docx）。"""
    def load_paragraphs(self, path: str) -> List[str]: ...


@runtime_checkable
class PptxWriter(Protocol):
    """PPT 写操作（适配 python-pptx）。"""
    def build(self, template_path: str, questions: List[List[str]],
              font_name: str, font_size: int, output_path: str,
              line_spacing: float, first_line_indent: bool,
              on_progress: Callable[[int, int], None]) -> int:
        """返回生成页数。"""
        ...
```

---

## 5. 交互时序图

### 5.1 题目查重（1对多）

```
UI(View)          ViewModel            SimilarityService      EventEmitter        UI(Bridge)
   |                  |                       |                    |                  |
   |-- check(req) -->|                       |                    |                  |
   |                  |-- check(req) ------->|                    |                  |
   |                  |                       |-- emit(STARTED) -->|                  |
   |                  |                       |                    |-- signal ------->| (进度条)
   |                  |                       |-- emit(PROGRESS) ->|--> signal ------->| (日志)
   |                  |                       |-- compute ...      |                  |
   |                  |<-- OneToManyResult ---|                    |                  |
   |                  |                       |-- emit(COMPLETED)>|--> signal ------->| (渲染摘要)
   |<-(更新状态)------|                       |                    |                  |
```

### 5.2 Word → Slide

```
UI(View)    ViewModel     ExtractionService   PptxService    EventEmitter    UI(Bridge)
   |            |               |                |              |               |
   |--convert->|               |                |              |               |
   |            |-- extract -->|                |              |               |
   |            |               |-- emit(COMPLETED:questions) ->|--> signal --->| (预览弹窗)
   |            |<-- questions -|                |              |               |
   |<- 预览确认弹窗 -----------|                |              |               |
   |-- confirm->|               |                |              |               |
   |            |               |-- generate --->|              |               |
   |            |               |                |-- emit(PROGRESS) -> signal ->| (进度条)
   |            |               |                |-- emit(COMPLETED) -> signal ->| (Toast)
```

---

## 6. 依赖注入容器（core/di.py 草案）

纯 Python，无 Qt。组装顺序：`ports 实现 → services → (注入 TaskRunner/EventEmitter 的 Qt 实现) → viewmodels → views`。

```python
# core/di.py（仅示意骨架，实现阶段落地）
class Container:
    def __init__(self) -> None:
        self._services: dict = {}

    def register(self, key: str, instance) -> None: ...
    def resolve(self, key: str): ...

    @classmethod
    def build(cls, *, task_runner, event_emitter):
        """生产环境：task_runner / event_emitter 由 ui/infra 提供 Qt 实现。
        测试环境：传入 FakeTaskRunner / CollectingEmitter 即可无 GUI 单测。"""
        c = cls()
        c.register("extraction", DocxExtractionService(loader=DocxLoaderAdapter()))
        c.register("similarity", SimilarityServiceImpl())
        c.register("pptx", PptxServiceImpl(writer=PptxWriterAdapter()))
        c.register("task_runner", task_runner)
        c.register("event_emitter", event_emitter)
        return c
```

**测试替换示例**：
```python
fake = CollectingEmitter()
container = Container.build(task_runner=SyncTaskRunner(), event_emitter=fake)
svc = container.resolve("similarity")
res = svc.check(SimilarityRequest(mode=..., main_path="x.docx", ...))
assert isinstance(res, OneToManyResult)
```

---

## 7. 异步任务框架（ui/infra 草案）

```python
# ui/infra/qt_task_runner.py
class QtTaskRunner:
    """TaskRunner 的 QThread 实现。把同步 func 丢到后台线程，
    通过回调（非 Signal）转发，由 ViewModel 桥接到 Qt Signal。"""
    def submit(self, func, *, args=(), kwargs=None, on_progress=None,
               on_result=None, on_error=None):
        worker = _QtWorker(func, args, kwargs, on_progress)
        worker.done.connect(lambda r: on_result(r) if on_result else None)
        worker.error.connect(lambda e: on_error(e) if on_error else None)
        worker.start()
        return worker


def async_task(method):
    """装饰器：将 ViewModel 中的同步方法自动转为非阻塞调用，
    进度/取消/错误经标准化事件传递。"""
    ...
```

---

## 8. 新增功能开发指南（验收标准②的落地形态）

新增一个业务功能只需三步，**无需改动任何现有 UI 组件**：

1. **定义契约** — 在 `shared/contracts.py` 加 `XxxRequest` / `XxxResult` / 必要时 `XxxEvent`。
2. **实现 service** — 在 `core/services/` 写 `XxxServiceImpl(SomePort)`，纯 Python 无 Qt，pytest 单测。
3. **绑定 ViewModel** — 在 `ui/viewmodels/` 新建 `XxxViewModel`，注入 service + runner + emitter，发射 Qt 信号；`ui/app.py` 注册新 view。

> 现有 `views/`（Quiz2SlideView / SimilarityView）**完全不改动**。

---

## 9. 迁移计划（Strangler Fig，按阶段）

- **阶段1**：落地 `shared/` + `core/ports/` + 本文档。无行为变化。（已完成）
- **阶段2（样板）**：把 `word_2_slide_tool.py` 的 `extract_questions` / `generate_pptx` 迁到 `core/services/slide_builder.py`，经 `DocxLoaderAdapter` 读文件；新建 `SlideViewModel` 跑通端到端，回归测试通过。（已完成）
- **阶段3（本次）**：把 `similarity_checker.py` 的 `score_question_pair` + 1对多/多对多比对循环迁到 `core/`；引入结构化 `Question` 领域模型；`SimilarityServiceImpl` 经 `DocumentLoader` + `parse_questions` 注入，发射 `CheckStarted/Progress/Completed` 事件；新建 `SimilarityViewModel` 桥接。遗留 `similarity_checker.py` 暂不改动（Strangler Fig）。（已完成）
- **阶段4（本次完成）**：删除遗留 `utils.py`/`base_tool.py`/`similarity_checker.py`/`word_2_slide_tool.py` 中已迁移逻辑，并用新 `SimilarityViewModel` / `SlideViewModel` 重建 `ui/views/` 真实界面（`SlideView` / `SimilarityView` / `BaseView`），替换 legacy `SimilarityCheckerTool` / `Word2SlideTool`；旧测试 `test_similarity_logic.py` 与 `test_similarity_legacy_parity.py` 下线；定稿本文档。`app.py` 改为 DI 接线（`Container.build(QtTaskRunner(), QtEventEmitter())` → ViewModels → Views），`closeEvent` 经 `stop_worker` 取消后台线程。验收：55 测试全绿（offscreen），`core/`+`shared/` mypy `--strict` 零报错。

---

## 10. 待你确认的关键决策

1. **Pydantic 作为契约载体**（新增 1 个依赖）是否接受？备选：纯 `dataclass` + `TypedDict`（零新依赖，但失去运行时校验/序列化）。
2. **Question 是否升级为领域模型**（stem + options 结构化）？当前为最小风险，契约先用 `List[List[str]]`（与现有 `score_question_pair` 完全一致），结构化留到阶段3。
3. 阶段2 是否以**相似度检测**作为样板（你原话建议），还是以更纯粹的 `word_2_slide` 提取逻辑优先？
```

> 本文件为**设计稿**，尚未创建任何 `shared/` `core/` `ui/` 运行时代码。确认后进入实现。

---

## 实施进度（截至 2026-07-15）

- **阶段1 契约层**：已落地。`shared/contracts.py`（Pydantic Request/Response/EventType/DomainEvent）、`shared/errors.py`、`core/ports/`（services/events/tasks/io 四个 Protocol）。`core/`+`shared/` 经 `grep` 确认**零 Qt 导入**；mypy `--strict` 无报错。
- **阶段2 Word→Slide 样板**：已落地并跑通。
  - `core/services/_question_parser.py`：纯解析（无文件 IO）。
  - `core/adapters/`：`DocxLoaderAdapter`（python-docx）、`PptxWriterAdapter`（python-pptx）。
  - `core/services/slide_builder.py`：`ExtractionServiceImpl` / `PptxServiceImpl`（经端口注入，发射事件）。
  - `core/di.py`：极简 DI 容器。
  - `ui/infra/`：`QtTaskRunner` + `@async_task`、`QtEventEmitter`（Qt Signal 桥接）。
  - `ui/viewmodels/slide_viewmodel.py`：胶水层，单向数据流验证通过。
  - `utils.py` 在阶段2退化为兼容薄壳，**旧模块 + 旧测试符号不变**（37 测试全绿，含 `test_same_path_raises_value_error`），**该文件已于阶段4删除**（见下）。
  - 新增测试：`tests/unit/core/test_slide_builder.py`（mock 注入）、`tests/integration/test_slide_viewmodel.py`（ViewModel 接线）、`tests/integration/test_slide_e2e.py`（真实适配器端到端）。
- **阶段4 遗留清理与界面重建**：已落地并完成验收。
  - **删除遗留源**：`similarity_checker.py` / `word_2_slide_tool.py` / `base_tool.py` / `utils.py`；其逻辑由 `core/`（后端）+ `ui/views/`（新界面）承接。
  - **新界面**：`ui/views/base_view.py`（`BaseView`）、`ui/views/slide_view.py`（`SlideView`：提取→预览确认→生成 + QSettings 持久化 + Toast + 主题热切换）、`ui/views/similarity_view.py`（`SimilarityView`：1对多/多对多查重 + 阈值持久化 + .docx 报告导出）。
  - **接口层复用**：`ui/infra/preview_escape.py`（从 legacy 迁来的纯函数转义）、`QtTaskRunner`/`QtEventEmitter`（结构实现 `EventEmitter` 端口，避免 Protocol 元类冲突）、`widgets.py` 的 `MultiDropZone`（从 legacy 迁入）。
  - **DI 接线**：`app.py` 由 `Container.build(QtTaskRunner(), QtEventEmitter())` 组装 `SlideViewModel`/`SimilarityViewModel` → `SlideView`/`SimilarityView`；`closeEvent` 调 `stop_worker` → `cancel_current` 阻塞等待后台线程终止（修复 SIGABRT）。
  - **测试迁移**：`tests/test_preview_escape.py`、`tests/test_p1_settings_and_threads.py`、`tests/test_p2_tech_debt.py`、`tests/test_generate_pptx.py` 改为直测 `core`/`ui.infra`；新增 `tests/unit/core/test_scorer.py`。下线 `tests/test_similarity_logic.py` 与 `tests/integration/test_similarity_legacy_parity.py`。
  - **修复的关键问题**：`QtEventEmitter(QObject, EventEmitter)` 元类冲突（改为结构实现）；`SimilarityView` 缺 `QPushButton`/`QSizePolicy` 导入；`_load_settings` 加载时触发 `_save_settings` 把半载状态（`opt_prefix=""`）写回（加载期间 `blockSignals`）；`QtTaskRunner` 后台线程销毁时仍运行导致 SIGABRT（`_active` 强引用 + `finished→deleteLater` + `join()/cancel()` 容错）。
  - **验收**：55 测试全绿（offscreen，无 SIGABRT）；`core/`+`shared/` mypy `--strict` 零报错；`core/`、`shared/` 零 Qt 导入复查通过。

---

## 阶段3 交付明细（相似度检测迁移）

### 新增 / 修改文件
| 文件 | 角色 | 说明 |
|------|------|------|
| `core/models/question.py` | 领域模型 | 结构化 `Question`（lines / source_file / index），替代裸 `List[str]` 在查重链路隐式传递 |
| `core/services/_scorer.py` | 纯打分逻辑 | 从 legacy `score_question_pair` **逐行移植**公式与阈值分支，输出 `QuestionScore`（零 Qt / 零 IO） |
| `core/services/similarity_service.py` | 业务服务 | `SimilarityServiceImpl` 实现 1对多 / 多对多查重，经注入的 `DocumentLoader` + `parse_questions` 读题，发射事件 |
| `core/di.py` | DI 容器 | 注册 `similarity` 服务 |
| `ui/viewmodels/similarity_viewmodel.py` | 视图模型 | 持有 `SimilarityService`，`@async_task` 转发 `check`，桥接事件为 Qt 信号（started/progress/completed/failed） |
| `tests/unit/core/test_similarity_service.py` | 单元测试 | mock `DocumentLoader`/`EventEmitter`，验证 1对多命中、多对多 cross/internal、阈值门控、异常、事件 |
| `tests/integration/test_similarity_viewmodel.py` | 集成测试 | `SyncTaskRunner` + `CollectingEmitter` 验证 ViewModel 单向数据流与异常转失败信号 |
| `tests/integration/test_similarity_legacy_parity.py` | 保真测试 | 新 `score_questions` 与 legacy `score_question_pair` 对多组题对数值完全等价 |

### 验收对照
- **core/ 零 Qt 导入**：`grep` 复查 `core/`、`shared/` 均无 `PySide/Qt*`（已验证）。
- **单向数据流**：UI → `SimilarityRequest` 命令；core → `CheckStarted/Progress/Completed` 事件 → Qt 信号。
- **契约优先**：前后端交互全部为 `shared/contracts.py` 的 Pydantic 模型，无裸 dict。
- **可测试性**：`core/services` 在 pytest + offscreen 下零 Qt 依赖；文件IO 经 mock 注入。
- **零功能丢失**：`test_similarity_legacy_parity.py` 锁定打分语义与 legacy 逐字段一致；遗留 `similarity_checker.py` 完全未改，旧回归测试 `tests/test_similarity_logic.py` 仍有效。

### 阶段3 未做项（已在阶段4 完成）
- **`ui/views/` 真实 QWidget 界面**：已在阶段4 以 `BaseView` / `SlideView` / `SimilarityView` 重建，legacy `SimilarityCheckerTool` / `Word2SlideTool` 已删除。
- **git 提交**：阶段1-4 成果已在提交 `16a2b24`（refactor: 前后端分离架构重构）中落库；本文档及测试修复为后续新增的工作区改动，待评审后提交。
