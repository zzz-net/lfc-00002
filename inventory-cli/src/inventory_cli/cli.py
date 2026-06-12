import typer
import json
import csv
import os
import sqlite3
from typing import Optional, List
from datetime import datetime
from .db import Database
from .config import ConfigManager
from .importer import InventoryImporter, ImportError
from .merger import InventoryMerger, MergeError
from .exporter import InventoryExporter, ExportError
from .config import ConfigError

VALID_OPERATION_TYPES = ["init", "import", "merge", "export", "rollback", "config", "prune"]

app = typer.Typer(
    help="""
    Offline Inventory Counting Merge CLI Tool.
    
    A local-first tool for merging inventory counts from multiple stores.
    Supports CSV/JSON import, configurable conflict resolution, 
    detailed export reports, and full audit history with rollback support.
    
    Quick Start:
      inventory init
      inventory import store_a.csv STORE001 --batch batch_store_a
      inventory import store_b.json STORE002 --batch batch_store_b
      inventory merge --strategy sum
      inventory export merged_report.report.json
    """,
    no_args_is_help=True,
    rich_markup_mode="rich"
)

DEFAULT_DB_PATH = "inventory.db"


def get_db(db_path: str = DEFAULT_DB_PATH) -> Database:
    db = Database(db_path)
    db.connect()
    return db


@app.command("init", help="Initialize a new inventory repository (creates SQLite database + example config)")
def init(
    db_path: str = typer.Option(
        DEFAULT_DB_PATH, "--database",
        help="Path to SQLite database file (created if not exists)"
    ),
    config_file: Optional[str] = typer.Option(
        ConfigManager.DEFAULT_CONFIG_FILE, "--config", "-c",
        help="Path to generate example config file (set to empty string to skip)"
    ),
    force_config: bool = typer.Option(
        False, "--force", "-f",
        help="Overwrite existing config file if it exists"
    )
):
    """
    Initialize a new inventory repository.
    
    Creates the SQLite database with required tables and sets default configuration:
    - Conflict strategy: require_manual
    - Validate negative quantities: enabled
    - Validate required columns (sku, quantity): enabled
    - Validate duplicate SKUs within batch: enabled
    
    Also generates an example 'inventory.config.json' file in current directory
    (use --config to specify a different path, or --config '' to skip).
    
    Examples:
        inventory init
        inventory init --database ./data/my_inventory.db
        inventory init --config ./configs/prod.json --force
        inventory init --config ''  # Skip config file generation
    """
    db = get_db(db_path)
    db.init_schema()
    
    config = ConfigManager(db)
    config.initialize_defaults()
    
    db.insert_history("init", "INIT", details="Initializing inventory repository")
    db.close()
    
    typer.secho(f"Successfully initialized inventory repository at {db_path}", fg=typer.colors.GREEN)
    typer.secho("Default configuration:", fg=typer.colors.BLUE)
    typer.secho("  - Conflict strategy: require_manual")
    typer.secho("  - Validate negative quantities: true")
    typer.secho("  - Validate required columns: true")
    typer.secho("  - Validate duplicate SKUs: true")
    
    if config_file:
        import os
        if os.path.exists(config_file) and not force_config:
            typer.secho(
                f"\nConfig file '{config_file}' already exists. Use --force to overwrite.",
                fg=typer.colors.YELLOW
            )
        else:
            try:
                ConfigManager.generate_example_config(config_file)
                typer.secho(
                    f"\nExample config generated at: {config_file}",
                    fg=typer.colors.GREEN
                )
                typer.secho(
                    "Edit the 'conflict_strategy' field to change default merge behavior.",
                    fg=typer.colors.CYAN
                )
            except Exception as e:
                typer.secho(
                    f"\nWarning: Could not generate config file: {str(e)}",
                    fg=typer.colors.YELLOW
                )


@app.command("import", help="Import inventory data from a CSV or JSON file into a new batch")
def import_inventory(
    file_path: str = typer.Argument(
        ..., 
        help="Path to input file (.csv or .json). Must contain 'sku' and 'quantity' columns/fields."
    ),
    store_id: str = typer.Argument(
        ..., 
        help="Store identifier (e.g., STORE001, BEIJING_01). Used to track data source."
    ),
    batch_id: str = typer.Option(
        None, "--batch", "-b",
        help="Custom batch identifier. If not provided, auto-generated as batch_YYYYMMDD_HHMMSS"
    ),
    config_file: Optional[str] = typer.Option(
        None, "--config", "-c",
        help="Path to JSON config file for validation rules. Default: ./inventory.config.json"
    ),
    db_path: str = typer.Option(
        DEFAULT_DB_PATH, "--database",
        help="Path to SQLite database file"
    )
):
    """
    Import inventory data from CSV or JSON file.
    
    Required file format:
      - CSV: Header row must contain 'sku' and 'quantity' columns
      - JSON: Array of objects with 'sku' and 'quantity' fields
    
    Validation rules (from config file or SQLite config):
      - validation.required_columns: Missing sku/quantity columns -> FAIL
      - validation.negative_quantities: Negative quantity values -> FAIL
      - validation.duplicate_sku: Duplicate SKU in same batch (inconsistent qty) -> FAIL
      - Unknown file format -> Always FAIL
    
    All validations are atomic: on failure, NO records are inserted into the database.
    Configuration file takes priority over SQLite-persisted config.
    
    Examples:
        inventory import ./store_a.csv STORE001 --batch batch_2025_store_a
        inventory import ./data/store_b.json STORE002
        inventory import ./counts.csv STORE003 --config ./lenient.config.json
    """
    if batch_id is None:
        batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    db = get_db(db_path)
    config = ConfigManager(db)
    
    try:
        loaded_config = config.load_config_file(config_file)
    except ConfigError as e:
        typer.secho(f"Configuration error: {str(e)}", fg=typer.colors.RED)
        typer.secho("No changes made to database.", fg=typer.colors.YELLOW)
        db.close()
        raise typer.Exit(code=1)
    
    importer = InventoryImporter(config)
    
    try:
        records = importer.import_file(file_path, store_id, batch_id)
        
        validation_errors = importer.validate_records(records, batch_id)
        if validation_errors:
            typer.secho("Validation failed - NO records were imported:", fg=typer.colors.RED)
            for error in validation_errors:
                typer.secho(f"  - {error}", fg=typer.colors.RED)
            typer.secho("\nFix the source file and try again.", fg=typer.colors.YELLOW)
            db.close()
            raise typer.Exit(code=1)
        
        db.insert_inventory_records(records)
        db.insert_history("import", batch_id, store_id, file_path, f"Imported {len(records)} records")
        
        typer.secho(f"Successfully imported {len(records)} records from {file_path}", fg=typer.colors.GREEN)
        typer.secho(f"Batch ID: {batch_id}", fg=typer.colors.BLUE)
        typer.secho(f"Store ID: {store_id}", fg=typer.colors.BLUE)
        
    except ImportError as e:
        typer.secho(f"Import failed: {str(e)}", fg=typer.colors.RED)
        typer.secho("Current database state is unchanged.", fg=typer.colors.YELLOW)
        db.close()
        raise typer.Exit(code=1)
    finally:
        db.close()


@app.command("merge", help="Merge inventory data from multiple batches with conflict resolution")
def merge(
    batches: Optional[List[str]] = typer.Argument(
        None, 
        help="Batch IDs to merge (space-separated). If not provided, merges ALL imported batches."
    ),
    conflict_strategy: str = typer.Option(
        None, "--strategy", "-s",
        help=f"Conflict resolution strategy for cross-store SKU mismatches: "
             f"{', '.join(ConfigManager.CONFLICT_STRATEGIES)}"
    ),
    config_file: Optional[str] = typer.Option(
        None, "--config", "-c",
        help="Path to JSON config file. If not specified, looks for 'inventory.config.json' in current directory."
    ),
    db_path: str = typer.Option(
        DEFAULT_DB_PATH, "--database",
        help="Path to SQLite database file"
    )
):
    """
    Merge inventory from multiple batches and create a snapshot.
    
    Configuration Priority (highest to lowest):
      1. --strategy flag (explicit command line)
      2. --config specified JSON file
      3. ./inventory.config.json (if exists in current directory)
      4. SQLite persisted config (via 'config' command)
      5. Built-in default (require_manual)
    
    Conflict Strategies (how to resolve same SKU with different quantities across stores):
      - first           : Use quantity from the earliest-imported store
      - last            : Use quantity from the latest-imported store
      - sum             : Keep each store's quantity separately (no cross-store resolution)
      - average         : Use the average (floor) of all store quantities for each store
      - require_manual  : [DEFAULT] Do NOT merge if any conflicts exist. Fail explicitly.
    
    Note: Same-batch SKU quantity conflicts ALWAYS fail regardless of strategy.
          Bad/invalid config file will FAIL before modifying any snapshots.
    
    Creates a snapshot that can be rolled back to later via 'rollback'.
    
    Examples:
        inventory merge batch_store_a batch_store_b --strategy sum
        inventory merge                                    # Merge all, use config from file or SQLite
        inventory merge --config ./prod.config.json        # Merge using specified config
        inventory merge --strategy last --config ./cfg.json  # --strategy takes priority over file
        inventory merge -s require_manual batch_001 batch_002
    """
    db = get_db(db_path)
    config = ConfigManager(db)
    
    try:
        loaded_config = config.load_config_file(config_file)
        if loaded_config and config_file:
            typer.secho(f"Loaded config from: {config_file}", fg=typer.colors.CYAN)
        elif loaded_config:
            typer.secho(
                f"Loaded config from default: {ConfigManager.DEFAULT_CONFIG_FILE}",
                fg=typer.colors.CYAN
            )
    except ConfigError as e:
        typer.secho(f"Configuration error: {str(e)}", fg=typer.colors.RED)
        typer.secho("\nNo changes made to database or snapshots.", fg=typer.colors.YELLOW)
        typer.secho("Use 'inventory init' to generate a valid config example.", fg=typer.colors.CYAN)
        db.close()
        raise typer.Exit(code=1)
    
    if conflict_strategy:
        config.set_cli_override('conflict_strategy', conflict_strategy)
        try:
            _ = config.get_conflict_strategy()
        except ValueError as e:
            typer.secho(f"Invalid strategy: {str(e)}", fg=typer.colors.RED)
            typer.secho(f"Valid strategies: {', '.join(ConfigManager.CONFLICT_STRATEGIES)}", fg=typer.colors.YELLOW)
            db.close()
            raise typer.Exit(code=1)
    
    strategy = config.get_conflict_strategy()
    
    config_summary = config.get_effective_config_summary()
    typer.secho(f"\nEffective configuration:", fg=typer.colors.BLUE, bold=True)
    for key, info in config_summary.items():
        source_colors = {
            'cli_parameter': typer.colors.GREEN,
            'config_file': typer.colors.CYAN,
            'sqlite_db': typer.colors.MAGENTA,
            'default': typer.colors.YELLOW
        }
        color = source_colors.get(info['source'], typer.colors.WHITE)
        typer.secho(
            f"  {key:<30} = {str(info['value']):<15}  [{info['source']}]",
            fg=color
        )
    typer.secho(f"\nConflict strategy: {strategy}", fg=typer.colors.BLUE, bold=True)
    
    if batches is None:
        batches = db.get_unique_batches()
    
    if not batches:
        typer.secho("No batches found to merge. Import data first with 'import' command.", fg=typer.colors.YELLOW)
        db.close()
        raise typer.Exit(code=0)
    
    typer.secho(f"Merging batches: {', '.join(batches)}", fg=typer.colors.BLUE)
    
    all_records = []
    for batch in batches:
        records = db.get_records_by_batch(batch)
        if not records:
            typer.secho(f"Warning: Batch '{batch}' has no records, skipping.", fg=typer.colors.YELLOW)
            continue
        all_records.extend(records)
    
    if not all_records:
        typer.secho("No records found in specified batches", fg=typer.colors.YELLOW)
        db.close()
        raise typer.Exit(code=0)
    
    merger = InventoryMerger(config)
    result = merger.merge(batches, all_records)
    
    if not result.success:
        typer.secho(f"\nMerge failed: {result.message}", fg=typer.colors.RED)
        if result.conflicts:
            typer.secho(f"\nDetailed conflicts ({len(result.conflicts)} found):", fg=typer.colors.YELLOW)
            typer.secho("-" * 80)
            for i, conflict in enumerate(result.conflicts, 1):
                typer.secho(
                    f"\n  Conflict #{i}: SKU '{conflict['sku']}'",
                    fg=typer.colors.YELLOW, bold=True
                )
                typer.secho(
                    f"    {conflict['store_id_1']} (batch {conflict['batch_id_1']}): {conflict['quantity_1']}",
                    fg=typer.colors.YELLOW
                )
                typer.secho(
                    f"    {conflict['store_id_2']} (batch {conflict['batch_id_2']}): {conflict['quantity_2']}",
                    fg=typer.colors.YELLOW
                )
        typer.secho("\nSuggestions:", fg=typer.colors.CYAN)
        typer.secho("  - Use a different strategy: merge --strategy sum", fg=typer.colors.CYAN)
        typer.secho("  - Or change default: config conflict_strategy sum", fg=typer.colors.CYAN)
        typer.secho("  - Or fix the source files and re-import", fg=typer.colors.CYAN)
        db.close()
        raise typer.Exit(code=1)
    
    merge_batch_id = f"merged_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    for r in result.merged_records:
        if r.created_at and isinstance(r.created_at, datetime):
            pass
    
    snapshot_data = {
        'records': [{
            'sku': r.sku,
            'quantity': r.quantity,
            'store_id': r.store_id,
            'batch_id': r.batch_id,
            'source_file': r.source_file,
            'created_at': r.created_at.isoformat() if r.created_at and isinstance(r.created_at, datetime) else None
        } for r in result.merged_records],
        'source_batches': batches,
        'strategy': strategy
    }
    db.insert_snapshot(merge_batch_id, snapshot_data)
    
    db.insert_history(
        "merge", merge_batch_id,
        details=f"Merged {len(batches)} batches ({len(all_records)} total records) with '{strategy}' strategy -> {len(result.merged_records)} merged records"
    )
    
    typer.secho(f"\nSuccessfully merged {len(result.merged_records)} records", fg=typer.colors.GREEN, bold=True)
    typer.secho(f"Merge batch ID: {merge_batch_id}", fg=typer.colors.BLUE)
    typer.secho(f"Snapshot saved. Use 'rollback' to revert to this version later.", fg=typer.colors.CYAN)
    
    if result.conflicts:
        typer.secho(f"\nNote: {len(result.conflicts)} cross-store conflicts were resolved using '{strategy}' strategy.", fg=typer.colors.YELLOW)
    
    db.close()


@app.command("export", help="Export inventory data to CSV, JSON, or detailed report with source batches")
def export(
    output_file: str = typer.Argument(..., help="Output file path (.csv, .json, .report.json)"),
    batch_id: Optional[str] = typer.Option(None, "--batch", "-b", help="Specific batch to export"),
    include_diff: bool = typer.Option(True, "--diff", help="Include difference report (use --no-diff to disable, default: True)"),
    db_path: str = typer.Option(DEFAULT_DB_PATH, "--database", help="Path to SQLite database")
):
    db = get_db(db_path)
    exporter = InventoryExporter()
    config = ConfigManager(db)
    merger = InventoryMerger(config)
    
    source_batches: Optional[List[str]] = None
    strategy: Optional[str] = None
    diff_report: Optional[Dict] = None
    
    if batch_id:
        records = db.get_records_by_batch(batch_id)
        if not records:
            typer.secho(f"No records found for batch {batch_id}", fg=typer.colors.YELLOW)
            db.close()
            raise typer.Exit(code=0)
        source_batches = [batch_id]
    else:
        snapshot = db.get_latest_snapshot()
        if snapshot:
            snapshot_data = json.loads(snapshot.inventory_data)
            raw_records = snapshot_data.get('records', [])
            from .models import InventoryRecord
            records = []
            for r in raw_records:
                record_data = dict(r)
                if 'created_at' in record_data and record_data['created_at']:
                    if isinstance(record_data['created_at'], str):
                        record_data['created_at'] = datetime.fromisoformat(record_data['created_at'])
                records.append(InventoryRecord(**record_data))
            source_batches = snapshot_data.get('source_batches')
            strategy = snapshot_data.get('strategy')
            if include_diff and records:
                diff_report = merger.generate_diff_report(records)
        else:
            records = db.get_all_records()
            source_batches = db.get_unique_batches()
            if include_diff and records:
                diff_report = merger.generate_diff_report(records)
    
    if not records:
        typer.secho("No records found to export", fg=typer.colors.YELLOW)
        db.close()
        raise typer.Exit(code=0)
    
    try:
        if output_file.endswith('.csv'):
            exporter.export_csv(records, output_file, source_batches, strategy)
        elif output_file.endswith('.report.json'):
            exporter.export_report(records, output_file, include_diff, source_batches, strategy, diff_report)
        elif output_file.endswith('.json'):
            exporter.export_json(records, output_file, source_batches, strategy)
        else:
            typer.secho("Unsupported output format. Use .csv, .json, or .report.json", fg=typer.colors.RED)
            db.close()
            raise typer.Exit(code=1)
        
        export_batch_ref = batch_id or (snapshot.batch_id if 'snapshot' in locals() and snapshot else "ALL")
        db.insert_history("export", export_batch_ref, file_path=output_file, 
                        details=f"Exported {len(records)} records to {output_file}")
        
        typer.secho(f"Successfully exported {len(records)} records to {output_file}", fg=typer.colors.GREEN)
        if source_batches:
            typer.secho(f"Source batches: {', '.join(source_batches)}", fg=typer.colors.BLUE)
        if strategy:
            typer.secho(f"Merge strategy: {strategy}", fg=typer.colors.BLUE)
        
    except ExportError as e:
        typer.secho(f"Export failed: {str(e)}", fg=typer.colors.RED)
        db.close()
        raise typer.Exit(code=1)
    finally:
        db.close()


@app.command("history", help="Show operation history (persists across restarts)")
def history(
    limit: int = typer.Option(
        50, "--limit", "-n",
        help="Maximum number of history entries to show (most recent first)"
    ),
    batch_id: Optional[str] = typer.Option(
        None, "--batch", "-b",
        help="Filter history by a specific batch ID"
    ),
    db_path: str = typer.Option(
        DEFAULT_DB_PATH, "--database",
        help="Path to SQLite database file"
    )
):
    """
    Display the audit history of all operations.
    
    Recorded operations: init, import, merge, export, rollback.
    History is stored in the SQLite database and persists across CLI restarts.
    
    Examples:
        inventory history                      # Show last 50 operations
        inventory history -n 100               # Show last 100 operations
        inventory history --batch batch_store_a  # Show operations for specific batch
    """
    db = get_db(db_path)
    
    if batch_id:
        entries = db.get_history_by_batch(batch_id)
    else:
        entries = db.get_history(limit)
    
    if not entries:
        typer.secho("No history entries found", fg=typer.colors.YELLOW)
        db.close()
        raise typer.Exit(code=0)
    
    typer.secho(f"Operation History (last {len(entries)} entries):", fg=typer.colors.BLUE, bold=True)
    typer.secho("-" * 100)
    
    for entry in entries:
        timestamp = entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        op_color = {
            'init': typer.colors.CYAN,
            'import': typer.colors.GREEN,
            'merge': typer.colors.MAGENTA,
            'export': typer.colors.BLUE,
            'rollback': typer.colors.YELLOW,
            'config': typer.colors.BRIGHT_BLUE,
            'prune': typer.colors.BRIGHT_RED
        }.get(entry.operation.lower(), typer.colors.WHITE)
        
        line_parts = [
            typer.style(f"[{timestamp}]", fg=typer.colors.WHITE, dim=True),
            typer.style(f"{entry.operation.upper():10}", fg=op_color, bold=True),
            typer.style(f"{entry.batch_id:25}", fg=typer.colors.WHITE)
        ]
        
        extra = []
        if entry.store_id:
            extra.append(f"Store: {entry.store_id}")
        if entry.file_path:
            extra.append(f"File: {entry.file_path}")
        if entry.details:
            extra.append(entry.details)
        
        if extra:
            line_parts.append(typer.style(" | ".join(extra), fg=typer.colors.WHITE, dim=True))
        
        typer.echo(" ".join(line_parts))
    
    db.close()


@app.command("rollback", help="Rollback to a previous snapshot (creates new snapshot, no data loss)")
def rollback(
    snapshot_id: Optional[int] = typer.Argument(
        None, 
        help="Snapshot ID to rollback to. Run without ID to list available snapshots."
    ),
    db_path: str = typer.Option(
        DEFAULT_DB_PATH, "--database",
        help="Path to SQLite database file"
    )
):
    """
    Rollback inventory to a previous merge snapshot.
    
    This does NOT delete data - it creates a NEW snapshot that is a copy of the target.
    The latest snapshot is what 'export' uses by default (without --batch flag).
    After rollback, running 'export' without --batch will use the rolled-back version.
    
    Examples:
        inventory rollback           # List all available snapshots
        inventory rollback 1         # Rollback to snapshot ID 1
        inventory rollback 2 --db ./data/inv.db
    """
    db = get_db(db_path)
    
    snapshots = db.get_all_snapshots()
    
    if not snapshots:
        typer.secho(
            "No snapshots found to rollback to. Snapshots are created by 'merge' command.",
            fg=typer.colors.YELLOW
        )
        db.close()
        raise typer.Exit(code=0)
    
    if snapshot_id is None:
        typer.secho("Available snapshots (latest first):", fg=typer.colors.BLUE, bold=True)
        typer.secho("-" * 100)
        typer.secho(
            f"{'ID':>4}  {'Created At':<20}  {'Batch ID':<28}  {'Records':>8}  {'Strategy':<16}",
            fg=typer.colors.CYAN, bold=True
        )
        typer.secho("-" * 100)
        for snap in snapshots:
            timestamp = snap.created_at.strftime('%Y-%m-%d %H:%M:%S')
            data = json.loads(snap.inventory_data)
            record_count = len(data.get('records', []))
            strategy = data.get('strategy', 'N/A')
            rolled_back = data.get('rolled_back_from', '')
            batch_display = snap.batch_id[:26] + ('..' if len(snap.batch_id) > 26 else '')
            if rolled_back:
                batch_display += ' ←'
            typer.secho(
                f"{snap.id:>4}  {timestamp:<20}  {batch_display:<28}  {record_count:>8}  {strategy:<16}"
            )
        typer.secho("\nRun: inventory rollback <ID>  to select a snapshot", fg=typer.colors.CYAN)
        db.close()
        raise typer.Exit(code=0)
    
    snapshot = db.get_snapshot_by_id(snapshot_id)
    
    if not snapshot:
        typer.secho(f"Snapshot {snapshot_id} not found", fg=typer.colors.RED)
        typer.secho("Run 'rollback' without arguments to see available IDs.", fg=typer.colors.YELLOW)
        db.close()
        raise typer.Exit(code=1)
    
    snapshot_data = json.loads(snapshot.inventory_data)
    record_count = len(snapshot_data.get('records', []))
    source_batches = snapshot_data.get('source_batches', [])
    
    new_batch_id = f"rollback_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    new_snapshot_data = {
        'records': snapshot_data['records'],
        'source_batches': source_batches,
        'strategy': snapshot_data.get('strategy', 'rollback'),
        'rolled_back_from': snapshot.batch_id
    }
    
    db.insert_snapshot(new_batch_id, new_snapshot_data)
    db.insert_history(
        "rollback", new_batch_id,
        details=f"Rolled back to snapshot #{snapshot_id} (batch: {snapshot.batch_id}, {record_count} records). "
                f"Source batches: {', '.join(source_batches) if source_batches else 'N/A'}"
    )
    
    typer.secho(f"Rollback successful!", fg=typer.colors.GREEN, bold=True)
    typer.secho(f"  Rolled back to snapshot #{snapshot_id} (batch: {snapshot.batch_id})", fg=typer.colors.BLUE)
    typer.secho(f"  New snapshot batch ID: {new_batch_id}", fg=typer.colors.BLUE)
    typer.secho(f"  Record count: {record_count}", fg=typer.colors.BLUE)
    typer.secho(
        "\nNext 'export' (without --batch) will use this rolled-back version.",
        fg=typer.colors.CYAN
    )
    
    db.close()


@app.command("config", help="View or update configuration (conflict strategy, validation rules)")
def config(
    key: Optional[str] = typer.Argument(
        None, 
        help="Configuration key. Omit both key and value to view all settings."
    ),
    value: Optional[str] = typer.Argument(
        None, 
        help="Value to set. Omit to view current value of the key."
    ),
    db_path: str = typer.Option(
        DEFAULT_DB_PATH, "--database",
        help="Path to SQLite database file"
    )
):
    """
    Manage tool configuration.
    
    Available configuration keys:
      - conflict_strategy        : One of first|last|sum|average|require_manual (default: require_manual)
      - validate_negative        : true|false, reject negative quantities (default: true)
      - validate_required_columns: true|false, require sku+quantity fields (default: true)
      - validate_duplicate_sku   : true|false, reject duplicate SKU in same batch (default: true)
    
    Examples:
        inventory config                                   # Show all config
        inventory config conflict_strategy                 # Show current strategy
        inventory config conflict_strategy sum             # Change strategy to 'sum'
        inventory config validate_negative false           # Disable negative quantity check
        inventory config validate_duplicate_sku true --db ./custom.db
    """
    db = get_db(db_path)
    config = ConfigManager(db)
    
    if key is None:
        all_config = config.get_all_config()
        typer.secho("Current configuration:", fg=typer.colors.BLUE, bold=True)
        typer.secho("-" * 50)
        for k, v in sorted(all_config.items()):
            typer.secho(f"  {k:<30} = {v}")
        typer.secho("-" * 50)
        typer.secho("\nTo change a value: inventory config <key> <value>", fg=typer.colors.CYAN)
    elif value is None:
        result = None
        if key == 'conflict_strategy':
            result = config.get_conflict_strategy()
        elif key == 'validate_negative':
            result = config.validate_negative()
        elif key == 'validate_required_columns':
            result = config.validate_required_columns()
        elif key == 'validate_duplicate_sku':
            result = config.validate_duplicate_sku()
        else:
            result = db.get_config(key)
        
        if result is not None:
            typer.secho(f"{key} = {result}", fg=typer.colors.BLUE, bold=True)
        else:
            typer.secho(f"Key '{key}' not found", fg=typer.colors.YELLOW)
            typer.secho(
                "Known keys: conflict_strategy, validate_negative, validate_required_columns, validate_duplicate_sku",
                fg=typer.colors.CYAN
            )
    else:
        try:
            if key == 'conflict_strategy':
                config.set_conflict_strategy(value)
            elif key == 'validate_negative':
                bool_val = value.lower() == 'true'
                config.set_validate_negative(bool_val)
            elif key == 'validate_required_columns':
                bool_val = value.lower() == 'true'
                config.set_validate_required_columns(bool_val)
            elif key == 'validate_duplicate_sku':
                bool_val = value.lower() == 'true'
                config.set_validate_duplicate_sku(bool_val)
            else:
                db.set_config(key, value)
            
            db.insert_history(
                "config", "CONFIG",
                details=f"Changed {key} = {value}"
            )
            
            typer.secho(f"Successfully set {key} = {value}", fg=typer.colors.GREEN, bold=True)
        except ValueError as e:
            typer.secho(f"Error setting {key}: {str(e)}", fg=typer.colors.RED)
            if key == 'conflict_strategy':
                typer.secho(
                    f"Valid values: {', '.join(ConfigManager.CONFLICT_STRATEGIES)}",
                    fg=typer.colors.YELLOW
                )
    
    db.close()


@app.command("batches", help="List all imported batches with record counts")
def list_batches(
    db_path: str = typer.Option(
        DEFAULT_DB_PATH, "--database",
        help="Path to SQLite database file"
    )
):
    """
    Display all imported batches and their record counts.
    
    Useful to find batch IDs for:
      - 'merge <batch1> <batch2>'  (merge specific batches)
      - 'export --batch <batch>'   (export a single batch)
      - 'history --batch <batch>'  (view history for a batch)
    
    Examples:
        inventory batches
        inventory batches --db ./data/my.db
    """
    db = get_db(db_path)
    batches = db.get_unique_batches()
    
    if not batches:
        typer.secho(
            "No batches found yet. Import data with: inventory import <file> <store_id>",
            fg=typer.colors.YELLOW
        )
        db.close()
        raise typer.Exit(code=0)
    
    typer.secho("Available batches:", fg=typer.colors.BLUE, bold=True)
    typer.secho("-" * 60)
    
    total_records = 0
    for batch in sorted(batches):
        records = db.get_records_by_batch(batch)
        stores = list(set(r.store_id for r in records))
        skus = list(set(r.sku for r in records))
        total_records += len(records)
        
        typer.secho(
            f"  {batch:<30}  {len(records):>5} records  "
            f"{len(skus):>4} SKUs  stores: {', '.join(stores)}"
        )
    
    typer.secho("-" * 60)
    typer.secho(f"  {'TOTAL':<30}  {total_records:>5} records", fg=typer.colors.CYAN, bold=True)
    
    db.close()


@app.command("prune", help="Clean up old snapshots and orphaned batches by date or retention count")
def prune(
    before: Optional[str] = typer.Option(
        None, "--before",
        help="Delete snapshots older than this ISO time, e.g. '2025-01-01' or '2025-01-01T00:00:00'"
    ),
    keep: Optional[int] = typer.Option(
        None, "--keep",
        help="Keep only N most recent snapshots. Older ones will be deleted."
    ),
    prune_orphans: bool = typer.Option(
        False, "--prune-orphans",
        help="Also delete batches no longer referenced by any retained snapshot"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Preview what would be deleted without making any changes"
    ),
    db_path: str = typer.Option(
        DEFAULT_DB_PATH, "--database",
        help="Path to SQLite database file"
    )
):
    """
    Clean up old snapshots and optionally orphaned batch data.

    Use --dry-run first to preview the changes. At least one of --before or --keep is required.
    When both are specified, the union of matching snapshots is deleted.

    Deleted snapshots will no longer appear in 'rollback' listing.
    When --prune-orphans is specified, batch data (inventory records) that are no longer
    referenced by any remaining snapshot will also be deleted.

    All deletions are atomic - either everything succeeds or nothing is changed.
    The prune operation is recorded in the history table.

    Examples:
        inventory prune --dry-run --keep 3                         # Preview keeping latest 3 snapshots
        inventory prune --keep 3                                   # Keep only latest 3 snapshots
        inventory prune --before 2025-01-01 --dry-run              # Preview deleting old snapshots
        inventory prune --before 2025-01-01T00:00:00               # Delete snapshots before 2025
        inventory prune --keep 5 --prune-orphans --dry-run         # Preview including orphan cleanup
        inventory prune --keep 2 --prune-orphans                   # Keep 2, delete orphans
    """
    if before is None and keep is None:
        typer.secho(
            "Error: At least one of --before or --keep must be specified.",
            fg=typer.colors.RED
        )
        typer.secho(
            "Use --dry-run --keep <N> or --dry-run --before <TIME> to preview changes.",
            fg=typer.colors.YELLOW
        )
        raise typer.Exit(code=1)

    if keep is not None and keep < 0:
        typer.secho(
            f"Error: --keep value must be non-negative, got {keep}",
            fg=typer.colors.RED
        )
        raise typer.Exit(code=1)

    before_time: Optional[datetime] = None
    if before:
        try:
            if 'T' not in before:
                before_time = datetime.fromisoformat(before + "T23:59:59")
            else:
                before_time = datetime.fromisoformat(before)
        except ValueError:
            typer.secho(
                f"Error: Invalid --before time format: '{before}'. "
                f"Use ISO format like '2025-01-01' or '2025-01-01T10:00:00'.",
                fg=typer.colors.RED
            )
            raise typer.Exit(code=1)

    if not os.path.exists(db_path):
        typer.secho(
            f"Error: Database file not found: {db_path}",
            fg=typer.colors.RED
        )
        typer.secho(
            "Run 'inventory init' first to create the database.",
            fg=typer.colors.CYAN
        )
        raise typer.Exit(code=1)

    try:
        db = get_db(db_path)
    except sqlite3.OperationalError as e:
        if "read-only" in str(e).lower() or "permission" in str(e).lower():
            typer.secho(
                f"Error: Database is read-only or inaccessible: {e}",
                fg=typer.colors.RED
            )
        else:
            typer.secho(
                f"Error opening database: {e}",
                fg=typer.colors.RED
            )
        raise typer.Exit(code=1)

    try:
        all_snapshots = db.get_all_snapshots()
        if not all_snapshots:
            typer.secho(
                "No snapshots found. Nothing to prune.",
                fg=typer.colors.YELLOW
            )
            db.close()
            raise typer.Exit(code=0)

        try:
            snapshots_to_delete, batches_to_delete, orphan_batches = db.plan_prune(
                before_time=before_time,
                keep_count=keep,
                prune_orphans=prune_orphans
            )
        except ValueError as e:
            typer.secho(f"Error: {str(e)}", fg=typer.colors.RED)
            db.close()
            raise typer.Exit(code=1)

        if not snapshots_to_delete and not orphan_batches:
            filter_desc = []
            if before:
                filter_desc.append(f"before {before}")
            if keep is not None:
                filter_desc.append(f"keep {keep}")
            typer.secho(
                f"No data to prune for filters: {', '.join(filter_desc)}",
                fg=typer.colors.YELLOW
            )
            db.close()
            raise typer.Exit(code=0)

        all_snapshot_ids = {s.id for s in all_snapshots}
        to_delete_ids = {s.id for s in snapshots_to_delete}
        remaining_ids = all_snapshot_ids - to_delete_ids
        still_referenced = db.get_batches_referenced_by_snapshots(list(remaining_ids))
        batches_in_deleted = db.get_batches_referenced_by_snapshots(list(to_delete_ids))
        referenced_conflicts = batches_in_deleted & still_referenced

        if dry_run:
            typer.secho("=== DRY RUN - No changes will be made ===", fg=typer.colors.CYAN, bold=True)
            typer.secho(f"\nSnapshots to delete ({len(snapshots_to_delete)}):", fg=typer.colors.YELLOW, bold=True)
            if snapshots_to_delete:
                typer.secho("-" * 90)
                typer.secho(
                    f"{'ID':>4}  {'Created At':<20}  {'Batch ID':<28}  {'Records':>8}",
                    fg=typer.colors.CYAN, bold=True
                )
                typer.secho("-" * 90)
                for snap in snapshots_to_delete:
                    data = json.loads(snap.inventory_data)
                    record_count = len(data.get('records', []))
                    timestamp = snap.created_at.strftime('%Y-%m-%d %H:%M:%S')
                    batch_display = snap.batch_id[:26] + ('..' if len(snap.batch_id) > 26 else '')
                    typer.secho(
                        f"{snap.id:>4}  {timestamp:<20}  {batch_display:<28}  {record_count:>8}"
                    )
            else:
                typer.secho("  (none)")

            if prune_orphans:
                all_orphans = list(set(batches_to_delete + orphan_batches))
                typer.secho(f"\nBatches to delete ({len(all_orphans)}):", fg=typer.colors.YELLOW, bold=True)
                if all_orphans:
                    for b in sorted(all_orphans):
                        status = "  (orphan)" if b in orphan_batches else ""
                        typer.secho(f"  - {b}{status}")
                else:
                    typer.secho("  (none)")

            if referenced_conflicts:
                typer.secho(
                    f"\nNote: {len(referenced_conflicts)} batches are still referenced "
                    f"by retained snapshots and will NOT be deleted:",
                    fg=typer.colors.MAGENTA
                )
                for b in sorted(referenced_conflicts):
                    typer.secho(f"  - {b}")

            typer.secho(
                f"\nSummary: Would delete {len(snapshots_to_delete)} snapshots"
                + (f" and {len(set(batches_to_delete + orphan_batches))} batches" if prune_orphans else ""),
                fg=typer.colors.CYAN, bold=True
            )
            typer.secho(
                "Remove --dry-run to execute the prune operation.",
                fg=typer.colors.YELLOW
            )
            db.close()
            raise typer.Exit(code=0)

        if referenced_conflicts:
            typer.secho(
                f"Warning: {len(referenced_conflicts)} batches are still referenced "
                f"by retained snapshots and will NOT be deleted:",
                fg=typer.colors.MAGENTA
            )
            for b in sorted(referenced_conflicts):
                typer.secho(f"  - {b}")
            typer.secho(
                "Only batches that are no longer referenced by any remaining snapshot will be deleted.\n",
                fg=typer.colors.MAGENTA
            )

        try:
            result = db.execute_prune(snapshots_to_delete, batches_to_delete, orphan_batches)
        except sqlite3.OperationalError as e:
            if "read-only" in str(e).lower() or "permission" in str(e).lower():
                typer.secho(
                    f"Error: Database is read-only, cannot write changes: {e}",
                    fg=typer.colors.RED
                )
            else:
                typer.secho(
                    f"Error during prune (no changes made): {e}",
                    fg=typer.colors.RED
                )
            db.close()
            raise typer.Exit(code=1)
        except Exception as e:
            typer.secho(
                f"Error during prune - all changes rolled back: {e}",
                fg=typer.colors.RED
            )
            db.close()
            raise typer.Exit(code=1)

        typer.secho("=== PRUNE COMPLETED ===", fg=typer.colors.GREEN, bold=True)
        typer.secho(
            f"Successfully deleted {len(result.snapshots_deleted)} snapshots"
            + (f" and {len(result.batches_deleted)} batches" if prune_orphans else ""),
            fg=typer.colors.GREEN
        )
        if result.snapshots_deleted:
            typer.secho(f"Deleted snapshot IDs: {sorted(result.snapshots_deleted)}", fg=typer.colors.BLUE)
        if result.batches_deleted:
            typer.secho(f"Deleted batches: {sorted(result.batches_deleted)}", fg=typer.colors.BLUE)
        typer.secho(
            f"Operation recorded in history. Use 'history' to view.",
            fg=typer.colors.CYAN
        )

        db.close()

    except typer.Exit:
        raise
    except Exception as e:
        typer.secho(f"Unexpected error: {e}", fg=typer.colors.RED)
        if 'db' in locals():
            try:
                db.close()
            except Exception:
                pass
        raise typer.Exit(code=1)


@app.command("audit-log", help="Query and export audit log with time range / operation type filters (CSV or JSON)")
def audit_log(
    output: str = typer.Argument(
        ...,
        help="Output file path. Must end with .csv or .json to specify export format."
    ),
    from_time: Optional[str] = typer.Option(
        None, "--from",
        help="Start time filter (inclusive), ISO format e.g. '2025-01-01' or '2025-01-01T10:00:00'"
    ),
    to_time: Optional[str] = typer.Option(
        None, "--to",
        help="End time filter (inclusive), ISO format e.g. '2025-12-31' or '2025-12-31T23:59:59'"
    ),
    operation_type: Optional[str] = typer.Option(
        None, "--type", "-t",
        help="Operation type filter, comma-separated. Valid: init,import,merge,export,rollback,config,prune"
    ),
    db_path: str = typer.Option(
        DEFAULT_DB_PATH, "--database",
        help="Path to SQLite database file"
    )
):
    if not output.endswith('.csv') and not output.endswith('.json'):
        typer.secho(
            f"Error: Output file must end with .csv or .json, got '{output}'",
            fg=typer.colors.RED
        )
        typer.secho(
            "Example: inventory audit-log audit.csv --type import,merge",
            fg=typer.colors.CYAN
        )
        raise typer.Exit(code=1)

    if from_time:
        try:
            if 'T' not in from_time:
                from_time_parsed = datetime.fromisoformat(from_time + "T00:00:00")
            else:
                from_time_parsed = datetime.fromisoformat(from_time)
        except ValueError:
            typer.secho(
                f"Error: Invalid --from time format: '{from_time}'. Use ISO format like '2025-01-01' or '2025-01-01T10:00:00'.",
                fg=typer.colors.RED
            )
            raise typer.Exit(code=1)
    else:
        from_time_parsed = None

    if to_time:
        try:
            if 'T' not in to_time:
                to_time_parsed = datetime.fromisoformat(to_time + "T23:59:59")
            else:
                to_time_parsed = datetime.fromisoformat(to_time)
        except ValueError:
            typer.secho(
                f"Error: Invalid --to time format: '{to_time}'. Use ISO format like '2025-12-31' or '2025-12-31T23:59:59'.",
                fg=typer.colors.RED
            )
            raise typer.Exit(code=1)
    else:
        to_time_parsed = None

    if from_time_parsed and to_time_parsed and from_time_parsed > to_time_parsed:
        typer.secho(
            f"Error: --from ({from_time}) is after --to ({to_time}). Time range is invalid.",
            fg=typer.colors.RED
        )
        raise typer.Exit(code=1)

    op_types: Optional[List[str]] = None
    if operation_type:
        op_types = [t.strip().lower() for t in operation_type.split(",")]
        invalid = [t for t in op_types if t not in VALID_OPERATION_TYPES]
        if invalid:
            typer.secho(
                f"Error: Invalid operation type(s): {', '.join(invalid)}",
                fg=typer.colors.RED
            )
            typer.secho(
                f"Valid types: {', '.join(VALID_OPERATION_TYPES)}",
                fg=typer.colors.YELLOW
            )
            raise typer.Exit(code=1)

    if not os.path.exists(db_path):
        typer.secho(
            f"Error: Database file not found: {db_path}",
            fg=typer.colors.RED
        )
        typer.secho(
            "Run 'inventory init' first to create the database.",
            fg=typer.colors.CYAN
        )
        raise typer.Exit(code=1)

    db = get_db(db_path)

    from_iso = from_time_parsed.isoformat() if from_time_parsed else None
    to_iso = to_time_parsed.isoformat() if to_time_parsed else None

    entries = db.get_history_filtered(
        from_time=from_iso,
        to_time=to_iso,
        operation_types=op_types,
    )

    if not entries:
        filter_desc = []
        if from_time:
            filter_desc.append(f"from {from_time}")
        if to_time:
            filter_desc.append(f"to {to_time}")
        if op_types:
            filter_desc.append(f"type={','.join(op_types)}")
        filter_str = " ".join(filter_desc) if filter_desc else "(no filters)"
        typer.secho(
            f"No audit log entries found for filters: {filter_str}",
            fg=typer.colors.YELLOW
        )
        db.close()
        raise typer.Exit(code=0)

    parent_dir = os.path.dirname(os.path.abspath(output))
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)

    rows = []
    for entry in entries:
        rows.append({
            "timestamp": entry.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            "operation": entry.operation,
            "batch_id": entry.batch_id or "",
            "store_id": entry.store_id or "",
            "file_path": entry.file_path or "",
            "details": entry.details or "",
        })

    try:
        if output.endswith('.csv'):
            with open(output, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=["timestamp", "operation", "batch_id", "store_id", "file_path", "details"])
                writer.writeheader()
                writer.writerows(rows)
        else:
            with open(output, 'w', encoding='utf-8') as f:
                json.dump(rows, f, indent=2, ensure_ascii=False)
    except Exception as e:
        typer.secho(f"Error writing audit log: {str(e)}", fg=typer.colors.RED)
        db.close()
        raise typer.Exit(code=1)

    typer.secho(
        f"Exported {len(entries)} audit log entries to {output}",
        fg=typer.colors.GREEN
    )
    if from_time or to_time:
        time_desc = []
        if from_time:
            time_desc.append(f"from {from_time}")
        if to_time:
            time_desc.append(f"to {to_time}")
        typer.secho(f"  Time range: {' '.join(time_desc)}", fg=typer.colors.BLUE)
    if op_types:
        typer.secho(f"  Operation types: {', '.join(op_types)}", fg=typer.colors.BLUE)

    db.close()


if __name__ == "__main__":
    app()