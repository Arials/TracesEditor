from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ConfigDict

class ConnectionDetails(BaseModel):
    source_mac: str = Field(..., json_schema_extra={'example': "00:00:00:AA:BB:CC"})
    destination_mac: str = Field(..., json_schema_extra={'example': "00:00:00:DD:EE:FF"})
    source_ip: str = Field(..., json_schema_extra={'example': "192.168.1.100"})
    destination_ip: str = Field(..., json_schema_extra={'example': "192.168.1.200"})
    source_port: int = Field(..., json_schema_extra={'example': 56789})
    destination_port: int = Field(..., json_schema_extra={'example': 104})

class PresentationContextItem(BaseModel):
    id: int = Field(..., json_schema_extra={'example': 1})
    abstract_syntax: str = Field(..., json_schema_extra={'example': "1.2.840.10008.5.1.4.1.1.2"}) # CT Image Storage
    transfer_syntaxes: List[str] = Field(..., json_schema_extra={'example': ["1.2.840.10008.1.2.1", "1.2.840.10008.1.2"]})

class AssociationRequestDetails(BaseModel):
    calling_ae_title: str = Field(..., max_length=16, json_schema_extra={'example': "SCU_AET"})
    called_ae_title: str = Field(..., max_length=16, json_schema_extra={'example': "SCP_AET"})
    application_context_name: str = Field(..., json_schema_extra={'example': "1.2.840.10008.3.1.1.1"}) # DICOM Application Context Name
    presentation_contexts: List[PresentationContextItem]

class SopClassDefinition(BaseModel):
    """
    Defines a SOP Class supported by an Asset, including its role and supported transfer syntaxes.
    """
    sop_class_uid: str = Field(..., json_schema_extra={'example': "1.2.840.10008.5.1.4.1.1.2"}, description="SOP Class UID.")
    role: str = Field(..., json_schema_extra={'example': "SCP"}, description="Role of the asset for this SOP Class (e.g., 'SCU', 'SCP', 'BOTH').")
    transfer_syntaxes: List[str] = Field(
        ..., 
        json_schema_extra={'example': ["1.2.840.10008.1.2.1", "1.2.840.10008.1.2"]}, 
        description="List of Transfer Syntax UIDs supported for this SOP Class."
    )

class AssetDicomProperties(BaseModel):
    """
    Represents the DICOM-specific properties of an Asset (DICOM device).
    """
    ae_title: Optional[str] = Field(
        None, 
        max_length=16, 
        json_schema_extra={'example': "CT_SCANNER_AE"}, 
        description="Application Entity Title of the asset."
    )
    implementation_class_uid: Optional[str] = Field(
        None, 
        json_schema_extra={'example': "1.2.826.0.1.3680043.2.1143.107.104.103.0"}, # Example pynetdicom's default
        description="Implementation Class UID of the asset."
    )
    implementation_version_name: Optional[str] = Field(
        None, 
        json_schema_extra={'example': "PYNETDICOM_1.5.7"}, 
        description="Implementation Version Name."
    )
    manufacturer: Optional[str] = Field(
        None, 
        json_schema_extra={'example': "ACME Medical Systems"}, 
        description="Manufacturer of the device."
    )
    model_name: Optional[str] = Field(
        None, 
        json_schema_extra={'example': "UltraScan 5000"}, 
        description="Model name of the device."
    )
    software_versions: Optional[List[str]] = Field(
        None, 
        json_schema_extra={'example': ["OS:1.2.3", "App:4.5.6b"]}, 
        description="List of software versions running on the device."
    )
    device_serial_number: Optional[str] = Field(
        None, 
        json_schema_extra={'example': "SN987654321"}, 
        description="Device serial number."
    )
    supported_sop_classes: Optional[List[SopClassDefinition]] = Field(
        None, 
        description="List of SOP Classes supported by this asset, including their roles and transfer syntaxes."
    )

    model_config = ConfigDict(json_schema_extra = {
            "example": {
                "ae_title": "CT_SCANNER_AE",
                "implementation_class_uid": "1.2.826.0.1.3680043.2.1143.107.104.103.0",
                "implementation_version_name": "PYNETDICOM_1.5.7",
                "manufacturer": "ACME Medical Systems",
                "model_name": "UltraScan 5000",
                "software_versions": ["OS:1.2.3", "App:4.5.6b"],
                "device_serial_number": "SN987654321",
                "supported_sop_classes": [
                    {
                        "sop_class_uid": "1.2.840.10008.5.1.4.1.1.2", # CT Image Storage
                        "role": "SCP",
                        "transfer_syntaxes": ["1.2.840.10008.1.2.1", "1.2.840.10008.1.2.4.50"]
                    },
                    {
                        "sop_class_uid": "1.2.840.10008.1.1", # Verification SOP Class
                        "role": "SCP",
                        "transfer_syntaxes": ["1.2.840.10008.1.2"]
                    }
                ]
            }
        })

# Core Models for Advanced DICOM Scene Generation (Task 1.3)

class Node(BaseModel):
    """
    Represents a network node/interface within an Asset.
    """
    node_id: str = Field(..., json_schema_extra={'example': "NODE_CT_PRIMARY_NIC"}, description="Unique identifier for this node within its Asset.")
    ip_address: str = Field(..., json_schema_extra={'example': "192.168.1.10"}, description="IP address of this node.")
    mac_address: str = Field(..., json_schema_extra={'example': "0A:1B:2C:3D:4E:5F"}, description="MAC address of this node.")
    dicom_port: Optional[int] = Field(104, json_schema_extra={'example': 104}, description="Default DICOM port this node listens on if it acts as an SCP. Can be overridden in Link.")

    model_config = ConfigDict(json_schema_extra = {
            "example": {
                "node_id": "NODE_CT_PRIMARY_NIC",
                "ip_address": "192.168.1.10",
                "mac_address": "0A:1B:2C:3D:4E:5F",
                "dicom_port": 104
            }
        })

class Asset(BaseModel):
    """
    Represents a DICOM device (Asset) in the simulation scene.
    """
    asset_id: str = Field(..., json_schema_extra={'example': "ASSET_CT_SCANNER_01"}, description="Unique identifier for this asset within the scene.")
    name: str = Field(..., json_schema_extra={'example': "Main CT Scanner"}, description="User-friendly name for the asset.")
    description: Optional[str] = Field(None, json_schema_extra={'example': "Primary CT scanner in radiology department."}, description="Optional detailed description.")
    
    asset_template_id_ref: Optional[str] = Field(
        None, 
        json_schema_extra={'example': "TEMPLATE_GENERIC_CT_V1"}, 
        description="Optional reference to an Asset Template ID. Properties from the template can be merged or overridden."
    )
    
    nodes: List[Node] = Field(..., min_length=1, description="List of network nodes/interfaces for this asset.")
    
    dicom_properties: AssetDicomProperties = Field(
        ..., 
        description="DICOM-specific configuration for this asset."
    )

    model_config = ConfigDict(json_schema_extra = {
            "example": {
                "asset_id": "ASSET_CT_SCANNER_01",
                "name": "Main CT Scanner",
                "description": "Primary CT scanner in radiology.",
                "asset_template_id_ref": "TEMPLATE_GENERIC_CT_V1",
                "nodes": [
                    Node.model_config["json_schema_extra"]["example"] # Reuse Node example
                ],
                "dicom_properties": AssetDicomProperties.model_config["json_schema_extra"]["example"] # Reuse AssetDicomProperties example
            }
        })

class LinkConnectionDetails(BaseModel):
    """
    Defines the specific L2-L4 connection parameters for a Link.
    These might be derived from Nodes or explicitly set.
    """
    source_mac: str = Field(..., json_schema_extra={'example': "00:1A:2B:3C:4D:5E"}, description="Source MAC address for this link's communication.")
    destination_mac: str = Field(..., json_schema_extra={'example': "00:6F:7E:8D:9C:0B"}, description="Destination MAC address for this link's communication.")
    source_ip: str = Field(..., json_schema_extra={'example': "192.168.1.100"}, description="Source IP address for this link.")
    destination_ip: str = Field(..., json_schema_extra={'example': "192.168.1.200"}, description="Destination IP address for this link.")
    source_port: int = Field(..., gt=0, le=65535, json_schema_extra={'example': 56789}, description="Source TCP port (often ephemeral).")
    destination_port: int = Field(..., gt=0, le=65535, json_schema_extra={'example': 104}, description="Destination TCP port (DICOM port of SCP).")

    model_config = ConfigDict(json_schema_extra = {
            "example": {
                "source_mac": "00:1A:2B:3C:4D:5E",
                "destination_mac": "00:6F:7E:8D:9C:0B",
                "source_ip": "192.168.1.100",
                "destination_ip": "192.168.1.200",
                "source_port": 50101,
                "destination_port": 104
            }
        })

# Moved CommandSetItem, DimseOperation, LinkDicomConfiguration before Link to resolve NameError

class CommandSetItem(BaseModel):
    MessageID: int = Field(..., json_schema_extra={'example': 1})
    Priority: Optional[int] = Field(None, json_schema_extra={'example': 1})
    AffectedSOPClassUID: Optional[str] = Field(None, json_schema_extra={'example': "1.2.840.10008.5.1.4.1.1.2"})
    AffectedSOPInstanceUID: Optional[str] = Field(None, json_schema_extra={'example': "1.2.826.0.1.3680043.9.1234.1.1"})
    # Add other common command set fields as needed, or allow arbitrary key-values
    # For now, we'll allow any additional fields that pydicom can handle.
    # Using Dict[str, Any] for flexibility, specific fields above for validation and OpenAPI docs.
    extra_fields: Dict[str, Any] = Field(default_factory=dict)

    def to_pydicom_dict(self) -> Dict[str, Any]:
        """Converts to a dictionary suitable for pydicom, merging specific and extra fields."""
        data = self.extra_fields.copy()
        if self.MessageID is not None:
            data['MessageID'] = self.MessageID
        if self.Priority is not None:
            data['Priority'] = self.Priority
        if self.AffectedSOPClassUID is not None:
            data['AffectedSOPClassUID'] = self.AffectedSOPClassUID
        if self.AffectedSOPInstanceUID is not None:
            data['AffectedSOPInstanceUID'] = self.AffectedSOPInstanceUID
        return data

class DimseOperation(BaseModel):
    """
    Defines a single DIMSE operation within a Link's communication sequence.
    """
    operation_name: str = Field(..., json_schema_extra={'example': "C-STORE Request for CT Image"}, description="A user-friendly name or description for this operation step.")
    message_type: str = Field(..., json_schema_extra={'example': "C-STORE-RQ"}, description="The DIMSE message type (e.g., C-STORE-RQ, C-ECHO-RQ, C-FIND-RQ).")
    
    presentation_context_id: int = Field(
        ..., 
        json_schema_extra={'example': 1}, 
        description="ID of the presentation context to use for this DIMSE message. This ID must correspond to one of the accepted presentation contexts for the association."
    )
    
    command_set: CommandSetItem = Field(
        ...,
        description="The command set for this DIMSE message. MessageID might be auto-managed by the processor if set to a specific value (e.g., 0 or -1) or based on sequence order."
    )
    
    dataset_content_rules: Optional[Dict[str, Any]] = Field(
        None,
        json_schema_extra={'example': {
            "SOPClassUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_CLASS_UID",
            "SOPInstanceUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_INSTANCE_UID",
            "PatientName": "AUTO_GENERATE_SAMPLE_PATIENT_NAME",
            "PatientID": "PATID12345", # Explicit value
            "StudyInstanceUID": "AUTO_GENERATE_UID_STUDY",
            "SeriesInstanceUID": "AUTO_GENERATE_UID_SERIES",
            "Modality": "CT",
            "Manufacturer": "AUTO_FROM_ASSET_SCU_MANUFACTURER", # Populated from SCU Asset
            "ModelName": "AUTO_FROM_ASSET_SCP_MODEL_NAME", # Populated from SCP Asset
            # ... other explicit DICOM tags or dynamic rule keywords
        }},
        description=(
            "Defines the content of the DICOM dataset for this operation, if applicable (e.g., for C-STORE-RQ). "
            "Keys are DICOM tag keywords. Values can be: "
            "1. Explicit values (strings, numbers, etc.). "
            "2. Special string keywords for dynamic population by the DicomSceneProcessor, such as: "
            "   - 'AUTO_FROM_COMMAND_AFFECTED_SOP_CLASS_UID': Uses AffectedSOPClassUID from command_set. "
            "   - 'AUTO_FROM_COMMAND_AFFECTED_SOP_INSTANCE_UID': Uses AffectedSOPInstanceUID from command_set. "
            "   - 'AUTO_GENERATE_UID_INSTANCE': Generates a new DICOM UID for SOPInstanceUID. "
            "   - 'AUTO_GENERATE_UID_STUDY': Generates a new DICOM UID for StudyInstanceUID. "
            "   - 'AUTO_GENERATE_UID_SERIES': Generates a new DICOM UID for SeriesInstanceUID. "
            "   - 'AUTO_GENERATE_SAMPLE_PATIENT_NAME': Generates a sample patient name. "
            "   - 'AUTO_FROM_ASSET_SCU_AE_TITLE': Uses ae_title from the SCU Asset's DicomProperties. "
            "   - 'AUTO_FROM_ASSET_SCP_AE_TITLE': Uses ae_title from the SCP Asset's DicomProperties. "
            "   - 'AUTO_FROM_ASSET_SCU_MANUFACTURER': Uses manufacturer from SCU Asset. "
            "   - 'AUTO_FROM_ASSET_SCP_MANUFACTURER': Uses manufacturer from SCP Asset. "
            "   - 'AUTO_FROM_ASSET_SCU_MODEL_NAME': Uses model_name from SCU Asset. "
            "   - 'AUTO_FROM_ASSET_SCP_MODEL_NAME': Uses model_name from SCP Asset. "
            "   - 'AUTO_FROM_ASSET_SCU_SOFTWARE_VERSIONS': Uses software_versions from SCU Asset. "
            "   - 'AUTO_FROM_ASSET_SCP_SOFTWARE_VERSIONS': Uses software_versions from SCP Asset. "
            "   - 'AUTO_FROM_ASSET_SCU_DEVICE_SERIAL_NUMBER': Uses device_serial_number from SCU Asset. "
            "   - 'AUTO_FROM_ASSET_SCP_DEVICE_SERIAL_NUMBER': Uses device_serial_number from SCP Asset. "
            "If None, no dataset is sent (e.g., for C-ECHO-RQ)."
        )
    )

    model_config = ConfigDict(json_schema_extra = {
            "example": {
                "operation_name": "Store CT Image",
                "message_type": "C-STORE-RQ",
                "presentation_context_id": 1,
                "command_set": {
                    "MessageID": 1,
                    "Priority": 0, # MEDIUM
                    "AffectedSOPClassUID": "1.2.840.10008.5.1.4.1.1.2", # CT Image Storage
                    "AffectedSOPInstanceUID": "AUTO_GENERATE_UID_INSTANCE" 
                },
                "dataset_content_rules": {
                    "SOPClassUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_CLASS_UID",
                    "SOPInstanceUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_INSTANCE_UID",
                    "PatientName": "AUTO_GENERATE_SAMPLE_PATIENT_NAME",
                    "PatientID": "SAMPLE001",
                    "StudyInstanceUID": "AUTO_GENERATE_UID_STUDY",
                    "SeriesInstanceUID": "AUTO_GENERATE_UID_SERIES",
                    "Modality": "CT",
                    "Manufacturer": "AUTO_FROM_ASSET_SCU_MANUFACTURER",
                    "ModelName": "AUTO_FROM_ASSET_SCU_MODEL_NAME",
                }
            }
        })


class LinkDicomConfiguration(BaseModel):
    """
    Configures the DICOM-specific aspects of a Link between two Assets in a Scene.
    """
    scu_asset_id_ref: str = Field(
        ..., 
        description="Reference ID of the Asset (defined in the Scene) that acts as the Service Class User (SCU) for this link."
    )
    scp_asset_id_ref: str = Field(
        ..., 
        description="Reference ID of the Asset (defined in the Scene) that acts as the Service Class Provider (SCP) for this link."
    )

    calling_ae_title_override: Optional[str] = Field(
        None, 
        max_length=16, 
        description="If provided, overrides the Calling AE Title derived from the SCU Asset's properties for this specific link."
    )
    called_ae_title_override: Optional[str] = Field(
        None, 
        max_length=16, 
        description="If provided, overrides the Called AE Title derived from the SCP Asset's properties for this specific link."
    )

    explicit_presentation_contexts: Optional[List[PresentationContextItem]] = Field(
        None, 
        description=(
            "Explicitly defines the presentation contexts to be proposed by the SCU for this link's A-ASSOCIATE-RQ. "
            "Each item's 'id' must be unique and odd within this list. "
            "If None, the DicomSceneProcessor may attempt to derive presentation contexts based on the SCU and SCP Asset's "
            "supported SOP classes and a pre-defined strategy (e.g., propose all SCU's SCU-role SOPs that SCP supports as SCP)."
        )
    )
    
    dimse_sequence: List[DimseOperation] = Field(
        ..., 
        description="An ordered list of DIMSE operations (e.g., C-ECHO-RQ, C-STORE-RQ, C-FIND-RQ) to be simulated over this link after successful association."
    )

    model_config = ConfigDict(json_schema_extra = {
            "example": {
                "scu_asset_id_ref": "ASSET_CT_SCANNER_01",
                "scp_asset_id_ref": "ASSET_PACS_SERVER_01",
                "calling_ae_title_override": "CT_SCU_LINK1",
                "called_ae_title_override": None, # Uses AE title from ASSET_PACS_SERVER_01
                "explicit_presentation_contexts": [
                    {
                        "id": 1, # Must be odd
                        "abstract_syntax": "1.2.840.10008.5.1.4.1.1.2", # CT Image Storage
                        "transfer_syntaxes": ["1.2.840.10008.1.2.1", "1.2.840.10008.1.2.4.50"] # Explicit Little Endian, JPEG Lossless
                    },
                    {
                        "id": 3, # Must be odd
                        "abstract_syntax": "1.2.840.10008.1.1", # Verification SOP Class
                        "transfer_syntaxes": ["1.2.840.10008.1.2"] # Implicit Little Endian
                    }
                ],
                "dimse_sequence": [
                    {
                        "operation_name": "Verification Echo",
                        "message_type": "C-ECHO-RQ",
                        "presentation_context_id": 3, # Uses PC ID 3 for Verification
                        "command_set": {
                            "MessageID": 1
                            # AffectedSOPClassUID for C-ECHO-RQ is implicitly Verification SOP Class UID.
                            # Processor can fill this if not provided based on message_type.
                        },
                        "dataset_content_rules": None # C-ECHO-RQ has no dataset
                    },
                    {
                        "operation_name": "Store CT Image 1",
                        "message_type": "C-STORE-RQ",
                        "presentation_context_id": 1, # Uses PC ID 1 for CT Image Storage
                        "command_set": {
                            "MessageID": 2,
                            "Priority": 0, # MEDIUM
                            "AffectedSOPClassUID": "1.2.840.10008.5.1.4.1.1.2", 
                            "AffectedSOPInstanceUID": "AUTO_GENERATE_UID_INSTANCE" 
                        },
                        "dataset_content_rules": {
                            "SOPClassUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_CLASS_UID",
                            "SOPInstanceUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_INSTANCE_UID",
                            "PatientName": "AUTO_GENERATE_SAMPLE_PATIENT_NAME",
                            "PatientID": "PAT001-LINK1",
                            "StudyInstanceUID": "AUTO_GENERATE_UID_STUDY", # Could also be a fixed value or from a scenario variable
                            "SeriesInstanceUID": "AUTO_GENERATE_UID_SERIES",
                            "Modality": "CT",
                            "Manufacturer": "AUTO_FROM_ASSET_SCU_MANUFACTURER",
                            "ModelName": "AUTO_FROM_ASSET_SCU_MODEL_NAME",
                            "SoftwareVersions": "AUTO_FROM_ASSET_SCU_SOFTWARE_VERSIONS",
                            "DeviceSerialNumber": "AUTO_FROM_ASSET_SCU_DEVICE_SERIAL_NUMBER",
                            "InstanceNumber": "1",
                            # Example of explicit pixel data related tags (actual pixel data generation is complex)
                            "Rows": 512, "Columns": 512, "PixelRepresentation": 0, 
                            "SamplesPerPixel": 1, "PhotometricInterpretation": "MONOCHROME2",
                            "BitsAllocated": 16, "BitsStored": 12, "HighBit": 11
                        }
                    }
                ]
            }
        })

class Link(BaseModel):
    """
    Represents a communication link and sequence of interactions between two Nodes of Assets.
    """
    link_id: str = Field(..., json_schema_extra={'example': "LINK_CT_TO_PACS_01"}, description="Unique identifier for this link within the scene.")
    name: str = Field(..., json_schema_extra={'example': "CT Scanner sends images to PACS"}, description="User-friendly name for the link.")
    description: Optional[str] = Field(None, json_schema_extra={'example': "Scheduled image transfer."}, description="Optional detailed description.")

    source_asset_id_ref: str = Field(
        ..., 
        json_schema_extra={'example': "ASSET_CT_SCANNER_01"}, 
        description="ID of the source Asset for this link."
    )
    source_node_id_ref: str = Field(
        ..., 
        json_schema_extra={'example': "CT_NIC1"}, 
        description="ID of the Node within the source Asset to use for this link."
    )
    
    destination_asset_id_ref: str = Field(
        ..., 
        json_schema_extra={'example': "ASSET_PACS_SERVER_01"}, 
        description="ID of the destination Asset for this link."
    )
    destination_node_id_ref: str = Field(
        ..., 
        json_schema_extra={'example': "PACS_NIC1"}, 
        description="ID of the Node within the destination Asset to use for this link."
    )

    connection_details: Optional[LinkConnectionDetails] = Field(
        None,
        description="Specific L2-L4 connection parameters for this link. If None, the DicomSceneProcessor will attempt to derive them from the linked nodes."
    )
    
    dicom_config: LinkDicomConfiguration = Field(
        ..., 
        description="DICOM-specific communication configuration for this link (SCU/SCP roles, AEs, presentation contexts, DIMSE sequence)."
    )

    model_config = ConfigDict(json_schema_extra = {
            "example": {
                "link_id": "LINK_CT_TO_PACS_01",
                "name": "CT Scanner sends images to PACS",
                "source_asset_id_ref": "ASSET_CT_SCANNER_01",
                "source_node_id_ref": "CT_NIC1",
                "destination_asset_id_ref": "ASSET_PACS_SERVER_01",
                "destination_node_id_ref": "PACS_NIC1",
                "connection_details": LinkConnectionDetails.model_config["json_schema_extra"]["example"], # Reuse LinkConnectionDetails example
                "dicom_config": LinkDicomConfiguration.model_config["json_schema_extra"]["example"] # Reuse LinkDicomConfiguration example
            }
        })
        
class Scene(BaseModel):
    """
    Defines a complete DICOM simulation scenario, including all assets and their interactions.
    """
    scene_id: str = Field(..., json_schema_extra={'example': "SCENE_RADIOLOGY_DEPT_NORMAL_OPS_01"}, description="Unique identifier for the scene.")
    name: str = Field(..., json_schema_extra={'example': "Radiology Department - Normal Operations"}, description="User-friendly name for the scene.")
    description: Optional[str] = Field(None, json_schema_extra={'example': "Simulates typical daily DICOM traffic in a radiology department."}, description="Optional detailed description.")
    
    assets: List[Asset] = Field(..., min_length=1, description="List of all DICOM assets participating in this scene.")
    links: List[Link] = Field(..., min_length=1, description="List of all communication links and interaction sequences between assets in this scene.")

    model_config = ConfigDict(json_schema_extra = {
            "example": {
                "scene_id": "SCENE_RADIOLOGY_DEPT_NORMAL_OPS_01",
                "name": "Radiology Department - Normal Operations",
                "assets": [
                    Asset.model_config["json_schema_extra"]["example"], # Example CT Scanner
                    { # Example PACS Server Asset
                        "asset_id": "ASSET_PACS_SERVER_01",
                        "name": "Main PACS Server",
                        "description": "Central archive for medical images.",
                        "asset_template_id_ref": "TEMPLATE_GENERIC_PACS_V1",
                        "nodes": [
                            {
                                "node_id": "PACS_NIC1",
                                "ip_address": "192.168.1.200",
                                "mac_address": "00:6F:7E:8D:9C:0B",
                                "dicom_port": 104
                            }
                        ],
                        "dicom_properties": { # Simplified example for brevity, reuse AssetDicomProperties example structure
                            "ae_title": "PACS_AE_MAIN",
                            "implementation_class_uid": "1.2.826.0.1.3680043.2.1143.107.104.103.1",
                            "manufacturer": "Archive Systems Inc.",
                            "model_name": "PACSStore Pro",
                            "software_versions": ["FW:3.2.1", "DB:9.8.7"],
                            "device_serial_number": "PACS_SN00001",
                            "supported_sop_classes": [
                                {
                                    "sop_class_uid": "1.2.840.10008.5.1.4.1.1.2", # CT Image Storage
                                    "role": "SCP",
                                    "transfer_syntaxes": ["1.2.840.10008.1.2.1", "1.2.840.10008.1.2.4.50"]
                                },
                                {
                                    "sop_class_uid": "1.2.840.10008.1.1", # Verification SOP Class
                                    "role": "SCP",
                                    "transfer_syntaxes": ["1.2.840.10008.1.2"]
                                }
                                # ... other supported SOP classes for a PACS
                            ]
                        }
                    }
                ],
                "links": [
                    Link.model_config["json_schema_extra"]["example"] # Example Link
                ]
            }
        })

# New Models for Advanced DICOM Scene Generation (Task 1.2)
# CommandSetItem, DimseOperation, LinkDicomConfiguration were moved up

class DataSetItem(BaseModel):
    # Using Dict[str, Any] for flexibility, as dataset contents are highly variable.
    # pydicom will handle keyword-to-tag mapping and VR assignment.
    elements: Dict[str, Any] = Field(..., json_schema_extra={'example': {
        "SOPClassUID": "1.2.840.10008.5.1.4.1.1.2",
        "SOPInstanceUID": "1.2.826.0.1.3680043.9.1234.1.1",
        "PatientName": "Doe^Jane",
        "PatientID": "PID001",
        "StudyInstanceUID": "1.2.826.0.1.3680043.9.1234",
        "SeriesInstanceUID": "1.2.826.0.1.3680043.9.1234.1",
        "Modality": "CT",
        "InstanceNumber": "1"
    }})

    def to_pydicom_dict(self) -> Dict[str, Any]:
        """Returns the elements dictionary."""
        return self.elements

class DicomMessageItem(BaseModel):
    presentation_context_id: int = Field(..., json_schema_extra={'example': 1})
    message_type: str = Field(..., json_schema_extra={'example': "C-STORE-RQ"}) # e.g., C-STORE-RQ, C-ECHO-RQ
    command_set: CommandSetItem
    data_set: Optional[DataSetItem] = None # Can be null for messages like C-ECHO-RQ

class DicomPcapRequestPayload(BaseModel):
    connection_details: ConnectionDetails
    association_request: AssociationRequestDetails
    dicom_messages: List[DicomMessageItem]

    model_config = ConfigDict(json_schema_extra = {
            "example": {
                "connection_details": {
                    "source_mac": "00:00:00:AA:BB:CC",
                    "destination_mac": "00:00:00:DD:EE:FF",
                    "source_ip": "192.168.1.100",
                    "destination_ip": "192.168.1.200",
                    "source_port": 56789,
                    "destination_port": 104
                },
                "association_request": {
                    "calling_ae_title": "SCU_AET",
                    "called_ae_title": "SCP_AET",
                    "application_context_name": "1.2.840.10008.3.1.1.1",
                    "presentation_contexts": [
                        {
                            "id": 1,
                            "abstract_syntax": "1.2.840.10008.5.1.4.1.1.2",
                            "transfer_syntaxes": [
                                "1.2.840.10008.1.2.1",
                                "1.2.840.10008.1.2"
                            ]
                        }
                    ]
                },
                "dicom_messages": [
                    {
                        "presentation_context_id": 1,
                        "message_type": "C-STORE-RQ",
                        "command_set": {
                            "MessageID": 1,
                            "Priority": 1,
                            "AffectedSOPClassUID": "1.2.840.10008.5.1.4.1.1.2",
                            "AffectedSOPInstanceUID": "1.2.826.0.1.3680043.9.1234.1.1"
                        },
                        "data_set": {
                            "elements": {
                                "SOPClassUID": "1.2.840.10008.5.1.4.1.1.2",
                                "SOPInstanceUID": "1.2.826.0.1.3680043.9.1234.1.1",
                                "PatientName": "Doe^Jane",
                                "PatientID": "PID001",
                                "StudyInstanceUID": "1.2.826.0.1.3680043.9.1234",
                                "SeriesInstanceUID": "1.2.826.0.1.3680043.9.1234.1",
                                "Modality": "CT",
                                "InstanceNumber": "1"
                            }
                        }
                    },
                    {
                        "presentation_context_id": 1,
                        "message_type": "C-ECHO-RQ",
                        "command_set": {
                            "MessageID": 2
                        },
                        "data_set": None
                    }
                ]
            }
        })
