import pytest
from pathlib import Path
import uuid

from backend.protocols.dicom.models import (
    Scene,
    Asset,
    Node,
    Link,
    AssetDicomProperties,
    LinkDicomConfiguration,
    LinkConnectionDetails,
    DimseOperation,
    CommandSetItem,
    SopClassDefinition,
    PresentationContextItem,
)
from backend.protocols.dicom.scene_processor import DicomSceneProcessor
from pydicom import uid as pydicom_uid
from pynetdicom.sop_class import (
    Verification, # UID string
    PatientRootQueryRetrieveInformationModelFind,
    PatientRootQueryRetrieveInformationModelMove,
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelMove
)
from scapy.utils import PcapWriter, export_object # Changed wrpcap to PcapWriter
from io import BytesIO

# Commonly used SOP Class UIDs
CT_IMAGE_STORAGE_UID = pydicom_uid.CTImageStorage
MR_IMAGE_STORAGE_UID = pydicom_uid.MRImageStorage
US_MULTIFRAME_IMAGE_STORAGE_UID = pydicom_uid.UltrasoundMultiFrameImageStorage # Or pydicom_uid.USImageStorage
RT_PLAN_STORAGE_UID = pydicom_uid.RTPlanStorage
RT_IMAGE_STORAGE_UID = pydicom_uid.RTImageStorage
SECONDARY_CAPTURE_IMAGE_STORAGE_UID = pydicom_uid.SecondaryCaptureImageStorage
VERIFICATION_SOP_CLASS_UID = Verification # This is already the UID string from pynetdicom.sop_class
PATIENT_ROOT_FIND_UID = PatientRootQueryRetrieveInformationModelFind
PATIENT_ROOT_MOVE_UID = PatientRootQueryRetrieveInformationModelMove
STUDY_ROOT_FIND_UID = StudyRootQueryRetrieveInformationModelFind
STUDY_ROOT_MOVE_UID = StudyRootQueryRetrieveInformationModelMove

# Commonly used Transfer Syntax UIDs
EXPLICIT_VR_LITTLE_ENDIAN_UID = pydicom_uid.ExplicitVRLittleEndian
IMPLICIT_VR_LITTLE_ENDIAN_UID = pydicom_uid.ImplicitVRLittleEndian


def create_c_store_dimse_sequence(
    base_name: str,
    pc_id: int,
    sop_class_uid: str,
    num_images: int,
    include_vendor_info_on_image_index: int = 0
) -> list[DimseOperation]:
    """Helper to create a sequence of C-STORE-RQ operations for a study/series."""
    operations = []
    for i in range(num_images):
        dataset_rules = {
            "SOPClassUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_CLASS_UID",
            "SOPInstanceUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_INSTANCE_UID",
            "PatientName": "AUTO_GENERATE_SAMPLE_PATIENT_NAME",
            "PatientID": f"PATID-{base_name.upper()}-{str(uuid.uuid4())[:4]}",
            "StudyInstanceUID": "AUTO_GENERATE_UID_STUDY",
            "SeriesInstanceUID": "AUTO_GENERATE_UID_SERIES",
            "InstanceNumber": i + 1,
            "Modality": sop_class_uid.split('.')[-1][:2], # Basic modality from SOP Class
        }
        if i == include_vendor_info_on_image_index:
            dataset_rules.update({
                "Manufacturer": "AUTO_FROM_ASSET_SCU_MANUFACTURER",
                "ManufacturerModelName": "AUTO_FROM_ASSET_SCU_MODEL_NAME",
                "SoftwareVersions": "AUTO_FROM_ASSET_SCU_SOFTWARE_VERSIONS",
                "DeviceSerialNumber": "AUTO_FROM_ASSET_SCU_DEVICE_SERIAL_NUMBER",
            })
        
        operations.append(
            DimseOperation(
                operation_name=f"{base_name} Store Image {i+1}",
                message_type="C-STORE-RQ",
                presentation_context_id=pc_id,
                command_set=CommandSetItem(
                    MessageID=i + 1, # MessageID should be unique per association typically
                    AffectedSOPClassUID=sop_class_uid,
                    AffectedSOPInstanceUID="AUTO_GENERATE_UID_INSTANCE",
                    Priority=0, # MEDIUM
                ),
                dataset_content_rules=dataset_rules,
            )
        )
    return operations


def test_generate_complex_multi_department_workflow():
    """
    Tests generation of a complex DICOM scene involving multiple departments,
    various modalities, and a central PACS, with specific vendor information exchange.
    """
    scene_id = f"COMPLEX_SCENE_{str(uuid.uuid4())[:8]}"

    # --- Define Assets ---
    assets = [
        Asset(
            asset_id="CT_SCANNER_GE_APEX",
            name="GE Revolution Apex CT Scanner",
            asset_template_id_ref="TEMPLATE_GENERIC_CT_V1",
            nodes=[Node(node_id="NIC1", ip_address="192.168.1.10", mac_address="00:00:00:AA:BB:10")],
            dicom_properties=AssetDicomProperties(
                ae_title="GE_APEX_CT",
                manufacturer="GE HealthCare",
                model_name="Revolution Apex",
                software_versions=["CTSys v1.0", "ReconApp v2.1"],
                device_serial_number="GEAPEX001",
                implementation_class_uid=pydicom_uid.generate_uid(prefix=None),
                implementation_version_name="ge_apex_ct_v1",
                supported_sop_classes=[
                    SopClassDefinition(sop_class_uid=CT_IMAGE_STORAGE_UID, role="SCU", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID, IMPLICIT_VR_LITTLE_ENDIAN_UID]),
                    SopClassDefinition(sop_class_uid=VERIFICATION_SOP_CLASS_UID, role="BOTH", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                    SopClassDefinition(sop_class_uid=SECONDARY_CAPTURE_IMAGE_STORAGE_UID, role="SCP", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]) # For Link 6
                ]
            ),
        ),
        Asset(
            asset_id="MRI_SCANNER_SIEMENS_VIDA",
            name="Siemens MAGNETOM Vida MRI",
            # No specific MRI template, adapt CT or define fully
            nodes=[Node(node_id="NIC1", ip_address="192.168.1.20", mac_address="00:00:00:AA:BB:20")],
            dicom_properties=AssetDicomProperties(
                ae_title="SIEMENS_VIDA_MR",
                manufacturer="Siemens Healthineers",
                    model_name="MAGNETOM Vida",
                    software_versions=["MRSys v3.5", "SeqLib v8.2"],
                    device_serial_number="SMVIDA002",
                    implementation_class_uid=pydicom_uid.generate_uid(prefix=None),
                    implementation_version_name="SIEMENS_VIDA_V1",
                    supported_sop_classes=[
                        SopClassDefinition(sop_class_uid=MR_IMAGE_STORAGE_UID, role="SCU", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                    SopClassDefinition(sop_class_uid=VERIFICATION_SOP_CLASS_UID, role="BOTH", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                ]
            ),
        ),
        Asset(
            asset_id="CT_SCANNER_PHILIPS_INCISIVE",
            name="Philips Incisive CT 7500",
                asset_template_id_ref="TEMPLATE_GENERIC_CT_V1",
                nodes=[Node(node_id="NIC1", ip_address="192.168.1.30", mac_address="00:00:00:AA:BB:30")],
                dicom_properties=AssetDicomProperties(
                    ae_title="PHILIPS_INC_CT",
                    manufacturer="Philips Healthcare",
                    model_name="Incisive CT 7500",
                software_versions=["CTHost v4.0", "ScanApp v1.8"],
                device_serial_number="PHINC003",
                implementation_class_uid=pydicom_uid.generate_uid(prefix=None),
                implementation_version_name="PHILIPS_INC_V1",
                supported_sop_classes=[
                    SopClassDefinition(sop_class_uid=CT_IMAGE_STORAGE_UID, role="SCU", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                    SopClassDefinition(sop_class_uid=VERIFICATION_SOP_CLASS_UID, role="BOTH", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                ]
            ),
        ),
        Asset(
            asset_id="ULTRASOUND_GE_LOGIQ_E10",
            name="GE LOGIQ E10 Ultrasound",
            nodes=[Node(node_id="NIC1", ip_address="192.168.1.40", mac_address="00:00:00:AA:BB:40")],
            dicom_properties=AssetDicomProperties(
                ae_title="GE_LOGIQ_US",
                manufacturer="GE HealthCare",
                model_name="LOGIQ E10",
                software_versions=["USOS v2.2", "ProbeLib v5.1"],
                device_serial_number="GELOGIQ004",
                implementation_class_uid=pydicom_uid.generate_uid(prefix=None),
                implementation_version_name="ge_logiq_us_v1",
                supported_sop_classes=[
                    SopClassDefinition(sop_class_uid=US_MULTIFRAME_IMAGE_STORAGE_UID, role="SCU", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                    SopClassDefinition(sop_class_uid=VERIFICATION_SOP_CLASS_UID, role="BOTH", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                ]
            ),
        ),
        Asset(
            asset_id="LINAC_VARIAN_TRUEBEAM",
            name="Varian TrueBeam Linac",
            nodes=[Node(node_id="NIC1", ip_address="192.168.1.50", mac_address="00:00:00:AA:BB:50")],
            dicom_properties=AssetDicomProperties(
                ae_title="VARIAN_TB_RT",
                manufacturer="Varian (Siemens Healthineers)", # From CSV
                    model_name="TrueBeam",
                    software_versions=["TBSys v6.0", "PlanDelivery v3.3"],
                    device_serial_number="VARTB005",
                    implementation_class_uid=pydicom_uid.generate_uid(prefix=None),
                    implementation_version_name="VARIAN_TB_V1",
                    supported_sop_classes=[
                        SopClassDefinition(sop_class_uid=RT_PLAN_STORAGE_UID, role="SCU", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                    SopClassDefinition(sop_class_uid=RT_IMAGE_STORAGE_UID, role="SCU", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                    SopClassDefinition(sop_class_uid=VERIFICATION_SOP_CLASS_UID, role="BOTH", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                ]
            ),
        ),
        Asset(
            asset_id="PACS_SECTRA",
            name="Sectra PACS Server",
            asset_template_id_ref="TEMPLATE_GENERIC_PACS_V1", # Provides base SCP capabilities
            nodes=[Node(node_id="NIC1", ip_address="192.168.1.100", mac_address="00:00:00:AA:BB:FF", dicom_port=11112)],
            dicom_properties=AssetDicomProperties(
                ae_title="SECTRA_PACS",
                manufacturer="Sectra",
                model_name="Sectra PACS",
                software_versions=["PACS Core v7.1", "DBInterface v3.0"],
                device_serial_number="SECPACS001",
                implementation_class_uid=pydicom_uid.generate_uid(prefix=None),
                implementation_version_name="sectra_pacs_v1",
                # Template provides SCP for CT, MR, etc. Add more if needed.
                # For Link 6, PACS acts as SCU for Verification and SC-Store
                supported_sop_classes=[ # This will override template's list
                    SopClassDefinition(sop_class_uid=CT_IMAGE_STORAGE_UID, role="SCP", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID, IMPLICIT_VR_LITTLE_ENDIAN_UID]),
                    SopClassDefinition(sop_class_uid=MR_IMAGE_STORAGE_UID, role="SCP", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID, IMPLICIT_VR_LITTLE_ENDIAN_UID]),
                    SopClassDefinition(sop_class_uid=US_MULTIFRAME_IMAGE_STORAGE_UID, role="SCP", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID, IMPLICIT_VR_LITTLE_ENDIAN_UID]),
                    SopClassDefinition(sop_class_uid=RT_PLAN_STORAGE_UID, role="SCP", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID, IMPLICIT_VR_LITTLE_ENDIAN_UID]),
                    SopClassDefinition(sop_class_uid=RT_IMAGE_STORAGE_UID, role="SCP", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID, IMPLICIT_VR_LITTLE_ENDIAN_UID]),
                    SopClassDefinition(sop_class_uid=SECONDARY_CAPTURE_IMAGE_STORAGE_UID, role="SCU", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]), # PACS as SCU
                    SopClassDefinition(sop_class_uid=VERIFICATION_SOP_CLASS_UID, role="BOTH", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                    SopClassDefinition(sop_class_uid=PATIENT_ROOT_FIND_UID, role="SCP", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                    SopClassDefinition(sop_class_uid=PATIENT_ROOT_MOVE_UID, role="SCP", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                    SopClassDefinition(sop_class_uid=STUDY_ROOT_FIND_UID, role="SCP", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                    SopClassDefinition(sop_class_uid=STUDY_ROOT_MOVE_UID, role="SCP", transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                ]
            ),
        ),
    ]

    # --- Define Links ---
    links = []

    # Link 1: CT1 (GE Apex) to PACS
    ct1_store_ops = create_c_store_dimse_sequence("CT1", pc_id=1, sop_class_uid=CT_IMAGE_STORAGE_UID, num_images=6)
    link1_dimse = [
        DimseOperation(operation_name="CT1 Echo", message_type="C-ECHO-RQ", presentation_context_id=3, command_set=CommandSetItem(MessageID=100)), # Assuming PC ID 3 for Verification
    ] + ct1_store_ops + [
        DimseOperation(
            operation_name="CT1 Patient Root Find", message_type="C-FIND-RQ", presentation_context_id=5, # Assuming PC ID 5 for Patient Root Find
            command_set=CommandSetItem(MessageID=101, AffectedSOPClassUID=PATIENT_ROOT_FIND_UID, Priority=0),
            dataset_content_rules={"PatientName": "AUTO_GENERATE_SAMPLE_PATIENT_NAME", "QueryRetrieveLevel": "PATIENT"} # Simplified
        ),
        DimseOperation(
            operation_name="CT1 Patient Root Move", message_type="C-MOVE-RQ", presentation_context_id=7, # Assuming PC ID 7 for Patient Root Move
            command_set=CommandSetItem(MessageID=102, AffectedSOPClassUID=PATIENT_ROOT_MOVE_UID, Priority=0),
            dataset_content_rules={"PatientID": "PATID-CT1*", "QueryRetrieveLevel": "PATIENT", "MoveDestination": "ANY_AET"} # Simplified
        ),
        DimseOperation(operation_name="CT1 Final Echo", message_type="C-ECHO-RQ", presentation_context_id=3, command_set=CommandSetItem(MessageID=103)),
    ] # Total 1+6+1+1+1 = 10 operations
    
    links.append(Link(
        link_id="LNK_CT1_PACS", name="CT1 (GE Apex) to PACS Storage",
        source_asset_id_ref="CT_SCANNER_GE_APEX", source_node_id_ref="NIC1",
        destination_asset_id_ref="PACS_SECTRA", destination_node_id_ref="NIC1",
        dicom_config=LinkDicomConfiguration(
            scu_asset_id_ref="CT_SCANNER_GE_APEX", scp_asset_id_ref="PACS_SECTRA",
            # Auto-negotiate presentation contexts by not providing explicit_presentation_contexts
            # OR define them explicitly if auto-negotiation is not robust enough for all SOP classes
            explicit_presentation_contexts=[
                 PresentationContextItem(id=1, abstract_syntax=CT_IMAGE_STORAGE_UID, transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                 PresentationContextItem(id=3, abstract_syntax=VERIFICATION_SOP_CLASS_UID, transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                 PresentationContextItem(id=5, abstract_syntax=PATIENT_ROOT_FIND_UID, transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                 PresentationContextItem(id=7, abstract_syntax=PATIENT_ROOT_MOVE_UID, transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
            ],
            dimse_sequence=link1_dimse
        )
    ))

    # Link 2: MRI (Siemens Vida) to PACS
    mri_store_ops = create_c_store_dimse_sequence("MRI1", pc_id=1, sop_class_uid=MR_IMAGE_STORAGE_UID, num_images=7)
    link2_dimse = [
        DimseOperation(operation_name="MRI1 Echo", message_type="C-ECHO-RQ", presentation_context_id=3, command_set=CommandSetItem(MessageID=200)),
    ] + mri_store_ops + [
        DimseOperation(
            operation_name="MRI1 Study Root Find", message_type="C-FIND-RQ", presentation_context_id=5, # Assuming PC ID 5 for Study Root Find
            command_set=CommandSetItem(MessageID=201, AffectedSOPClassUID=STUDY_ROOT_FIND_UID, Priority=1),
            dataset_content_rules={"PatientName": "AUTO_GENERATE_SAMPLE_PATIENT_NAME", "QueryRetrieveLevel": "STUDY"}
        ),
        DimseOperation(operation_name="MRI1 Final Echo", message_type="C-ECHO-RQ", presentation_context_id=3, command_set=CommandSetItem(MessageID=202)),
    ] # Total 1+7+1+1 = 10 operations

    links.append(Link(
        link_id="LNK_MRI_PACS", name="MRI (Siemens Vida) to PACS Storage",
        source_asset_id_ref="MRI_SCANNER_SIEMENS_VIDA", source_node_id_ref="NIC1",
        destination_asset_id_ref="PACS_SECTRA", destination_node_id_ref="NIC1",
        dicom_config=LinkDicomConfiguration(
            scu_asset_id_ref="MRI_SCANNER_SIEMENS_VIDA", scp_asset_id_ref="PACS_SECTRA",
            explicit_presentation_contexts=[
                 PresentationContextItem(id=1, abstract_syntax=MR_IMAGE_STORAGE_UID, transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                 PresentationContextItem(id=3, abstract_syntax=VERIFICATION_SOP_CLASS_UID, transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                 PresentationContextItem(id=5, abstract_syntax=STUDY_ROOT_FIND_UID, transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
            ],
            dimse_sequence=link2_dimse
        )
    ))

    # Link 3: CT2 (Philips Incisive) to PACS
    ct2_store_ops = create_c_store_dimse_sequence("CT2", pc_id=1, sop_class_uid=CT_IMAGE_STORAGE_UID, num_images=8)
    link3_dimse = [
        DimseOperation(operation_name="CT2 Echo", message_type="C-ECHO-RQ", presentation_context_id=3, command_set=CommandSetItem(MessageID=300)),
    ] + ct2_store_ops + [
        DimseOperation(operation_name="CT2 Final Echo", message_type="C-ECHO-RQ", presentation_context_id=3, command_set=CommandSetItem(MessageID=301)),
    ] # Total 1+8+1 = 10 operations

    links.append(Link(
        link_id="LNK_CT2_PACS", name="CT2 (Philips Incisive) to PACS Storage",
        source_asset_id_ref="CT_SCANNER_PHILIPS_INCISIVE", source_node_id_ref="NIC1",
        destination_asset_id_ref="PACS_SECTRA", destination_node_id_ref="NIC1",
        dicom_config=LinkDicomConfiguration(
            scu_asset_id_ref="CT_SCANNER_PHILIPS_INCISIVE", scp_asset_id_ref="PACS_SECTRA",
            explicit_presentation_contexts=[
                 PresentationContextItem(id=1, abstract_syntax=CT_IMAGE_STORAGE_UID, transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                 PresentationContextItem(id=3, abstract_syntax=VERIFICATION_SOP_CLASS_UID, transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
            ],
            dimse_sequence=link3_dimse
        )
    ))

    # Link 4: US (GE LOGIQ) to PACS
    us_store_ops = create_c_store_dimse_sequence("US1", pc_id=1, sop_class_uid=US_MULTIFRAME_IMAGE_STORAGE_UID, num_images=9)
    link4_dimse = [
        DimseOperation(operation_name="US1 Echo", message_type="C-ECHO-RQ", presentation_context_id=3, command_set=CommandSetItem(MessageID=400)),
    ] + us_store_ops + [
        DimseOperation(operation_name="US1 Final Echo", message_type="C-ECHO-RQ", presentation_context_id=3, command_set=CommandSetItem(MessageID=401)),
    ] # Total 1+9+1 = 11 operations

    links.append(Link(
        link_id="LNK_US_PACS", name="US (GE LOGIQ) to PACS Storage",
        source_asset_id_ref="ULTRASOUND_GE_LOGIQ_E10", source_node_id_ref="NIC1",
        destination_asset_id_ref="PACS_SECTRA", destination_node_id_ref="NIC1",
        dicom_config=LinkDicomConfiguration(
            scu_asset_id_ref="ULTRASOUND_GE_LOGIQ_E10", scp_asset_id_ref="PACS_SECTRA",
            explicit_presentation_contexts=[
                 PresentationContextItem(id=1, abstract_syntax=US_MULTIFRAME_IMAGE_STORAGE_UID, transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                 PresentationContextItem(id=3, abstract_syntax=VERIFICATION_SOP_CLASS_UID, transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
            ],
            dimse_sequence=link4_dimse
        )
    ))
    
    # Link 5: RT (Varian TrueBeam) to PACS
    rt_plan_store_op = create_c_store_dimse_sequence("RTPLAN1", pc_id=1, sop_class_uid=RT_PLAN_STORAGE_UID, num_images=1)[0]
    rt_image_store_ops = create_c_store_dimse_sequence("RTIMAGE1", pc_id=5, sop_class_uid=RT_IMAGE_STORAGE_UID, num_images=8) # 8 images
    
    # Adjust MessageIDs for RT link to be sequential within its own operations
    rt_plan_store_op.command_set.MessageID = 501
    for idx, op in enumerate(rt_image_store_ops):
        op.command_set.MessageID = 502 + idx

    link5_dimse = [
        DimseOperation(operation_name="RT Echo", message_type="C-ECHO-RQ", presentation_context_id=3, command_set=CommandSetItem(MessageID=500)),
        rt_plan_store_op, # 1 C-STORE for RT Plan
    ] + rt_image_store_ops + [ # 8 C-STORE for RT Images
        DimseOperation(operation_name="RT Final Echo", message_type="C-ECHO-RQ", presentation_context_id=3, command_set=CommandSetItem(MessageID=502 + len(rt_image_store_ops))),
    ] # Total 1+1+8+1 = 11 operations

    links.append(Link(
        link_id="LNK_RT_PACS", name="RT (Varian TrueBeam) to PACS Storage",
        source_asset_id_ref="LINAC_VARIAN_TRUEBEAM", source_node_id_ref="NIC1",
        destination_asset_id_ref="PACS_SECTRA", destination_node_id_ref="NIC1",
        dicom_config=LinkDicomConfiguration(
            scu_asset_id_ref="LINAC_VARIAN_TRUEBEAM", scp_asset_id_ref="PACS_SECTRA",
            explicit_presentation_contexts=[
                 PresentationContextItem(id=1, abstract_syntax=RT_PLAN_STORAGE_UID, transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                 PresentationContextItem(id=3, abstract_syntax=VERIFICATION_SOP_CLASS_UID, transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                 PresentationContextItem(id=5, abstract_syntax=RT_IMAGE_STORAGE_UID, transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
            ],
            dimse_sequence=link5_dimse
        )
    ))

    # Link 6: PACS (Sectra) to CT1 (GE Apex) - PACS as SCU
    # PACS sends 9 SC images to CT1, plus one C-ECHO
    pacs_sc_store_ops = create_c_store_dimse_sequence(
        "PACS_SC", pc_id=1, sop_class_uid=SECONDARY_CAPTURE_IMAGE_STORAGE_UID, num_images=9,
        include_vendor_info_on_image_index=0 # PACS (SCU) vendor info on first image
    )
    # Adjust MessageIDs for PACS SCU link
    for idx, op in enumerate(pacs_sc_store_ops):
        op.command_set.MessageID = 601 + idx

    link6_dimse = [
        DimseOperation(operation_name="PACS to CT1 Echo", message_type="C-ECHO-RQ", presentation_context_id=3, command_set=CommandSetItem(MessageID=600)),
    ] + pacs_sc_store_ops + [
        # DimseOperation(operation_name="PACS to CT1 Final Echo", message_type="C-ECHO-RQ", presentation_context_id=3, command_set=CommandSetItem(MessageID=601+len(pacs_sc_store_ops))),
    ] # Total 1+9 = 10 operations

    links.append(Link(
        link_id="LNK_PACS_CT1_SC", name="PACS (Sectra) to CT1 (GE Apex) SC Storage",
        source_asset_id_ref="PACS_SECTRA", source_node_id_ref="NIC1", # PACS is source
        destination_asset_id_ref="CT_SCANNER_GE_APEX", destination_node_id_ref="NIC1", # CT1 is dest
        dicom_config=LinkDicomConfiguration(
            scu_asset_id_ref="PACS_SECTRA", scp_asset_id_ref="CT_SCANNER_GE_APEX", # PACS is SCU
            explicit_presentation_contexts=[
                 PresentationContextItem(id=1, abstract_syntax=SECONDARY_CAPTURE_IMAGE_STORAGE_UID, transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
                 PresentationContextItem(id=3, abstract_syntax=VERIFICATION_SOP_CLASS_UID, transfer_syntaxes=[EXPLICIT_VR_LITTLE_ENDIAN_UID]),
            ],
            dimse_sequence=link6_dimse
        )
    ))

    # --- Create Scene ---
    scene_definition = Scene(
        scene_id=scene_id,
        name="Complex Multi-Department Imaging Workflow",
        description="Simulates various modalities sending data to PACS, and PACS performing some SCU operations.",
        assets=assets,
        links=links,
    )

    # --- Process Scene ---
    processor = DicomSceneProcessor(scene=scene_definition)
    # Assuming process_scene returns pcap_data directly or a structure containing it
    # Based on docs, it's likely process_scene_to_pcap_data or similar
    # For now, let's assume a method process_scene that might return a path or data
    # If the API is POST /v2/.../generate-pcap-from-scene, the processor likely has a method that takes the Scene model
    
    # Check if process_scene_to_pcap_data exists, otherwise adapt
    # For testing, we usually want bytes in memory, not a file written.
    # The API endpoint implies it returns a PCAP file. The processor might have a method for that.
    # Let's assume a method like `generate_pcap_data(scene: Scene) -> bytes` exists or can be adapted.
    # The documentation mentions: `http://localhost:8000/v2/protocols/dicom/generate-pcap-from-scene`
    # The `DicomSceneProcessor` is likely what backs this endpoint.
    # Let's assume `processor.process_scene_to_pcap_bytes(scene_definition)` or similar.
    # Looking at `backend/protocols/dicom/scene_processor.py` (if I could), I'd find the exact method.
    # For now, I'll use a plausible method name.
    
    pcap_data: bytes | None = None
    try:
        packet_list_result = processor.process_scene()
        print(f"DEBUG: packet_list_result type: {type(packet_list_result)}")
        if packet_list_result:
            print(f"DEBUG: packet_list_result length: {len(packet_list_result)}")
        else:
            print(f"DEBUG: packet_list_result is None or empty.")

        if packet_list_result and len(packet_list_result) > 0:
            bio = BytesIO()
            writer = None # Initialize writer to ensure it's defined for finally block
            try:
                writer = PcapWriter(bio, sync=True)  # Create PcapWriter with BytesIO
                writer.write(packet_list_result)     # Write packets
                writer.flush()                       # Ensure data is flushed to BytesIO's buffer
                pcap_data = bio.getvalue()           # Get the bytes BEFORE writer.close() closes bio
                
                print(f"DEBUG: PcapWriter with BytesIO successful. pcap_data length: {len(pcap_data) if pcap_data is not None else 'None'}")

            except Exception as e_pcapwriter:
                print(f"DEBUG: PcapWriter with BytesIO FAILED: {type(e_pcapwriter).__name__}: {e_pcapwriter}")
                pcap_data = None # Set to None on failure
            finally:
                if writer:
                    writer.close() # This will also close the underlying bio
                elif bio and not bio.closed: # Should not be reached if writer was created, but as a safeguard
                    bio.close()
        else:
            print(f"DEBUG: packet_list_result was initially empty or None. Setting pcap_data to b''.")
            pcap_data = b""
    
    except Exception as e: # Outer exception for DicomSceneProcessor or other issues
        print(f"DEBUG: DicomSceneProcessor or outer try block failed: {type(e).__name__}: {e}")
        pytest.fail(f"DicomSceneProcessor failed to generate PCAP: {e}")

    assert pcap_data is not None, "PCAP data should not be None"
    # The following assertion might fail if no packets are generated for an empty/default scene.
    # Consider if an empty pcap_data (b"") is a valid outcome for some scene configurations.
    # For this complex scene, we expect data.
    assert len(pcap_data) > 0, "PCAP data should not be empty for this complex scene"

    # Optional: Write to file for manual inspection during development
    output_dir = Path(__file__).parent / "generated_pcaps"
    output_dir.mkdir(exist_ok=True)
    with open(output_dir / f"{scene_id}.pcap", "wb") as f:
        f.write(pcap_data)

    print(f"Successfully generated PCAP for scene {scene_id}, size: {len(pcap_data)} bytes.")
