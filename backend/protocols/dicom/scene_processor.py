from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path
import random

from scapy.all import Packet, PacketList

from backend.protocols.dicom.models import (
    Scene,
    Link,
    Asset,
    Node,
    LinkConnectionDetails,
    AssetDicomProperties,
    PresentationContextItem as ModelPresentationContextItem,
    LinkDicomConfiguration
)
from backend.protocols.dicom.resolver import (
    resolve_asset_dicom_properties,
    DEFAULT_ASSET_TEMPLATES_DIR,
    AssetTemplateNotFoundError,
    InvalidAssetTemplateError
)
from backend.protocols.dicom.pdu_wrappers import (
    create_scene_associate_rq_pdu,
    create_scene_associate_ac_pdu,
    DEFAULT_APPLICATION_CONTEXT_NAME
)
# Removed import: from pynetdicom.sop_class import VerificationSOPClass
from backend.protocols.dicom.dataset_builder import (
    generate_p_data_tf_pdus_for_dimse_operation
)
from backend.protocols.dicom.handler import generate_dicom_session_packet_list
from pydicom.uid import generate_uid as pydicom_generate_uid


class DicomSceneProcessorError(Exception):
    """Base exception for errors during DICOM scene processing."""
    pass

class AssetNotFoundError(DicomSceneProcessorError):
    """Raised when an Asset referenced by ID is not found in the Scene."""
    pass

class NodeNotFoundError(DicomSceneProcessorError):
    """Raised when a Node referenced by ID is not found in an Asset."""
    pass

class DicomSceneProcessor:
    """
    Processes a Scene object to generate a list of Scapy packets representing
    all DICOM communications defined in the scene.
    """
    def __init__(self, scene: Scene, asset_templates_base_path: Path = DEFAULT_ASSET_TEMPLATES_DIR):
        self.scene = scene
        self.asset_templates_base_path = asset_templates_base_path
        self._resolved_assets_cache: Dict[str, AssetDicomProperties] = {}
        self._asset_map: Dict[str, Asset] = {asset.asset_id: asset for asset in self.scene.assets}

    def _get_asset_by_id(self, asset_id: str) -> Asset:
        asset = self._asset_map.get(asset_id)
        if not asset:
            raise AssetNotFoundError(f"Asset with ID '{asset_id}' not found in scene.")
        return asset

    def _get_node_from_asset(self, asset: Asset, node_id: str) -> Node:
        for node in asset.nodes:
            if node.node_id == node_id:
                return node
        raise NodeNotFoundError(f"Node with ID '{node_id}' not found in Asset '{asset.asset_id}'.")

    def _get_resolved_dicom_properties(self, asset_id: str) -> AssetDicomProperties:
        if asset_id in self._resolved_assets_cache:
            return self._resolved_assets_cache[asset_id]

        asset = self._get_asset_by_id(asset_id)
        try:
            resolved_props = resolve_asset_dicom_properties(asset, self.asset_templates_base_path)
            self._resolved_assets_cache[asset_id] = resolved_props
            return resolved_props
        except (AssetTemplateNotFoundError, InvalidAssetTemplateError) as e:
            raise DicomSceneProcessorError(f"Error resolving DICOM properties for Asset '{asset_id}': {e}")

    def _derive_connection_details(self, link: Link) -> LinkConnectionDetails:
        if link.connection_details:
            return link.connection_details

        # Derive from source and destination nodes
        source_asset = self._get_asset_by_id(link.source_asset_id_ref)
        source_node = self._get_node_from_asset(source_asset, link.source_node_id_ref)

        dest_asset = self._get_asset_by_id(link.destination_asset_id_ref)
        dest_node = self._get_node_from_asset(dest_asset, link.destination_node_id_ref)
        
        # Determine SCU and SCP based on LinkDicomConfiguration
        # This is important for port selection if not overridden.
        # The LinkDicomConfiguration specifies which asset is SCU and which is SCP.
        # The source_asset_id_ref in the Link model is not necessarily the SCU.
        
        # For port selection, the destination_port is typically the SCP's listening port.
        # The source_port is ephemeral.
        
        # Identify which node is the SCP for this link to get the correct destination port.
        # The Link.dicom_config.scp_asset_id_ref tells us which asset is the SCP.
        # If link.destination_asset_id_ref is the SCP, then dest_node.dicom_port is the target.
        # If link.source_asset_id_ref is the SCP (e.g. for a C-GET response), then source_node.dicom_port is target.
        # However, for a typical SCU->SCP request flow, destination_asset_id_ref is the SCP.
        
        # Let's assume the Link's source/destination implies SCU/SCP direction for connection setup.
        # The DICOM SCU/SCP roles are defined in link.dicom_config.
        
        # The destination_port for the TCP connection should be the listening port of the SCP node.
        # The source_port for the TCP connection is an ephemeral port from the SCU node.

        # If link.dicom_config.scp_asset_id_ref == link.destination_asset_id_ref:
        #   actual_scp_node = dest_node
        # else: # link.dicom_config.scp_asset_id_ref == link.source_asset_id_ref
        #   actual_scp_node = source_node
        # This logic is more for determining AE titles. For connection, it's simpler:
        # The 'destination_node' of the Link is where we are connecting TO.

        return LinkConnectionDetails(
            source_mac=source_node.mac_address,
            destination_mac=dest_node.mac_address,
            source_ip=source_node.ip_address,
            destination_ip=dest_node.ip_address,
            source_port=random.randint(49152, 65535), # Ephemeral port for SCU
            destination_port=dest_node.dicom_port or 104 # SCP's listening port
        )

    def _negotiate_presentation_contexts(
        self,
        link_dicom_config: LinkDicomConfiguration, # Contains explicit_presentation_contexts
        scu_props: AssetDicomProperties,
        scp_props: AssetDicomProperties
    ) -> Tuple[List[ModelPresentationContextItem], List[Dict[str, Any]]]:
        """
        Determines the presentation contexts to propose (for RQ) and the results (for AC).
        If link_dicom_config.explicit_presentation_contexts is provided, they are used directly.
        Otherwise, automatically negotiates presentation contexts based on SCU and SCP capabilities.

        Returns:
            A tuple: 
                - List of ModelPresentationContextItem for the A-ASSOCIATE-RQ.
                - List of dicts for presentation_contexts_results_input for A-ASSOCIATE-AC.
        """
        proposed_rq_contexts_models: List[ModelPresentationContextItem] = []
        accepted_ac_results_dicts: List[Dict[str, Any]] = []
        
        next_pc_id = 1 # Presentation context IDs must be odd and unique per RQ

        if link_dicom_config.explicit_presentation_contexts is not None: # Check for None, empty list means explicitly no contexts
            # User has provided explicit presentation contexts
            for pc_model in link_dicom_config.explicit_presentation_contexts:
                proposed_rq_contexts_models.append(pc_model)
                # Simulate SCP acceptance of the first transfer syntax if any are proposed
                if pc_model.transfer_syntaxes:
                    accepted_ac_results_dicts.append({
                        "id": pc_model.id,
                        "result": 0,  # Acceptance
                        "transfer_syntax": pc_model.transfer_syntaxes[0]
                    })
                else: # No transfer syntaxes proposed by SCU for this abstract syntax
                     accepted_ac_results_dicts.append({
                        "id": pc_model.id,
                        "result": 4,  # Transfer syntaxes not supported (provider rejection)
                        "transfer_syntax": "1.2.840.10008.1.2" # Default for rejected AC item
                    })
        else:
            # Automatic negotiation based on SCU/SCP capabilities
            scu_sop_map = {
                sop.sop_class_uid: sop for sop in scu_props.supported_sop_classes 
                if sop.role.upper() in ["SCU", "BOTH"]
            }
            scp_sop_map = {
                sop.sop_class_uid: sop for sop in scp_props.supported_sop_classes
                if sop.role.upper() in ["SCP", "BOTH"]
            }

            for scu_sop_uid, scu_sop_def in scu_sop_map.items():
                if scu_sop_uid in scp_sop_map:
                    scp_sop_def = scp_sop_map[scu_sop_uid]
                    
                    # Find common transfer syntaxes
                    # SCU proposes its list; SCP must support at least one.
                    # For simplicity, we'll propose all SCU's transfer syntaxes for this SOP.
                    # The SCP will then "choose" one if it supports any.
                    
                    common_ts = [
                        ts for ts in scu_sop_def.transfer_syntaxes 
                        if ts in scp_sop_def.transfer_syntaxes
                    ]

                    if common_ts:
                        # Propose this abstract syntax
                        rq_pc_item = ModelPresentationContextItem(
                            id=next_pc_id,
                            abstract_syntax=scu_sop_uid,
                            transfer_syntaxes=list(scu_sop_def.transfer_syntaxes) # SCU proposes all it supports for this AS
                        )
                        proposed_rq_contexts_models.append(rq_pc_item)
                        
                        # SCP accepts with the first common transfer syntax
                        accepted_ac_results_dicts.append({
                            "id": next_pc_id,
                            "result": 0, # Acceptance
                            "transfer_syntax": common_ts[0] 
                        })
                        next_pc_id += 2 # Increment by 2 to keep it odd
                    # else: No common transfer syntax, so this abstract syntax cannot be negotiated.
            
            # Update the link's dicom_config with the auto-negotiated contexts for RQ
            # This is important if other parts of the system expect explicit_presentation_contexts to be populated
            link_dicom_config.explicit_presentation_contexts = list(proposed_rq_contexts_models)


        return proposed_rq_contexts_models, accepted_ac_results_dicts

    def process_scene(self) -> PacketList:
        """
        Processes the entire scene and generates a PacketList of all DICOM communications.
        """
        all_packets = PacketList()
        
        # Resolve all asset DICOM properties first (populates cache)
        for asset_in_scene in self.scene.assets:
            self._get_resolved_dicom_properties(asset_in_scene.asset_id)

        for link in self.scene.links:
            try:
                # 1. Resolve SCU and SCP AssetDicomProperties for this link
                # The LinkDicomConfiguration specifies which asset is SCU and SCP for this interaction
                scu_asset_id = link.dicom_config.scu_asset_id_ref
                scp_asset_id = link.dicom_config.scp_asset_id_ref
                
                resolved_scu_props = self._get_resolved_dicom_properties(scu_asset_id)
                resolved_scp_props = self._get_resolved_dicom_properties(scp_asset_id)

                # 2. Determine Connection Details (L2-L4)
                # The Link model's source/destination asset/node refs define the L2-L4 path.
                # This might not align with DICOM SCU/SCP roles (e.g., C-GET response).
                # For now, assume Link source/dest implies TCP initiator/acceptor.
                conn_details_model = self._derive_connection_details(link)
                network_params_dict = conn_details_model.model_dump()

                # 3. Prepare A-ASSOCIATE-RQ
                # Negotiate/determine presentation contexts
                # This is a placeholder for more advanced negotiation (Task 3.2)
                # For now, it primarily uses explicit_presentation_contexts from the link.
                # If explicit_presentation_contexts is None, this will currently return empty lists.
                # The LinkDicomConfiguration's explicit_presentation_contexts might be None (for auto)
                # or an empty list (explicitly no contexts) or a populated list.
                # _negotiate_presentation_contexts handles this:
                # - If explicit_presentation_contexts is a list (empty or not), it uses that.
                # - If explicit_presentation_contexts is None, it performs auto-negotiation
                #   and updates link.dicom_config.explicit_presentation_contexts.
                
                # Call negotiation first. This will populate link.dicom_config.explicit_presentation_contexts
                # if it was None (auto-mode).
                negotiated_rq_context_models, negotiated_ac_results_dicts = self._negotiate_presentation_contexts(
                    link.dicom_config, resolved_scu_props, resolved_scp_props
                )
                
                # Now, link.dicom_config.explicit_presentation_contexts is guaranteed to be a list (possibly empty).
                # create_scene_associate_rq_pdu uses this populated/original list.
                assoc_rq_pdu_bytes = create_scene_associate_rq_pdu(
                    link_dicom_config=link.dicom_config, # This now has populated explicit_presentation_contexts if auto
                    resolved_scu_dicom_props=resolved_scu_props,
                    resolved_scp_dicom_props=resolved_scp_props
                )

                # 4. Prepare A-ASSOCIATE-AC (Simulated SCP Response)
                # Use the results from _negotiate_presentation_contexts
                original_rq_calling_ae = link.dicom_config.calling_ae_title_override or resolved_scu_props.ae_title
                original_rq_called_ae = link.dicom_config.called_ae_title_override or resolved_scp_props.ae_title
                
                assoc_ac_pdu_bytes = b''
                if negotiated_ac_results_dicts: # Only generate AC if there were contexts to respond to
                    assoc_ac_pdu_bytes = create_scene_associate_ac_pdu(
                        original_rq_calling_ae_title=original_rq_calling_ae,
                        original_rq_called_ae_title=original_rq_called_ae,
                        resolved_scp_dicom_props=resolved_scp_props, 
                        application_context_name=DEFAULT_APPLICATION_CONTEXT_NAME, 
                        presentation_contexts_results_input=negotiated_ac_results_dicts
                    )
                
                # 5. Prepare P-DATA-TF PDUs for DIMSE sequence
                current_dimse_sequence = link.dicom_config.dimse_sequence
                if not current_dimse_sequence: # If empty, try to generate a default sequence
                    # TODO: Implement more sophisticated default DIMSE sequence generation
                    # based on negotiated presentation contexts and asset roles.
                    # For now, if Verification (C-ECHO) was negotiated, add a C-ECHO-RQ.
                    # This is a very basic example of auto-generating a DIMSE sequence.
                    
                    # Check if Verification SOP Class (1.2.840.10008.1.1) was accepted
                    verification_pc_id = None
                    for pc_result in negotiated_ac_results_dicts:
                        # Find the corresponding RQ context model to get abstract_syntax
                        rq_model_for_id = next((m for m in negotiated_rq_context_models if m.id == pc_result["id"]), None)
                        if rq_model_for_id and rq_model_for_id.abstract_syntax == "1.2.840.10008.1.1" and pc_result["result"] == 0:
                            verification_pc_id = pc_result["id"]
                            break
                    
                    if verification_pc_id is not None:
                        from backend.protocols.dicom.models import DimseOperation, CommandSetItem # Import here to avoid circularity at top
                        default_echo_op = DimseOperation(
                            operation_name="Automatic C-ECHO Request",
                            message_type="C-ECHO-RQ",
                            presentation_context_id=verification_pc_id,
                            command_set=CommandSetItem(
                                MessageID=1,
                                AffectedSOPClassUID="1.2.840.10008.1.1" # Explicitly set AffectedSOPClassUID using UID string
                            ),
                            dataset_content_rules=None # C-ECHO-RQ has no dataset
                        )
                        current_dimse_sequence = [default_echo_op]
                        # print(f"Info: Auto-generated C-ECHO-RQ for link {link.link_id} on PC ID {verification_pc_id}")
                    # else:
                        # print(f"Info: No default DIMSE sequence generated for link {link.link_id} as Verification was not negotiated or no other rules apply.")
                        
                all_p_data_pdus_bytes: List[bytes] = []
                for dimse_op in current_dimse_sequence: # Use current_dimse_sequence which might be auto-generated
                    # Handle shared UID for C-STORE AffectedSOPInstanceUID if needed
                    shared_uid_for_op = None
                    if dimse_op.message_type == "C-STORE-RQ" and \
                       dimse_op.command_set.AffectedSOPInstanceUID == "AUTO_GENERATE_UID_INSTANCE" and \
                       dimse_op.dataset_content_rules and \
                       dimse_op.dataset_content_rules.get("SOPInstanceUID") == "AUTO_FROM_COMMAND_AFFECTED_SOP_INSTANCE_UID":
                        shared_uid_for_op = pydicom_generate_uid()

                    # Find the accepted transfer syntax for this DIMSE operation's PC ID
                    accepted_ts_for_op = None
                    pc_id_for_op = dimse_op.presentation_context_id
                    for ac_result in negotiated_ac_results_dicts:
                        if ac_result["id"] == pc_id_for_op and ac_result["result"] == 0: # Accepted
                            accepted_ts_for_op = ac_result["transfer_syntax"]
                            break
                    
                    if accepted_ts_for_op is None:
                        # This should ideally not happen if the PC ID in DIMSE op is valid and was accepted.
                        # Handle error or default, for now, raise an error or log.
                        # For robustness, could default to a common one like Explicit VR Little Endian,
                        # but it's better to ensure valid configuration.
                        print(f"Warning: Could not find accepted transfer syntax for PC ID {pc_id_for_op} in link {link.link_id}. Skipping DIMSE op: {dimse_op.operation_name}")
                        continue # Skip this DIMSE operation

                    p_data_pdus_for_one_op = generate_p_data_tf_pdus_for_dimse_operation(
                        operation=dimse_op,
                        scu_dicom_properties=resolved_scu_props,
                        scp_dicom_properties=resolved_scp_props,
                        accepted_transfer_syntax_uid=accepted_ts_for_op, # Pass the TS UID
                        shared_affected_sop_instance_uid=shared_uid_for_op
                    )
                    all_p_data_pdus_bytes.extend(p_data_pdus_for_one_op)

                # 6. Generate TCP session packets for this link
                # TODO: Handle client/server ISN from Link model if specified
                link_packets = generate_dicom_session_packet_list(
                    network_params=network_params_dict,
                    associate_rq_pdu_bytes=assoc_rq_pdu_bytes,
                    associate_ac_pdu_bytes=assoc_ac_pdu_bytes,
                    p_data_tf_pdu_list=all_p_data_pdus_bytes
                    # client_isn, server_isn can be added if configurable per link
                )
                all_packets.extend(link_packets)

            except AssetNotFoundError as anfe: # Catch AssetNotFoundError specifically
                print(f"Critical Error processing Link '{link.link_id}': {anfe}")
                raise anfe # Re-raise to halt processing and propagate to main.py
            except DicomSceneProcessorError as e:
                # Log or handle link processing errors, e.g., skip link, collect errors
                print(f"Error processing Link '{link.link_id}': {e}")
                # Optionally re-raise or collect errors to return to caller
                # For now, we'll print and continue to process other links for other DicomSceneProcessorError types.
            except Exception as e:
                # Catch any other unexpected errors during link processing
                print(f"Unexpected error processing Link '{link.link_id}': {e}")


        return all_packets
