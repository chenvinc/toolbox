"""图片并发预下载（零 Qt 依赖，无文件副作用）。

在生成 Word 文档之前，把全部题目涉及的图片一次性并发下载到内存缓存，
避免逐段渲染时串行下载导致的卡顿，并以有限并发数（线程池）降低被图床封禁的风险。

下载失败不抛异常：对应 URL 在缓存中记为 ``None``，由上层（适配器）就地插入灰色占位框。
本模块同时导出 ``_fetch_image_bytes`` 供适配器在「未预下载」场景下惰性回退使用。
"""
from __future__ import annotations

import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional, Tuple

# 图片下载超时（秒）。
_IMAGE_TIMEOUT = 10
# 并发下载上限：限制线程数，避免对图床造成过大压力被封。
_MAX_IMAGE_WORKERS = 6
# 单张图片下载失败重试次数。
_MAX_RETRIES = 1

ProgressFn = Callable[[int, int, int], None]  # (已完成数, 图片总数, 已失败数)


def _fetch_image_bytes(
    src: str,
    cache: Dict[str, Optional[bytes]],
    lock: Optional[threading.Lock] = None,
) -> Optional[bytes]:
    """下载图片字节（带超时），按 URL 缓存；失败返回 None（不抛异常）。

    ``cache`` 为调用方持有的共享字典；多线程预下载时传入 ``lock`` 保证写入安全。
    单线程（适配器惰性回退）场景可不传 ``lock``。
    """
    if src in cache:
        return cache[src]
    data: Optional[bytes] = None
    last_err: Optional[Exception] = None
    for _ in range(_MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=_IMAGE_TIMEOUT) as resp:
                data = bytes(resp.read())
            break
        except Exception as exc:  # 网络/解码等任意异常均视为失败
            last_err = exc
            continue
    if data is None:
        # 下载失败：记录日志来源以便在需要时排查，但不中断主流程
        import logging
        logging.getLogger(__name__).warning("图片下载失败: %s (%s)", src, last_err)
    if lock is not None:
        with lock:
            cache[src] = data
    else:
        cache[src] = data
    return data


def prefetch_images(
    urls: List[str],
    *,
    max_workers: int = _MAX_IMAGE_WORKERS,
    on_progress: Optional[ProgressFn] = None,
) -> Tuple[Dict[str, Optional[bytes]], List[str]]:
    """并发下载全部图片，返回 ``(缓存字典, 失败 URL 列表)``。

    Args:
        urls: 去重后的图片地址列表。
        max_workers: 并发线程上限。
        on_progress: 每完成一张回调 ``(已完成数, 总数, 已失败数)``，用于进度反馈。

    Returns:
        cache: ``url -> bytes | None``，失败项值为 None。
        failed: 下载失败的 URL（与 cache 中值为 None 的键一致）。
    """
    cache: Dict[str, Optional[bytes]] = {}
    failed: List[str] = []
    total = len(urls)
    if total == 0:
        return cache, failed

    lock = threading.Lock()
    done = 0
    failed_count = 0
    workers = min(max_workers, total) if max_workers > 0 else total

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_url = {
            executor.submit(_fetch_image_bytes, u, cache, lock): u
            for u in urls
        }
        for fut in as_completed(future_to_url):
            url = future_to_url[fut]
            try:
                data = fut.result()
            except Exception:  # 防御：理论上 _fetch_image_bytes 已吞异常
                data = None
            if data is None:
                failed_count += 1
                if url not in failed:
                    failed.append(url)
            done += 1
            if on_progress is not None:
                on_progress(done, total, failed_count)

    return cache, failed
