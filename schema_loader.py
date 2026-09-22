"""Load a Grist table schema from a human-readable YAML file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def _widget_options(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def load_schema(path: str | Path) -> list[dict[str, Any]]:
    """Return Grist column definitions from ``path``."""
    source = Path(path)
    with source.open(encoding="utf-8") as stream:
        document = yaml.safe_load(stream) or {}

    columns = document.get("columns")
    if not isinstance(columns, list) or not columns:
        raise ValueError(f"{source}: expected a non-empty 'columns' list")

    result = []
    for index, column in enumerate(columns, start=1):
        if not isinstance(column, dict) or not column.get("id"):
            raise ValueError(f"{source}: column {index} needs an 'id'")

        fields = dict(column.get("fields") or {})
        for key in ("label", "type"):
            if not fields.get(key):
                raise ValueError(f"{source}: column {column['id']} needs '{key}'")

        if "choices" in column:
            fields["widgetOptions"] = _widget_options({
                "choices": column["choices"],
                "choiceOptions": column.get("choice_options", {}),
            })
        elif "widget_options" in column:
            fields["widgetOptions"] = _widget_options(column["widget_options"])

        if "formula" in column:
            fields["formula"] = str(column["formula"]).strip()
            fields["isFormula"] = column.get("is_formula", True)
        elif "is_formula" in column:
            fields["isFormula"] = column["is_formula"]

        if "recalc_when" in column:
            fields["recalcWhen"] = column["recalc_when"]
        if "recalc_deps" in column:
            fields["recalcDeps"] = column["recalc_deps"]

        result.append({"id": column["id"], "fields": fields})

    return result