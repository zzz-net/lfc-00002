import json
import os
from typing import Dict, Optional, Any
from .db import Database


class ConfigError(Exception):
    """Raised when configuration is invalid or missing."""
    pass


class ConfigManager:
    CONFLICT_STRATEGIES = ['first', 'last', 'sum', 'average', 'require_manual']
    DEFAULT_CONFIG_FILE = 'inventory.config.json'
    
    def __init__(self, db: Database):
        self.db = db
        self._file_config: Optional[Dict[str, Any]] = None
        self._cli_overrides: Dict[str, Any] = {}

    @staticmethod
    def get_example_config() -> Dict[str, Any]:
        """Return a complete example configuration dictionary."""
        return {
            "$schema": "https://example.com/inventory-config-schema.json",
            "description": "Offline Inventory CLI Configuration File",
            "conflict_strategy": "require_manual",
            "validation": {
                "negative_quantities": True,
                "required_columns": True,
                "duplicate_sku": True
            },
            "export": {
                "include_diff_report": True,
                "include_source_batches": True
            }
        }

    @staticmethod
    def generate_example_config(file_path: str) -> None:
        """Generate an example JSON configuration file at the given path."""
        config = ConfigManager.get_example_config()
        config['_comments'] = {
            "conflict_strategy": "One of: first, last, sum, average, require_manual",
            "validation": "Toggle import validation rules (true=enable, false=disable)",
            "require_manual_note": "require_manual will FAIL merge if any cross-store SKU quantity conflicts exist"
        }
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def load_config_file(self, file_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Load configuration from a JSON file.
        If file_path is None, looks for 'inventory.config.json' in current directory.
        Raises ConfigError if the file exists but is invalid.
        Returns empty dict if file does not exist (not an error).
        """
        if file_path is None:
            file_path = self.DEFAULT_CONFIG_FILE
        
        if not os.path.exists(file_path):
            return {}
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(
                f"Invalid JSON in config file '{file_path}': {str(e)}. "
                "Use 'inventory init' to generate a valid example."
            )
        except Exception as e:
            raise ConfigError(f"Cannot read config file '{file_path}': {str(e)}")
        
        self._validate_config(config, file_path)
        self._file_config = config
        return config

    def _validate_config(self, config: Dict[str, Any], file_path: str) -> None:
        """Validate configuration from file. Raises ConfigError if invalid."""
        if not isinstance(config, dict):
            raise ConfigError(
                f"Config file '{file_path}' must contain a JSON object at top level."
            )
        
        if 'conflict_strategy' in config:
            strategy = config['conflict_strategy']
            if not isinstance(strategy, str) or strategy not in self.CONFLICT_STRATEGIES:
                raise ConfigError(
                    f"Invalid 'conflict_strategy' in '{file_path}': '{strategy}'. "
                    f"Must be one of: {', '.join(self.CONFLICT_STRATEGIES)}"
                )
        
        if 'validation' in config:
            validation = config['validation']
            if not isinstance(validation, dict):
                raise ConfigError(f"'validation' in '{file_path}' must be an object.")
            for key in ['negative_quantities', 'required_columns', 'duplicate_sku']:
                if key in validation and not isinstance(validation[key], bool):
                    raise ConfigError(
                        f"'validation.{key}' in '{file_path}' must be true or false."
                    )

    def set_cli_override(self, key: str, value: Any) -> None:
        """Set a CLI parameter override (highest priority)."""
        self._cli_overrides[key] = value

    def _get_effective_value(self, key: str, db_key: Optional[str] = None, 
                             default: Any = None) -> Any:
        """
        Get effective config value with priority:
        1. CLI override > 2. File config > 3. SQLite config > 4. Default
        """
        if db_key is None:
            db_key = key
        
        if key in self._cli_overrides:
            return self._cli_overrides[key]
        
        if self._file_config:
            if key in self._file_config:
                return self._file_config[key]
            if 'validation' in self._file_config and isinstance(self._file_config['validation'], dict):
                val_key_map = {
                    'validate_negative': 'negative_quantities',
                    'validate_required_columns': 'required_columns',
                    'validate_duplicate_sku': 'duplicate_sku'
                }
                if key in val_key_map and val_key_map[key] in self._file_config['validation']:
                    return self._file_config['validation'][val_key_map[key]]
        
        db_val = self.db.get_config(db_key)
        if db_val is not None:
            return db_val
        
        return default

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
        val = self._get_effective_value('conflict_strategy', 'conflict_strategy', 'require_manual')
        return str(val)

    def set_conflict_strategy(self, strategy: str):
        if strategy not in self.CONFLICT_STRATEGIES:
            raise ValueError(f"Invalid conflict strategy. Must be one of: {', '.join(self.CONFLICT_STRATEGIES)}")
        self.db.set_config('conflict_strategy', strategy)

    def validate_negative(self) -> bool:
        val = self._get_effective_value('validate_negative', 'validate_negative', 'true')
        if isinstance(val, bool):
            return val
        return str(val).lower() == 'true'

    def validate_required_columns(self) -> bool:
        val = self._get_effective_value('validate_required_columns', 'validate_required_columns', 'true')
        if isinstance(val, bool):
            return val
        return str(val).lower() == 'true'

    def validate_duplicate_sku(self) -> bool:
        val = self._get_effective_value('validate_duplicate_sku', 'validate_duplicate_sku', 'true')
        if isinstance(val, bool):
            return val
        return str(val).lower() == 'true'

    def set_validate_negative(self, value: bool):
        self.db.set_config('validate_negative', 'true' if value else 'false')

    def set_validate_required_columns(self, value: bool):
        self.db.set_config('validate_required_columns', 'true' if value else 'false')

    def set_validate_duplicate_sku(self, value: bool):
        self.db.set_config('validate_duplicate_sku', 'true' if value else 'false')

    def get_all_config(self) -> Dict[str, str]:
        result = dict(self.db.get_all_config())
        if self._file_config:
            result['_config_file'] = json.dumps(self._file_config, ensure_ascii=False)
        if self._cli_overrides:
            result['_cli_overrides'] = json.dumps(self._cli_overrides, ensure_ascii=False)
        return result

    def get_effective_config_summary(self) -> Dict[str, Any]:
        """Return a summary of effective configuration values and their sources."""
        return {
            'conflict_strategy': {
                'value': self.get_conflict_strategy(),
                'source': self._get_value_source('conflict_strategy')
            },
            'validate_negative': {
                'value': self.validate_negative(),
                'source': self._get_value_source('validate_negative')
            },
            'validate_required_columns': {
                'value': self.validate_required_columns(),
                'source': self._get_value_source('validate_required_columns')
            },
            'validate_duplicate_sku': {
                'value': self.validate_duplicate_sku(),
                'source': self._get_value_source('validate_duplicate_sku')
            }
        }

    def _get_value_source(self, key: str) -> str:
        """Determine which source the effective config value comes from."""
        if key in self._cli_overrides:
            return 'cli_parameter'
        if self._file_config:
            if key in self._file_config:
                return 'config_file'
            if 'validation' in self._file_config and isinstance(self._file_config['validation'], dict):
                val_key_map = {
                    'validate_negative': 'negative_quantities',
                    'validate_required_columns': 'required_columns',
                    'validate_duplicate_sku': 'duplicate_sku'
                }
                if key in val_key_map and val_key_map[key] in self._file_config['validation']:
                    return 'config_file'
        if self.db.get_config(key):
            return 'sqlite_db'
        return 'default'