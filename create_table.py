#!/usr/bin/env python3
"""Create a Grist table from a YAML schema."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

from config import load_env_file
from schema_loader import load_schema

BASE_URL = "https://grist.numerique.gouv.fr/api"
DEFAULT_SCHEMA = Path("data/schema.yml")


class Grist:
    def __init__(self, api_key: str, doc_id: str, base_url: str = BASE_URL):
        self.doc_id = doc_id
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    def _url(self, suffix: str) -> str:
        return f"{self.base_url}/docs/{self.doc_id}{suffix}"

    def tables(self) -> list[str]:
        response = self.session.get(self._url("/tables"))
        response.raise_for_status()
        return [table["id"] for table in response.json().get("tables", [])]

    def add_table(self, table: str) -> None:
        response = self.session.post(
            self._url("/apply"),
            json=[["AddTable", table, []]],
        )
        if not response.ok:
            raise RuntimeError(f"{response.status_code} - {response.text}")

    def columns(self, table: str) -> list[str]:
        return [column["id"] for column in self.column_details(table)]

    def column_details(self, table: str) -> list[dict]:
        response = self.session.get(self._url(f"/tables/{table}/columns"))
        response.raise_for_status()
        return response.json().get("columns", [])

    def add_columns(self, table: str, columns: list[dict]) -> None:
        response = self.session.post(
            self._url(f"/tables/{table}/columns"),
            json={"columns": columns},
        )
        if not response.ok:
            raise RuntimeError(f"{response.status_code} - {response.text}")

    def modify_columns(self, table: str, columns: list[dict]) -> None:
        response = self.session.patch(
            self._url(f"/tables/{table}/columns"),
            json={"columns": columns},
        )
        if not response.ok:
            raise RuntimeError(f"{response.status_code} - {response.text}")

    def delete_column(self, table: str, column_id: str) -> None:
        response = self.session.delete(
            self._url(f"/tables/{table}/columns/{column_id}")
        )
        if not response.ok:
            raise RuntimeError(f"{response.status_code} - {response.text}")


def print_dry_run(columns: list[dict]) -> None:
    print(f"{len(columns)} colonnes définies.\n")
    for column in columns:
        fields = column["fields"]
        nature = "formule" if fields.get("isFormula") else (
            "déclencheur" if fields.get("formula") else "saisie"
        )
        print(f"  {column['id']:<18} {fields['type']:<22} {nature}")
    print("\n--dry-run : rien n'a été envoyé.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doc", help="Document ID Grist (ou DOC_ID dans .env)")
    parser.add_argument("--table", default="Table1", help="Identifiant de la table")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA),
                        help="Fichier YAML de définition des colonnes")
    parser.add_argument("--env-file", default=".env",
                        help="Fichier de variables (défaut : .env)")
    parser.add_argument("--base", default=BASE_URL, help="URL de l'API Grist")
    parser.add_argument("--dry-run", action="store_true",
                        help="Afficher le schéma sans modifier Grist")
    parser.add_argument("--keep-defaults", action="store_true",
                        help="Conserver les colonnes A, B et C de Grist")
    parser.add_argument("--update-formulas", action="store_true",
                        help="Mettre à jour les formules existantes sans "
                             "convertir les colonnes gelées en formules")
    parser.add_argument("--update-gpu-fields", action="store_true",
                        help="Mettre à jour les choix des colonnes GPU/VRAM "
                             "déjà présentes")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_env_file(args.env_file)

    try:
        columns = load_schema(args.schema)
    except (OSError, ValueError) as error:
        sys.exit(f"Schéma invalide : {error}")

    if args.dry_run:
        print_dry_run(columns)
        return

    doc_id = args.doc or os.environ.get("DOC_ID")
    api_key = os.environ.get("GRIST_API_KEY")
    if not doc_id:
        sys.exit("DOC_ID absent : utilisez --doc ou renseignez DOC_ID dans .env.")
    if not api_key:
        sys.exit("GRIST_API_KEY absente de l'environnement.")

    grist = Grist(api_key, doc_id, args.base)
    table_created = args.table not in grist.tables()
    if table_created:
        try:
            grist.add_table(args.table)
        except Exception as error:
            sys.exit(f"Impossible de créer la table « {args.table} » : {error}")
        print(f"Table « {args.table} » créée.")

    existing_details = [] if table_created else grist.column_details(args.table)
    existing = [column["id"] for column in existing_details]
    print(f"Table « {args.table} » : {len(existing)} colonne(s) existante(s).")

    if args.update_gpu_fields and not table_created:
        gpu_columns = [
            column for column in columns
            if column["id"] in {"d_gpu", "d_vram"}
            and column["id"] in existing
        ]
        print(f"\nMise à jour de {len(gpu_columns)} question(s) GPU existante(s) :")
        for column in gpu_columns:
            try:
                grist.modify_columns(args.table, [column])
                print(f"  ~ {column['id']}")
            except Exception as error:
                print(f"  ! {column['id']} - ÉCHEC : {error}")

    if args.update_formulas and not table_created:
        existing_formulas = {
            column["id"] for column in existing_details
            if column.get("fields", {}).get("isFormula")
        }
        formulas = [
            column for column in columns
            if column["id"] in existing_formulas
            and column["fields"].get("isFormula")
        ]
        print(f"\nMise à jour de {len(formulas)} formule(s) existante(s) :")
        for column in formulas:
            try:
                grist.modify_columns(args.table, [column])
                print(f"  ~ {column['id']}")
            except Exception as error:
                print(f"  ! {column['id']} - ÉCHEC : {error}")
        print("  Les colonnes gelées en données ne sont pas modifiées.")

    to_create = [column for column in columns if column["id"] not in existing]
    if len(to_create) < len(columns):
        print(f"  {len(columns) - len(to_create)} déjà présente(s), ignorée(s).")

    created = []
    for column in to_create:
        try:
            grist.add_columns(args.table, [column])
            created.append(column["id"])
            print(f"  + {column['id']}")
        except Exception as error:
            print(f"  ! {column['id']} - ÉCHEC : {error}")

    print(f"\n{len(created)} colonne(s) créée(s).")

    if not args.keep_defaults:
        current = grist.columns(args.table)
        schema_ids = {column["id"] for column in columns}
        for column_id in (column for column in current if column in {"A", "B", "C"}):
            if column_id not in schema_ids:
                try:
                    grist.delete_column(args.table, column_id)
                    print(f"  - {column_id} (colonne Grist par défaut)")
                except Exception as error:
                    print(f"  ! suppression de {column_id} impossible : {error}")


if __name__ == "__main__":
    main()