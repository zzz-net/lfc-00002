from datetime import datetime
from typing import Optional, List, Dict
from dataclasses import dataclass


@dataclass
class InventoryRecord:
    sku: str
    quantity: int
    store_id: str
    batch_id: str
    source_file: str
    created_at: Optional[datetime] = None


@dataclass
class MergeResult:
    success: bool
    message: str
    conflicts: List[Dict] = None
    merged_records: List[InventoryRecord] = None


@dataclass
class HistoryEntry:
    id: int
    operation: str
    batch_id: str
    store_id: Optional[str]
    file_path: Optional[str]
    timestamp: datetime
    details: Optional[str]


@dataclass
class Snapshot:
    id: int
    batch_id: str
    inventory_data: str
    created_at: datetime


@dataclass
class MergeConflict:
    sku: str
    store_id_1: str
    quantity_1: int
    store_id_2: str
    quantity_2: int
    batch_id_1: str
    batch_id_2: str


@dataclass
class PruneResult:
    snapshots_to_delete: List[Snapshot]
    batches_to_delete: List[str]
    orphan_batches: List[str]
    snapshots_deleted: List[int]
    batches_deleted: List[str]