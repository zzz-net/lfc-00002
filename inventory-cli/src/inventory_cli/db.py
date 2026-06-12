import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from .models import InventoryRecord, HistoryEntry, Snapshot


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None

    def connect(self):
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
                       file_path: Optional[str] = None, details: Optional[str] = None):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO history (operation, batch_id, store_id, file_path, timestamp, details)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (operation, batch_id, store_id, file_path, datetime.now().isoformat(), details))
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

    def get_unique_batches(self) -> List[str]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT DISTINCT batch_id FROM inventory ORDER BY batch_id')
        rows = cursor.fetchall()
        return [row['batch_id'] for row in rows]

    def delete_all_inventory(self):
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM inventory')
        self.conn.commit()