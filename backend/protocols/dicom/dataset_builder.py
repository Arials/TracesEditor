import random
from typing import Optional, Dict, Any, List
from datetime import datetime # Added import

from pydicom.dataset import Dataset
from pydicom.uid import generate_uid as pydicom_generate_uid
from pydicom.uid import UID # Changed to import UID

from backend.protocols.dicom.models import DimseOperation, AssetDicomProperties, CommandSetItem
from backend.protocols.dicom import utils as pdu_utils

# Sample data for generation rules
SAMPLE_PATIENT_NAMES = [
    "DOE^JOHN", "ROE^JANE", "SMITH^ROBERT", "WILLIAMS^MARY", "BROWN^JAMES",
    "JONES^PATRICIA", "GARCIA^LINDA", "MILLER^DAVID", "DAVIS^ELIZABETH"
]

# --- Main function to be called by DicomSceneProcessor ---
def generate_p_data_tf_pdus_for_dimse_operation(
    operation: DimseOperation,
    scu_dicom_properties: AssetDicomProperties,
    scp_dicom_properties: AssetDicomProperties,
    accepted_transfer_syntax_uid: str, # New parameter
    # Optional: provide a pre-generated UID if it needs to be consistent across command and data
    # for AffectedSOPInstanceUID when both use an AUTO_GENERATE_UID_INSTANCE rule.
    # This could be managed by the DicomSceneProcessor for a given C-STORE operation.
    shared_affected_sop_instance_uid: Optional[str] = None
) -> List[bytes]:
    """
    Generates a list of P-DATA-TF PDUs (bytes) for a given DIMSE operation.
    This includes the command PDU and, if applicable, the data PDU.
    """
    pdus = []

    # Determine Transfer Syntax properties using UID object
    ts = UID(accepted_transfer_syntax_uid)

    # 1. Build Command Dataset
    # Determine the AffectedSOPInstanceUID to be used for the command,
    # prioritizing shared UID if provided and rule is AUTO_GENERATE.
    cmd_affected_sop_instance_uid = shared_affected_sop_instance_uid
    if operation.command_set.AffectedSOPInstanceUID == "AUTO_GENERATE_UID_INSTANCE" and \
       not shared_affected_sop_instance_uid:
        cmd_affected_sop_instance_uid = pydicom_generate_uid()
    
    command_ds = _build_command_dataset(
        command_set_model=operation.command_set,
        # Pass the potentially pre-generated/shared UID.
        # _build_command_dataset will use this if the rule is AUTO_GENERATE_UID_INSTANCE.
        # If command_set_model.AffectedSOPInstanceUID is explicit, this param is ignored.
        auto_generated_affected_sop_instance_uid=cmd_affected_sop_instance_uid
    )
    
    # Set endianness and VR mode based on negotiated transfer syntax
    command_ds.is_little_endian = ts.is_little_endian
    command_ds.is_implicit_VR = ts.is_implicit_VR
    
    command_pdu_bytes = pdu_utils.create_p_data_tf_pdu(
        dimse_dataset=command_ds,
        presentation_context_id=operation.presentation_context_id,
        is_command=True
    )
    pdus.append(command_pdu_bytes)

    # 2. Build Data Dataset (if rules are defined)
    if operation.dataset_content_rules:
        data_ds = _build_data_dataset(
            rules=operation.dataset_content_rules,
            resolved_command_ds=command_ds, # Pass the fully resolved command dataset
            scu_dicom_properties=scu_dicom_properties,
            scp_dicom_properties=scp_dicom_properties
        )
        # Only add data PDU if a non-empty dataset was actually built
        if data_ds and len(data_ds) > 0:
            # Set endianness and VR mode based on negotiated transfer syntax
            data_ds.is_little_endian = ts.is_little_endian
            data_ds.is_implicit_VR = ts.is_implicit_VR
            
            data_pdu_bytes = pdu_utils.create_p_data_tf_pdu(
                dimse_dataset=data_ds,
                presentation_context_id=operation.presentation_context_id,
                is_command=False
            )
            pdus.append(data_pdu_bytes)
            
    return pdus


# --- Helper function to build the Command Dataset ---
def _build_command_dataset(
    command_set_model: CommandSetItem,
    auto_generated_affected_sop_instance_uid: Optional[str] = None
) -> Dataset:
    """
    Builds a pydicom Dataset for the command part of a DIMSE message.
    Handles 'AUTO_GENERATE_UID_INSTANCE' for AffectedSOPInstanceUID if present in command_set.
    """
    ds = Dataset()
    # Start with a copy of extra_fields, then explicitly set defined fields
    # to ensure defined fields take precedence and are correctly typed by Pydantic.
    if command_set_model.extra_fields:
        for key, value in command_set_model.extra_fields.items():
            setattr(ds, key, value)

    # Explicitly set well-known fields from the model
    ds.MessageID = command_set_model.MessageID # MessageID is mandatory in model

    if command_set_model.Priority is not None:
        ds.Priority = command_set_model.Priority
    
    if command_set_model.AffectedSOPClassUID is not None:
        ds.AffectedSOPClassUID = command_set_model.AffectedSOPClassUID

    # Handle AffectedSOPInstanceUID with potential auto-generation
    if command_set_model.AffectedSOPInstanceUID == "AUTO_GENERATE_UID_INSTANCE":
        ds.AffectedSOPInstanceUID = auto_generated_affected_sop_instance_uid or pydicom_generate_uid()
    elif command_set_model.AffectedSOPInstanceUID is not None:
        ds.AffectedSOPInstanceUID = command_set_model.AffectedSOPInstanceUID
    
    # pynetdicom usually sets these if not present, but good to be explicit if needed
    # ds.CommandDataSetType = 0x0101 # Example: C-STORE-RQ has CommandDataSetType = 1 (0x0001), no dataset = 0x0101
                                     # This is usually handled by pynetdicom based on message type.
                                     # For now, we don't set CommandDataSetType here.
    return ds


# --- Helper function to build the Data Dataset based on rules ---
def _build_data_dataset(
    rules: Dict[str, Any],
    resolved_command_ds: Dataset, # Takes the fully resolved command dataset
    scu_dicom_properties: AssetDicomProperties,
    scp_dicom_properties: AssetDicomProperties
) -> Optional[Dataset]:
    """
    Builds a pydicom Dataset based on the dataset_content_rules.
    Returns None if rules are empty or result in an empty dataset.
    """
    if not rules:
        return None

    ds = Dataset()
    has_elements = False

    # Categorize rules to enforce a specific processing order for UID generation
    study_uid_rules_list: List[tuple[str, Any]] = []
    series_uid_rules_list: List[tuple[str, Any]] = []
    instance_uid_rules_list: List[tuple[str, Any]] = []
    other_rules_list: List[tuple[str, Any]] = []

    for tag_keyword, rule_or_value in rules.items():
        if isinstance(rule_or_value, str):
            if rule_or_value == "AUTO_GENERATE_UID_STUDY":
                study_uid_rules_list.append((tag_keyword, rule_or_value))
            elif rule_or_value == "AUTO_GENERATE_UID_SERIES":
                series_uid_rules_list.append((tag_keyword, rule_or_value))
            elif rule_or_value == "AUTO_GENERATE_UID_INSTANCE":
                instance_uid_rules_list.append((tag_keyword, rule_or_value))
            else: # Other AUTO_ rules or explicit string values that are not UIDs
                other_rules_list.append((tag_keyword, rule_or_value))
        else: # Explicit non-string values
            other_rules_list.append((tag_keyword, rule_or_value))

    # Sort each category by tag_keyword for deterministic processing within the category
    study_uid_rules_list.sort(key=lambda item: item[0])
    series_uid_rules_list.sort(key=lambda item: item[0])
    instance_uid_rules_list.sort(key=lambda item: item[0])
    other_rules_list.sort(key=lambda item: item[0])

    # Construct the final processing order
    ordered_processing_list = (
        study_uid_rules_list +
        series_uid_rules_list +
        instance_uid_rules_list +
        other_rules_list
    )

    for tag_keyword, rule_or_value in ordered_processing_list:
        resolved_value: Any = None 
        is_resolved = False # Flag to track if a rule was processed and yielded a value (even if None)

        if isinstance(rule_or_value, str) and rule_or_value.startswith("AUTO_"):
            # This 'is_resolved' is primarily for the final step of adding to dataset.
            # Most AUTO_ rules will resolve to something or be explicitly handled.
            is_resolved = True 

            if rule_or_value == "AUTO_FROM_COMMAND_AFFECTED_SOP_CLASS_UID":
                resolved_value = resolved_command_ds.get("AffectedSOPClassUID", None)
            elif rule_or_value == "AUTO_FROM_COMMAND_AFFECTED_SOP_INSTANCE_UID":
                resolved_value = resolved_command_ds.get("AffectedSOPInstanceUID", None)
            
            elif rule_or_value == "AUTO_GENERATE_UID_INSTANCE":
                if tag_keyword == "SOPInstanceUID" and "AffectedSOPInstanceUID" in resolved_command_ds:
                    resolved_value = resolved_command_ds.AffectedSOPInstanceUID
                else: 
                    resolved_value = pydicom_generate_uid()
            elif rule_or_value == "AUTO_GENERATE_UID_STUDY":
                resolved_value = pydicom_generate_uid(prefix="1.2.826.0.1.3680043.2.1143.1.1.1.") 
            elif rule_or_value == "AUTO_GENERATE_UID_SERIES":
                resolved_value = pydicom_generate_uid(prefix="1.2.826.0.1.3680043.2.1143.1.1.2.")
            elif rule_or_value == "AUTO_GENERATE_UID": # Generic UID generation
                resolved_value = pydicom_generate_uid()
            elif rule_or_value == "AUTO_GENERATE_SAMPLE_PATIENT_NAME":
                resolved_value = random.choice(SAMPLE_PATIENT_NAMES)
            elif rule_or_value == "AUTO_GENERATE_SAMPLE_DATE_TODAY":
                resolved_value = datetime.today().strftime('%Y%m%d')
            
            # Asset-based rules
            elif rule_or_value == "AUTO_FROM_ASSET_SCU_AE_TITLE":
                resolved_value = scu_dicom_properties.ae_title
            elif rule_or_value == "AUTO_FROM_ASSET_SCP_AE_TITLE":
                resolved_value = scp_dicom_properties.ae_title
            elif rule_or_value == "AUTO_FROM_ASSET_SCU_MANUFACTURER":
                resolved_value = scu_dicom_properties.manufacturer
            elif rule_or_value == "AUTO_FROM_ASSET_SCP_MANUFACTURER":
                resolved_value = scp_dicom_properties.manufacturer
            elif rule_or_value == "AUTO_FROM_ASSET_SCU_MODEL_NAME":
                resolved_value = scu_dicom_properties.model_name
            elif rule_or_value == "AUTO_FROM_ASSET_SCP_MODEL_NAME":
                resolved_value = scp_dicom_properties.model_name
            elif rule_or_value == "AUTO_FROM_ASSET_SCU_SOFTWARE_VERSIONS":
                resolved_value = scu_dicom_properties.software_versions 
            elif rule_or_value == "AUTO_FROM_ASSET_SCP_SOFTWARE_VERSIONS":
                resolved_value = scp_dicom_properties.software_versions 
            elif rule_or_value == "AUTO_FROM_ASSET_SCU_DEVICE_SERIAL_NUMBER":
                resolved_value = scu_dicom_properties.device_serial_number
            elif rule_or_value == "AUTO_FROM_ASSET_SCP_DEVICE_SERIAL_NUMBER":
                resolved_value = scp_dicom_properties.device_serial_number
            else:
                # Unknown AUTO_ rule, treat as explicit string value.
                resolved_value = rule_or_value 
                # is_resolved remains True as we are treating it as an explicit value.
        else:
            # Explicit value (not an AUTO_ string)
            # Check if it's a nested structure (dict for a single sequence item, or list of dicts for multiple items)
            if isinstance(rule_or_value, dict):
                # Recursively build the dataset for the single sequence item
                nested_ds = _build_data_dataset(
                    rules=rule_or_value, 
                    resolved_command_ds=resolved_command_ds, 
                    scu_dicom_properties=scu_dicom_properties, 
                    scp_dicom_properties=scp_dicom_properties
                )
                if nested_ds: # Only add if the nested dataset is not empty
                    resolved_value = [nested_ds] # DICOM sequences are lists of datasets
                else:
                    resolved_value = [] # Assign empty list if nested_ds is None or empty
                is_resolved = True
            elif isinstance(rule_or_value, list):
                # Recursively build datasets for each item in the list (sequence of items)
                sequence_datasets = []
                for item_rules in rule_or_value:
                    if isinstance(item_rules, dict):
                        nested_item_ds = _build_data_dataset(
                            rules=item_rules,
                            resolved_command_ds=resolved_command_ds,
                            scu_dicom_properties=scu_dicom_properties,
                            scp_dicom_properties=scp_dicom_properties
                        )
                        if nested_item_ds: # Only add if the nested item dataset is not empty
                            sequence_datasets.append(nested_item_ds)
                    else:
                        # If items in the list are not dicts, treat them as simple values in a multi-value field (e.g. SoftwareVersions)
                        # This part of the logic might need refinement if lists can contain non-dict, non-AUTO_ items
                        # For now, assume if it's a list, it's a list of sequence item dicts or simple multi-value elements.
                        # The current loop structure handles simple multi-value elements (like SoftwareVersions) correctly
                        # if they are not AUTO_ strings. This 'elif isinstance(rule_or_value, list):'
                        # is specifically for lists of sequence items (list of dicts).
                        # If rule_or_value is a list of simple types, it will be handled by the final setattr.
                        # This specific block is for list of dicts (sequence items).
                        pass # Let the outer loop handle simple list values if any. This branch is for list of dicts.
                
                if sequence_datasets: # Only assign if we actually built some sequence datasets
                    resolved_value = sequence_datasets
                else: # If no valid sequence items were built, assign an empty list
                    resolved_value = []
                is_resolved = True
            else:
                # Standard explicit value (not a dict or list for sequence, not an AUTO_ string)
                resolved_value = rule_or_value
                is_resolved = True

        # Add to dataset if the rule was resolved and the value is not None,
        # OR if the rule was an explicit value (which could be None if user provided None explicitly).
        # The main case to avoid adding is when an AUTO_FROM_ASSET_ rule resolves to None
        # because the optional asset property was not set.
        if is_resolved:
            actual_dicom_tag_keyword = tag_keyword
            # Map ModelName rule to ManufacturerModelName DICOM tag
            if tag_keyword == "ModelName" and isinstance(rule_or_value, str) and \
               (rule_or_value == "AUTO_FROM_ASSET_SCU_MODEL_NAME" or \
                rule_or_value == "AUTO_FROM_ASSET_SCP_MODEL_NAME"):
                actual_dicom_tag_keyword = "ManufacturerModelName"

            if resolved_value is not None:
                setattr(ds, actual_dicom_tag_keyword, resolved_value)
                has_elements = True
            elif not (isinstance(rule_or_value, str) and rule_or_value.startswith("AUTO_FROM_ASSET_")):
                # If resolved_value is None, but it wasn't from an optional AUTO_FROM_ASSET_ rule,
                # it means the user explicitly provided None or an AUTO_ rule (not asset-based) resolved to None.
                # In such cases, we might still want to set the attribute if DICOM allows None for that tag,
                # or pydicom handles it. For now, let's be consistent: if resolved_value is None,
                # we only add it if it was an *explicitly provided None* rather than an *unresolved optional asset property*.
                # This behavior might need refinement based on desired handling of explicit None values.
                # For now, if resolved_value is None, we only add it if it's an explicit value from the rules.
                if not (isinstance(rule_or_value, str) and rule_or_value.startswith("AUTO_")): # It's an explicit value
                     setattr(ds, actual_dicom_tag_keyword, resolved_value) # Set explicit None using mapped keyword
                     has_elements = True # Count it as an element
            # If resolved_value is None AND it came from an AUTO_FROM_ASSET_ rule, we skip adding it.
            
    return ds if has_elements else None
