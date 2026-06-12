from datetime import datetime
from typing import List, Dict, Optional, Tuple
from .models import InventoryRecord, MergeResult, MergeConflict
from .config import ConfigManager


class MergeError(Exception):
    pass


class InventoryMerger:
    def __init__(self, config: ConfigManager):
        self.config = config

    def merge(self, batches: List[str], records: List[InventoryRecord]) -> MergeResult:
        strategy = self.config.get_conflict_strategy()
        same_batch_conflicts, cross_store_conflicts = self._detect_conflicts(records, batches)
        all_conflicts = same_batch_conflicts + cross_store_conflicts
        
        if same_batch_conflicts:
            return MergeResult(
                success=False,
                message=f"Found {len(same_batch_conflicts)} same-batch SKU quantity conflicts. "
                        f"These must be resolved before merging. Fix the source files and re-import.",
                conflicts=[c.__dict__ for c in same_batch_conflicts]
            )
        
        if cross_store_conflicts and strategy == 'require_manual':
            return MergeResult(
                success=False,
                message=f"Manual resolution required. Found {len(cross_store_conflicts)} cross-store SKU conflicts "
                        f"and conflict strategy is 'require_manual'. "
                        f"Change strategy with 'config conflict_strategy <strategy>' or resolve manually.",
                conflicts=[c.__dict__ for c in cross_store_conflicts]
            )
        
        merged = self._apply_strategy(records, cross_store_conflicts, strategy)
        return MergeResult(
            success=True,
            message=f"Merged {len(merged)} records successfully",
            merged_records=merged,
            conflicts=[c.__dict__ for c in cross_store_conflicts] if cross_store_conflicts else None
        )

    def _detect_conflicts(self, records: List[InventoryRecord], batches: List[str]) -> Tuple[List[MergeConflict], List[MergeConflict]]:
        same_batch_conflicts = []
        cross_store_conflicts = []
        
        sku_batch_store_map: Dict[str, Dict[str, Dict[str, int]]] = {}
        for record in records:
            key = record.sku
            if key not in sku_batch_store_map:
                sku_batch_store_map[key] = {}
            if record.batch_id not in sku_batch_store_map[key]:
                sku_batch_store_map[key][record.batch_id] = {}
            if record.store_id in sku_batch_store_map[key][record.batch_id]:
                existing_qty = sku_batch_store_map[key][record.batch_id][record.store_id]
                if existing_qty != record.quantity:
                    same_batch_conflicts.append(MergeConflict(
                        sku=record.sku,
                        store_id_1=record.store_id,
                        quantity_1=existing_qty,
                        store_id_2=record.store_id,
                        quantity_2=record.quantity,
                        batch_id_1=record.batch_id,
                        batch_id_2=record.batch_id
                    ))
            else:
                sku_batch_store_map[key][record.batch_id][record.store_id] = record.quantity
        
        sku_store_qty_map: Dict[str, Dict[str, List[Tuple[int, str]]]] = {}
        for record in records:
            key = record.sku
            if key not in sku_store_qty_map:
                sku_store_qty_map[key] = {}
            if record.store_id not in sku_store_qty_map[key]:
                sku_store_qty_map[key][record.store_id] = []
            sku_store_qty_map[key][record.store_id].append((record.quantity, record.batch_id))
        
        for sku, store_map in sku_store_qty_map.items():
            if len(store_map) > 1:
                store_list = []
                for store_id, qty_batch_list in store_map.items():
                    unique_qtys = set(q for q, _ in qty_batch_list)
                    if len(unique_qtys) == 1:
                        store_list.append((store_id, list(unique_qtys)[0], qty_batch_list[0][1]))
                    else:
                        continue
                
                if len(store_list) > 1:
                    qtys = [q for _, q, _ in store_list]
                    if len(set(qtys)) > 1:
                        for i in range(len(store_list)):
                            for j in range(i + 1, len(store_list)):
                                store_id_1, qty_1, batch_1 = store_list[i]
                                store_id_2, qty_2, batch_2 = store_list[j]
                                if qty_1 != qty_2:
                                    cross_store_conflicts.append(MergeConflict(
                                        sku=sku,
                                        store_id_1=store_id_1,
                                        quantity_1=qty_1,
                                        store_id_2=store_id_2,
                                        quantity_2=qty_2,
                                        batch_id_1=batch_1,
                                        batch_id_2=batch_2
                                    ))
        
        return same_batch_conflicts, cross_store_conflicts

    def _apply_strategy(self, records: List[InventoryRecord], conflicts: List[MergeConflict], 
                       strategy: str) -> List[InventoryRecord]:
        merged_records = []
        sku_store_map: Dict[str, Dict[str, InventoryRecord]] = {}
        
        for record in records:
            key = record.sku
            if key not in sku_store_map:
                sku_store_map[key] = {}
            
            if record.store_id in sku_store_map[key]:
                existing = sku_store_map[key][record.store_id]
                
                if strategy == 'first':
                    continue
                elif strategy == 'last':
                    sku_store_map[key][record.store_id] = record
                elif strategy == 'sum':
                    new_qty = existing.quantity + record.quantity
                    sku_store_map[key][record.store_id] = InventoryRecord(
                        sku=record.sku,
                        quantity=new_qty,
                        store_id=record.store_id,
                        batch_id=f"{existing.batch_id}+{record.batch_id}",
                        source_file=f"{existing.source_file};{record.source_file}",
                        created_at=record.created_at
                    )
                elif strategy == 'average':
                    new_qty = (existing.quantity + record.quantity) // 2
                    sku_store_map[key][record.store_id] = InventoryRecord(
                        sku=record.sku,
                        quantity=new_qty,
                        store_id=record.store_id,
                        batch_id=f"{existing.batch_id}+{record.batch_id}",
                        source_file=f"{existing.source_file};{record.source_file}",
                        created_at=record.created_at
                    )
            else:
                sku_store_map[key][record.store_id] = record
        
        conflict_skus = {c.sku for c in conflicts}
        
        for sku in conflict_skus:
            if sku in sku_store_map:
                store_entries = list(sku_store_map[sku].items())
                if len(store_entries) >= 2:
                    quantities = [rec.quantity for _, rec in store_entries]
                    if len(set(quantities)) > 1:
                        sku_store_map[sku] = self._resolve_cross_store_conflict(
                            sku, store_entries, strategy
                        )
        
        for store_map in sku_store_map.values():
            merged_records.extend(store_map.values())
        
        return merged_records

    def _resolve_cross_store_conflict(self, sku: str, 
                                       store_entries: List[Tuple[str, InventoryRecord]],
                                       strategy: str) -> Dict[str, InventoryRecord]:
        result: Dict[str, InventoryRecord] = {}
        
        if strategy in ('first', 'last'):
            if strategy == 'first':
                sorted_entries = sorted(store_entries, key=lambda x: x[1].created_at or datetime.min)
            else:
                sorted_entries = sorted(store_entries, key=lambda x: x[1].created_at or datetime.min, reverse=True)
            
            chosen_store, chosen_record = sorted_entries[0]
            result[chosen_store] = chosen_record
            
        elif strategy == 'sum':
            total_qty = sum(rec.quantity for _, rec in store_entries)
            all_batches = "+".join(sorted(set(rec.batch_id for _, rec in store_entries)))
            all_sources = ";".join(sorted(set(rec.source_file for _, rec in store_entries)))
            
            for store_id, rec in store_entries:
                result[store_id] = InventoryRecord(
                    sku=sku,
                    quantity=rec.quantity,
                    store_id=store_id,
                    batch_id=rec.batch_id,
                    source_file=rec.source_file,
                    created_at=rec.created_at
                )
            
        elif strategy == 'average':
            avg_qty = sum(rec.quantity for _, rec in store_entries) // len(store_entries)
            for store_id, rec in store_entries:
                result[store_id] = InventoryRecord(
                    sku=sku,
                    quantity=avg_qty,
                    store_id=store_id,
                    batch_id=rec.batch_id,
                    source_file=rec.source_file,
                    created_at=rec.created_at
                )
        
        else:
            for store_id, rec in store_entries:
                result[store_id] = rec
        
        return result

    def generate_diff_report(self, records: List[InventoryRecord]) -> Dict:
        batches = list(set(r.batch_id for r in records))
        same_batch_conflicts, cross_store_conflicts = self._detect_conflicts(records, batches)
        all_conflicts = same_batch_conflicts + cross_store_conflicts
        
        report = {
            'summary': {
                'total_records': len(records),
                'unique_skus': len(set(r.sku for r in records)),
                'unique_stores': len(set(r.store_id for r in records)),
                'unique_batches': len(batches),
                'same_batch_conflicts': len(same_batch_conflicts),
                'cross_store_conflicts': len(cross_store_conflicts),
                'total_conflicts': len(all_conflicts)
            },
            'by_sku': {},
            'by_store': {},
            'source_batches': batches,
            'conflicts': [c.__dict__ for c in all_conflicts],
            'conflict_count': len(all_conflicts),
            'same_batch_conflicts': [c.__dict__ for c in same_batch_conflicts],
            'cross_store_conflicts': [c.__dict__ for c in cross_store_conflicts]
        }
        
        for record in records:
            if record.sku not in report['by_sku']:
                report['by_sku'][record.sku] = []
            report['by_sku'][record.sku].append({
                'store_id': record.store_id,
                'quantity': record.quantity,
                'batch_id': record.batch_id,
                'source_file': record.source_file
            })
            
            if record.store_id not in report['by_store']:
                report['by_store'][record.store_id] = []
            report['by_store'][record.store_id].append({
                'sku': record.sku,
                'quantity': record.quantity,
                'batch_id': record.batch_id
            })
        
        return report