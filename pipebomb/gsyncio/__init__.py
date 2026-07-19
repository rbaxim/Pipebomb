from typing import Callable, Optional, List, Sequence
import ctypes
import os
import sys
import threading
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

NO_GSYNCIO_CFFI = True
ffi = None

_gil_ensure_fn = None
_gil_release_fn = None
gsyncio_lib: Optional["ffi.CData"] = None  # type: ignore
tasks: dict[int, Callable[[], None]] = {}
_live_callbacks: List[Callable[[], None]] = []
_task_results: dict[int, dict] = {}
_lock = threading.Lock()
_cancel_flags: dict[int, "ffi.CData"] = {} # type: ignore


def _find_cffi_ext():
    if sys.platform.startswith("win"):
        comp_ext = ".pyd"
    else:
        comp_ext = ".so"

    env_path = os.environ.get("GSYNCIO_PATH")
    if env_path:
        gsyncio_folder = Path(env_path).resolve()
        cffi_path = gsyncio_folder / f"gsyncio_cffi{comp_ext}"
        if cffi_path.exists():
            logger.debug("Found gsyncio_cffi")
            return str(cffi_path)


    parent_dist = Path(__file__).resolve().parent.parent.parent / "dist"
    
    nested_cffi = parent_dist / f"gsyncio_cffi{comp_ext}"
    if nested_cffi.exists():
        logger.debug("Found gsyncio_cffi")
        return str(nested_cffi)

    pkg_dir = Path(__file__).resolve().parent
    if (pkg_dir / f"gsyncio_cffi{comp_ext}").exists():
        logger.debug("Found gsyncio_cffi")
        return str(pkg_dir / f"gsyncio_cffi{comp_ext}")

    logger.warning("Could not find gsyncio_cffi")
    return None


def _init():
    global NO_GSYNCIO_CFFI, ffi, _gil_ensure_fn, _gil_release_fn
    global gsyncio_lib, tasks, _live_callbacks, _task_results, _lock, _cancel_flags

    cffi_path = _find_cffi_ext()
    if not cffi_path:
        logger.warning("Could not find gsyncio_cffi")
        return
    else:
        logger.info("Found gsyncio_cffi")

    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pipebomb.gsyncio.gsyncio_cffi", cffi_path)
        if not spec or not spec.loader:
            return
        gsyncio_cffi_mod = importlib.util.module_from_spec(spec)
        sys.modules["pipebomb.gsyncio.gsyncio_cffi"] = gsyncio_cffi_mod
        spec.loader.exec_module(gsyncio_cffi_mod)

        ffi = gsyncio_cffi_mod.ffi
        
        _ensure_addr = ctypes.cast(
            ctypes.CDLL(None).PyGILState_Ensure, ctypes.c_void_p
        ).value
        _release_addr = ctypes.cast(
            ctypes.CDLL(None).PyGILState_Release, ctypes.c_void_p
        ).value
        _gil_ensure_fn = ffi.cast("void *", _ensure_addr)
        _gil_release_fn = ffi.cast("void *", _release_addr)
    except Exception as e:
        logger.error(f"[gsyncio] _init: EXCEPTION {type(e).__name__}: {e}")
        return


_init()

if ffi is not None:
    NO_GSYNCIO_CFFI = False

    def load_go_library(lib: str):
        global gsyncio_lib
        gsyncio_lib = ffi.dlopen(lib, ffi.RTLD_NOW | ffi.RTLD_GLOBAL) # type: ignore

    def StartGoTask(callback, task_id):
        if gsyncio_lib is None:
            raise RuntimeError("Go library not loaded")
        @ffi.callback("void(void)") # type: ignore
        def c_callback():
            callback()
        _live_callbacks.append(c_callback)
        gsyncio_lib._StartGoTask(c_callback, task_id, _gil_ensure_fn, _gil_release_fn)
        tasks[task_id] = callback

    def StartGoTaskWithResult(callback, task_id):
        if gsyncio_lib is None:
            raise RuntimeError("Go library not loaded")
        canceled_flag = ffi.new("int32_t *", 0) # type: ignore
        _cancel_flags[task_id] = canceled_flag
        with _lock:
            if task_id not in _task_results:
                _task_results[task_id] = {"_event": threading.Event()}
        @ffi.callback("void(void)") # type: ignore
        def c_callback():
            callback()
        _live_callbacks.append(c_callback)
        gsyncio_lib._StartGoTaskWithResult(
            c_callback, task_id, canceled_flag,
            _gil_ensure_fn, _gil_release_fn
        )

    def CancelGoTask(task_id):
        if gsyncio_lib is None:
            raise RuntimeError("Go library not loaded")
        gsyncio_lib._CancelGoTask(task_id)
        flag = _cancel_flags.get(task_id)
        if flag is not None:
            flag[0] = 1

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
