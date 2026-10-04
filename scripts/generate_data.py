from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from construction_iq.config import DATA_ROOT, PROFILE_PATH, DemoProfile
from construction_iq.generate import write_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic, synthetic construction demo fixtures.")
    parser.add_argument("--output-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--profile", type=Path, default=PROFILE_PATH)
    args = parser.parse_args()
    manifest = write_dataset(args.output_root, DemoProfile.load(args.profile))
    print(json.dumps({
        "outputRoot": str(args.output_root.resolve()),
        "counts": manifest["counts"],
        "scenarioRecordCount": manifest["scenarioRecordCount"],
        "anchorRecordCount": manifest["anchorRecordCount"],
        "workContextDocumentCount": manifest["workContextDocumentCount"],
        "goldenScenario": manifest["goldenScenario"],
    }, indent=2))


if __name__ == "__main__":
    main()
