"""Import + re-export with no changes (checks the pipeline keeps the runtime contract)."""
from common import args, export_glb, import_glb
from pathlib import Path

import_glb()
export_glb(Path(args()[0]))
