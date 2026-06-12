import csv
import json
from datetime import datetime
from typing import List, Dict, Any
from .models import InventoryRecord
from .config import ConfigManager


class ImportError(Exception):
    pass


class InventoryImporter:
    REQUIRED_COLUMNS = ['sku', 'quantity']
    
    def __init__(self, config: ConfigManager):
        self.config = config

    def import_file(self, file_path: str, store_id: str, batch_id: str) -> List[InventoryRecord]:
        if file_path.endswith('.csv'):
            return self._import_csv(file_path, store_id, batch_id)
        elif file_path.endswith('.json'):
            return self._import_json(file_path, store_id, batch_id)
        else:
            raise ImportError(f"Unsupported file format: {file_path}. Only CSV and JSON are supported.")

    def _import_csv(self, file_path: str, store_id: str, batch_id: str) -> List[InventoryRecord]:
        records = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames
                
                if self.config.validate_required_columns():
                    for col in self.REQUIRED_COLUMNS:
                        if col not in headers:
                            raise ImportError(f"Missing required column '{col}' in CSV file")
                
                for row_num, row in enumerate(reader, start=2):
                    sku = row.get('sku', '').strip()
                    quantity_str = row.get('quantity', '')
                    
                    if not sku:
                        raise ImportError(f"Empty SKU at row {row_num}")
                    
                    try:
                        quantity = int(quantity_str)
                    except ValueError:
                        raise ImportError(f"Invalid quantity '{quantity_str}' at row {row_num}")
                    
                    if self.config.validate_negative() and quantity < 0:
                        raise ImportError(f"Negative quantity '{quantity}' at row {row_num}")
                    
                    records.append(InventoryRecord(
                        sku=sku,
                        quantity=quantity,
                        store_id=store_id,
                        batch_id=batch_id,
                        source_file=file_path,
                        created_at=datetime.now()
                    ))
        except FileNotFoundError:
            raise ImportError(f"File not found: {file_path}")
        except Exception as e:
            raise ImportError(f"Error reading CSV file: {str(e)}")
        
        return records

    def _import_json(self, file_path: str, store_id: str, batch_id: str) -> List[InventoryRecord]:
        records = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not isinstance(data, list):
                raise ImportError("JSON file must contain an array of inventory records")
            
            for idx, item in enumerate(data, start=1):
                if not isinstance(item, dict):
                    raise ImportError(f"Invalid record format at index {idx}")
                
                if self.config.validate_required_columns():
                    if 'sku' not in item:
                        raise ImportError(f"Missing 'sku' field at index {idx}")
                    if 'quantity' not in item:
                        raise ImportError(f"Missing 'quantity' field at index {idx}")
                
                sku = str(item['sku']).strip()
                quantity = item['quantity']
                
                if not sku:
                    raise ImportError(f"Empty SKU at index {idx}")
                
                if not isinstance(quantity, int):
                    try:
                        quantity = int(quantity)
                    except ValueError:
                        raise ImportError(f"Invalid quantity '{quantity}' at index {idx}")
                
                if self.config.validate_negative() and quantity < 0:
                    raise ImportError(f"Negative quantity '{quantity}' at index {idx}")
                
                records.append(InventoryRecord(
                    sku=sku,
                    quantity=quantity,
                    store_id=store_id,
                    batch_id=batch_id,
                    source_file=file_path,
                    created_at=datetime.now()
                ))
        except FileNotFoundError:
            raise ImportError(f"File not found: {file_path}")
        except json.JSONDecodeError as e:
            raise ImportError(f"Invalid JSON format: {str(e)}")
        except Exception as e:
            raise ImportError(f"Error reading JSON file: {str(e)}")
        
        return records

    def validate_records(self, records: List[InventoryRecord], batch_id: str) -> List[str]:
        errors = []
        sku_quantities: Dict[str, List[int]] = {}
        
        for record in records:
            if record.quantity < 0 and self.config.validate_negative():
                errors.append(f"Negative quantity for SKU '{record.sku}': {record.quantity}")
            
            if record.sku not in sku_quantities:
                sku_quantities[record.sku] = []
            sku_quantities[record.sku].append(record.quantity)
        
        if self.config.validate_duplicate_sku():
            for sku, quantities in sku_quantities.items():
                if len(quantities) > 1:
                    unique_qtys = set(quantities)
                    if len(unique_qtys) > 1:
                        errors.append(
                            f"Duplicate SKU '{sku}' with inconsistent quantities: {quantities}. "
                            f"Same SKU in a batch must have identical quantities."
                        )
                    else:
                        errors.append(
                            f"Duplicate SKU '{sku}' found {len(quantities)} times in batch "
                            f"(all with quantity {quantities[0]})"
                        )
        
        return errors