import asyncio
from pathlib import Path


async def test_ruff(pipebomb_folder: Path):
    proc = await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "ruff",
        "check",
        str(pipebomb_folder),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = [s.decode("utf-8") for s in await proc.communicate()]

    if proc.returncode != 0:
        assert False, (
            f"ruff check failed with logs:\nSTDOUT:\n    {stdout}\nSTDERR:\n    {stderr}"
        )


async def test_mypy(pipebomb_folder: Path):
    proc = await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "mypy",
        str(pipebomb_folder),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = [s.decode("utf-8") for s in await proc.communicate()]

    if proc.returncode != 0:
        assert False, (
            f"mypy check failed with logs:\nSTDOUT:\n    {stdout}\nSTDERR:\n    {stderr}"
        )


async def test_bandit(pipebomb_folder: Path):
    import os

    root_dir = pipebomb_folder.parent
    sarif_path = root_dir / "tests" / "bandit_results.sarif"
    use_sarif = os.environ.get("GITHUB_TOKEN") is not None

    cmd = [
        "bandit",
        "-r",
        str(pipebomb_folder),
        "-c",
        str(root_dir / "pyproject.toml"),
        "--skip",
        "B110",
    ]

    if use_sarif:
        cmd.extend(["-f", "sarif", "-o", str(sarif_path)])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = [s.decode("utf-8") for s in await proc.communicate()]

    if proc.returncode != 0:
        assert False, (
            f"bandit check failed with logs:\nSTDOUT:\n    {stdout}\nSTDERR:\n    {stderr}"
        )

    if use_sarif:
        assert sarif_path.exists(), "SARIF file was not generated"
