import json
from pathlib import Path
from typing import Optional

from backend.protocols.dicom.models import Asset, AssetDicomProperties

# Default directory for asset templates, relative to this resolver.py file
DEFAULT_ASSET_TEMPLATES_DIR = Path(__file__).resolve().parent / "asset_templates"

class AssetTemplateNotFoundError(FileNotFoundError):
    """Custom exception for when an asset template file is not found."""
    pass

class InvalidAssetTemplateError(ValueError):
    """Custom exception for errors in asset template content (e.g., missing keys, invalid JSON)."""
    pass

def resolve_asset_dicom_properties(
    asset: Asset,
    templates_base_path: Path = DEFAULT_ASSET_TEMPLATES_DIR
) -> AssetDicomProperties:
    """
    Resolves the full AssetDicomProperties for a given Asset.

    This involves:
    1. Optionally loading a base configuration from an "Asset Template" if 
       Asset.asset_template_id_ref is specified.
    2. Merging or overriding the template's properties with those explicitly 
       defined in Asset.dicom_properties.
    3. Returning the final, complete AssetDicomProperties object.

    Args:
        asset: The Asset object for which to resolve DICOM properties.
        templates_base_path: The base directory path where asset template JSON files are stored.
                             Defaults to DEFAULT_ASSET_TEMPLATES_DIR.

    Returns:
        The fully resolved AssetDicomProperties.

    Raises:
        AssetTemplateNotFoundError: If a referenced template file does not exist.
        InvalidAssetTemplateError: If the template file is not valid JSON or is missing
                                   the 'dicom_properties' key.
    """
    if not asset.asset_template_id_ref:
        # No template referenced, return a deep copy of the asset's own DICOM properties.
        # The Asset model ensures dicom_properties is always present.
        return asset.dicom_properties.model_copy(deep=True)

    # A template is referenced, attempt to load it.
    template_file_name = f"{asset.asset_template_id_ref}.json"
    template_file_path = templates_base_path / template_file_name

    try:
        with open(template_file_path, 'r') as f:
            template_data = json.load(f)
    except FileNotFoundError:
        raise AssetTemplateNotFoundError(
            f"Asset template file not found: {template_file_path}"
        )
    except json.JSONDecodeError as e:
        raise InvalidAssetTemplateError(
            f"Invalid JSON in asset template file {template_file_path}: {e}"
        )

    template_dicom_props_dict = template_data.get("dicom_properties")
    if template_dicom_props_dict is None:
        raise InvalidAssetTemplateError(
            f"Asset template file {template_file_path} is missing the 'dicom_properties' key."
        )

    try:
        base_properties = AssetDicomProperties(**template_dicom_props_dict)
    except Exception as e: # Catch Pydantic validation errors or other issues
        raise InvalidAssetTemplateError(
            f"Could not parse 'dicom_properties' from template {template_file_path}: {e}"
        )

    # Merge base (template) properties with overrides from the asset's dicom_properties.
    # model_dump(exclude_unset=True) ensures that only explicitly set fields in
    # asset.dicom_properties are used for overriding.
    override_props_dict = asset.dicom_properties.model_dump(exclude_unset=True)

    # Create the resolved properties by updating the base properties with the overrides.
    # For list fields like 'supported_sop_classes', if 'override_props_dict' contains the key,
    # the entire list from the override will replace the base list.
    # If the key is not in 'override_props_dict' (because it wasn't set in asset.dicom_properties),
    # the list from 'base_properties' (template) is retained.
    
    # Dump the base_properties to a dictionary
    merged_dict = base_properties.model_dump()
    
    # Update this dictionary with the override_props_dict.
    # If 'supported_sop_classes' is in override_props_dict, it will be a list of dicts
    # from asset.dicom_properties.model_dump().
    merged_dict.update(override_props_dict)
    
    # Re-parse the merged dictionary to create the final AssetDicomProperties instance.
    # This ensures that all fields, including nested models like SopClassDefinition items
    # in 'supported_sop_classes', are properly validated and instantiated from dicts if necessary.
    try:
        resolved_properties = AssetDicomProperties(**merged_dict)
    except Exception as e: # Catch Pydantic validation errors or other issues during re-parsing
        # This indicates an issue with the merged data structure.
        raise ValueError( # Or a more specific custom error if defined
            f"Failed to instantiate AssetDicomProperties from merged template and asset data: {e}"
        )

    return resolved_properties
