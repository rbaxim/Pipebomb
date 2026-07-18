from ctypes import (
    CDLL, c_int32, CFUNCTYPE, pythonapi, c_void_p, cast, RTLD_GLOBAL, addressof,
)
from typing import Callable, Optional, List, Sequence
import sys
import threading

sys.setdlopenflags(sys.getdlopenflags() | RTLD_GLOBAL)

tasks: dict[int, Callable[[], None]] = {}
_live_callbacks: List[Callable[[], None]] = []
_task_results: dict[int, dict] = {}
_lock = threading.Lock()

gsyncio_lib: Optional[CDLL] = None

PyGILState_Ensure = cast(pythonapi.PyGILState_Ensure, c_void_p).value
PyGILState_Release = cast(pythonapi.PyGILState_Release, c_void_p).value


def load_go_library(lib: str):
    global gsyncio_lib

    pythonapi.PyEval_InitThreads()

    gsyncio_lib = CDLL(lib)
    gsyncio_lib._StartGoTask.argtypes = (CFUNCTYPE(None), c_int32, c_void_p, c_void_p)
    gsyncio_lib._StartGoTask.restype = None
    gsyncio_lib._CancelGoTask.argtypes = (c_int32,)
    gsyncio_lib._CancelGoTask.restype = None
    gsyncio_lib._IsCanceled.argtypes = (c_int32,)
    gsyncio_lib._IsCanceled.restype = c_int32
    gsyncio_lib._GetNextTaskId.argtypes = ()
    gsyncio_lib._GetNextTaskId.restype = c_int32

    # _StartGoTaskWithResult: callback, task_id, canceled_flag_ptr, gil_ensure_ptr, gil_release_ptr
    gsyncio_lib._StartGoTaskWithResult.argtypes = (
        CFUNCTYPE(None), c_int32, c_void_p, c_void_p, c_void_p
    )
    gsyncio_lib._StartGoTaskWithResult.restype = None


def StartGoTask(callback, task_id):
    if gsyncio_lib is None:
        raise RuntimeError("Go library not loaded")
    c_callback = CFUNCTYPE(None)(callback)
    _live_callbacks.append(c_callback)
    gsyncio_lib._StartGoTask(c_callback, task_id, PyGILState_Ensure, PyGILState_Release)
    tasks[task_id] = callback

_cancel_flags: dict[int, "c_int32"] = {}


def StartGoTaskWithResult(callback, task_id):
    if gsyncio_lib is None:
        raise RuntimeError("Go library not loaded")

    flag = c_int32(0)
    _cancel_flags[task_id] = flag

    with _lock:
        if task_id not in _task_results:
            _task_results[task_id] = {"_event": threading.Event()}

    c_callback = CFUNCTYPE(None)(callback)
    _live_callbacks.append(c_callback)

    gsyncio_lib._StartGoTaskWithResult(
        c_callback, task_id, cast(addressof(flag), c_void_p), PyGILState_Ensure, PyGILState_Release
    )


def CancelGoTask(task_id):
    if gsyncio_lib is None:
        raise RuntimeError("Go library not loaded")
    gsyncio_lib._CancelGoTask(task_id)
    flag = _cancel_flags.get(task_id)
    if flag is not None:
        flag.value = 1


def IsCanceled(task_id):
    if gsyncio_lib is None:
        raise RuntimeError("Go library not loaded")
    return bool(gsyncio_lib._IsCanceled(task_id))


def get_next_task_id() -> int:
    if gsyncio_lib is None:
        raise RuntimeError("Go library not loaded")
    return int(gsyncio_lib._GetNextTaskId())


__all__: Sequence[str] = [
    "load_go_library",
    "StartGoTask",
    "StartGoTaskWithResult",
    "CancelGoTask",
    "IsCanceled",
    "get_next_task_id",
]
