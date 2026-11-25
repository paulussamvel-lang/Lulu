"""Install a small Paul工作台 runtime into a dedicated Python environment."""

from pathlib import Path
import shutil
import sys
import sysconfig


def main():
    if sys.prefix == sys.base_prefix:
        raise SystemExit("请用工作台 MCP 专用虚拟环境的 Python 运行此脚本。")
    source = Path(__file__).resolve().parents[1] / "src"
    package = Path(sysconfig.get_path("purelib")) / "paul_workbench_runtime"
    package.mkdir(mode=0o700)
    (package / "core").mkdir(mode=0o700)
    for folder in (package, package / "core"):
        (folder / "__init__.py").touch()
    for name in (
        "paul_workbench_mcp.py",
        "core/content_workbench.py",
        "core/creator_workbench.py",
        "core/creator_workflow.py",
        "core/revision_conflict.py",
    ):
        shutil.copyfile(source / name, package / name)
    print(package)


if __name__ == "__main__":
    main()
