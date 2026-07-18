from typing import Callable, Sequence


def load_go_library(lib: str) -> None: ...


def StartGoTask(callback: Callable[[], None], task_id: int) -> None: ...


def StartGoTaskWithResult(callback: Callable[[], None], task_id: int) -> None: ...


def CancelGoTask(task_id: int) -> None: ...


def IsCanceled(task_id: int) -> bool: ...


def get_next_task_id() -> int: ...


__all__: Sequence[str] = [
    "load_go_library",
    "StartGoTask",
    "StartGoTaskWithResult",
    "CancelGoTask",
    "IsCanceled",
    "get_next_task_id",
]
