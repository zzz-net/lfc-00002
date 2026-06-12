import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any, Set, Tuple
from .models import InventoryRecord, HistoryEntry, Snapshot, PruneResult


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None

    def connect(self):
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        if self.conn:
            self.conn.close()

    def init_schema(self):
        cursor = self.conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                store_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                source_file TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                inventory_data TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                store_id TEXT,
                file_path TEXT,
                timestamp TEXT NOT NULL,
                details TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        
        self.conn.commit()

    def insert_inventory_records(self, records: List[InventoryRecord]):
        cursor = self.conn.cursor()
        for record in records:
            cursor.execute('''
                INSERT INTO inventory (sku, quantity, store_id, batch_id, source_file, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (record.sku, record.quantity, record.store_id, record.batch_id, 
                  record.source_file, record.created_at.isoformat()))
        self.conn.commit()

    def get_records_by_batch(self, batch_id: str) -> List[InventoryRecord]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM inventory WHERE batch_id = ?', (batch_id,))
        rows = cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_all_records(self) -> List[InventoryRecord]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM inventory ORDER BY store_id, sku')
        rows = cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    def delete_records_by_batch(self, batch_id: str):
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM inventory WHERE batch_id = ?', (batch_id,))
        self.conn.commit()

    def insert_snapshot(self, batch_id: str, inventory_data: Dict):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO snapshots (batch_id, inventory_data, created_at)
            VALUES (?, ?, ?)
        ''', (batch_id, json.dumps(inventory_data), datetime.now().isoformat()))
        self.conn.commit()

    def get_latest_snapshot(self) -> Optional[Snapshot]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM snapshots ORDER BY id DESC LIMIT 1')
        row = cursor.fetchone()
        if row:
            return Snapshot(
                id=row['id'],
                batch_id=row['batch_id'],
                inventory_data=row['inventory_data'],
                created_at=datetime.fromisoformat(row['created_at'])
            )
        return None

    def get_snapshot_by_id(self, snapshot_id: int) -> Optional[Snapshot]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM snapshots WHERE id = ?', (snapshot_id,))
        row = cursor.fetchone()
        if row:
            return Snapshot(
                id=row['id'],
                batch_id=row['batch_id'],
                inventory_data=row['inventory_data'],
                created_at=datetime.fromisoformat(row['created_at'])
            )
        return None

    def get_all_snapshots(self) -> List[Snapshot]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM snapshots ORDER BY id DESC')
        rows = cursor.fetchall()
        return [Snapshot(
            id=row['id'],
            batch_id=row['batch_id'],
            inventory_data=row['inventory_data'],
            created_at=datetime.fromisoformat(row['created_at'])
        ) for row in rows]

    def insert_history(self, operation: str, batch_id: str, store_id: Optional[str] = None, 
                       file_path: Optional[str] = None, details: Optional[str] = None,
                       commit: bool = True):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO history (operation, batch_id, store_id, file_path, timestamp, details)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (operation, batch_id, store_id, file_path, datetime.now().isoformat(), details))
        if commit:
            self.conn.commit()

    def get_history(self, limit: int = 100) -> List[HistoryEntry]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM history ORDER BY id DESC LIMIT ?', (limit,))
        rows = cursor.fetchall()
        return [HistoryEntry(
            id=row['id'],
            operation=row['operation'],
            batch_id=row['batch_id'],
            store_id=row['store_id'],
            file_path=row['file_path'],
            timestamp=datetime.fromisoformat(row['timestamp']),
            details=row['details']
        ) for row in rows]

    def get_history_by_batch(self, batch_id: str) -> List[HistoryEntry]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM history WHERE batch_id = ? ORDER BY id DESC', (batch_id,))
        rows = cursor.fetchall()
        return [HistoryEntry(
            id=row['id'],
            operation=row['operation'],
            batch_id=row['batch_id'],
            store_id=row['store_id'],
            file_path=row['file_path'],
            timestamp=datetime.fromisoformat(row['timestamp']),
            details=row['details']
        ) for row in rows]

    def set_config(self, key: str, value: str):
        cursor = self.conn.cursor()
        cursor.execute('REPLACE INTO config (key, value) VALUES (?, ?)', (key, value))
        self.conn.commit()

    def get_config(self, key: str, default: Optional[str] = None) -> Optional[str]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT value FROM config WHERE key = ?', (key,))
        row = cursor.fetchone()
        return row['value'] if row else default

    def get_all_config(self) -> Dict[str, str]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT key, value FROM config')
        rows = cursor.fetchall()
        return {row['key']: row['value'] for row in rows}

    def _row_to_record(self, row: sqlite3.Row) -> InventoryRecord:
        return InventoryRecord(
            sku=row['sku'],
            quantity=row['quantity'],
            store_id=row['store_id'],
            batch_id=row['batch_id'],
            source_file=row['source_file'],
            created_at=datetime.fromisoformat(row['created_at'])
        )

    def check_duplicate_sku_in_batch(self, batch_id: str) -> List[str]:
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT sku, COUNT(*) as cnt FROM inventory 
            WHERE batch_id = ? 
            GROUP BY sku 
            HAVING cnt > 1
        ''', (batch_id,))
        rows = cursor.fetchall()
        return [row['sku'] for row in rows]

    def get_history_filtered(
        self,
        from_time: Optional[str] = None,
        to_time: Optional[str] = None,
        operation_types: Optional[List[str]] = None,
    ) -> List[HistoryEntry]:
        conditions = []
        params: list = []

        if from_time:
            conditions.append("timestamp >= ?")
            params.append(from_time)
        if to_time:
            conditions.append("timestamp <= ?")
            params.append(to_time)
        if operation_types:
            placeholders = ",".join("?" for _ in operation_types)
            conditions.append(f"operation IN ({placeholders})")
            params.extend(operation_types)

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        cursor = self.conn.cursor()
        cursor.execute(
            f"SELECT * FROM history {where} ORDER BY id DESC", params
        )
        rows = cursor.fetchall()
        return [
            HistoryEntry(
                id=row["id"],
                operation=row["operation"],
                batch_id=row["batch_id"],
                store_id=row["store_id"],
                file_path=row["file_path"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                details=row["details"],
            )
            for row in rows
        ]

    def get_unique_batches(self) -> List[str]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT DISTINCT batch_id FROM inventory ORDER BY batch_id')
        rows = cursor.fetchall()
        return [row['batch_id'] for row in rows]

    def delete_all_inventory(self):
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM inventory')
        self.conn.commit()

    def get_snapshots_before(self, before_time: datetime) -> List[Snapshot]:
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT * FROM snapshots WHERE created_at <= ? ORDER BY id DESC',
            (before_time.isoformat(),)
        )
        rows = cursor.fetchall()
        return [Snapshot(
            id=row['id'],
            batch_id=row['batch_id'],
            inventory_data=row['inventory_data'],
            created_at=datetime.fromisoformat(row['created_at'])
        ) for row in rows]

    def get_snapshots_keep_recent(self, keep_count: int) -> List[Snapshot]:
        all_snapshots = self.get_all_snapshots()
        if keep_count >= len(all_snapshots):
            return []
        return all_snapshots[keep_count:]

    def get_all_referenced_batches(self) -> Set[str]:
        snapshots = self.get_all_snapshots()
        referenced: Set[str] = set()
        for snap in snapshots:
            data = json.loads(snap.inventory_data)
            source_batches = data.get('source_batches', [])
            referenced.update(source_batches)
        return referenced

    def get_orphan_batches(self) -> List[str]:
        all_batches = set(self.get_unique_batches())
        referenced = self.get_all_referenced_batches()
        return sorted(all_batches - referenced)

    def get_batches_referenced_by_snapshots(self, snapshot_ids: List[int]) -> Set[str]:
        if not snapshot_ids:
            return set()
        placeholders = ",".join("?" for _ in snapshot_ids)
        cursor = self.conn.cursor()
        cursor.execute(
            f'SELECT id, inventory_data FROM snapshots WHERE id IN ({placeholders})',
            snapshot_ids
        )
        rows = cursor.fetchall()
        referenced: Set[str] = set()
        for row in rows:
            data = json.loads(row['inventory_data'])
            source_batches = data.get('source_batches', [])
            referenced.update(source_batches)
        return referenced

    def delete_snapshot(self, snapshot_id: int, commit: bool = True):
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM snapshots WHERE id = ?', (snapshot_id,))
        if commit:
            self.conn.commit()

    def delete_batch(self, batch_id: str, commit: bool = True):
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM inventory WHERE batch_id = ?', (batch_id,))
        if commit:
            self.conn.commit()

    def plan_prune(
        self,
        before_time: Optional[datetime] = None,
        keep_count: Optional[int] = None,
        prune_orphans: bool = False
    ) -> Tuple[List[Snapshot], List[str], List[str]]:
        all_snapshots = self.get_all_snapshots()
        if not all_snapshots:
            return [], [], []

        to_delete_by_time: Set[int] = set()
        to_delete_by_keep: Set[int] = set()

        if before_time is not None:
            old_snaps = self.get_snapshots_before(before_time)
            to_delete_by_time = {s.id for s in old_snaps}

        if keep_count is not None:
            if keep_count < 0:
                raise ValueError("keep_count must be non-negative")
            old_snaps = self.get_snapshots_keep_recent(keep_count)
            to_delete_by_keep = {s.id for s in old_snaps}

        if before_time is not None and keep_count is not None:
            to_delete_ids = to_delete_by_time | to_delete_by_keep
        elif before_time is not None:
            to_delete_ids = to_delete_by_time
        elif keep_count is not None:
            to_delete_ids = to_delete_by_keep
        else:
            return [], [], []

        snapshots_to_delete = [s for s in all_snapshots if s.id in to_delete_ids]
        snapshot_ids_to_delete = [s.id for s in snapshots_to_delete]

        remaining_snapshot_ids = [s.id for s in all_snapshots if s.id not in to_delete_ids]
        still_referenced = self.get_batches_referenced_by_snapshots(remaining_snapshot_ids)
        batches_in_deleted = self.get_batches_referenced_by_snapshots(snapshot_ids_to_delete)
        batches_to_delete = sorted(batches_in_deleted - still_referenced) if prune_orphans else []

        orphan_batches = self.get_orphan_batches() if prune_orphans else []

        return snapshots_to_delete, batches_to_delete, orphan_batches

    def execute_prune(
        self,
        snapshots_to_delete: List[Snapshot],
        batches_to_delete: List[str],
        orphan_batches: List[str]
    ) -> PruneResult:
        snapshots_deleted: List[int] = []
        batches_deleted: List[str] = []
        all_batches_to_delete = list(set(batches_to_delete + orphan_batches))

        self.conn.execute('BEGIN IMMEDIATE')
        try:
            for snap in snapshots_to_delete:
                self.delete_snapshot(snap.id, commit=False)
                snapshots_deleted.append(snap.id)

            for batch_id in all_batches_to_delete:
                self.delete_batch(batch_id, commit=False)
                batches_deleted.append(batch_id)

            prune_details = (
                f"Pruned {len(snapshots_deleted)} snapshots, "
                f"{len(batches_deleted)} batches: "
                f"snapshots={snapshots_deleted}, batches={batches_deleted}"
            )
            self.insert_history("prune", "PRUNE", details=prune_details, commit=False)

            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return PruneResult(
            snapshots_to_delete=snapshots_to_delete,
            batches_to_delete=all_batches_to_delete,
            orphan_batches=orphan_batches,
            snapshots_deleted=snapshots_deleted,
            batches_deleted=batches_deleted
        )