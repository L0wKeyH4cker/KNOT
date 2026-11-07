"""TeamBlocks local application services."""

from pathlib import Path
import sys

# Optional project-local dependencies installed with pip --target .tools/python.
_dependencies = Path(__file__).resolve().parent.parent / ".tools" / "python"
if _dependencies.is_dir():
    sys.path.insert(0, str(_dependencies))
