"""
Configuration loader for field extraction and column mapping.

This module reads the YAML configuration files and provides
a convenient Python interface for accessing extraction settings.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any
import yaml


class FieldType(Enum):
    """Data types for extracted fields."""
    TEXT = "text"
    INTEGER = "integer"
    FLOAT = "float"
    PERCENTAGE = "percentage"
    DURATION = "duration"
    IMAGE_MATCH = "image_match"
    IMAGE_ARRAY = "image_array"


class OCRConfig(Enum):
    """OCR configuration presets."""
    TEXT = "text"
    DIGITS = "digits"
    DIGITS_DECIMAL = "digits_decimal"
    PERCENT = "percent"


@dataclass
class FieldDefinition:
    """Definition of a single field to extract."""
    name: str
    enabled: bool
    field_type: FieldType
    ocr_config: Optional[str]
    required: bool
    column_key: str
    description: str
    validation: Dict[str, Any] = field(default_factory=dict)
    note: Optional[str] = None


@dataclass
class ColumnDefinition:
    """Definition of a column region."""
    key: str
    x_start_pct: float
    x_end_pct: float
    y_offset_pct: float
    height_pct: float
    description: str
    preprocessing: str


@dataclass
class MatchMetadataRegion:
    """Definition of a match metadata region."""
    key: str
    x_start_pct: float
    x_end_pct: float
    y_start_pct: float
    y_end_pct: float
    description: str
    preprocessing: str


@dataclass
class ResolutionConfig:
    """Reference resolution for column mappings."""
    width: int
    height: int


class FieldConfig:
    """
    Manages field extraction and column mapping configuration.
    
    Loads configuration from YAML files and provides methods to
    access enabled fields, column mappings, and validation rules.
    """
    
    def __init__(self, config_dir: Path):
        """
        Initialize configuration loader.
        
        Args:
            config_dir: Path to directory containing config YAML files
        """
        self.config_dir = Path(config_dir)
        self._load_configs()
    
    def _load_configs(self):
        """Load all configuration files."""
        # Load field extraction config
        field_config_path = self.config_dir / "field_extraction.yaml"
        with open(field_config_path, 'r', encoding='utf-8') as f:
            self.field_config = yaml.safe_load(f)
        
        # Load column mapping config
        column_config_path = self.config_dir / "column_mapping.yaml"
        with open(column_config_path, 'r', encoding='utf-8') as f:
            self.column_config = yaml.safe_load(f)
        
        # Load hero config
        hero_config_path = self.config_dir / "heroes.yaml"
        with open(hero_config_path, 'r', encoding='utf-8') as f:
            self.hero_config = yaml.safe_load(f)
        
        # Parse field definitions
        self._parse_fields()
        self._parse_columns()
        self._parse_match_regions()
    
    def _parse_fields(self):
        """Parse field definitions into structured objects."""
        self.fields: Dict[str, FieldDefinition] = {}
        
        # Parse player fields
        for name, config in self.field_config.get('fields', {}).items():
            field_def = FieldDefinition(
                name=name,
                enabled=config.get('enabled', False),
                field_type=FieldType(config.get('type')),
                ocr_config=config.get('ocr_config'),
                required=config.get('required', False),
                column_key=config.get('column_key', name),
                description=config.get('description', ''),
                validation=config.get('validation', {}),
                note=config.get('note')
            )
            self.fields[name] = field_def
        
        # Parse match fields
        self.match_fields: Dict[str, FieldDefinition] = {}
        for name, config in self.field_config.get('match_fields', {}).items():
            field_def = FieldDefinition(
                name=name,
                enabled=config.get('enabled', False),
                field_type=FieldType(config.get('type')),
                ocr_config=config.get('ocr_config'),
                required=config.get('required', False),
                column_key=config.get('region_key', name),
                description=config.get('description', ''),
                validation=config.get('validation', {})
            )
            self.match_fields[name] = field_def
    
    def _parse_columns(self):
        """Parse column definitions."""
        self.columns: Dict[str, ColumnDefinition] = {}
        
        for key, config in self.column_config.get('columns', {}).items():
            col_def = ColumnDefinition(
                key=key,
                x_start_pct=config['x_start_pct'],
                x_end_pct=config['x_end_pct'],
                y_offset_pct=config['y_offset_pct'],
                height_pct=config['height_pct'],
                description=config.get('description', ''),
                preprocessing=config.get('preprocessing', 'binarize')
            )
            self.columns[key] = col_def
    
    def _parse_match_regions(self):
        """Parse match metadata regions."""
        self.match_regions: Dict[str, MatchMetadataRegion] = {}
        self.metadata_regions: Dict[str, MatchMetadataRegion] = {}
        
        # Try both 'metadata_regions' and 'match_metadata_regions' for backwards compatibility
        regions_config = self.column_config.get('metadata_regions', {})
        if not regions_config:
            regions_config = self.column_config.get('match_metadata_regions', {})
        
        for key, config in regions_config.items():
            region_def = MatchMetadataRegion(
                key=key,
                x_start_pct=config['x_start_pct'],
                x_end_pct=config['x_end_pct'],
                y_start_pct=config['y_start_pct'],
                y_end_pct=config['y_end_pct'],
                description=config.get('description', ''),
                preprocessing=config.get('preprocessing', 'binarize')
            )
            self.match_regions[key] = region_def
            self.metadata_regions[key] = region_def
    
    @property
    def enabled_fields(self) -> List[FieldDefinition]:
        """Get list of enabled player fields."""
        return [f for f in self.fields.values() if f.enabled]
    
    @property
    def enabled_match_fields(self) -> List[FieldDefinition]:
        """Get list of enabled match fields."""
        return [f for f in self.match_fields.values() if f.enabled]
    
    @property
    def reference_resolution(self) -> ResolutionConfig:
        """Get reference resolution."""
        res = self.column_config['reference_resolution']
        return ResolutionConfig(width=res['width'], height=res['height'])
    
    @property
    def row_config(self) -> Dict:
        """Get row detection configuration."""
        return self.column_config.get('rows', {})
    
    @property
    def preprocessing_settings(self) -> Dict:
        """Get preprocessing settings."""
        return self.column_config.get('preprocessing_settings', {})
    
    @property
    def ocr_settings(self) -> Dict:
        """Get OCR settings."""
        return self.field_config.get('ocr', {})
    
    @property
    def heroes(self) -> List[Dict]:
        """Get hero definitions."""
        return self.hero_config.get('heroes', [])
    
    @property
    def hero_matching_settings(self) -> Dict:
        """Get hero matching settings."""
        return self.hero_config.get('matching', {})
    
    def get_column_for_field(self, field_name: str) -> Optional[ColumnDefinition]:
        """
        Get column definition for a field.
        
        Args:
            field_name: Name of the field
            
        Returns:
            ColumnDefinition if found, None otherwise
        """
        field = self.fields.get(field_name) or self.match_fields.get(field_name)
        if not field:
            return None
        
        column_key = field.column_key
        return self.columns.get(column_key)
    
    def get_region_for_match_field(self, field_name: str) -> Optional[MatchMetadataRegion]:
        """
        Get metadata region for a match field.
        
        Args:
            field_name: Name of the match field
            
        Returns:
            MatchMetadataRegion if found, None otherwise
        """
        field = self.match_fields.get(field_name)
        if not field:
            return None
        
        region_key = field.column_key
        return self.match_regions.get(region_key)
    
    def get_ocr_corrections(self) -> Dict[str, Dict]:
        """Get OCR correction rules."""
        return self.field_config.get('post_processing', {}).get('ocr_corrections', {})
    
    def validate_field_value(self, field_name: str, value: Any) -> bool:
        """
        Validate a field value against configured rules.
        
        Args:
            field_name: Name of the field
            value: Value to validate
            
        Returns:
            True if valid, False otherwise
        """
        field = self.fields.get(field_name) or self.match_fields.get(field_name)
        if not field or not field.validation:
            return True
        
        validation = field.validation
        
        # Check min/max for numeric fields
        if 'min' in validation and value < validation['min']:
            return False
        if 'max' in validation and value > validation['max']:
            return False
        
        # Check length for text fields
        if 'min_length' in validation and len(str(value)) < validation['min_length']:
            return False
        if 'max_length' in validation and len(str(value)) > validation['max_length']:
            return False
        
        # Check allowed values
        if 'allowed_values' in validation and value not in validation['allowed_values']:
            return False
        
        return True


# Singleton instance
_config_instance: Optional[FieldConfig] = None


def get_config(config_dir: Optional[Path] = None) -> FieldConfig:
    """
    Get the global configuration instance.
    
    Args:
        config_dir: Path to config directory (only needed on first call)
        
    Returns:
        FieldConfig instance
    """
    global _config_instance
    
    if _config_instance is None:
        if config_dir is None:
            # Default to config/ directory relative to project root
            config_dir = Path(__file__).parent.parent.parent / "config"
        _config_instance = FieldConfig(config_dir)
    
    return _config_instance


if __name__ == "__main__":
    # Test loading configuration
    config = get_config()
    
    print(f"Reference resolution: {config.reference_resolution.width}x{config.reference_resolution.height}")
    print(f"\nEnabled player fields ({len(config.enabled_fields)}):")
    for field in config.enabled_fields:
        print(f"  - {field.name}: {field.field_type.value} ({field.column_key})")
    
    print(f"\nEnabled match fields ({len(config.enabled_match_fields)}):")
    for field in config.enabled_match_fields:
        print(f"  - {field.name}: {field.field_type.value}")
    
    print(f"\nColumns ({len(config.columns)}):")
    for key, col in config.columns.items():
        print(f"  - {key}: x=[{col.x_start_pct:.2%}, {col.x_end_pct:.2%}]")
    
    print(f"\nHeroes loaded: {len(config.heroes)}")
