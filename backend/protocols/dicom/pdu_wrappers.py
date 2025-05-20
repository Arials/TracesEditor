from typing import List, Dict, Any, Optional
from pathlib import Path

from backend.protocols.dicom.models import (
    Asset,
    LinkDicomConfiguration,
    AssetDicomProperties,
    PresentationContextItem as ModelPresentationContextItem
)
from backend.protocols.dicom import utils # Existing utils
# Assuming resolver is in the same package directory
# from backend.protocols.dicom.resolver import resolve_asset_dicom_properties 

# Default Application Context Name UID, consider making this configurable if needed
DEFAULT_APPLICATION_CONTEXT_NAME = "1.2.840.10008.3.1.1.1"


def create_scene_associate_rq_pdu(
    # scu_asset: Asset, # Not directly used if resolved_scu_dicom_props is provided
    # scp_asset: Asset, # Not directly used if resolved_scp_dicom_props is provided
    link_dicom_config: LinkDicomConfiguration,
    resolved_scu_dicom_props: AssetDicomProperties,
    resolved_scp_dicom_props: AssetDicomProperties,
    max_pdu_length_override: Optional[int] = None,
    application_context_name_override: Optional[str] = None
) -> bytes:
    """
    Creates an A-ASSOCIATE-RQ PDU based on Scene, Asset, and Link configurations.
    This wraps utils.create_associate_rq_pdu.

    Args:
        link_dicom_config: The DICOM configuration for the link.
        resolved_scu_dicom_props: Resolved DICOM properties for the SCU asset.
        resolved_scp_dicom_props: Resolved DICOM properties for the SCP asset.
        max_pdu_length_override: Optional override for max PDU length.
        application_context_name_override: Optional override for app context name.

    Returns:
        The A-ASSOCIATE-RQ PDU as bytes.
        
    Raises:
        ValueError: If explicit_presentation_contexts are required but not provided
                    (and automatic generation is not yet supported here).
    """

    calling_ae_title = link_dicom_config.calling_ae_title_override or resolved_scu_dicom_props.ae_title
    called_ae_title = link_dicom_config.called_ae_title_override or resolved_scp_dicom_props.ae_title
    
    application_context_name = application_context_name_override or DEFAULT_APPLICATION_CONTEXT_NAME

    presentation_contexts_input = []
    if link_dicom_config.explicit_presentation_contexts:
        for pc_item_model in link_dicom_config.explicit_presentation_contexts:
            presentation_contexts_input.append({
                "id": pc_item_model.id,
                "abstract_syntax": pc_item_model.abstract_syntax,
                "transfer_syntaxes": pc_item_model.transfer_syntaxes
            })
    else:
        # If explicit_presentation_contexts is None, this means automatic mode is intended.
        # For Task 2.2, the generation of these contexts is out of scope.
        # The DicomSceneProcessor or Task 3.2 logic should populate explicit_presentation_contexts
        # before calling this function if relying on this wrapper.
        # If it's truly meant to be empty, utils.create_associate_rq_pdu might handle it or fail.
        # For robustness, we might require it to be non-empty if no auto-gen logic here.
        # However, allowing an empty list to be passed to utils.py is also an option.
        # Let's assume for now that if it's empty, it's intentional by the caller.
        pass

    # Max PDU length:
    # Future: Could be sourced from resolved_scu_dicom_props if added there.
    max_pdu = max_pdu_length_override or utils.DEFAULT_MAX_PDU_LENGTH

    # Implementation details from SCU
    impl_class_uid = resolved_scu_dicom_props.implementation_class_uid
    # Ensure implementation_version_name is not None for the utils function
    impl_version_name = resolved_scu_dicom_props.implementation_version_name or utils.DEFAULT_IMPLEMENTATION_VERSION_NAME

    # User Identity - not yet in models, pass None for now
    user_identity_input = None 

    return utils.create_associate_rq_pdu(
        calling_ae_title=calling_ae_title,
        called_ae_title=called_ae_title,
        application_context_name=application_context_name,
        presentation_contexts_input=presentation_contexts_input,
        max_pdu_length=max_pdu,
        our_implementation_class_uid_str=impl_class_uid,
        our_implementation_version_name=impl_version_name,
        user_identity_input=user_identity_input
    )


def create_scene_associate_ac_pdu(
    original_rq_calling_ae_title: str, 
    original_rq_called_ae_title: str, 
    resolved_scp_dicom_props: AssetDicomProperties, 
    application_context_name: str, # Should be the one from RQ
    presentation_contexts_results_input: List[Dict[str, Any]], 
    association_result: int = 0, 
    association_result_source: int = 2, 
    association_diagnostic: int = 1,
    max_pdu_length_override: Optional[int] = None
    # application_context_name_override is not typical for AC as it's fixed by RQ
) -> bytes:
    """
    Creates an A-ASSOCIATE-AC PDU based on Scene, Asset, Link configurations,
    and the results of the association negotiation.
    This wraps utils.create_associate_ac_pdu.

    Args:
        original_rq_calling_ae_title: The Calling AE Title from the A-ASSOCIATE-RQ.
        original_rq_called_ae_title: The Called AE Title from the A-ASSOCIATE-RQ.
        resolved_scp_dicom_props: Resolved DICOM properties for the SCP asset (responder).
        application_context_name: The Application Context Name from the A-ASSOCIATE-RQ.
        presentation_contexts_results_input: List of dicts defining the results for each
                                             presentation context proposed in the RQ.
        association_result: Overall result of the association (e.g., 0 for acceptance).
        association_result_source: Source of the result (e.g., 2 for ACSE service provider).
        association_diagnostic: Diagnostic information if the result is not acceptance.
        max_pdu_length_override: Optional override for max PDU length the SCP can receive.

    Returns:
        The A-ASSOCIATE-AC PDU as bytes.
    """

    # Max PDU length for SCP:
    # Future: Could be sourced from resolved_scp_dicom_props if added there.
    max_pdu = max_pdu_length_override or utils.DEFAULT_MAX_PDU_LENGTH
    
    # Implementation details from SCP (the responder)
    impl_class_uid = resolved_scp_dicom_props.implementation_class_uid
    # Ensure implementation_version_name is not None for the utils function
    impl_version_name = resolved_scp_dicom_props.implementation_version_name or utils.DEFAULT_IMPLEMENTATION_VERSION_NAME
    
    return utils.create_associate_ac_pdu(
        calling_ae_title=original_rq_calling_ae_title, # As it was in the RQ
        called_ae_title=original_rq_called_ae_title,   # As it was in the RQ
        application_context_name=application_context_name, # As it was in the RQ
        presentation_contexts_results_input=presentation_contexts_results_input,
        max_pdu_length=max_pdu,
        responding_implementation_class_uid_str=impl_class_uid,
        responding_implementation_version_name=impl_version_name,
        result=association_result,
        result_source=association_result_source,
        diagnostic=association_diagnostic
    )
