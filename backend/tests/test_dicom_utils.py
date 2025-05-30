"""
Test suite for DICOM utility functions in `backend.protocols.dicom.utils`.

This module contains pytest-based tests to verify the correct creation and
serialization of various DICOM Protocol Data Units (PDUs) and DICOM datasets
using the utility functions. It covers:
- A-ASSOCIATE-RQ PDU creation.
- A-ASSOCIATE-AC PDU creation (both acceptance and rejection scenarios).
- DICOM Dataset object creation.
- P-DATA-TF PDU creation (for both DIMSE commands and data).

The tests ensure that the generated byte streams can be correctly decoded and
that the decoded PDU/Dataset objects contain the expected values and structures.
"""
import pytest
from io import BytesIO

from pydicom.dataset import Dataset
from pynetdicom.pdu import (
    A_ASSOCIATE_RQ,
    A_ASSOCIATE_AC,
    P_DATA_TF,
    PresentationDataValueItem,
    UserInformationItem
)
from pynetdicom.pdu_items import (
    ImplementationClassUIDSubItem,
    ImplementationVersionNameSubItem,
    MaximumLengthSubItem,
    PresentationContextItemRQ,
    PresentationContextItemAC
)
from pynetdicom.presentation import PresentationContext # Still needed for constructing PDUs in utils
from pydicom.uid import UID
from pydicom.filereader import dcmread # For decoding dataset from P-DATA-TF, changed from read_dataset

from backend.protocols.dicom.utils import (
    create_associate_rq_pdu,
    create_associate_ac_pdu,
    create_dicom_dataset,
    create_p_data_tf_pdu,
    DEFAULT_IMPLEMENTATION_CLASS_UID_STR,
    DEFAULT_IMPLEMENTATION_VERSION_NAME,
    DEFAULT_MAX_PDU_LENGTH
)

# --- Test Data ---
# These constants define common values used across multiple tests for DICOM communication.

CALLING_AE = "PYDICOMSCU"
"""Default Calling AE Title for tests."""

CALLED_AE = "ANY_SCP"
"""Default Called AE Title for tests."""

APP_CONTEXT_NAME = "1.2.840.10008.3.1.1.1"
"""Standard DICOM Application Context Name UID."""

ABSTRACT_SYNTAX_UID = "1.2.840.10008.5.1.4.1.1.2"
"""Example Abstract Syntax UID (CT Image Storage)."""

TRANSFER_SYNTAX_UIDS = [
    "1.2.840.10008.1.2.1",  # Explicit VR Little Endian
    "1.2.840.10008.1.2"    # Implicit VR Little Endian
]
"""List of example Transfer Syntax UIDs."""

PRESENTATION_CONTEXT_ID = 1
"""Default Presentation Context ID for tests."""

SAMPLE_PRESENTATION_CONTEXTS_RQ_INPUT = [
    {
        "id": PRESENTATION_CONTEXT_ID,
        "abstract_syntax": ABSTRACT_SYNTAX_UID,
        "transfer_syntaxes": TRANSFER_SYNTAX_UIDS
    }
]
"""Sample input for creating Presentation Contexts in an A-ASSOCIATE-RQ PDU."""

SAMPLE_PRESENTATION_CONTEXTS_AC_INPUT_ACCEPT = [
    {
        "id": PRESENTATION_CONTEXT_ID,
        "result": 0,  # Acceptance
        "transfer_syntax": TRANSFER_SYNTAX_UIDS[0]  # Choose Explicit VR LE
    }
]
"""Sample input for accepted Presentation Contexts in an A-ASSOCIATE-AC PDU."""

SAMPLE_PRESENTATION_CONTEXTS_AC_INPUT_REJECT = [
    {
        "id": PRESENTATION_CONTEXT_ID,
        "result": 3,  # Abstract syntax not supported
        # transfer_syntax is omitted or ignored for rejection as per DICOM standard
    }
]
"""Sample input for rejected Presentation Contexts in an A-ASSOCIATE-AC PDU."""

SAMPLE_DATASET_INPUT = {
    "PatientName": "Test^Patient",
    "PatientID": "123456",
    "SOPClassUID": ABSTRACT_SYNTAX_UID,      # Example, could be any valid UID
    "SOPInstanceUID": "1.2.3.4.5.6.7.8.9.0"  # Example
}
"""Sample input for creating a DICOM Dataset object."""


# --- Test Functions ---

def test_create_associate_rq_pdu():
    """
    Test the creation of an A-ASSOCIATE-RQ PDU.

    Verifies that:
    - The output is a non-empty byte string.
    - The decoded PDU contains the correct AE titles, application context name.
    - User Information items (Implementation Class UID, Version Name, Max PDU Length)
      are correctly set.
    - Presentation Contexts are correctly formed with the specified abstract syntax
      and transfer syntaxes.
    """
    output_bytes = create_associate_rq_pdu(
        calling_ae_title=CALLING_AE,
        called_ae_title=CALLED_AE,
        application_context_name=APP_CONTEXT_NAME,
        presentation_contexts_input=SAMPLE_PRESENTATION_CONTEXTS_RQ_INPUT,
        max_pdu_length=DEFAULT_MAX_PDU_LENGTH,
        our_implementation_class_uid_str=DEFAULT_IMPLEMENTATION_CLASS_UID_STR,
        our_implementation_version_name=DEFAULT_IMPLEMENTATION_VERSION_NAME
    )

    assert isinstance(output_bytes, bytes)
    assert len(output_bytes) > 0

    # Decode and verify
    # For pynetdicom, PDU classes can often be decoded from bytes directly
    # or via a class method like `from_primitive`.
    # Let's try instantiating and then decoding, similar to pydicom for consistency if it works.
    # pynetdicom PDUs are typically decoded using `PDU.decode(data: bytes)`
    assoc_rq = A_ASSOCIATE_RQ()
    assoc_rq.decode(output_bytes)

    assert assoc_rq.calling_ae_title == CALLING_AE  # AE titles are str after decode
    assert assoc_rq.called_ae_title == CALLED_AE    # AE titles are str after decode
    assert assoc_rq.application_context_name == UID(APP_CONTEXT_NAME)
    
    # User Information items
    # When decoded, the PDU object should have user_information populated directly
    assert assoc_rq.user_information is not None
    
    # Access UserInformationItem sub-items directly by their attributes on the decoded user_information object
    # as per dicom_best_practices_3.md (Sección II.B.1 y II.B.4)
    assert assoc_rq.user_information.implementation_class_uid == UID(DEFAULT_IMPLEMENTATION_CLASS_UID_STR)
    assert assoc_rq.user_information.implementation_version_name == DEFAULT_IMPLEMENTATION_VERSION_NAME
    assert assoc_rq.user_information.maximum_length == DEFAULT_MAX_PDU_LENGTH

    # When decoded, the PDU object should have presentation_context_definition_list populated
    assert len(assoc_rq.presentation_context) == 1
    pc_rq_item = assoc_rq.presentation_context[0]
    assert isinstance(pc_rq_item, PresentationContextItemRQ)
    assert pc_rq_item.context_id == PRESENTATION_CONTEXT_ID
    assert pc_rq_item.abstract_syntax == UID(ABSTRACT_SYNTAX_UID)
    assert len(pc_rq_item.transfer_syntax) == 2
    assert UID(TRANSFER_SYNTAX_UIDS[0]) in pc_rq_item.transfer_syntax
    assert UID(TRANSFER_SYNTAX_UIDS[1]) in pc_rq_item.transfer_syntax


def test_create_associate_ac_pdu_accept():
    """
    Test the creation of an A-ASSOCIATE-AC PDU with an accepted Presentation Context.

    Verifies that:
    - The output is a non-empty byte string.
    - The decoded PDU contains the correct AE titles and application context name.
    - User Information items (Responding Implementation Class UID, Version Name, Max PDU Length)
      are correctly set.
    - The Presentation Context is marked as accepted (result 0) and includes the
      negotiated transfer syntax.
    """
    output_bytes = create_associate_ac_pdu(
        calling_ae_title=CALLING_AE, # Responding to this SCU
        called_ae_title=CALLED_AE,   # This SCP's AE title
        application_context_name=APP_CONTEXT_NAME,
        presentation_contexts_results_input=SAMPLE_PRESENTATION_CONTEXTS_AC_INPUT_ACCEPT,
        responding_implementation_class_uid_str=DEFAULT_IMPLEMENTATION_CLASS_UID_STR,
        responding_implementation_version_name=DEFAULT_IMPLEMENTATION_VERSION_NAME
    )

    assert isinstance(output_bytes, bytes)
    assert len(output_bytes) > 0

    assoc_ac = A_ASSOCIATE_AC()
    assoc_ac.decode(output_bytes)

    assert assoc_ac.calling_ae_title == CALLING_AE # AE titles are str after decode
    assert assoc_ac.called_ae_title == CALLED_AE   # AE titles are str after decode
    assert assoc_ac.application_context_name == UID(APP_CONTEXT_NAME)

    # User Information items
    assert assoc_ac.user_information is not None
    # Access UserInformationItem sub-items directly
    assert assoc_ac.user_information.implementation_class_uid == UID(DEFAULT_IMPLEMENTATION_CLASS_UID_STR) # Responding UID
    assert assoc_ac.user_information.implementation_version_name == DEFAULT_IMPLEMENTATION_VERSION_NAME
    assert assoc_ac.user_information.maximum_length == DEFAULT_MAX_PDU_LENGTH # Assuming default is used for AC too

    assert len(assoc_ac.presentation_context) == 1
    pc_ac_item = assoc_ac.presentation_context[0]
    assert isinstance(pc_ac_item, PresentationContextItemAC)
    assert pc_ac_item.context_id == PRESENTATION_CONTEXT_ID
    assert pc_ac_item.result == 0 # Acceptance
    assert pc_ac_item.transfer_syntax == UID(TRANSFER_SYNTAX_UIDS[0]) # Accepted TS


def test_create_associate_ac_pdu_reject():
    """
    Test the creation of an A-ASSOCIATE-AC PDU with a rejected Presentation Context.

    Verifies that:
    - The decoded PDU's Presentation Context is marked as rejected
      (e.g., result 3 - abstract syntax not supported).
    - The transfer syntax for a rejected context is the default (Implicit VR Little Endian).
    """
    output_bytes = create_associate_ac_pdu(
        calling_ae_title=CALLING_AE,
        called_ae_title=CALLED_AE,
        application_context_name=APP_CONTEXT_NAME,
        presentation_contexts_results_input=SAMPLE_PRESENTATION_CONTEXTS_AC_INPUT_REJECT,
    )
    assoc_ac = A_ASSOCIATE_AC()
    assoc_ac.decode(output_bytes)

    assert len(assoc_ac.presentation_context) == 1
    pc_ac_item = assoc_ac.presentation_context[0]
    assert pc_ac_item.context_id == PRESENTATION_CONTEXT_ID
    assert pc_ac_item.result == 3 # Abstract syntax not supported
    # For rejection, transfer_syntaxes list should contain the default UID as per utils.py
    assert pc_ac_item.transfer_syntax == UID("1.2.840.10008.1.2")


def test_create_dicom_dataset():
    """
    Test the creation of a DICOM Dataset object from a dictionary.

    Verifies that:
    - The created object is an instance of `pydicom.dataset.Dataset`.
    - All specified DICOM tags (PatientName, PatientID, etc.) are present in the
      dataset with the correct values.
    - No `file_meta` information is added by default by this utility function.
    """
    ds = create_dicom_dataset(SAMPLE_DATASET_INPUT)

    assert isinstance(ds, Dataset)
    assert ds.PatientName == SAMPLE_DATASET_INPUT["PatientName"]
    assert ds.PatientID == SAMPLE_DATASET_INPUT["PatientID"]
    assert ds.SOPClassUID == SAMPLE_DATASET_INPUT["SOPClassUID"]
    assert ds.SOPInstanceUID == SAMPLE_DATASET_INPUT["SOPInstanceUID"]
    assert not hasattr(ds, 'file_meta') # No file meta by default from this function

def test_create_dicom_dataset_empty():
    """
    Test creating an empty DICOM Dataset.

    Verifies that:
    - Calling `create_dicom_dataset` with an empty dictionary results in an empty Dataset.
    - Calling `create_dicom_dataset` with `None` also results in an empty Dataset.
    """
    ds = create_dicom_dataset({})
    assert isinstance(ds, Dataset)
    assert len(ds) == 0

    ds_none = create_dicom_dataset(None)
    assert isinstance(ds_none, Dataset)
    assert len(ds_none) == 0


def test_create_p_data_tf_pdu_command():
    """
    Test the creation of a P-DATA-TF PDU for a DIMSE command.

    Verifies that:
    - The output is a non-empty byte string.
    - The decoded PDU contains one Presentation Data Value (PDV) item.
    - The PDV item has the correct Presentation Context ID.
    - The Message Control Header byte indicates a command (bit 0 = 1) and
      last fragment (bit 1 = 1).
    - The data within the PDV item, when decoded, matches the original command dataset.
    """
    # 1. Create a sample DIMSE command dataset
    command_ds = Dataset()
    command_ds.AffectedSOPClassUID = ABSTRACT_SYNTAX_UID
    command_ds.CommandField = 0x0001  # C-STORE-RQ
    command_ds.MessageID = 1
    command_ds.Priority = 0x0002 # LOW
    command_ds.CommandDataSetType = 0x0101 # Has dataset
    command_ds.AffectedSOPInstanceUID = SAMPLE_DATASET_INPUT["SOPInstanceUID"]
    # For commands, file_meta is not part of the PDU encoding
    # but ensure it's not accidentally added by the create_dicom_dataset if used
    command_ds.is_implicit_VR = True
    command_ds.is_little_endian = True


    output_bytes = create_p_data_tf_pdu(
        dimse_dataset=command_ds,
        presentation_context_id=PRESENTATION_CONTEXT_ID,
        is_command=True
    )

    assert isinstance(output_bytes, bytes)
    assert len(output_bytes) > 0

    p_data_tf = P_DATA_TF()
    p_data_tf.decode(output_bytes)

    # After decoding, P_DATA_TF object has presentation_data_value_items attribute
    assert hasattr(p_data_tf, 'presentation_data_value_items')
    assert p_data_tf.presentation_data_value_items is not None
    assert len(p_data_tf.presentation_data_value_items) == 1
    
    pdv_item = p_data_tf.presentation_data_value_items[0]
    assert isinstance(pdv_item, PresentationDataValueItem)
    
    context_id_decoded = pdv_item.context_id
    data_with_header_decoded = pdv_item.data # .data attribute holds the [header_byte] + value_bytes
    
    assert context_id_decoded == PRESENTATION_CONTEXT_ID
    assert isinstance(data_with_header_decoded, bytes)
    
    # Extract Message Control Header and encoded dataset
    message_control_header_byte = data_with_header_decoded[0:1]
    assert isinstance(message_control_header_byte, bytes) # It's already bytes
    assert len(message_control_header_byte) == 1
    # Message Control Header: Bit 0 = 1 (Command), Bit 1 = 1 (Last Fragment) -> 0x03
    assert message_control_header_byte[0] == 0x03

    encoded_dataset_bytes_from_pdv = data_with_header_decoded[1:]
    assert isinstance(encoded_dataset_bytes_from_pdv, bytes)

    # Decode the dataset from PDV
    pdv_data_buffer = BytesIO(encoded_dataset_bytes_from_pdv)
    # Use dcmread; is_implicit_VR and is_little_endian are not direct args for dcmread.
    # These properties should be inherent in the byte stream if written correctly by pydicom.filewriter.write_dataset
    # using a DicomFileLike object configured with these settings.
    decoded_command_ds = dcmread(pdv_data_buffer, force=True)
    
    assert decoded_command_ds.AffectedSOPClassUID == command_ds.AffectedSOPClassUID
    assert decoded_command_ds.CommandField == command_ds.CommandField
    assert decoded_command_ds.MessageID == command_ds.MessageID
    assert decoded_command_ds.AffectedSOPInstanceUID == command_ds.AffectedSOPInstanceUID


def test_create_p_data_tf_pdu_data():
    """
    Test the creation of a P-DATA-TF PDU for a DIMSE dataset (not a command).

    Verifies that:
    - The output is a non-empty byte string.
    - The decoded PDU contains one Presentation Data Value (PDV) item.
    - The PDV item has the correct Presentation Context ID.
    - The Message Control Header byte indicates data (bit 0 = 0) and
      last fragment (bit 1 = 1).
    - The data within the PDV item, when decoded, matches the original data dataset.
    """
    # 1. Create a sample data dataset (e.g., the one from SAMPLE_DATASET_INPUT)
    data_ds = create_dicom_dataset(SAMPLE_DATASET_INPUT)
    # Ensure it's set for Implicit VR Little Endian for encoding
    data_ds.is_implicit_VR = True
    data_ds.is_little_endian = True


    output_bytes = create_p_data_tf_pdu(
        dimse_dataset=data_ds,
        presentation_context_id=PRESENTATION_CONTEXT_ID,
        is_command=False # This is data
    )

    assert isinstance(output_bytes, bytes)
    assert len(output_bytes) > 0

    p_data_tf = P_DATA_TF()
    p_data_tf.decode(output_bytes)

    assert hasattr(p_data_tf, 'presentation_data_value_items')
    assert p_data_tf.presentation_data_value_items is not None
    assert len(p_data_tf.presentation_data_value_items) == 1

    pdv_item_data = p_data_tf.presentation_data_value_items[0]
    assert isinstance(pdv_item_data, PresentationDataValueItem)

    context_id_decoded_data = pdv_item_data.context_id
    data_with_header_decoded_data = pdv_item_data.data

    assert context_id_decoded_data == PRESENTATION_CONTEXT_ID
    assert isinstance(data_with_header_decoded_data, bytes)

    message_control_header_byte_data = data_with_header_decoded_data[0:1]
    assert isinstance(message_control_header_byte_data, bytes)
    assert len(message_control_header_byte_data) == 1
    # Message Control Header: Bit 0 = 0 (Data), Bit 1 = 1 (Last Fragment) -> 0x02
    assert message_control_header_byte_data[0] == 0x02
    
    encoded_data_ds_bytes_from_pdv = data_with_header_decoded_data[1:]
    assert isinstance(encoded_data_ds_bytes_from_pdv, bytes)

    # Decode the dataset from PDV
    pdv_data_buffer = BytesIO(encoded_data_ds_bytes_from_pdv)
    # Use dcmread; is_implicit_VR and is_little_endian are not direct args for dcmread.
    decoded_data_ds = dcmread(pdv_data_buffer, force=True)

    assert decoded_data_ds.PatientName == data_ds.PatientName
    assert decoded_data_ds.PatientID == data_ds.PatientID
    assert decoded_data_ds.SOPClassUID == data_ds.SOPClassUID
    assert decoded_data_ds.SOPInstanceUID == data_ds.SOPInstanceUID
