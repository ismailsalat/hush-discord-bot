"""ZIP bundles combining JSON, CSV and TXT views of one export."""

from __future__ import annotations

import zipfile
from pathlib import Path

from app.exports import csv_exporter, json_exporter, txt_exporter
from app.exports.bundle import ExportBundle

#: Tables rendered as CSV as well as JSON (flat, spreadsheet friendly).
CSV_TABLES = {"ratings", "confessions", "bookmarks", "follows", "reports"}


def write_zip(path: Path, bundle: ExportBundle) -> Path:
    """Write a self-describing archive of the bundle."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("metadata.json", json_exporter.dumps(bundle.metadata))

        for name, rows in bundle.tables.items():
            archive.writestr(f"{name}.json", json_exporter.dumps(rows))
            if name in CSV_TABLES and rows:
                archive.writestr(f"{name}.csv", csv_exporter.dumps(rows))

        archive.writestr(
            "audit.txt", txt_exporter.dumps(bundle.metadata, bundle.tables)
        )
        archive.writestr(
            "README.txt",
            "Hush data export\n"
            "=====================\n\n"
            "metadata.json  provenance: scope, target, generation time, row counts\n"
            "<table>.json   full records for each table\n"
            "<table>.csv    spreadsheet-friendly view of the main tables\n"
            "audit.txt      human-readable rendering of everything above\n\n"
            "If 'identity_redacted' is true in metadata.json, Discord user ids\n"
            "have been removed because the requester was not authorised to see them.\n",
        )
    return path
