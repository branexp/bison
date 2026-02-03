from __future__ import annotations

import json
from pathlib import Path

from emailbison.models import CampaignCreateSpec


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    out_path = root / "campaign.schema.json"

    schema = CampaignCreateSpec.model_json_schema()

    # Make the schema friendlier for editors.
    schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
    schema.setdefault("title", "CampaignCreateSpec")

    out_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
