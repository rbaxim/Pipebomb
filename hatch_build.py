import os
import shutil
import subprocess
from hatchling.builders.hooks.plugin.interface import BuildHookInterface  # type: ignore
from pathlib import Path
import sys


class DynamicGoBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if self.target_name != "wheel":
            return

        go_binary = shutil.which("go")

        if go_binary is None:
            build_data["infer_tag"] = False
            print(
                "[gsyncio Build] 'go' compiler not found in PATH. Packaging pure-Python fallback."
            )
            return
        
        build_data["infer_tag"] = True

        print(f"[gsyncio Build] Found Go compiler at: {go_binary}. Compiling module.")

        gsyncio_path = Path(self.root) / "pipebomb" / "gsyncio"

        compiled_library_extension = ""

        if sys.platform.startswith("win"):
            compiled_library_extension = ".pyd"
        else:
            compiled_library_extension = ".so"

        compiled_library_path = (
            Path(self.root) / "dist" / f"gsyncio{compiled_library_extension}"
        )

        try:
            os.unlink(str(compiled_library_path))
        except FileNotFoundError:
            pass

        print(
            f"[gsyncio Build] Attempting to compile {gsyncio_path} to {compiled_library_path}."
        )

        try:
            subprocess.run(
                [
                    "go",
                    "build",
                    "-buildmode=c-shared",
                    "-o",
                    str(compiled_library_path),
                    str(gsyncio_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                cwd=gsyncio_path,
            )

            header_file = compiled_library_path.with_suffix(".h")
            if header_file.exists():
                header_file.unlink()

            relative_artifact_path = (
                f"pipebomb/gsyncio/gsyncio{compiled_library_extension}"
            )
            build_data["force_include"][str(compiled_library_path)] = str(
                relative_artifact_path
            )
            print(
                "[gsyncio Build] Native Go extension module compiled and bundled successfully!"
            )

        except subprocess.CalledProcessError as e:
            print(f"[gsyncio Build] Compilation failed: {e.stderr}")
            print(
                "[gsyncio Build] Aborting native compilation. Packaging pure-Python fallback."
            )