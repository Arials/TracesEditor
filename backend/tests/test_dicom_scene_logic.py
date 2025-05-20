import pytest
import json
from pathlib import Path

from pydantic import ValidationError

from backend.protocols.dicom.models import (
    Asset, AssetDicomProperties, SopClassDefinition, Node, LinkConnectionDetails
)
from backend.protocols.dicom.resolver import (
    resolve_asset_dicom_properties,
    AssetTemplateNotFoundError,
    InvalidAssetTemplateError
)
from backend.protocols.dicom.pdu_wrappers import (
    create_scene_associate_rq_pdu,
    create_scene_associate_ac_pdu,
    DEFAULT_APPLICATION_CONTEXT_NAME
)
from backend.protocols.dicom.models import (
    LinkDicomConfiguration, 
    PresentationContextItem as ModelPresentationContextItem,
    DimseOperation,
    CommandSetItem
)
from backend.protocols.dicom.dataset_builder import (
    _build_command_dataset,
    _build_data_dataset,
    generate_p_data_tf_pdus_for_dimse_operation,
    SAMPLE_PATIENT_NAMES
)
from backend.protocols.dicom.scene_processor import DicomSceneProcessor # For testing auto-defaults
from backend.protocols.dicom.models import Scene, Link # For scene processor tests
from pydicom.dataset import Dataset
from pydicom.uid import generate_uid as pydicom_generate_uid


# Helper to get the path to the test templates directory
@pytest.fixture
def test_templates_dir(tmp_path: Path) -> Path:
    # Using tmp_path provided by pytest for isolated test files
    # If you need to use the ones created in backend/tests/test_asset_templates,
    # you'd construct the path relative to this test file.
    # For now, let's assume we'll create templates directly in tmp_path for full isolation.
    # templates_dir = tmp_path / "test_asset_templates"
    # templates_dir.mkdir(exist_ok=True)
    # return templates_dir

    # For this iteration, let's use the pre-created ones relative to the project structure
    # This assumes tests are run from the project root.
    # Adjust if your test runner has a different CWD.
    current_file_dir = Path(__file__).parent
    templates_dir = current_file_dir / "test_asset_templates"
    return templates_dir


# Sample data for AssetDicomProperties to be used in Asset instances
SAMPLE_ASSET_DICOM_PROPS_DATA = {
    "ae_title": "ASSET_AE",
    "implementation_class_uid": "1.2.3.4.5.666",
    "supported_sop_classes": [
        {
            "sop_class_uid": "1.2.840.10008.5.1.4.1.1.4", # MR Image Storage
            "role": "SCU",
            "transfer_syntaxes": ["1.2.840.10008.1.2.1"]
        }
    ]
}

SAMPLE_NODE_DATA = {
    "node_id": "N1", "ip_address": "1.1.1.1", "mac_address": "AA:AA:AA:AA:AA:AA"
}


class TestDicomAssetResolver:
    def test_resolve_no_template_referenced(self, test_templates_dir: Path):
        asset_props = AssetDicomProperties(**SAMPLE_ASSET_DICOM_PROPS_DATA)
        asset = Asset(
            asset_id="ASSET_NO_TPL",
            name="No Template Asset",
            nodes=[Node(**SAMPLE_NODE_DATA)],
            dicom_properties=asset_props
        )
        
        resolved_props = resolve_asset_dicom_properties(asset, test_templates_dir)
        
        assert resolved_props.ae_title == "ASSET_AE"
        assert resolved_props.implementation_class_uid == "1.2.3.4.5.666"
        assert resolved_props.manufacturer is None # Not set in asset_props
        # Ensure it's a deep copy, not the same object
        assert resolved_props is not asset.dicom_properties 
        assert resolved_props == asset.dicom_properties

    def test_resolve_with_valid_template_no_overrides(self, test_templates_dir: Path):
        # Asset's dicom_properties are minimal, relying mostly on template
        minimal_asset_props_data = {
            "ae_title": "MINIMAL_FOR_TPL", # This is required
            "implementation_class_uid": "1.2.3.4.5.MINIMAL", # Required
            "supported_sop_classes": [] # Required, can be empty if template provides them
        }
        asset_props = AssetDicomProperties(**minimal_asset_props_data)
        asset = Asset(
            asset_id="ASSET_WITH_TPL_NO_OVERRIDE",
            name="Asset With Template",
            nodes=[Node(**SAMPLE_NODE_DATA)],
            asset_template_id_ref="TEST_TEMPLATE_A", # Uses the pre-created template
            dicom_properties=asset_props 
        )

        resolved_props = resolve_asset_dicom_properties(asset, test_templates_dir)

        # Values should come from TEST_TEMPLATE_A.json, except for those explicitly set by asset_props
        assert resolved_props.ae_title == "MINIMAL_FOR_TPL" # Overridden by asset
        assert resolved_props.implementation_class_uid == "1.2.3.4.5.MINIMAL" # Overridden by asset
        
        # These should come from the template
        assert resolved_props.manufacturer == "Template Manufacturer"
        assert resolved_props.model_name == "Template Model X"
        assert resolved_props.implementation_version_name == "TemplateVersion1.0"
        assert resolved_props.software_versions == ["TPL:1.0", "FW:0.9"]
        assert resolved_props.device_serial_number == "TPL_SN001"
        
        # supported_sop_classes: if asset_props.supported_sop_classes was empty and template had some,
        # the Pydantic model_copy(update=...) with exclude_unset=True on the override
        # might lead to the empty list from asset_props "winning" if it was explicitly set (even if empty).
        # Let's check the behavior. The current resolver logic:
        # `resolved_properties = base_properties.model_copy(update=override_props_dict)`
        # If `override_props_dict` contains `supported_sop_classes` (even as []), it will replace.
        # So, if `asset_props.supported_sop_classes` is `[]`, resolved will be `[]`.
        # If `asset_props.supported_sop_classes` was not set at all (field omitted), then template's would be used.
        # Pydantic models require `supported_sop_classes`, so it's always "set".
        assert len(resolved_props.supported_sop_classes) == 0 # Because asset_props provided an empty list

    def test_resolve_with_valid_template_and_overrides(self, test_templates_dir: Path):
        asset_override_props_data = {
            "ae_title": "OVERRIDE_AE", # Override
            "implementation_class_uid": "1.2.3.4.5.OVERRIDE", # Override
            "manufacturer": "Asset Manufacturer", # Override
            "supported_sop_classes": [ # Override
                {
                    "sop_class_uid": "1.2.840.10008.5.1.4.1.1.7", # Secondary Capture
                    "role": "SCU",
                    "transfer_syntaxes": ["1.2.840.10008.1.2"]
                }
            ]
        }
        asset_props = AssetDicomProperties(**asset_override_props_data)
        asset = Asset(
            asset_id="ASSET_WITH_TPL_OVERRIDE",
            name="Asset With Template and Overrides",
            nodes=[Node(**SAMPLE_NODE_DATA)],
            asset_template_id_ref="TEST_TEMPLATE_A",
            dicom_properties=asset_props
        )

        resolved_props = resolve_asset_dicom_properties(asset, test_templates_dir)

        assert resolved_props.ae_title == "OVERRIDE_AE"
        assert resolved_props.implementation_class_uid == "1.2.3.4.5.OVERRIDE"
        assert resolved_props.manufacturer == "Asset Manufacturer"
        
        # These should still come from template as they were not overridden
        assert resolved_props.model_name == "Template Model X" 
        assert resolved_props.implementation_version_name == "TemplateVersion1.0"

        # SOP classes should be fully from the asset's override
        assert len(resolved_props.supported_sop_classes) == 1
        assert resolved_props.supported_sop_classes[0].sop_class_uid == "1.2.840.10008.5.1.4.1.1.7"

    def test_resolve_template_not_found(self, test_templates_dir: Path):
        asset_props = AssetDicomProperties(**SAMPLE_ASSET_DICOM_PROPS_DATA)
        asset = Asset(
            asset_id="ASSET_BAD_TPL_REF",
            name="Asset with Bad Template Ref",
            nodes=[Node(**SAMPLE_NODE_DATA)],
            asset_template_id_ref="NON_EXISTENT_TEMPLATE",
            dicom_properties=asset_props
        )
        
        with pytest.raises(AssetTemplateNotFoundError) as excinfo:
            resolve_asset_dicom_properties(asset, test_templates_dir)
        assert "NON_EXISTENT_TEMPLATE.json" in str(excinfo.value)

    def test_resolve_invalid_json_template(self, test_templates_dir: Path):
        # Create a malformed JSON template
        malformed_template_path = test_templates_dir / "MALFORMED_TEMPLATE.json"
        with open(malformed_template_path, 'w') as f:
            f.write("{ 'bad_json': true, ") # Invalid JSON syntax

        asset_props = AssetDicomProperties(**SAMPLE_ASSET_DICOM_PROPS_DATA)
        asset = Asset(
            asset_id="ASSET_MALFORMED_TPL",
            name="Asset with Malformed Template",
            nodes=[Node(**SAMPLE_NODE_DATA)],
            asset_template_id_ref="MALFORMED_TEMPLATE",
            dicom_properties=asset_props
        )

        with pytest.raises(InvalidAssetTemplateError) as excinfo:
            resolve_asset_dicom_properties(asset, test_templates_dir)
        assert "Invalid JSON" in str(excinfo.value)
        
        malformed_template_path.unlink() # Clean up

    def test_resolve_template_missing_dicom_properties_key(self, test_templates_dir: Path):
        # Create a template without the 'dicom_properties' key
        no_props_template_path = test_templates_dir / "NO_PROPS_TEMPLATE.json"
        with open(no_props_template_path, 'w') as f:
            json.dump({"template_id": "NO_PROPS_TEMPLATE"}, f)

        asset_props = AssetDicomProperties(**SAMPLE_ASSET_DICOM_PROPS_DATA)
        asset = Asset(
            asset_id="ASSET_NO_PROPS_TPL",
            name="Asset with No Props Key Template",
            nodes=[Node(**SAMPLE_NODE_DATA)],
            asset_template_id_ref="NO_PROPS_TEMPLATE",
            dicom_properties=asset_props
        )

        with pytest.raises(InvalidAssetTemplateError) as excinfo:
            resolve_asset_dicom_properties(asset, test_templates_dir)
        assert "missing the 'dicom_properties' key" in str(excinfo.value)

        no_props_template_path.unlink() # Clean up

    def test_resolve_template_invalid_dicom_properties_structure(self, test_templates_dir: Path):
        # Create a template with invalid structure for 'dicom_properties'
        bad_props_template_path = test_templates_dir / "BAD_PROPS_TEMPLATE.json"
        with open(bad_props_template_path, 'w') as f:
            json.dump({"dicom_properties": {"ae_title": 12345}}, f) # ae_title should be str

        asset_props = AssetDicomProperties(**SAMPLE_ASSET_DICOM_PROPS_DATA)
        asset = Asset(
            asset_id="ASSET_BAD_PROPS_TPL",
            name="Asset with Bad Props Structure Template",
            nodes=[Node(**SAMPLE_NODE_DATA)],
            asset_template_id_ref="BAD_PROPS_TEMPLATE",
            dicom_properties=asset_props
        )

        with pytest.raises(InvalidAssetTemplateError) as excinfo:
            resolve_asset_dicom_properties(asset, test_templates_dir)
        assert "Could not parse 'dicom_properties'" in str(excinfo.value)
        
        bad_props_template_path.unlink() # Clean up


@pytest.fixture
def sample_resolved_scu_props() -> AssetDicomProperties:
    return AssetDicomProperties(
        ae_title="SCU_AE_RESOLVED",
        implementation_class_uid="1.2.3.SCU.IMPL.UID",
        implementation_version_name="SCU_IMPL_V1",
        manufacturer="SCU Manufacturer",
        model_name="SCU Model",
        supported_sop_classes=[] 
    )

@pytest.fixture
def sample_resolved_scp_props() -> AssetDicomProperties:
    return AssetDicomProperties(
        ae_title="SCP_AE_RESOLVED",
        implementation_class_uid="1.2.3.SCP.IMPL.UID",
        implementation_version_name="SCP_IMPL_V1",
        manufacturer="SCP Manufacturer",
        model_name="SCP Model",
        supported_sop_classes=[]
    )

@pytest.fixture
def sample_link_dicom_config() -> LinkDicomConfiguration:
    return LinkDicomConfiguration(
        scu_asset_id_ref="ASSET_SCU",
        scp_asset_id_ref="ASSET_SCP",
        explicit_presentation_contexts=[
            ModelPresentationContextItem(id=1, abstract_syntax="1.2.840.10008.1.1", transfer_syntaxes=["1.2.840.10008.1.2"])
        ],
        dimse_sequence=[] # Not relevant for PDU wrapper tests directly
    )


class TestPduWrappers:
    def test_create_scene_associate_rq_pdu_basic(
        self, mocker, sample_link_dicom_config, sample_resolved_scu_props, sample_resolved_scp_props
    ):
        mock_create_rq_util = mocker.patch("backend.protocols.dicom.pdu_wrappers.utils.create_associate_rq_pdu")
        mock_create_rq_util.return_value = b"test_rq_pdu_bytes"

        result_pdu = create_scene_associate_rq_pdu(
            link_dicom_config=sample_link_dicom_config,
            resolved_scu_dicom_props=sample_resolved_scu_props,
            resolved_scp_dicom_props=sample_resolved_scp_props
        )

        assert result_pdu == b"test_rq_pdu_bytes"
        mock_create_rq_util.assert_called_once()
        call_args = mock_create_rq_util.call_args[1] # Get kwargs

        assert call_args["calling_ae_title"] == sample_resolved_scu_props.ae_title
        assert call_args["called_ae_title"] == sample_resolved_scp_props.ae_title
        assert call_args["application_context_name"] == DEFAULT_APPLICATION_CONTEXT_NAME
        assert len(call_args["presentation_contexts_input"]) == 1
        assert call_args["presentation_contexts_input"][0]["id"] == 1
        assert call_args["our_implementation_class_uid_str"] == sample_resolved_scu_props.implementation_class_uid
        assert call_args["our_implementation_version_name"] == sample_resolved_scu_props.implementation_version_name

    def test_create_scene_associate_rq_pdu_with_overrides(
        self, mocker, sample_link_dicom_config, sample_resolved_scu_props, sample_resolved_scp_props
    ):
        mock_create_rq_util = mocker.patch("backend.protocols.dicom.pdu_wrappers.utils.create_associate_rq_pdu")
        
        sample_link_dicom_config.calling_ae_title_override = "OVERRIDE_CALLING_AE"
        sample_link_dicom_config.called_ae_title_override = "OVERRIDE_CALLED_AE"
        
        create_scene_associate_rq_pdu(
            link_dicom_config=sample_link_dicom_config,
            resolved_scu_dicom_props=sample_resolved_scu_props,
            resolved_scp_dicom_props=sample_resolved_scp_props,
            max_pdu_length_override=8192,
            application_context_name_override="1.2.3.APP_CONTEXT"
        )
        
        call_args = mock_create_rq_util.call_args[1]
        assert call_args["calling_ae_title"] == "OVERRIDE_CALLING_AE"
        assert call_args["called_ae_title"] == "OVERRIDE_CALLED_AE"
        assert call_args["application_context_name"] == "1.2.3.APP_CONTEXT"
        assert call_args["max_pdu_length"] == 8192

    def test_create_scene_associate_rq_pdu_no_explicit_contexts(
        self, mocker, sample_link_dicom_config, sample_resolved_scu_props, sample_resolved_scp_props
    ):
        mock_create_rq_util = mocker.patch("backend.protocols.dicom.pdu_wrappers.utils.create_associate_rq_pdu")
        sample_link_dicom_config.explicit_presentation_contexts = None # Simulate auto-mode before negotiation
        
        create_scene_associate_rq_pdu(
            link_dicom_config=sample_link_dicom_config,
            resolved_scu_dicom_props=sample_resolved_scu_props,
            resolved_scp_dicom_props=sample_resolved_scp_props
        )
        call_args = mock_create_rq_util.call_args[1]
        assert call_args["presentation_contexts_input"] == []


    def test_create_scene_associate_ac_pdu_basic(
        self, mocker, sample_resolved_scp_props
    ):
        mock_create_ac_util = mocker.patch("backend.protocols.dicom.pdu_wrappers.utils.create_associate_ac_pdu")
        mock_create_ac_util.return_value = b"test_ac_pdu_bytes"

        rq_calling_ae = "RQ_CALLING_AE"
        rq_called_ae = "RQ_CALLED_AE"
        app_context = "1.2.840.10008.3.1.1.1"
        pc_results_input = [{"id": 1, "result": 0, "transfer_syntax": "1.2.840.10008.1.2"}]

        result_pdu = create_scene_associate_ac_pdu(
            original_rq_calling_ae_title=rq_calling_ae,
            original_rq_called_ae_title=rq_called_ae,
            resolved_scp_dicom_props=sample_resolved_scp_props,
            application_context_name=app_context,
            presentation_contexts_results_input=pc_results_input
        )

        assert result_pdu == b"test_ac_pdu_bytes"
        mock_create_ac_util.assert_called_once()
        call_args = mock_create_ac_util.call_args[1]

        assert call_args["calling_ae_title"] == rq_calling_ae
        assert call_args["called_ae_title"] == rq_called_ae
        assert call_args["application_context_name"] == app_context
        assert call_args["presentation_contexts_results_input"] == pc_results_input
        assert call_args["responding_implementation_class_uid_str"] == sample_resolved_scp_props.implementation_class_uid
        assert call_args["responding_implementation_version_name"] == sample_resolved_scp_props.implementation_version_name

    def test_create_scene_associate_ac_pdu_with_overrides(
        self, mocker, sample_resolved_scp_props
    ):
        mock_create_ac_util = mocker.patch("backend.protocols.dicom.pdu_wrappers.utils.create_associate_ac_pdu")
        
        create_scene_associate_ac_pdu(
            original_rq_calling_ae_title="RQ_CALLING",
            original_rq_called_ae_title="RQ_CALLED",
            resolved_scp_dicom_props=sample_resolved_scp_props,
            application_context_name="APP_CTX",
            presentation_contexts_results_input=[],
            max_pdu_length_override=4096
        )
        
        call_args = mock_create_ac_util.call_args[1]
        assert call_args["max_pdu_length"] == 4096


@pytest.fixture
def sample_command_set_item() -> CommandSetItem:
    return CommandSetItem(
        MessageID=1,
        Priority=0,
        AffectedSOPClassUID="1.2.840.10008.5.1.4.1.1.2", # CT Image Storage
        AffectedSOPInstanceUID="1.2.3.AFFECTED.INSTANCE.UID"
    )

@pytest.fixture
def sample_dimse_operation(sample_command_set_item: CommandSetItem) -> DimseOperation:
    return DimseOperation(
        operation_name="Test C-STORE",
        message_type="C-STORE-RQ",
        presentation_context_id=1,
        command_set=sample_command_set_item,
        dataset_content_rules={
            "PatientName": "Test^Patient",
            "Modality": "CT"
        }
    )

class TestDatasetBuilder:
    def test_build_command_dataset_basic(self, sample_command_set_item: CommandSetItem):
        ds = _build_command_dataset(sample_command_set_item)
        assert ds.MessageID == 1
        assert ds.Priority == 0
        assert ds.AffectedSOPClassUID == "1.2.840.10008.5.1.4.1.1.2"
        assert ds.AffectedSOPInstanceUID == "1.2.3.AFFECTED.INSTANCE.UID"

    def test_build_command_dataset_auto_generate_uid(self, mocker, sample_command_set_item: CommandSetItem):
        mock_generate_uid = mocker.patch("backend.protocols.dicom.dataset_builder.pydicom_generate_uid")
        mock_generate_uid.return_value = "GENERATED.UID.123"
        
        sample_command_set_item.AffectedSOPInstanceUID = "AUTO_GENERATE_UID_INSTANCE"
        ds = _build_command_dataset(sample_command_set_item)
        
        assert ds.AffectedSOPInstanceUID == "GENERATED.UID.123"
        mock_generate_uid.assert_called_once()

    def test_build_command_dataset_with_pre_generated_uid(self, mocker, sample_command_set_item: CommandSetItem):
        mock_generate_uid = mocker.patch("backend.protocols.dicom.dataset_builder.pydicom_generate_uid")
        
        sample_command_set_item.AffectedSOPInstanceUID = "AUTO_GENERATE_UID_INSTANCE"
        # This pre-generated UID should be used instead of calling pydicom_generate_uid
        ds = _build_command_dataset(
            sample_command_set_item, 
            auto_generated_affected_sop_instance_uid="PRE.GENERATED.UID.456"
        )
        
        assert ds.AffectedSOPInstanceUID == "PRE.GENERATED.UID.456"
        mock_generate_uid.assert_not_called() # Ensure it wasn't called because pre-gen was provided

    def test_build_command_dataset_extra_fields(self):
        command_item = CommandSetItem(MessageID=5, extra_fields={"MoveOriginatorApplicationEntityTitle": "ORIGIN_AET"})
        ds = _build_command_dataset(command_item)
        assert ds.MessageID == 5
        assert ds.MoveOriginatorApplicationEntityTitle == "ORIGIN_AET"

    def test_build_data_dataset_explicit_values(self, sample_resolved_scu_props, sample_resolved_scp_props):
        rules = {"PatientName": "Explicit^Name", "PatientID": "ID123"}
        # Command DS is needed for some rules, but not for purely explicit ones.
        # Provide a minimal one.
        command_ds = Dataset() 
        command_ds.AffectedSOPClassUID = "1.2.3"
        command_ds.AffectedSOPInstanceUID = "4.5.6"

        data_ds = _build_data_dataset(rules, command_ds, sample_resolved_scu_props, sample_resolved_scp_props)
        assert data_ds.PatientName == "Explicit^Name"
        assert data_ds.PatientID == "ID123"

    def test_build_data_dataset_auto_from_command(self, sample_resolved_scu_props, sample_resolved_scp_props):
        rules = {
            "SOPClassUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_CLASS_UID",
            "SOPInstanceUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_INSTANCE_UID"
        }
        command_ds = Dataset()
        command_ds.AffectedSOPClassUID = "CMD.SOP.CLASS.UID"
        command_ds.AffectedSOPInstanceUID = "CMD.SOP.INSTANCE.UID"
        
        data_ds = _build_data_dataset(rules, command_ds, sample_resolved_scu_props, sample_resolved_scp_props)
        assert data_ds.SOPClassUID == "CMD.SOP.CLASS.UID"
        assert data_ds.SOPInstanceUID == "CMD.SOP.INSTANCE.UID"

    def test_build_data_dataset_auto_generate_rules(self, mocker, sample_resolved_scu_props, sample_resolved_scp_props):
        mock_gen_uid = mocker.patch("backend.protocols.dicom.dataset_builder.pydicom_generate_uid")
        # Adjusted side_effect: SOPInstanceUID uses command's, so only Study and Series UIDs are generated here.
        # The order of generation in code is Study, then Series.
        mock_gen_uid.side_effect = ["GEN.STUDY.UID", "GEN.SERIES.UID"]
        
        mock_random_choice = mocker.patch("backend.protocols.dicom.dataset_builder.random.choice")
        mock_random_choice.return_value = "DOE^JANE"

        rules = {
            "SOPInstanceUID": "AUTO_GENERATE_UID_INSTANCE", # Should use command's if tag is SOPInstanceUID
            "StudyInstanceUID": "AUTO_GENERATE_UID_STUDY",
            "SeriesInstanceUID": "AUTO_GENERATE_UID_SERIES",
            "PatientName": "AUTO_GENERATE_SAMPLE_PATIENT_NAME"
        }
        command_ds = Dataset() # Minimal command_ds
        command_ds.AffectedSOPInstanceUID = "CMD.AFFECTED.SOP.INSTANCE.UID" # For SOPInstanceUID rule

        data_ds = _build_data_dataset(rules, command_ds, sample_resolved_scu_props, sample_resolved_scp_props)
        
        assert data_ds.SOPInstanceUID == "CMD.AFFECTED.SOP.INSTANCE.UID" # Takes from command_ds
        assert data_ds.StudyInstanceUID == "GEN.STUDY.UID"
        assert data_ds.SeriesInstanceUID == "GEN.SERIES.UID"
        assert data_ds.PatientName == "DOE^JANE"
        
        # pydicom_generate_uid called for Study and Series, but not for SOPInstanceUID (used command's)
        assert mock_gen_uid.call_count == 2 
        mock_random_choice.assert_called_once_with(SAMPLE_PATIENT_NAMES)

    def test_build_data_dataset_auto_from_asset(self, sample_resolved_scu_props, sample_resolved_scp_props):
        rules = {
            "Manufacturer": "AUTO_FROM_ASSET_SCU_MANUFACTURER",
            "StationName": "AUTO_FROM_ASSET_SCP_AE_TITLE", # Example, StationName might not be typical for AE
            "DeviceSerialNumber": "AUTO_FROM_ASSET_SCU_DEVICE_SERIAL_NUMBER", # SCU has no serial in fixture
            "SoftwareVersions": "AUTO_FROM_ASSET_SCP_SOFTWARE_VERSIONS" # SCP has no sw versions in fixture
        }
        sample_resolved_scu_props.manufacturer = "SCU Corp"
        sample_resolved_scu_props.device_serial_number = None # Explicitly None
        sample_resolved_scp_props.ae_title = "SCP_AE_FOR_TEST"
        sample_resolved_scp_props.software_versions = ["SCP_SW_V1", "SCP_SW_V2"]

        command_ds = Dataset()
        data_ds = _build_data_dataset(rules, command_ds, sample_resolved_scu_props, sample_resolved_scp_props)

        assert data_ds.Manufacturer == "SCU Corp"
        assert data_ds.StationName == "SCP_AE_FOR_TEST"
        assert "DeviceSerialNumber" not in data_ds # Rule resulted in None, so tag not added
        assert data_ds.SoftwareVersions == ["SCP_SW_V1", "SCP_SW_V2"]

    def test_build_data_dataset_empty_rules(self, sample_resolved_scu_props, sample_resolved_scp_props):
        command_ds = Dataset()
        data_ds = _build_data_dataset({}, command_ds, sample_resolved_scu_props, sample_resolved_scp_props)
        assert data_ds is None

    def test_build_data_dataset_unknown_auto_rule(self, sample_resolved_scu_props, sample_resolved_scp_props):
        rules = {"UnknownTag": "AUTO_UNKNOWN_RULE"}
        command_ds = Dataset()
        data_ds = _build_data_dataset(rules, command_ds, sample_resolved_scu_props, sample_resolved_scp_props)
        # Unknown AUTO_ rule is treated as an explicit string value
        assert data_ds.UnknownTag == "AUTO_UNKNOWN_RULE"

    def test_generate_p_data_tf_pdus_for_dimse_operation_no_dataset(
        self, mocker, sample_dimse_operation, sample_resolved_scu_props, sample_resolved_scp_props
    ):
        mock_create_pdata_util = mocker.patch("backend.protocols.dicom.dataset_builder.pdu_utils.create_p_data_tf_pdu")
        mock_create_pdata_util.return_value = b"test_pdata_pdu"

        sample_dimse_operation.dataset_content_rules = None # e.g., C-ECHO

        pdus = generate_p_data_tf_pdus_for_dimse_operation(
            sample_dimse_operation, sample_resolved_scu_props, sample_resolved_scp_props
        )

        assert len(pdus) == 1 # Only command PDU
        assert pdus[0] == b"test_pdata_pdu"
        # Check that create_p_data_tf_pdu was called once for command
        mock_create_pdata_util.assert_called_once() 
        call_args_cmd = mock_create_pdata_util.call_args_list[0][1]
        assert call_args_cmd["is_command"] is True
        assert call_args_cmd["presentation_context_id"] == sample_dimse_operation.presentation_context_id

    def test_generate_p_data_tf_pdus_for_dimse_operation_with_dataset(
        self, mocker, sample_dimse_operation, sample_resolved_scu_props, sample_resolved_scp_props
    ):
        mock_create_pdata_util = mocker.patch("backend.protocols.dicom.dataset_builder.pdu_utils.create_p_data_tf_pdu")
        mock_create_pdata_util.side_effect = [b"command_pdu_bytes", b"data_pdu_bytes"]
        
        # sample_dimse_operation already has dataset_content_rules
        pdus = generate_p_data_tf_pdus_for_dimse_operation(
            sample_dimse_operation, sample_resolved_scu_props, sample_resolved_scp_props
        )

        assert len(pdus) == 2 # Command and Data PDUs
        assert pdus[0] == b"command_pdu_bytes"
        assert pdus[1] == b"data_pdu_bytes"
        
        assert mock_create_pdata_util.call_count == 2
        # Call 1 (Command)
        call_args_cmd = mock_create_pdata_util.call_args_list[0][1]
        assert call_args_cmd["is_command"] is True
        assert call_args_cmd["dimse_dataset"].MessageID == sample_dimse_operation.command_set.MessageID
        # Call 2 (Data)
        call_args_data = mock_create_pdata_util.call_args_list[1][1]
        assert call_args_data["is_command"] is False
        assert call_args_data["dimse_dataset"].PatientName == "Test^Patient" # From sample_dimse_operation rules

    def test_generate_p_data_tf_pdus_shared_uid_for_cstore(
        self, mocker, sample_resolved_scu_props, sample_resolved_scp_props
    ):
        mock_create_pdata_util = mocker.patch("backend.protocols.dicom.dataset_builder.pdu_utils.create_p_data_tf_pdu")
        mock_create_pdata_util.side_effect = [b"cmd_pdu", b"data_pdu"]
        
        mock_pydicom_generate_uid = mocker.patch("backend.protocols.dicom.dataset_builder.pydicom_generate_uid")
        mock_pydicom_generate_uid.return_value = "SHARED.INSTANCE.UID.789"

        cstore_op = DimseOperation(
            operation_name="C-STORE with shared UID",
            message_type="C-STORE-RQ",
            presentation_context_id=1,
            command_set=CommandSetItem(
                MessageID=10,
                AffectedSOPClassUID="1.2.3",
                AffectedSOPInstanceUID="AUTO_GENERATE_UID_INSTANCE" # Rule for command
            ),
            dataset_content_rules={
                "SOPInstanceUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_INSTANCE_UID" # Rule for data
            }
        )

        generate_p_data_tf_pdus_for_dimse_operation(
            cstore_op, sample_resolved_scu_props, sample_resolved_scp_props,
            shared_affected_sop_instance_uid="SHARED.INSTANCE.UID.789" # This should be passed by scene_processor
        )
        
        # Check that pydicom_generate_uid was NOT called inside _build_command_dataset
        # because shared_affected_sop_instance_uid was provided to generate_p_data_tf_pdus...
        # and then passed to _build_command_dataset.
        # Actually, the current logic in generate_p_data_tf_pdus_for_dimse_operation is:
        # if operation.command_set.AffectedSOPInstanceUID == "AUTO_GENERATE_UID_INSTANCE" and not shared_affected_sop_instance_uid:
        #    cmd_affected_sop_instance_uid = pydicom_generate_uid()
        # So if shared_affected_sop_instance_uid IS provided, pydicom_generate_uid is NOT called at that top level.
        # And _build_command_dataset receives this shared UID.
        mock_pydicom_generate_uid.assert_not_called()


        cmd_ds = mock_create_pdata_util.call_args_list[0][1]["dimse_dataset"]
        data_ds = mock_create_pdata_util.call_args_list[1][1]["dimse_dataset"]

        assert cmd_ds.AffectedSOPInstanceUID == "SHARED.INSTANCE.UID.789"
        assert data_ds.SOPInstanceUID == "SHARED.INSTANCE.UID.789"


class TestSceneProcessorAutoDefaults:
    @pytest.fixture
    def scu_asset_props_for_negotiation(self) -> AssetDicomProperties:
        return AssetDicomProperties(
            ae_title="SCU_NEGOTIATE",
            implementation_class_uid="1.2.3.SCU.N",
            supported_sop_classes=[
                SopClassDefinition(sop_class_uid="1.2.840.10008.1.1", role="SCU", transfer_syntaxes=["1.2.840.10008.1.2", "1.2.840.10008.1.2.1"]), # Verification
                SopClassDefinition(sop_class_uid="1.2.840.10008.5.1.4.1.1.2", role="SCU", transfer_syntaxes=["1.2.840.10008.1.2.1"]), # CT
                SopClassDefinition(sop_class_uid="1.2.840.10008.5.1.4.1.1.4", role="SCU", transfer_syntaxes=["1.2.840.10008.1.2.4.50"])  # MR
            ]
        )

    @pytest.fixture
    def scp_asset_props_for_negotiation(self) -> AssetDicomProperties:
        return AssetDicomProperties(
            ae_title="SCP_NEGOTIATE",
            implementation_class_uid="1.2.3.SCP.N",
            supported_sop_classes=[
                SopClassDefinition(sop_class_uid="1.2.840.10008.1.1", role="SCP", transfer_syntaxes=["1.2.840.10008.1.2.1"]), # Verification (only explicit)
                SopClassDefinition(sop_class_uid="1.2.840.10008.5.1.4.1.1.2", role="SCP", transfer_syntaxes=["1.2.840.10008.1.2", "1.2.840.10008.1.2.1"]), # CT (both)
                SopClassDefinition(sop_class_uid="1.2.840.10008.5.1.4.1.1.128", role="SCP", transfer_syntaxes=["1.2.840.10008.1.2"]) # PET (SCP only, SCU doesn't have)
            ]
        )
    
    @pytest.fixture
    def sample_scene_for_negotiation(
        self, scu_asset_props_for_negotiation, scp_asset_props_for_negotiation
    ) -> Scene:
        scu_asset = Asset(
            asset_id="SCU_ASSET_NEG", name="SCU Asset Neg", 
            nodes=[Node(node_id="N_SCU", ip_address="1.1.1.1", mac_address="AA:00", dicom_port=11111)],
            dicom_properties=scu_asset_props_for_negotiation
        )
        scp_asset = Asset(
            asset_id="SCP_ASSET_NEG", name="SCP Asset Neg",
            nodes=[Node(node_id="N_SCP", ip_address="2.2.2.2", mac_address="BB:00", dicom_port=104)],
            dicom_properties=scp_asset_props_for_negotiation
        )
        # Add a minimal valid link to satisfy Scene.links min_length=1
        dummy_link = Link(
            link_id="LNK_DUMMY_NEG", name="Dummy Link for Negotiation Scene",
            source_asset_id_ref="SCU_ASSET_NEG", source_node_id_ref="N_SCU",
            destination_asset_id_ref="SCP_ASSET_NEG", destination_node_id_ref="N_SCP",
            dicom_config=LinkDicomConfiguration(
                scu_asset_id_ref="SCU_ASSET_NEG", 
                scp_asset_id_ref="SCP_ASSET_NEG",
                dimse_sequence=[ # Minimal DIMSE sequence
                    DimseOperation(
                        operation_name="Dummy Echo", message_type="C-ECHO-RQ", presentation_context_id=1, # Assuming PC ID 1 will be valid
                        command_set=CommandSetItem(MessageID=1)
                    )
                ]
            )
        )
        return Scene(scene_id="NEG_SCENE", name="Negotiation Scene", assets=[scu_asset, scp_asset], links=[dummy_link])


    def test_negotiate_presentation_contexts_auto_mode(
        self, sample_scene_for_negotiation, scu_asset_props_for_negotiation, scp_asset_props_for_negotiation
    ):
        processor = DicomSceneProcessor(scene=sample_scene_for_negotiation)
        # Manually cache resolved properties for this test, as process_scene() would do
        processor._resolved_assets_cache["SCU_ASSET_NEG"] = scu_asset_props_for_negotiation
        processor._resolved_assets_cache["SCP_ASSET_NEG"] = scp_asset_props_for_negotiation

        link_dicom_cfg = LinkDicomConfiguration(
            scu_asset_id_ref="SCU_ASSET_NEG",
            scp_asset_id_ref="SCP_ASSET_NEG",
            explicit_presentation_contexts=None, # AUTO MODE
            dimse_sequence=[]
        )

        rq_contexts, ac_results = processor._negotiate_presentation_contexts(
            link_dicom_cfg, scu_asset_props_for_negotiation, scp_asset_props_for_negotiation
        )

        # Expected: Verification (1.1) and CT (1.1.2) should be negotiated. MR (1.1.4) should not.
        assert len(rq_contexts) == 2
        assert len(ac_results) == 2
        
        # Check Verification SOP Class (1.2.840.10008.1.1)
        ver_rq = next((pc for pc in rq_contexts if pc.abstract_syntax == "1.2.840.10008.1.1"), None)
        ver_ac = next((pc for pc in ac_results if pc["id"] == ver_rq.id), None) if ver_rq else None
        assert ver_rq is not None
        assert ver_rq.transfer_syntaxes == ["1.2.840.10008.1.2", "1.2.840.10008.1.2.1"] # SCU proposes all it supports
        assert ver_ac is not None
        assert ver_ac["result"] == 0 # Accepted
        assert ver_ac["transfer_syntax"] == "1.2.840.10008.1.2.1" # First common TS (SCP supports 1.2.1)

        # Check CT Image Storage (1.2.840.10008.5.1.4.1.1.2)
        ct_rq = next((pc for pc in rq_contexts if pc.abstract_syntax == "1.2.840.10008.5.1.4.1.1.2"), None)
        ct_ac = next((pc for pc in ac_results if pc["id"] == ct_rq.id), None) if ct_rq else None
        assert ct_rq is not None
        assert ct_rq.transfer_syntaxes == ["1.2.840.10008.1.2.1"] # SCU proposes all it supports
        assert ct_ac is not None
        assert ct_ac["result"] == 0 # Accepted
        assert ct_ac["transfer_syntax"] == "1.2.840.10008.1.2.1" # First common TS

        # Ensure link_dicom_cfg was updated
        assert link_dicom_cfg.explicit_presentation_contexts == rq_contexts


    def test_negotiate_presentation_contexts_explicit_mode(
        self, sample_scene_for_negotiation, scu_asset_props_for_negotiation, scp_asset_props_for_negotiation
    ):
        processor = DicomSceneProcessor(scene=sample_scene_for_negotiation)
        processor._resolved_assets_cache["SCU_ASSET_NEG"] = scu_asset_props_for_negotiation
        processor._resolved_assets_cache["SCP_ASSET_NEG"] = scp_asset_props_for_negotiation

        explicit_pcs = [
            ModelPresentationContextItem(id=1, abstract_syntax="1.2.840.10008.1.1", transfer_syntaxes=["1.2.840.10008.1.2"])
        ]
        link_dicom_cfg = LinkDicomConfiguration(
            scu_asset_id_ref="SCU_ASSET_NEG",
            scp_asset_id_ref="SCP_ASSET_NEG",
            explicit_presentation_contexts=list(explicit_pcs), # EXPLICIT MODE
            dimse_sequence=[]
        )
        original_explicit_pcs_copy = list(explicit_pcs) # Keep a copy

        rq_contexts, ac_results = processor._negotiate_presentation_contexts(
            link_dicom_cfg, scu_asset_props_for_negotiation, scp_asset_props_for_negotiation
        )
        
        assert rq_contexts == original_explicit_pcs_copy # Should use the explicit ones
        assert len(ac_results) == 1
        assert ac_results[0]["id"] == 1
        assert ac_results[0]["result"] == 0 # Assumes SCP accepts the first TS if any
        assert ac_results[0]["transfer_syntax"] == "1.2.840.10008.1.2"
        # Ensure link_dicom_cfg was NOT updated (it was already explicit)
        assert link_dicom_cfg.explicit_presentation_contexts == original_explicit_pcs_copy


    def test_default_dimse_sequence_generation_c_echo(
        self, mocker, sample_scene_for_negotiation, scu_asset_props_for_negotiation, scp_asset_props_for_negotiation
    ):
        # This test focuses on the part of process_scene that might add a default C-ECHO
        # We need to mock dependencies of process_scene to isolate this logic.
        
        # Mock dependencies called before DIMSE sequence generation
        mocker.patch.object(DicomSceneProcessor, "_derive_connection_details", return_value=LinkConnectionDetails(
            source_mac="00:00", destination_mac="00:01", source_ip="1.1.1.1", destination_ip="1.1.1.2", source_port=1, destination_port=2
        ))
        mocker.patch("backend.protocols.dicom.scene_processor.create_scene_associate_rq_pdu", return_value=b"mock_rq")
        mocker.patch("backend.protocols.dicom.scene_processor.create_scene_associate_ac_pdu", return_value=b"mock_ac")
        mock_generate_pdata_pdus = mocker.patch("backend.protocols.dicom.scene_processor.generate_p_data_tf_pdus_for_dimse_operation")
        mocker.patch("backend.protocols.dicom.scene_processor.generate_dicom_session_packet_list", return_value=[])


        processor = DicomSceneProcessor(scene=sample_scene_for_negotiation)
        processor._resolved_assets_cache["SCU_ASSET_NEG"] = scu_asset_props_for_negotiation
        processor._resolved_assets_cache["SCP_ASSET_NEG"] = scp_asset_props_for_negotiation

        # Setup a link where auto-negotiation will accept Verification
        link = Link(
            link_id="LNK_AUTO_ECHO", name="Auto Echo Link",
            source_asset_id_ref="SCU_ASSET_NEG", source_node_id_ref="N_SCU",
            destination_asset_id_ref="SCP_ASSET_NEG", destination_node_id_ref="N_SCP",
            dicom_config=LinkDicomConfiguration(
                scu_asset_id_ref="SCU_ASSET_NEG", scp_asset_id_ref="SCP_ASSET_NEG",
                explicit_presentation_contexts=None, # Auto-negotiate
                dimse_sequence=[] # Empty, so default C-ECHO might be added
            )
        )
        sample_scene_for_negotiation.links = [link]
        
        processor.process_scene()

        # Check if generate_p_data_tf_pdus_for_dimse_operation was called with a C-ECHO-RQ
        mock_generate_pdata_pdus.assert_called_once()
        call_args = mock_generate_pdata_pdus.call_args[1] # kwargs
        dimse_op_arg: DimseOperation = call_args["operation"]
        
        assert dimse_op_arg.message_type == "C-ECHO-RQ"
        assert dimse_op_arg.dataset_content_rules is None
        # Check that the presentation_context_id used for C-ECHO was one that was accepted for Verification
        # From the _negotiate_presentation_contexts test, Verification (1.2.840.10008.1.1) should get an ID (e.g. 1 or 3)
        # This requires a bit more introspection or a more direct way to test this part of process_scene.
        # For now, checking message_type is a good start.
        # The actual PC ID for Verification would be determined by the _negotiate_presentation_contexts call inside process_scene.
        # We know from the negotiation test that Verification (1.2.840.10008.1.1) is accepted.
        # The first negotiated context (Verification) will get ID 1.
        assert dimse_op_arg.presentation_context_id == 1 # Assuming Verification is the first one negotiated and gets ID 1.
