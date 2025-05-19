from typing import List, Dict, Any, Tuple
from pynetdicom.pdu import (
    A_ASSOCIATE_RQ,
    A_ASSOCIATE_AC,
    P_DATA_TF,
    # PresentationDataValueItem, # No longer directly used for P_DATA_TF construction with primitives
    # UserInformationItem # No longer directly used for A_ASSOCIATE primitive construction
)
from pynetdicom.pdu_primitives import (
    A_ASSOCIATE, 
    P_DATA, 
    MaximumLengthNotification,
    ImplementationClassUIDNotification,
    ImplementationVersionNameNotification,
    UserIdentityNegotiation # Added for user identity
) # Added primitive imports
from pynetdicom.pdu_items import ( # These might not be needed if we use Notification Primitives exclusively for construction
    ImplementationClassUIDSubItem, # Keeping for now, in case they are used elsewhere or for type hinting
    ImplementationVersionNameSubItem,
    MaximumLengthSubItem
)
from pynetdicom.presentation import PresentationContext
from pydicom.dataset import Dataset
from scapy.all import Ether, IP, TCP # Added Scapy imports
from pydicom.uid import UID, generate_uid # For default ImplementationClassUID
from io import BytesIO
import pydicom.filewriter # Replaced dcmwrite with filewriter
from pydicom.filebase import DicomFileLike # For writing dataset to BytesIO

# Default values that might be commonly used
DEFAULT_MAX_PDU_LENGTH = 16384
# Generate a default UID for implementation class, can be customized or passed as arg
DEFAULT_IMPLEMENTATION_CLASS_UID_STR = generate_uid(prefix="1.2.826.0.1.3680043.9.3811.1.99.") 
DEFAULT_IMPLEMENTATION_VERSION_NAME = "PYDICOM_GEN_V1"

def create_associate_rq_pdu(
    calling_ae_title: str,
    called_ae_title: str,
    application_context_name: str,
    presentation_contexts_input: List[Dict[str, Any]],
    max_pdu_length: int = DEFAULT_MAX_PDU_LENGTH,
    our_implementation_class_uid_str: str = DEFAULT_IMPLEMENTATION_CLASS_UID_STR,
    our_implementation_version_name: str = DEFAULT_IMPLEMENTATION_VERSION_NAME,
    protocol_version: int = 1, # Default to protocol version 1
    user_identity_input: Dict[str, Any] = None, # Added user_identity_input
    # Added other A_ASSOCIATE primitive fields as optional params with defaults if needed
    # For now, keeping it simple and assuming these are derived or fixed
    application_context_negotiation_role: str = "scu", # 'scu', 'scp', 'scu-scp'
    # Other primitive fields like 'mode', 'result_source', 'diagnostic' are not typically set by SCU for RQ
    # 'calling_presentation_address', 'called_presentation_address' are also options
    # 'maximum_operations_invoked', 'maximum_operations_performed'
    # 'implementation_information', 'instance_creator_uid'
    # 'sop_class_extended_negotiation_sub_items', 'user_identity'
) -> bytes:
    """
    Creates an A-ASSOCIATE-RQ PDU byte string using pynetdicom's A_ASSOCIATE primitive.

    Args:
        calling_ae_title: The Calling AE Title (max 16 chars, ASCII).
        called_ae_title: The Called AE Title (max 16 chars, ASCII).
        application_context_name: The Application Context Name UID string.
        presentation_contexts_input: A list of presentation context definitions.
            Each definition is a dict with:
            - "id": int (e.g., 1, 3, 5, ...)
            - "abstract_syntax": str (UID string)
            - "transfer_syntaxes": List[str] (list of UID strings)
        max_pdu_length: Maximum PDU length our SCU can receive.
        our_implementation_class_uid_str: Our implementation class UID string.
        our_implementation_version_name: Our implementation version name string.

    Returns:
        The A-ASSOCIATE-RQ PDU as bytes.
    """

    # Construct PresentationContext objects from the input
    presentation_contexts = []
    for pc_input in presentation_contexts_input:
        context_item = PresentationContext()
        context_item.context_id = pc_input['id']
        context_item.abstract_syntax = UID(pc_input['abstract_syntax'])
        context_item.transfer_syntax = [UID(ts) for ts in pc_input['transfer_syntaxes']] # Using singular for RQ primitive list
        presentation_contexts.append(context_item)

    # User Information Items (using Notification Primitives)
    user_information_primitives = []
    
    # Maximum PDU Length
    max_len_prim = MaximumLengthNotification()
    max_len_prim.maximum_length_received = max_pdu_length
    user_information_primitives.append(max_len_prim)

    # Implementation Class UID
    impl_uid_prim = ImplementationClassUIDNotification()
    impl_uid_prim.implementation_class_uid = UID(our_implementation_class_uid_str)
    user_information_primitives.append(impl_uid_prim)

    # Implementation Version Name
    impl_ver_prim = ImplementationVersionNameNotification()
    impl_ver_prim.implementation_version_name = our_implementation_version_name
    user_information_primitives.append(impl_ver_prim)

    # User Identity (if provided)
    if user_identity_input:
        user_identity_prim = UserIdentityNegotiation()
        user_identity_prim.user_identity_type = user_identity_input.get("type", 1) # Default to 1 (Username)
        user_identity_prim.positive_response_requested = user_identity_input.get("positive_response_requested", False)
        user_identity_prim.primary_field = user_identity_input.get("primary_field", b"") # Expect bytes
        if "secondary_field" in user_identity_input:
            user_identity_prim.secondary_field = user_identity_input.get("secondary_field", b"") # Expect bytes
        user_information_primitives.append(user_identity_prim)

    # Create and populate the A_ASSOCIATE primitive
    assoc_primitive_rq = A_ASSOCIATE()
    assoc_primitive_rq.application_context_name = UID(application_context_name)
    assoc_primitive_rq.calling_ae_title = calling_ae_title # pynetdicom expects str, handles encoding
    assoc_primitive_rq.called_ae_title = called_ae_title   # pynetdicom expects str, handles encoding
    assoc_primitive_rq.user_information = user_information_primitives
    assoc_primitive_rq.presentation_context_definition_list = presentation_contexts
    # assoc_primitive_rq.protocol_version = protocol_version # protocol_version is part of PDU, not primitive
    # Other primitive fields can be set here if needed, e.g.:
    # assoc_primitive_rq.mode = application_context_negotiation_role # 'scu', 'scp', or 'scu-scp' (defaults to 'scu')

    # Create the A_ASSOCIATE_RQ PDU from the primitive
    # The PDU's protocol_version is set on the PDU object itself, not the primitive.
    assoc_rq_pdu = A_ASSOCIATE_RQ(primitive=assoc_primitive_rq)
    assoc_rq_pdu.protocol_version = protocol_version # Set protocol version on PDU
    
    return assoc_rq_pdu.encode()


def create_associate_ac_pdu(
    calling_ae_title: str,
    called_ae_title: str,
    application_context_name: str,
    presentation_contexts_results_input: List[Dict[str, Any]],
    max_pdu_length: int = DEFAULT_MAX_PDU_LENGTH,
    responding_implementation_class_uid_str: str = DEFAULT_IMPLEMENTATION_CLASS_UID_STR,
    responding_implementation_version_name: str = DEFAULT_IMPLEMENTATION_VERSION_NAME,
    protocol_version: int = 1, # Default to protocol version 1
    result: int = 0, # 0: 'Result.ACCEPTANCE'
    result_source: int = 2, # 2: 'ResultSource.SERVICE_PROVIDER_ACSE'
    # Default diagnostic to 1 (no-reason-given) if source is ACSE provider, as 0 is invalid.
    # See pynetdicom.pdu_primitives.DIAGNOSTIC_VALUES
    diagnostic: int = 1 # 1: 'Diagnostic.NO_REASON_GIVEN' 
    # Other primitive fields like 'mode' (defaults to 'scp' for AC)
) -> bytes:
    """
    Creates an A-ASSOCIATE-AC PDU byte string using pynetdicom's A_ASSOCIATE primitive.

    Args:
        calling_ae_title: The Calling AE Title (from A-ASSOCIATE-RQ).
        called_ae_title: The Called AE Title (this system's AE Title as responder).
        application_context_name: The Application Context Name UID string (from A-ASSOCIATE-RQ).
        presentation_contexts_results_input: A list of presentation context results.
            Each dict should contain:
            - "id": int (matching an ID from the RQ)
            - "result": int (0: acceptance, 1: user-rejection, 2: no-reason (provider), 
                             3: abstract-syntax-not-supported (provider), 
                             4: transfer-syntaxes-not-supported (provider))
            - "transfer_syntax": str (UID string of the chosen transfer syntax if 'result' is 0,
                                      otherwise this can be omitted or will be ignored)
        max_pdu_length: Maximum PDU length this SCP can receive.
        responding_implementation_class_uid_str: This SCP's implementation class UID string.
        responding_implementation_version_name: This SCP's implementation version name string.

    Returns:
        The A-ASSOCIATE-AC PDU as bytes.
    """

    presentation_contexts_results = []
    for pc_result_input in presentation_contexts_results_input:
        context_item = PresentationContext() # pynetdicom uses the same class for RQ and AC contexts
        context_item.context_id = pc_result_input['id']
        context_item.result = pc_result_input['result']
        # Only set transfer_syntax if the context is accepted
        if pc_result_input['result'] == 0: # 0 for Acceptance
            context_item.transfer_syntax = [UID(pc_result_input['transfer_syntax'])] # Note: transfer_syntax (singular) is a list for AC primitive
        else:
            # For rejection, transfer_syntax is not meaningful but pynetdicom's
            # PresentationContextItemAC.from_primitive expects a non-empty list
            # for primitive.transfer_syntax to avoid IndexError.
            # Use a default UID, e.g., Implicit VR Little Endian.
            context_item.transfer_syntax = [UID("1.2.840.10008.1.2")] # Implicit VR Little Endian
        presentation_contexts_results.append(context_item)

    # User Information Items (using Notification Primitives)
    user_information_primitives = []

    # Maximum PDU Length
    max_len_prim = MaximumLengthNotification()
    max_len_prim.maximum_length_received = max_pdu_length
    user_information_primitives.append(max_len_prim)

    # Implementation Class UID
    impl_uid_prim = ImplementationClassUIDNotification()
    impl_uid_prim.implementation_class_uid = UID(responding_implementation_class_uid_str)
    user_information_primitives.append(impl_uid_prim)

    # Implementation Version Name
    impl_ver_prim = ImplementationVersionNameNotification()
    impl_ver_prim.implementation_version_name = responding_implementation_version_name
    user_information_primitives.append(impl_ver_prim)

    # Create and populate the A_ASSOCIATE primitive for AC
    assoc_primitive_ac = A_ASSOCIATE()
    assoc_primitive_ac.application_context_name = UID(application_context_name)
    # For AC, calling/called might be swapped or based on original RQ.
    # The primitive expects the AE titles as they will appear in the AC PDU.
    # Typically, the AC's "Calling AE Title" is the original RQ's "Called AE Title" (i.e., us, the SCP)
    # and the AC's "Called AE Title" is the original RQ's "Calling AE Title" (i.e., the remote SCU).
    # However, the PDU fields are named `calling_ae_title` and `called_ae_title` consistently.
    # The arguments to this function `calling_ae_title` and `called_ae_title` should be
    # the values as they appeared in the RQ.
    # The AC PDU will have:
    #   - its `called_ae_title` set to the RQ's `calling_ae_title`
    #   - its `calling_ae_title` set to the RQ's `called_ae_title`
    # The primitive should be populated with these "final" values for the AC PDU.
    # The current PDU direct assignment was:
    #   assoc_ac_pdu.calling_ae_title = calling_ae_title.encode('ascii') # This is RQ's calling AE
    #   assoc_ac_pdu.called_ae_title = called_ae_title.encode('ascii')   # This is RQ's called AE (us)
    # This seems to imply the primitive should also take them in this order.
    # Let's assume the function parameters `calling_ae_title` and `called_ae_title` are
    # the values that should go into the AC PDU's respective fields.
    assoc_primitive_ac.calling_ae_title = calling_ae_title # pynetdicom expects str
    assoc_primitive_ac.called_ae_title = called_ae_title   # pynetdicom expects str
    
    assoc_primitive_ac.user_information = user_information_primitives
    assoc_primitive_ac.presentation_context_definition_results_list = presentation_contexts_results
    
    # Set result for the association
    assoc_primitive_ac.result = result 
    assoc_primitive_ac.result_source = result_source
    if result_source == 2: # SERVICE_PROVIDER_ACSE
        assoc_primitive_ac.diagnostic = diagnostic
    # assoc_primitive_ac.mode = 'scp' # Default for AC

    # Create the A_ASSOCIATE_AC PDU from the primitive
    assoc_ac_pdu = A_ASSOCIATE_AC(primitive=assoc_primitive_ac)
    assoc_ac_pdu.protocol_version = protocol_version # Set protocol version on PDU

    return assoc_ac_pdu.encode()


def create_dicom_dataset(data_set_input: Dict[str, Any]) -> Dataset:
    """
    Creates a pydicom Dataset object from a dictionary of DICOM elements.

    Args:
        data_set_input: A dictionary where keys are DICOM keywords (e.g., "PatientName")
                        and values are the corresponding element values.
                        Can be None or empty, in which case an empty Dataset is returned.

    Returns:
        A pydicom.dataset.Dataset object populated with the provided elements.
    """
    ds = Dataset()
    if data_set_input:
        for key, value in data_set_input.items():
            # setattr allows dynamic setting of attributes by string name.
            # pydicom's Dataset class handles keyword-to-tag mapping and VR assignment
            # for known tags. For unknown tags, it might require explicit VR.
            # For this project's scope, we assume known tags from the JSON definition.
            setattr(ds, key, value)
    return ds


def create_p_data_tf_pdu(
    dimse_dataset: Dataset, 
    presentation_context_id: int, 
    is_command: bool = True
) -> bytes:
    """
    Encapsulates a DICOM DIMSE dataset into a P-DATA-TF PDU.

    Args:
        dimse_dataset: The pydicom.Dataset object representing the DIMSE message
                       (e.g., a C-STORE-RQ dataset).
        presentation_context_id: The integer ID of the presentation context for this data.
        is_command: True if the dimse_dataset is a DIMSE command, False if it's data.
                    This determines the Message Control Header byte. 
                    Defaults to True.

    Returns:
        A byte string representing the encoded P-DATA-TF PDU.
    """
    # 1. Encode the DIMSE dataset to bytes.
    #    For network transfer, DICOM datasets within P-DATA-TF PDUs are typically
    #    encoded using Implicit VR Little Endian, unless a different transfer syntax
    #    was negotiated. This function uses Implicit VR Little Endian.
    #    The caller should ensure dimse_dataset.is_implicit_VR and dimse_dataset.is_little_endian are set.
    
    buffer = BytesIO()
    fp = DicomFileLike(buffer)
    # Ensure dimse_dataset has these properties set, or set defaults
    fp.is_implicit_VR = getattr(dimse_dataset, 'is_implicit_VR', True)
    fp.is_little_endian = getattr(dimse_dataset, 'is_little_endian', True)
    
    pydicom.filewriter.write_dataset(fp, dimse_dataset)
    encoded_dataset_bytes = buffer.getvalue()

    # 2. Determine Message Control Header byte:
    # Bit 0: 1 for Command, 0 for Data
    # Bit 1: 1 for Last fragment of the message, 0 for Not last fragment
    # Assuming a single PDV carries the entire message, so it's always the last fragment.
    if is_command:
        message_control_header_byte = 0x03  # Command, Last fragment (0b11)
    else:
        message_control_header_byte = 0x02  # Data, Last fragment (0b10)
        
    # 3. Construct the presentation data value element data
    # This is: Message Control Header (1 byte) + Value Data (encoded dataset)
    pdv_data_with_header = message_control_header_byte.to_bytes(1, 'big') + encoded_dataset_bytes

    # 4. Create and populate the P_DATA primitive
    p_data_primitive = P_DATA()
    # The presentation_data_value_list is a list of [context_id, data_with_header] lists
    p_data_primitive.presentation_data_value_list = [[presentation_context_id, pdv_data_with_header]]

    # 5. Create the P_DATA_TF PDU from the primitive
    # The P_DATA_TF PDU will internally create PresentationDataValueItem(s) from the primitive's list.
    p_data_tf_pdu = P_DATA_TF(primitive=p_data_primitive)
    # The pdu_length will be calculated automatically by pynetdicom upon encoding.

    # 6. Encode the P_DATA_TF PDU to bytes.
    return p_data_tf_pdu.encode()


def create_network_layers(
    source_mac: str,
    destination_mac: str,
    source_ip: str,
    destination_ip: str,
    source_port: int,
    destination_port: int
) -> Tuple[Ether, IP, TCP]:
    """
    Creates and returns Scapy layers for Ethernet, IP, and TCP
    based on the provided connection details.

    TCP sequence/acknowledgment numbers and specific flags (e.g., SYN, ACK, PSH)
    will be handled by the logic in Task 2.6, which is responsible for
    managing the TCP flow and encapsulating PDU data. This function
    focuses on constructing the basic header structures.
    """
    ether_layer = Ether(src=source_mac, dst=destination_mac)
    ip_layer = IP(src=source_ip, dst=destination_ip)
    # Initial TCP layer; seq, ack, and flags will be refined in Task 2.6
    tcp_layer = TCP(sport=source_port, dport=destination_port)

    return ether_layer, ip_layer, tcp_layer
