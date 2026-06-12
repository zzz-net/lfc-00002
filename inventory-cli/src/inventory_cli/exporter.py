import csv
import json
from datetime import datetime
from typing import List, Dict, Optional
from .models import InventoryRecord, Snapshot


class ExportError(Exception):
    pass


class InventoryExporter:
    def export_csv(self, records: List[InventoryRecord], file_path: str,
                   source_batches: Optional[List[str]] = None,
                   strategy: Optional[str] = None):
        if not records:
            raise ExportError("No records to export")
        
        try:
            with open(file_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['sku', 'quantity', 'store_id', 'batch_id', 'source_file'])
                
                for record in sorted(records, key=lambda x: (x.store_id, x.sku)):
                    writer.writerow([
                        record.sku,
                        record.quantity,
                        record.store_id,
                        record.batch_id,
                        record.source_file
                    ])
                
                if source_batches or strategy:
                    writer.writerow([])
                    writer.writerow(['# Export Metadata'])
                    if source_batches:
                        writer.writerow(['# Source Batches:', ', '.join(source_batches)])
                    if strategy:
                        writer.writerow(['# Merge Strategy:', strategy])
        except Exception as e:
            raise ExportError(f"Error writing CSV file: {str(e)}")

    def export_json(self, records: List[InventoryRecord], file_path: str,
                    source_batches: Optional[List[str]] = None,
                    strategy: Optional[str] = None):
        if not records:
            raise ExportError("No records to export")
        
        try:
            data = {
                'metadata': {
                    'exported_at': datetime.now().isoformat(),
                    'record_count': len(records),
                    'unique_skus': len(set(r.sku for r in records)),
                    'unique_stores': len(set(r.store_id for r in records)),
                    'unique_batches': len(set(r.batch_id for r in records))
                },
                'inventory': []
            }
            
            if source_batches:
                data['metadata']['source_batches'] = source_batches
            if strategy:
                data['metadata']['merge_strategy'] = strategy
            
            for record in sorted(records, key=lambda x: (x.store_id, x.sku)):
                data['inventory'].append({
                    'sku': record.sku,
                    'quantity': record.quantity,
                    'store_id': record.store_id,
                    'batch_id': record.batch_id,
                    'source_file': record.source_file,
                    'created_at': record.created_at.isoformat() if record.created_at else None
                })
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            raise ExportError(f"Error writing JSON file: {str(e)}")

    def export_report(self, records: List[InventoryRecord], file_path: str, 
                     include_diff: bool = True,
                     source_batches: Optional[List[str]] = None,
                     strategy: Optional[str] = None,
                     diff_report: Optional[Dict] = None):
        report = self._generate_report(records, include_diff, source_batches, strategy, diff_report)
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
        except Exception as e:
            raise ExportError(f"Error writing report file: {str(e)}")

    def _generate_report(self, records: List[InventoryRecord], include_diff: bool,
                        source_batches: Optional[List[str]] = None,
                        strategy: Optional[str] = None,
                        diff_report: Optional[Dict] = None) -> Dict:
        batches = list(set(r.batch_id for r in records))
        if source_batches is None:
            source_batches = batches
        
        report = {
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'record_count': len(records),
                'unique_skus': len(set(r.sku for r in records)),
                'unique_stores': len(set(r.store_id for r in records)),
                'unique_batches': len(batches),
                'source_batches': source_batches,
                'merge_strategy': strategy
            },
            'inventory': [],
            'by_store_summary': {},
            'by_batch_summary': {}
        }
        
        for record in sorted(records, key=lambda x: (x.store_id, x.sku)):
            report['inventory'].append({
                'sku': record.sku,
                'quantity': record.quantity,
                'store_id': record.store_id,
                'batch_id': record.batch_id,
                'source_file': record.source_file
            })
            
            if record.store_id not in report['by_store_summary']:
                report['by_store_summary'][record.store_id] = {
                    'sku_count': 0,
                    'total_quantity': 0,
                    'batches': set()
                }
            report['by_store_summary'][record.store_id]['sku_count'] += 1
            report['by_store_summary'][record.store_id]['total_quantity'] += record.quantity
            report['by_store_summary'][record.store_id]['batches'].add(record.batch_id)
            
            if record.batch_id not in report['by_batch_summary']:
                report['by_batch_summary'][record.batch_id] = {
                    'sku_count': 0,
                    'total_quantity': 0,
                    'stores': set()
                }
            report['by_batch_summary'][record.batch_id]['sku_count'] += 1
            report['by_batch_summary'][record.batch_id]['total_quantity'] += record.quantity
            report['by_batch_summary'][record.batch_id]['stores'].add(record.store_id)
        
        for store_id in report['by_store_summary']:
            report['by_store_summary'][store_id]['batches'] = list(
                report['by_store_summary'][store_id]['batches']
            )
        
        for batch_id in report['by_batch_summary']:
            report['by_batch_summary'][batch_id]['stores'] = list(
                report['by_batch_summary'][batch_id]['stores']
            )
        
        if include_diff and diff_report:
            report['diff_report'] = diff_report
        elif include_diff:
            sku_store_map: Dict[str, List[Dict]] = {}
            conflicts = []
            
            for record in records:
                if record.sku not in sku_store_map:
                    sku_store_map[record.sku] = []
                sku_store_map[record.sku].append({
                    'store_id': record.store_id,
                    'quantity': record.quantity,
                    'batch_id': record.batch_id,
                    'source_file': record.source_file
                })
            
            for sku, entries in sku_store_map.items():
                if len(entries) > 1:
                    qty_values = [e['quantity'] for e in entries]
                    if len(set(qty_values)) > 1:
                        conflicts.append({
                            'sku': sku,
                            'entries': entries,
                            'quantities': qty_values
                        })
            
            report['diff_report'] = {
                'summary': {
                    'total_conflicts': len(conflicts),
                    'conflict_skus': [c['sku'] for c in conflicts]
                },
                'conflicts': conflicts,
                'consolidated_by_sku': sku_store_map
            }
        
        return report