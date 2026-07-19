import os
import shutil
import subprocess
import sysconfig
from hatchling.builders.hooks.plugin.interface import BuildHookInterface  # type: ignore
from pathlib import Path
import sys
from cffi import FFI # type: ignore

class DynamicGoBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if not self.config.get("should_use_gsyncio", False):
            print("[gsyncio Build] Skipping gsyncio build.")
            return
        if self.target_name != "wheel" and not self.config.get("compiled_sdist", False):
            print("[gsyncio Build] Skipping gsyncio build for sdist.")
            return
        
        if self.config.get("compiled_sdist", False) and self.target_name == "wheel":
            print("[gsyncio Build] WARNING. COMPILING FOR SDIST AND WHEEL CAN CAUSE ISSUES WITH BUILDING.")
            print("    THIS IS MEANT FOR DEBUGGING. I RECOMMEND ONLY USING THIS PROPERTY IF YOU KNOW WHAT YOU ARE DOING")

        go_binary = shutil.which("go")

        if go_binary is None:
            build_data["infer_tag"] = False
            print(
                "[gsyncio Build] 'go' compiler not found in PATH. Packaging pure-Python fallback."
            )
            return
        
        build_data["infer_tag"] = True

        print(f"[gsyncio Build] Found Go compiler at: {go_binary}. Starting Step 1.")

        gsyncio_path = Path(self.root) / "pipebomb" / "gsyncio"
        print(f"[gsyncio Build] Using gsyncio path: {gsyncio_path}")
        dist_path = Path(self.root) / "dist"
        
        go_library_extension = ""
        compiled_library_extension = ""

        if sys.platform.startswith("win"):
            go_library_extension = ".dll"
            compiled_library_extension = ".pyd"
        elif sys.platform.startswith("darwin"):
            go_library_extension = ".dylib"
            compiled_library_extension = ".so"
        else:
            go_library_extension = ".so"
            compiled_library_extension = ".so"

        go_compiled_library_path = (
            dist_path / f"gsyncio{go_library_extension}"
        )

        compiled_library_path = (
            dist_path / f"gsyncio{compiled_library_extension}"
        )
        
        print(compiled_library_path)
        
        try:
            os.unlink(str(go_compiled_library_path))
        except FileNotFoundError:
            pass
        
        try:
            os.unlink(str(go_compiled_library_path.parent.with_suffix(".h")))
        except FileNotFoundError:
            pass

        print(
            f"[gsyncio Build] Attempting to compile go folder {gsyncio_path} to {go_compiled_library_path}."
        )

        try:
            subprocess.run(
                [
                    "go",
                    "build",
                    "-buildmode=c-shared",
                    "-o",
                    str(go_compiled_library_path),
                    str(gsyncio_path),
                ],
                cwd=gsyncio_path,
            )
            print(
                "[gsyncio Build] Native Go extension module compiled successfully!"
            )

        except subprocess.CalledProcessError as e:
            print(f"[gsyncio Build] Compilation failed: {e.stderr}")
            print(
                "[gsyncio Build] Aborting native compilation. Packaging pure-Python fallback."
            )
            return
            
        print("[gsyncio Build] Step 1 completed. Starting Step 2.")
        try:
            shutil.rmtree(dist_path / "pipebomb", ignore_errors=True)
            os.remove(dist_path / "gsyncio_cffi.so")
            os.remove(dist_path / "gsyncio.h")
        except FileNotFoundError:
            pass

        try:
            # py_include = sysconfig.get_path('include')
            py_libdir = sysconfig.get_config_var('LIBDIR') or ''
            ldlibrary = sysconfig.get_config_var('LDLIBRARY') or 'python3.13'
            libname = ldlibrary.replace('.so', '').replace('.a', '')

            cffi_ffibuilder = FFI()
            cffi_ffibuilder.cdef("""
void _StartGoTaskWithResult(void* callback, int32_t taskId, int32_t* canceled, void* ensure, void* release);
void _StartGoTask(void* callback, int32_t taskId, void* ensure, void* release);
int32_t _GetNextTaskId();
void _CancelGoTask(int32_t taskId);
bool _IsCanceled(int32_t taskId);
""")

            link_args = []
            if py_libdir:
                link_args.extend([f"-L{py_libdir}", f"-Wl,-rpath,{py_libdir}"])
            link_args.append(f"-l{libname[len('lib'):]}")
            
            # go_lib_filename = f"gsyncio{go_library_extension}"
            link_args.extend(["-L.", f"-l:gsyncio{go_library_extension}"])
            
            link_args.append("-Wl,-rpath,$ORIGIN:$ORIGIN/..:$ORIGIN/../..")

            cffi_ffibuilder.set_source(
                "pipebomb.gsyncio.gsyncio_cffi",
                """
#include <stdint.h>
#include <stdbool.h>
#include <Python.h>

typedef void (*gil_ensure_fn)(void);
typedef void (*gil_release_fn)(int);

static gil_ensure_fn get_gil_ensure(void) {
    return (gil_ensure_fn)(intptr_t)PyGILState_Ensure;
}

static gil_release_fn get_gil_release(void) {
    return (gil_release_fn)(intptr_t)PyGILState_Release;
}

void _StartGoTaskWithResult(void* callback, int32_t taskId, int32_t* canceled, void* ensure, void* release);
void _StartGoTask(void* callback, int32_t taskId, void* ensure, void* release);
int32_t _GetNextTaskId();
void _CancelGoTask(int32_t taskId);
bool _IsCanceled(int32_t taskId);
""",
                extra_compile_args=["-O3", "-Werror", "-Wno-unused-function"],
                extra_link_args=link_args,
            )

            compiled_library_path = cffi_ffibuilder.compile(
                str(dist_path),
                verbose=1,
            )
        except Exception as e:
            print(f"[gsyncio Build] CFFI compilation failed: {e}")
            print(
                "[gsyncio Build] Aborting native compilation. Packaging pure-Python fallback."
            )
            build_data["infer_tag"] = False
            import traceback
            traceback.print_exc()
            return
        
        os.rename(compiled_library_path, str(dist_path / f"gsyncio_cffi{compiled_library_extension}"))
        
        build_data["force_include"][str(dist_path / f"gsyncio_cffi{compiled_library_extension}")] = f"pipebomb/gsyncio/gsyncio_cffi{compiled_library_extension}"
        build_data["force_include"][str(go_compiled_library_path)] = f"pipebomb/gsyncio/gsyncio{go_library_extension}"
        print("[gsyncio Build] Successfully compiled both libraries.")
