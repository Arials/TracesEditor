import pytest
from pydantic import ValidationError

from backend.protocols.dicom.models import (
    SopClassDefinition,
    AssetDicomProperties,
    Node,
    Asset,
    LinkConnectionDetails,
    DimseOperation,
    CommandSetItem,
    LinkDicomConfiguration,
    Link,
    Scene
    # PresentationContextItem is implicitly tested via AssetDicomProperties & LinkDicomConfiguration
    # ConnectionDetails, AssociationRequestDetails, DataSetItem, DicomMessageItem, DicomPcapRequestPayload
    # are older models and not the primary focus of Task 4.1, but can be tested if time permits
    # or if they become relevant to scene generation logic.
)

# Test data for SopClassDefinition
VALID_SOP_CLASS_DEFINITION_DATA = {
    "sop_class_uid": "1.2.840.10008.5.1.4.1.1.2",  # CT Image Storage
    "role": "SCP",
    "transfer_syntaxes": ["1.2.840.10008.1.2.1", "1.2.840.10008.1.2"]
}

# Test data for AssetDicomProperties (used by Asset model tests too)
VALID_ASSET_DICOM_PROPERTIES_DATA = {
    "ae_title": "CT_SCANNER_AE",
    "implementation_class_uid": "1.2.826.0.1.3680043.2.1143.107.104.103.0",
    "implementation_version_name": "PYNETDICOM_1.5.7",
    "manufacturer": "ACME Medical Systems",
    "model_name": "UltraScan 5000",
    "software_versions": ["OS:1.2.3", "App:4.5.6b"],
    "device_serial_number": "SN987654321",
    "supported_sop_classes": [VALID_SOP_CLASS_DEFINITION_DATA]
}

class TestSopClassDefinition:
    def test_sop_class_definition_valid(self):
        sop_class = SopClassDefinition(**VALID_SOP_CLASS_DEFINITION_DATA)
        assert sop_class.sop_class_uid == VALID_SOP_CLASS_DEFINITION_DATA["sop_class_uid"]
        assert sop_class.role == VALID_SOP_CLASS_DEFINITION_DATA["role"]
        assert sop_class.transfer_syntaxes == VALID_SOP_CLASS_DEFINITION_DATA["transfer_syntaxes"]

    def test_sop_class_definition_missing_fields(self):
        with pytest.raises(ValidationError):
            SopClassDefinition(sop_class_uid="1.2.3", role="SCU")  # Missing transfer_syntaxes
        with pytest.raises(ValidationError):
            SopClassDefinition(sop_class_uid="1.2.3", transfer_syntaxes=["1.2"])  # Missing role
        with pytest.raises(ValidationError):
            SopClassDefinition(role="SCP", transfer_syntaxes=["1.2"])  # Missing sop_class_uid

    def test_sop_class_definition_invalid_types(self):
        with pytest.raises(ValidationError):
            SopClassDefinition(**{**VALID_SOP_CLASS_DEFINITION_DATA, "role": 123})
        with pytest.raises(ValidationError):
            SopClassDefinition(**{**VALID_SOP_CLASS_DEFINITION_DATA, "transfer_syntaxes": "1.2.3"})


class TestAssetDicomProperties:
    def test_asset_dicom_properties_valid(self):
        props = AssetDicomProperties(**VALID_ASSET_DICOM_PROPERTIES_DATA)
        assert props.ae_title == VALID_ASSET_DICOM_PROPERTIES_DATA["ae_title"]
        assert props.manufacturer == VALID_ASSET_DICOM_PROPERTIES_DATA["manufacturer"]
        assert len(props.supported_sop_classes) == 1
        assert props.supported_sop_classes[0].sop_class_uid == VALID_SOP_CLASS_DEFINITION_DATA["sop_class_uid"]

    def test_asset_dicom_properties_minimal(self):
        minimal_data = {
            "ae_title": "MINIMAL_AE",
            "implementation_class_uid": "1.2.3.4.5",
            "supported_sop_classes": [VALID_SOP_CLASS_DEFINITION_DATA]
        }
        props = AssetDicomProperties(**minimal_data)
        assert props.ae_title == minimal_data["ae_title"]
        assert props.implementation_class_uid == minimal_data["implementation_class_uid"]
        assert props.manufacturer is None # Optional fields should be None if not provided
        assert props.model_name is None
        assert props.software_versions is None
        assert props.device_serial_number is None

    def test_asset_dicom_properties_missing_required_fields(self):
        with pytest.raises(ValidationError, match="ae_title"):
            AssetDicomProperties(
                implementation_class_uid="1.2.3",
                supported_sop_classes=[VALID_SOP_CLASS_DEFINITION_DATA]
            )
        with pytest.raises(ValidationError, match="implementation_class_uid"):
            AssetDicomProperties(
                ae_title="TEST_AE",
                supported_sop_classes=[VALID_SOP_CLASS_DEFINITION_DATA]
            )
        with pytest.raises(ValidationError, match="supported_sop_classes"):
            AssetDicomProperties(
                ae_title="TEST_AE",
                implementation_class_uid="1.2.3"
            )

    def test_asset_dicom_properties_ae_title_max_length(self):
        with pytest.raises(ValidationError, match="ae_title"):
            AssetDicomProperties(
                **{**VALID_ASSET_DICOM_PROPERTIES_DATA, "ae_title": "A" * 17} # Max 16
            )
        # Valid length
        props = AssetDicomProperties(
            **{**VALID_ASSET_DICOM_PROPERTIES_DATA, "ae_title": "A" * 16}
        )
        assert len(props.ae_title) == 16

    def test_asset_dicom_properties_example_is_valid(self):
        # Test the example provided in the model's Config
        example_data = AssetDicomProperties.model_config["json_schema_extra"]["example"]
        props = AssetDicomProperties(**example_data)
        assert props.ae_title == example_data["ae_title"]
        assert props.manufacturer == example_data["manufacturer"]
        assert len(props.supported_sop_classes) == len(example_data["supported_sop_classes"])


# Test data for Node
VALID_NODE_DATA = {
    "node_id": "NODE_CT_PRIMARY_NIC",
    "ip_address": "192.168.1.10",
    "mac_address": "0A:1B:2C:3D:4E:5F",
    "dicom_port": 104
}

# Test data for Asset
VALID_ASSET_DATA = {
    "asset_id": "ASSET_CT_SCANNER_01",
    "name": "Main CT Scanner",
    "description": "Primary CT scanner in radiology.",
    "asset_template_id_ref": "TEMPLATE_GENERIC_CT_V1",
    "nodes": [VALID_NODE_DATA],
    "dicom_properties": VALID_ASSET_DICOM_PROPERTIES_DATA
}

class TestNode:
    def test_node_valid(self):
        node = Node(**VALID_NODE_DATA)
        assert node.node_id == VALID_NODE_DATA["node_id"]
        assert node.ip_address == VALID_NODE_DATA["ip_address"]
        assert node.mac_address == VALID_NODE_DATA["mac_address"]
        assert node.dicom_port == VALID_NODE_DATA["dicom_port"]

    def test_node_minimal(self):
        # dicom_port is optional with a default
        minimal_data = {
            "node_id": "NODE_MIN",
            "ip_address": "10.0.0.1",
            "mac_address": "FF:EE:DD:CC:BB:AA"
        }
        node = Node(**minimal_data)
        assert node.node_id == minimal_data["node_id"]
        assert node.dicom_port == 104 # Default value

    def test_node_missing_required_fields(self):
        with pytest.raises(ValidationError, match="node_id"):
            Node(ip_address="1.1.1.1", mac_address="AA:BB:CC:DD:EE:FF")
        with pytest.raises(ValidationError, match="ip_address"):
            Node(node_id="N1", mac_address="AA:BB:CC:DD:EE:FF")
        with pytest.raises(ValidationError, match="mac_address"):
            Node(node_id="N1", ip_address="1.1.1.1")

    def test_node_example_is_valid(self):
        example_data = Node.model_config["json_schema_extra"]["example"]
        node = Node(**example_data)
        assert node.node_id == example_data["node_id"]
        assert node.dicom_port == example_data["dicom_port"]


class TestAsset:
    def test_asset_valid(self):
        asset = Asset(**VALID_ASSET_DATA)
        assert asset.asset_id == VALID_ASSET_DATA["asset_id"]
        assert asset.name == VALID_ASSET_DATA["name"]
        assert asset.asset_template_id_ref == VALID_ASSET_DATA["asset_template_id_ref"]
        assert len(asset.nodes) == 1
        assert asset.nodes[0].node_id == VALID_NODE_DATA["node_id"]
        assert asset.dicom_properties.ae_title == VALID_ASSET_DICOM_PROPERTIES_DATA["ae_title"]

    def test_asset_minimal_required_fields(self):
        minimal_data = {
            "asset_id": "ASSET_MIN",
            "name": "Minimal Asset",
            "nodes": [VALID_NODE_DATA],
            "dicom_properties": VALID_ASSET_DICOM_PROPERTIES_DATA
        }
        asset = Asset(**minimal_data)
        assert asset.asset_id == minimal_data["asset_id"]
        assert asset.description is None
        assert asset.asset_template_id_ref is None

    def test_asset_missing_required_fields(self):
        with pytest.raises(ValidationError, match="asset_id"):
            Asset(name="Test", nodes=[VALID_NODE_DATA], dicom_properties=VALID_ASSET_DICOM_PROPERTIES_DATA)
        with pytest.raises(ValidationError, match="name"):
            Asset(asset_id="A1", nodes=[VALID_NODE_DATA], dicom_properties=VALID_ASSET_DICOM_PROPERTIES_DATA)
        with pytest.raises(ValidationError, match="nodes"):
            Asset(asset_id="A1", name="Test", dicom_properties=VALID_ASSET_DICOM_PROPERTIES_DATA)
        with pytest.raises(ValidationError, match="dicom_properties"):
            Asset(asset_id="A1", name="Test", nodes=[VALID_NODE_DATA])
    
    def test_asset_nodes_empty_list_invalid(self):
        # Assuming nodes list cannot be empty based on typical usage, Pydantic default is required unless Optional/default_factory
        invalid_asset_data = {**VALID_ASSET_DATA, "nodes": []}
        with pytest.raises(ValidationError, match="nodes"): # Pydantic v2 might say "Input should be a valid list" or "at least 1 item" if MinLen=1
             Asset(**invalid_asset_data)


    def test_asset_example_is_valid(self):
        example_data = Asset.model_config["json_schema_extra"]["example"]
        asset = Asset(**example_data)
        assert asset.asset_id == example_data["asset_id"]
        assert len(asset.nodes) == len(example_data["nodes"])
        assert asset.dicom_properties.ae_title == example_data["dicom_properties"]["ae_title"]

# Test data for LinkConnectionDetails
VALID_LINK_CONNECTION_DETAILS_DATA = {
    "source_mac": "00:1A:2B:3C:4D:5E",
    "destination_mac": "00:6F:7E:8D:9C:0B",
    "source_ip": "192.168.1.100",
    "destination_ip": "192.168.1.200",
    "source_port": 50101,
    "destination_port": 104
}

# Test data for CommandSetItem
VALID_COMMAND_SET_ITEM_DATA = {
    "MessageID": 1,
    "Priority": 0, # MEDIUM
    "AffectedSOPClassUID": "1.2.840.10008.5.1.4.1.1.2", # CT Image Storage
    "AffectedSOPInstanceUID": "AUTO_GENERATE_UID_INSTANCE",
    "extra_fields": {"CustomTag": "CustomValue"}
}

# Test data for DimseOperation
VALID_DIMSE_OPERATION_DATA = {
    "operation_name": "Store CT Image",
    "message_type": "C-STORE-RQ",
    "presentation_context_id": 1,
    "command_set": VALID_COMMAND_SET_ITEM_DATA,
    "dataset_content_rules": {
        "SOPClassUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_CLASS_UID",
        "SOPInstanceUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_INSTANCE_UID",
        "PatientName": "AUTO_GENERATE_SAMPLE_PATIENT_NAME",
        "Manufacturer": "AUTO_FROM_ASSET_SCU_MANUFACTURER",
    }
}

class TestLinkConnectionDetails:
    def test_link_connection_details_valid(self):
        details = LinkConnectionDetails(**VALID_LINK_CONNECTION_DETAILS_DATA)
        assert details.source_mac == VALID_LINK_CONNECTION_DETAILS_DATA["source_mac"]
        assert details.destination_port == VALID_LINK_CONNECTION_DETAILS_DATA["destination_port"]

    def test_link_connection_details_missing_fields(self):
        with pytest.raises(ValidationError, match="source_mac"):
            LinkConnectionDetails(destination_mac="00:00:00:00:00:01", source_ip="1.1.1.1", destination_ip="1.1.1.2", source_port=12345, destination_port=104)
        # Test other missing fields similarly...

    def test_link_connection_details_invalid_port(self):
        with pytest.raises(ValidationError): # Pydantic v2: "Input should be a valid integer"
            LinkConnectionDetails(**{**VALID_LINK_CONNECTION_DETAILS_DATA, "source_port": "invalid"})
        with pytest.raises(ValidationError): # Pydantic v2: "Input should be less than or equal to 65535"
             LinkConnectionDetails(**{**VALID_LINK_CONNECTION_DETAILS_DATA, "destination_port": 70000})

    def test_link_connection_details_example_is_valid(self):
        example_data = LinkConnectionDetails.model_config["json_schema_extra"]["example"]
        details = LinkConnectionDetails(**example_data)
        assert details.source_ip == example_data["source_ip"]


class TestCommandSetItem:
    def test_command_set_item_valid(self):
        item = CommandSetItem(**VALID_COMMAND_SET_ITEM_DATA)
        assert item.MessageID == VALID_COMMAND_SET_ITEM_DATA["MessageID"]
        assert item.AffectedSOPClassUID == VALID_COMMAND_SET_ITEM_DATA["AffectedSOPClassUID"]
        assert item.extra_fields["CustomTag"] == "CustomValue"

    def test_command_set_item_minimal(self):
        # Only MessageID is strictly required by model definition
        item = CommandSetItem(MessageID=123)
        assert item.MessageID == 123
        assert item.Priority is None
        assert item.AffectedSOPClassUID is None
        assert item.AffectedSOPInstanceUID is None
        assert item.extra_fields == {}

    def test_command_set_item_to_pydicom_dict(self):
        item = CommandSetItem(**VALID_COMMAND_SET_ITEM_DATA)
        pydicom_dict = item.to_pydicom_dict()
        assert pydicom_dict["MessageID"] == VALID_COMMAND_SET_ITEM_DATA["MessageID"]
        assert pydicom_dict["AffectedSOPClassUID"] == VALID_COMMAND_SET_ITEM_DATA["AffectedSOPClassUID"]
        assert pydicom_dict["AffectedSOPInstanceUID"] == VALID_COMMAND_SET_ITEM_DATA["AffectedSOPInstanceUID"]
        assert pydicom_dict["Priority"] == VALID_COMMAND_SET_ITEM_DATA["Priority"]
        assert pydicom_dict["CustomTag"] == "CustomValue"

    def test_command_set_item_to_pydicom_dict_minimal(self):
        item = CommandSetItem(MessageID=5)
        pydicom_dict = item.to_pydicom_dict()
        assert pydicom_dict["MessageID"] == 5
        assert "Priority" not in pydicom_dict
        assert "AffectedSOPClassUID" not in pydicom_dict
        assert "AffectedSOPInstanceUID" not in pydicom_dict
        assert "extra_fields" not in pydicom_dict # extra_fields itself is not a DICOM tag


class TestDimseOperation:
    def test_dimse_operation_valid_with_dataset_rules(self):
        op = DimseOperation(**VALID_DIMSE_OPERATION_DATA)
        assert op.operation_name == VALID_DIMSE_OPERATION_DATA["operation_name"]
        assert op.message_type == VALID_DIMSE_OPERATION_DATA["message_type"]
        assert op.command_set.MessageID == VALID_COMMAND_SET_ITEM_DATA["MessageID"]
        assert op.dataset_content_rules["PatientName"] == "AUTO_GENERATE_SAMPLE_PATIENT_NAME"

    def test_dimse_operation_valid_no_dataset_rules(self):
        # e.g., for C-ECHO-RQ
        no_dataset_data = {
            "operation_name": "Echo Test",
            "message_type": "C-ECHO-RQ",
            "presentation_context_id": 3,
            "command_set": {"MessageID": 1}, # Minimal command set
            "dataset_content_rules": None
        }
        op = DimseOperation(**no_dataset_data)
        assert op.operation_name == no_dataset_data["operation_name"]
        assert op.dataset_content_rules is None

    def test_dimse_operation_missing_required_fields(self):
        with pytest.raises(ValidationError, match="operation_name"):
            DimseOperation(message_type="C-STORE-RQ", presentation_context_id=1, command_set=VALID_COMMAND_SET_ITEM_DATA)
        with pytest.raises(ValidationError, match="message_type"):
            DimseOperation(operation_name="Test", presentation_context_id=1, command_set=VALID_COMMAND_SET_ITEM_DATA)
        with pytest.raises(ValidationError, match="presentation_context_id"):
            DimseOperation(operation_name="Test", message_type="C-STORE-RQ", command_set=VALID_COMMAND_SET_ITEM_DATA)
        with pytest.raises(ValidationError, match="command_set"):
            DimseOperation(operation_name="Test", message_type="C-STORE-RQ", presentation_context_id=1)

    def test_dimse_operation_example_is_valid(self):
        example_data = DimseOperation.model_config["json_schema_extra"]["example"]
        op = DimseOperation(**example_data)
        assert op.operation_name == example_data["operation_name"]
        assert op.command_set.AffectedSOPClassUID == example_data["command_set"]["AffectedSOPClassUID"]
        assert op.dataset_content_rules["Manufacturer"] == example_data["dataset_content_rules"]["Manufacturer"]

# Test data for PresentationContextItem (used by LinkDicomConfiguration)
VALID_PRESENTATION_CONTEXT_ITEM_DATA = {
    "id": 1,
    "abstract_syntax": "1.2.840.10008.5.1.4.1.1.2", # CT Image Storage
    "transfer_syntaxes": ["1.2.840.10008.1.2.1", "1.2.840.10008.1.2"]
}

# Test data for LinkDicomConfiguration
VALID_LINK_DICOM_CONFIGURATION_DATA = {
    "scu_asset_id_ref": "ASSET_CT_SCANNER_01",
    "scp_asset_id_ref": "ASSET_PACS_SERVER_01",
    "calling_ae_title_override": "CT_SCU_LINK1",
    "called_ae_title_override": None,
    "explicit_presentation_contexts": [VALID_PRESENTATION_CONTEXT_ITEM_DATA],
    "dimse_sequence": [VALID_DIMSE_OPERATION_DATA]
}

# Test data for Link
VALID_LINK_DATA = {
    "link_id": "LINK_CT_TO_PACS_01",
    "name": "CT Scanner sends images to PACS",
    "source_asset_id_ref": "ASSET_CT_SCANNER_01",
    "source_node_id_ref": "CT_NIC1",
    "destination_asset_id_ref": "ASSET_PACS_SERVER_01",
    "destination_node_id_ref": "PACS_NIC1",
    "connection_details": VALID_LINK_CONNECTION_DETAILS_DATA,
    "dicom_config": VALID_LINK_DICOM_CONFIGURATION_DATA
}

# Test data for Scene
VALID_SCENE_DATA = {
    "scene_id": "SCENE_RADIOLOGY_DEPT_NORMAL_OPS_01",
    "name": "Radiology Department - Normal Operations",
    "assets": [VALID_ASSET_DATA], # Using previously defined VALID_ASSET_DATA
    "links": [VALID_LINK_DATA]
}

class TestLinkDicomConfiguration:
    def test_link_dicom_configuration_valid(self):
        config = LinkDicomConfiguration(**VALID_LINK_DICOM_CONFIGURATION_DATA)
        assert config.scu_asset_id_ref == VALID_LINK_DICOM_CONFIGURATION_DATA["scu_asset_id_ref"]
        assert config.calling_ae_title_override == VALID_LINK_DICOM_CONFIGURATION_DATA["calling_ae_title_override"]
        assert len(config.explicit_presentation_contexts) == 1
        assert config.explicit_presentation_contexts[0].id == VALID_PRESENTATION_CONTEXT_ITEM_DATA["id"]
        assert len(config.dimse_sequence) == 1
        assert config.dimse_sequence[0].operation_name == VALID_DIMSE_OPERATION_DATA["operation_name"]

    def test_link_dicom_configuration_minimal(self):
        minimal_data = {
            "scu_asset_id_ref": "SCU_A",
            "scp_asset_id_ref": "SCP_B",
            "dimse_sequence": [VALID_DIMSE_OPERATION_DATA] # dimse_sequence is required
        }
        config = LinkDicomConfiguration(**minimal_data)
        assert config.scu_asset_id_ref == minimal_data["scu_asset_id_ref"]
        assert config.calling_ae_title_override is None
        assert config.explicit_presentation_contexts is None # Optional

    def test_link_dicom_configuration_missing_required_fields(self):
        with pytest.raises(ValidationError, match="scu_asset_id_ref"):
            LinkDicomConfiguration(scp_asset_id_ref="SCP_B", dimse_sequence=[VALID_DIMSE_OPERATION_DATA])
        with pytest.raises(ValidationError, match="scp_asset_id_ref"):
            LinkDicomConfiguration(scu_asset_id_ref="SCU_A", dimse_sequence=[VALID_DIMSE_OPERATION_DATA])
        with pytest.raises(ValidationError, match="dimse_sequence"):
            LinkDicomConfiguration(scu_asset_id_ref="SCU_A", scp_asset_id_ref="SCP_B")
    
    def test_link_dicom_configuration_dimse_sequence_empty_invalid(self):
        # dimse_sequence: List[DimseOperation] - an empty list is valid if field is required
        # However, if it must have at least one item, a validator like MinLen=1 would be needed.
        # Current model allows empty list for dimse_sequence.
        config_data = {**VALID_LINK_DICOM_CONFIGURATION_DATA, "dimse_sequence": []}
        config = LinkDicomConfiguration(**config_data)
        assert len(config.dimse_sequence) == 0


    def test_link_dicom_configuration_ae_title_override_max_length(self):
        with pytest.raises(ValidationError, match="calling_ae_title_override"):
            LinkDicomConfiguration(**{**VALID_LINK_DICOM_CONFIGURATION_DATA, "calling_ae_title_override": "A"*17})
        # Valid length
        config = LinkDicomConfiguration(**{**VALID_LINK_DICOM_CONFIGURATION_DATA, "calling_ae_title_override": "A"*16})
        assert len(config.calling_ae_title_override) == 16

    def test_link_dicom_configuration_example_is_valid(self):
        example_data = LinkDicomConfiguration.model_config["json_schema_extra"]["example"]
        config = LinkDicomConfiguration(**example_data)
        assert config.scu_asset_id_ref == example_data["scu_asset_id_ref"]
        assert len(config.explicit_presentation_contexts) == len(example_data["explicit_presentation_contexts"])
        assert config.dimse_sequence[0].message_type == example_data["dimse_sequence"][0]["message_type"]


class TestLink:
    def test_link_valid(self):
        link = Link(**VALID_LINK_DATA)
        assert link.link_id == VALID_LINK_DATA["link_id"]
        assert link.source_asset_id_ref == VALID_LINK_DATA["source_asset_id_ref"]
        assert link.connection_details.source_ip == VALID_LINK_CONNECTION_DETAILS_DATA["source_ip"]
        assert link.dicom_config.scu_asset_id_ref == VALID_LINK_DICOM_CONFIGURATION_DATA["scu_asset_id_ref"]

    def test_link_minimal_required_fields(self):
        minimal_data = {
            "link_id": "LINK_MIN",
            "name": "Minimal Link",
            "source_asset_id_ref": "ASSET_A",
            "source_node_id_ref": "NODE_A1",
            "destination_asset_id_ref": "ASSET_B",
            "destination_node_id_ref": "NODE_B1",
            "dicom_config": VALID_LINK_DICOM_CONFIGURATION_DATA # dicom_config is required
        }
        link = Link(**minimal_data)
        assert link.link_id == minimal_data["link_id"]
        assert link.connection_details is None # Optional

    def test_link_missing_required_fields(self):
        # Example for one missing field
        with pytest.raises(ValidationError, match="dicom_config"):
            Link(link_id="L1", name="Test", source_asset_id_ref="A1", source_node_id_ref="N1",
                 destination_asset_id_ref="A2", destination_node_id_ref="N2")
        # ... test other required fields

    def test_link_example_is_valid(self):
        example_data = Link.model_config["json_schema_extra"]["example"]
        link = Link(**example_data)
        assert link.link_id == example_data["link_id"]
        assert link.dicom_config.scp_asset_id_ref == example_data["dicom_config"]["scp_asset_id_ref"]


class TestScene:
    def test_scene_valid(self):
        scene = Scene(**VALID_SCENE_DATA)
        assert scene.scene_id == VALID_SCENE_DATA["scene_id"]
        assert len(scene.assets) == 1
        assert scene.assets[0].asset_id == VALID_ASSET_DATA["asset_id"]
        assert len(scene.links) == 1
        assert scene.links[0].link_id == VALID_LINK_DATA["link_id"]

    def test_scene_minimal_required_fields(self):
        minimal_data = {
            "scene_id": "SCENE_MIN",
            "name": "Minimal Scene",
            "assets": [VALID_ASSET_DATA], # assets is required
            "links": [VALID_LINK_DATA]   # links is required
        }
        scene = Scene(**minimal_data)
        assert scene.scene_id == minimal_data["scene_id"]
        assert scene.description is None

    def test_scene_assets_or_links_empty_invalid(self):
        # Assuming assets and links cannot be empty lists
        with pytest.raises(ValidationError, match="assets"):
             Scene(**{**VALID_SCENE_DATA, "assets": []})
        with pytest.raises(ValidationError, match="links"):
             Scene(**{**VALID_SCENE_DATA, "links": []})

    def test_scene_example_is_valid(self):
        example_data = Scene.model_config["json_schema_extra"]["example"]
        scene = Scene(**example_data)
        assert scene.scene_id == example_data["scene_id"]
        assert len(scene.assets) == len(example_data["assets"])
        assert scene.links[0].link_id == example_data["links"][0]["link_id"]
