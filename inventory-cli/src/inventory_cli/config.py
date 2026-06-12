from typing import Dict, Optional
from .db import Database


class ConfigManager:
    CONFLICT_STRATEGIES = ['first', 'last', 'sum', 'average', 'require_manual']
    
    def __init__(self, db: Database):
        self.db = db

    def initialize_defaults(self):
        if not self.db.get_config('conflict_strategy'):
            self.db.set_config('conflict_strategy', 'require_manual')
        if not self.db.get_config('validate_negative'):
            self.db.set_config('validate_negative', 'true')
        if not self.db.get_config('validate_required_columns'):
            self.db.set_config('validate_required_columns', 'true')
        if not self.db.get_config('validate_duplicate_sku'):
            self.db.set_config('validate_duplicate_sku', 'true')

    def get_conflict_strategy(self) -> str:
        return self.db.get_config('conflict_strategy', 'require_manual')

    def set_conflict_strategy(self, strategy: str):
        if strategy not in self.CONFLICT_STRATEGIES:
            raise ValueError(f"Invalid conflict strategy. Must be one of: {', '.join(self.CONFLICT_STRATEGIES)}")
        self.db.set_config('conflict_strategy', strategy)

    def validate_negative(self) -> bool:
        return self.db.get_config('validate_negative', 'true').lower() == 'true'

    def validate_required_columns(self) -> bool:
        return self.db.get_config('validate_required_columns', 'true').lower() == 'true'

    def validate_duplicate_sku(self) -> bool:
        return self.db.get_config('validate_duplicate_sku', 'true').lower() == 'true'

    def set_validate_negative(self, value: bool):
        self.db.set_config('validate_negative', 'true' if value else 'false')

    def set_validate_required_columns(self, value: bool):
        self.db.set_config('validate_required_columns', 'true' if value else 'false')

    def set_validate_duplicate_sku(self, value: bool):
        self.db.set_config('validate_duplicate_sku', 'true' if value else 'false')

    def get_all_config(self) -> Dict[str, str]:
        return self.db.get_all_config()