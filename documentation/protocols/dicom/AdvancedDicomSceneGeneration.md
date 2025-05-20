# Advanced DICOM Scene Generation

## 1. Overview

This document describes the advanced DICOM scene generation capabilities within the PcapAnonymizer application. This feature allows users to define complex DICOM communication scenarios involving multiple configurable "Assets" (DICOM devices) and specific "Links" (interactions) between them. The system processes these scene definitions to generate PCAP files that accurately reflect the specified DICOM communications, including dynamically populated DICOM datasets.

## 2. Core Concepts

The scene generation is built around a few core concepts:

*   **Scene:** The top-level container for a simulation. It defines all participating assets and the links between them.
*   **Asset:** Represents a DICOM device (e.g., CT Scanner, PACS Server, Modality Worklist SCU). Each asset has one or more network nodes and specific DICOM properties.
*   **Node:** Represents a network interface (IP address, MAC address, DICOM port) for an Asset.
*   **Link:** Defines a communication pathway and a sequence of DICOM interactions between two nodes (belonging to specific assets). It includes L2-L4 connection details and DICOM-specific configurations like A-ASSOCIATE parameters and a DIMSE message sequence.

## 3. Data Models

The scene generation relies on Pydantic models to define its structure. Key models are detailed below.

### 3.1. `Scene`

The root object for defining a simulation.

*   `scene_id` (str, required): Unique identifier for the scene.
*   `name` (str, required): User-friendly name for the scene.
*   `description` (str, optional): Detailed description of the scene.
*   `assets` (List[`Asset`], required, min_length=1): List of all DICOM assets in the scene.
*   `links` (List[`Link`], required, min_length=1): List of all communication links between assets.

**Example Snippet:**
```json
{
  "scene_id": "SCENE_RADIOLOGY_01",
  "name": "Radiology Dept - CT to PACS",
  "assets": [ /* ... Asset objects ... */ ],
  "links": [ /* ... Link objects ... */ ]
}
```

### 3.2. `Asset`

Represents a DICOM device.

*   `asset_id` (str, required): Unique identifier for this asset within the scene.
*   `name` (str, required): User-friendly name for the asset.
*   `description` (str, optional): Optional detailed description.
*   `asset_template_id_ref` (str, optional): Reference to an Asset Template ID (e.g., "TEMPLATE_GENERIC_CT_V1"). Properties from the template can be merged or overridden.
*   `nodes` (List[`Node`], required, min_length=1): List of network nodes for this asset.
*   `dicom_properties` (`AssetDicomProperties`, required): DICOM-specific configuration for this asset.

### 3.3. `Node`

Represents a network interface for an Asset.

*   `node_id` (str, required): Unique identifier for this node within its Asset.
*   `ip_address` (str, required): IP address of this node.
*   `mac_address` (str, required): MAC address of this node.
*   `dicom_port` (int, optional, default=104): Default DICOM port if this node acts as an SCP.

### 3.4. `AssetDicomProperties`

Defines the DICOM characteristics of an Asset.

*   `ae_title` (str, optional, max_length=16): Application Entity Title.
*   `implementation_class_uid` (str, optional): Implementation Class UID.
*   `implementation_version_name` (str, optional): Implementation Version Name.
*   `manufacturer` (str, optional): Manufacturer of the device.
*   `model_name` (str, optional): Model name of the device.
*   `software_versions` (List[str], optional): List of software versions.
*   `device_serial_number` (str, optional): Device serial number.
*   `supported_sop_classes` (List[`SopClassDefinition`], optional): List of SOP Classes supported by this asset.
    *   `SopClassDefinition`:
        *   `sop_class_uid` (str, required): SOP Class UID.
        *   `role` (str, required): Role ("SCU", "SCP", "BOTH").
        *   `transfer_syntaxes` (List[str], required): List of supported Transfer Syntax UIDs.

### 3.5. `Link`

Defines a communication interaction.

*   `link_id` (str, required): Unique identifier for this link.
*   `name` (str, required): User-friendly name for the link.
*   `description` (str, optional): Optional description.
*   `source_asset_id_ref` (str, required): ID of the source Asset.
*   `source_node_id_ref` (str, required): ID of the Node within the source Asset.
*   `destination_asset_id_ref` (str, required): ID of the destination Asset.
*   `destination_node_id_ref` (str, required): ID of the Node within the destination Asset.
*   `connection_details` (`LinkConnectionDetails`, optional): Specific L2-L4 parameters. If `None`, derived from nodes.
    *   `LinkConnectionDetails`: `source_mac`, `destination_mac`, `source_ip`, `destination_ip`, `source_port`, `destination_port`.
*   `dicom_config` (`LinkDicomConfiguration`, required): DICOM-specific communication configuration.

### 3.6. `LinkDicomConfiguration`

Configures DICOM aspects of a Link.

*   `scu_asset_id_ref` (str, required): Asset ID acting as SCU for this link.
*   `scp_asset_id_ref` (str, required): Asset ID acting as SCP for this link.
*   `calling_ae_title_override` (str, optional): Overrides SCU Asset's AE Title for this link.
*   `called_ae_title_override` (str, optional): Overrides SCP Asset's AE Title for this link.
*   `explicit_presentation_contexts` (List[`PresentationContextItem`], optional): Defines presentation contexts for A-ASSOCIATE-RQ. If `None`, auto-negotiation occurs.
    *   `PresentationContextItem`: `id` (int), `abstract_syntax` (str), `transfer_syntaxes` (List[str]).
*   `dimse_sequence` (List[`DimseOperation`], required): Ordered list of DIMSE operations.

### 3.7. `DimseOperation`

Defines a single DIMSE operation.

*   `operation_name` (str, required): User-friendly name for this step.
*   `message_type` (str, required): DIMSE message type (e.g., "C-STORE-RQ", "C-ECHO-RQ").
*   `presentation_context_id` (int, required): ID of the presentation context to use.
*   `command_set` (`CommandSetItem`, required): Command set for the DIMSE message.
    *   `CommandSetItem`: `MessageID` (int), `Priority` (int, optional), `AffectedSOPClassUID` (str, optional), `AffectedSOPInstanceUID` (str, optional, can be "AUTO_GENERATE_UID_INSTANCE"), `extra_fields` (Dict[str, Any]).
*   `dataset_content_rules` (Dict[str, Any], optional): Defines content for the DICOM dataset (see [Dynamic Dataset Content](#7-dynamic-dataset-content)).

## 4. API Endpoint

A new API endpoint is provided to generate a PCAP file from a scene definition.

*   **Path:** `/v2/protocols/dicom/generate-pcap-from-scene`
*   **Method:** `POST`
*   **Request Body:** A JSON object conforming to the `Scene` model.
*   **Response:** A PCAP file (`application/vnd.tcpdump.pcap`).

**Example Usage (conceptual curl):**
```bash
curl -X POST -H "Content-Type: application/json" \
     --data @scene_definition.json \
     --output generated_scene.pcap \
     http://localhost:8000/v2/protocols/dicom/generate-pcap-from-scene
```
(Where `scene_definition.json` contains the `Scene` payload.)

## 5. Asset Templates

Asset Templates provide a way to define reusable configurations for common DICOM device types.

### 5.1. Purpose and Benefits

*   Simplify Asset definition in a Scene by providing a base set of DICOM properties.
*   Promote consistency for similar device types.
*   Reduce redundancy in Scene definitions.

### 5.2. Structure

Asset Templates are JSON files stored in `backend/protocols/dicom/asset_templates/`. Each template typically contains:

*   `template_id` (str): Unique identifier for the template (matches filename without `.json`).
*   `template_name` (str): User-friendly name.
*   `template_description` (str): Description of the template.
*   `dicom_properties` (object): An object conforming to the `AssetDicomProperties` model, providing default values.

**Example (`TEMPLATE_GENERIC_CT_V1.json`):**
```json
{
  "template_id": "TEMPLATE_GENERIC_CT_V1",
  "template_name": "Generic CT Scanner",
  "template_description": "A general-purpose CT scanner template...",
  "dicom_properties": {
    "ae_title": "CT_GENERIC_AE",
    "implementation_class_uid": "1.2.826.0.1.3680043.2.1143.107.104.103.0",
    "manufacturer": "Generic Medical Devices",
    "model_name": "GenericScanner 1000",
    // ... other AssetDicomProperties fields ...
    "supported_sop_classes": [
      {
        "sop_class_uid": "1.2.840.10008.5.1.4.1.1.2", // CT Image Storage
        "role": "SCP",
        "transfer_syntaxes": ["1.2.840.10008.1.2.1", "1.2.840.10008.1.2.4.50"]
      }
      // ... other supported SOP classes ...
    ]
  }
}
```

### 5.3. How to Create and Use Custom Templates

1.  Create a new JSON file in the `backend/protocols/dicom/asset_templates/` directory.
2.  The filename (without `.json`) will be the `template_id`.
3.  Structure the JSON according to the example above, ensuring `template_id` in the content matches the filename.
4.  In your `Scene` definition, reference this `template_id` in an `Asset`'s `asset_template_id_ref` field.

### 5.4. Available Default Templates

*   `TEMPLATE_GENERIC_CT_V1.json`
*   `TEMPLATE_GENERIC_MWL_SCU_V1.json`
*   `TEMPLATE_GENERIC_PACS_V1.json`

### 5.5. Resolution Logic

When an `Asset` in a Scene references an `asset_template_id_ref`:
1.  The system loads the specified template JSON file.
2.  The `dicom_properties` from the template are taken as the base configuration.
3.  The `dicom_properties` explicitly defined within the `Asset` object in the Scene are then merged.
    *   If a field is set in the `Asset`'s `dicom_properties`, it overrides the value from the template.
    *   If a field is *not* set in the `Asset`'s `dicom_properties` (i.e., it's `None` or absent), the value from the template is used.
    *   For list fields like `supported_sop_classes`, if the `Asset`'s `dicom_properties` provides this list, it *entirely replaces* the template's list. Otherwise, the template's list is used.

## 6. Link Configuration Details

### 6.1. Connection Details

The `Link.connection_details` field allows specifying exact L2-L4 parameters. If it's `null` or omitted, the system derives these:
*   MAC and IP addresses are taken from the `source_node_id_ref` and `destination_node_id_ref` of the `Link`.
*   The source TCP port is chosen randomly from the ephemeral range.
*   The destination TCP port is taken from the `dicom_port` of the `destination_node_id_ref` (defaulting to 104 if not set on the node).

### 6.2. Presentation Contexts

Defined in `LinkDicomConfiguration.explicit_presentation_contexts`.
*   If this list is provided (even if empty), it's used directly for the A-ASSOCIATE-RQ.
*   If `explicit_presentation_contexts` is `null` (or omitted), the system performs **automatic negotiation**:
    *   It compares the `supported_sop_classes` of the resolved SCU and SCP assets (considering their roles).
    *   For each SOP Class the SCU can use and the SCP can provide, if they share common transfer syntaxes, a presentation context is proposed.
    *   The SCU proposes all its supported transfer syntaxes for that SOP Class.
    *   The SCP (simulated) accepts with the first common transfer syntax found.
    *   The `LinkDicomConfiguration.explicit_presentation_contexts` field is then populated with these auto-negotiated contexts for the A-ASSOCIATE-RQ.

### 6.3. DIMSE Sequence

The `LinkDicomConfiguration.dimse_sequence` is an ordered list of `DimseOperation` objects that will be simulated over the established association. Each operation specifies its type, command set, and rules for dataset content.

## 7. Dynamic Dataset Content

The `DimseOperation.dataset_content_rules` field allows for dynamic population of DICOM datasets. It's a dictionary where keys are DICOM tag keywords (e.g., "PatientName", "SOPInstanceUID") and values are either explicit values or special "AUTO\_" string keywords.

### Available "AUTO\_" Keywords:

*   **From Command Set:**
    *   `AUTO_FROM_COMMAND_AFFECTED_SOP_CLASS_UID`: Uses `AffectedSOPClassUID` from the operation's `command_set`.
    *   `AUTO_FROM_COMMAND_AFFECTED_SOP_INSTANCE_UID`: Uses `AffectedSOPInstanceUID` from the operation's `command_set`.

*   **UID Generation:**
    *   `AUTO_GENERATE_UID_INSTANCE`: Generates a new DICOM UID. If used for `SOPInstanceUID` tag and `AffectedSOPInstanceUID` in command set was also `AUTO_GENERATE_UID_INSTANCE`, they will share the same generated UID for that C-STORE operation.
    *   `AUTO_GENERATE_UID_STUDY`: Generates a new Study Instance UID.
    *   `AUTO_GENERATE_UID_SERIES`: Generates a new Series Instance UID.
    *   `AUTO_GENERATE_UID`: Generates a generic new DICOM UID.

*   **Sample Data Generation:**
    *   `AUTO_GENERATE_SAMPLE_PATIENT_NAME`: Selects a random patient name from a predefined list.
    *   `AUTO_GENERATE_SAMPLE_DATE_TODAY`: Inserts the current date in YYYYMMDD format.

*   **From Asset Properties (SCU or SCP of the Link):**
    *   `AUTO_FROM_ASSET_SCU_AE_TITLE`: Uses `ae_title` from the SCU Asset's resolved `dicom_properties`.
    *   `AUTO_FROM_ASSET_SCP_AE_TITLE`: Uses `ae_title` from the SCP Asset's resolved `dicom_properties`.
    *   `AUTO_FROM_ASSET_SCU_MANUFACTURER`: Uses `manufacturer` from SCU Asset.
    *   `AUTO_FROM_ASSET_SCP_MANUFACTURER`: Uses `manufacturer` from SCP Asset.
    *   `AUTO_FROM_ASSET_SCU_MODEL_NAME`: Uses `model_name` from SCU Asset (inserted into `ManufacturerModelName` DICOM tag).
    *   `AUTO_FROM_ASSET_SCP_MODEL_NAME`: Uses `model_name` from SCP Asset (inserted into `ManufacturerModelName` DICOM tag).
    *   `AUTO_FROM_ASSET_SCU_SOFTWARE_VERSIONS`: Uses `software_versions` (list) from SCU Asset.
    *   `AUTO_FROM_ASSET_SCP_SOFTWARE_VERSIONS`: Uses `software_versions` (list) from SCP Asset.
    *   `AUTO_FROM_ASSET_SCU_DEVICE_SERIAL_NUMBER`: Uses `device_serial_number` from SCU Asset.
    *   `AUTO_FROM_ASSET_SCP_DEVICE_SERIAL_NUMBER`: Uses `device_serial_number` from SCP Asset.

If an "AUTO\_FROM\_ASSET\_..." rule refers to an optional property that is not set on the resolved asset, the tag will not be added to the dataset. Explicit values (including `null`) in the rules will be set as provided.

## 8. Automatic/Default Link Configuration

The system provides limited automatic behavior for link configuration:

*   **Presentation Contexts:** As described in [6.2. Presentation Contexts](#62-presentation-contexts), if `explicit_presentation_contexts` is `null`, they are auto-negotiated.
*   **DIMSE Sequence:** If `LinkDicomConfiguration.dimse_sequence` is empty or `null`:
    *   The `DicomSceneProcessor` will check if the Verification SOP Class ("1.2.840.10008.1.1") was successfully negotiated for the link.
    *   If so, it will automatically generate a single C-ECHO-RQ operation for that link.
    *   Otherwise, no DIMSE operations will occur for that link.

More sophisticated automatic DIMSE sequence generation based on negotiated contexts and asset roles may be added in the future.

## 9. Usage Examples

### Example 1: Simple C-ECHO between two Assets using Templates

```json
{
  "scene_id": "SCENE_SIMPLE_ECHO_01",
  "name": "Simple C-ECHO Test",
  "assets": [
    {
      "asset_id": "ASSET_SCU_ECHO",
      "name": "Echo SCU Device",
      "asset_template_id_ref": "TEMPLATE_GENERIC_MWL_SCU_V1", // A template that supports C-ECHO as SCU
      "nodes": [
        {
          "node_id": "SCU_NIC1",
          "ip_address": "192.168.1.50",
          "mac_address": "00:00:00:AA:BB:50"
        }
      ],
      "dicom_properties": { 
        "ae_title": "ECHOSCU" 
      }
    },
    {
      "asset_id": "ASSET_SCP_ECHO",
      "name": "Echo SCP Device",
      "asset_template_id_ref": "TEMPLATE_GENERIC_PACS_V1", // A template that supports C-ECHO as SCP
      "nodes": [
        {
          "node_id": "SCP_NIC1",
          "ip_address": "192.168.1.60",
          "mac_address": "00:00:00:AA:BB:60",
          "dicom_port": 11112
        }
      ],
      "dicom_properties": { 
        "ae_title": "ECHOSCP"
      }
    }
  ],
  "links": [
    {
      "link_id": "LINK_ECHO_1",
      "name": "SCU to SCP Echo",
      "source_asset_id_ref": "ASSET_SCU_ECHO",
      "source_node_id_ref": "SCU_NIC1",
      "destination_asset_id_ref": "ASSET_SCP_ECHO",
      "destination_node_id_ref": "SCP_NIC1",
      "dicom_config": {
        "scu_asset_id_ref": "ASSET_SCU_ECHO",
        "scp_asset_id_ref": "ASSET_SCP_ECHO",
        // explicit_presentation_contexts is null, so auto-negotiation will occur.
        // dimse_sequence is empty/null, so C-ECHO-RQ will be auto-generated if Verification is negotiated.
        "dimse_sequence": [] 
      }
    }
  ]
}
```

### Example 2: CT Sending Image to PACS with Dynamic Data

```json
{
  "scene_id": "SCENE_CT_TO_PACS_DYNAMIC_01",
  "name": "CT Sends Image to PACS with Dynamic Data",
  "assets": [
    {
      "asset_id": "ASSET_CT_001",
      "name": "Main CT Scanner",
      "asset_template_id_ref": "TEMPLATE_GENERIC_CT_V1",
      "nodes": [{ "node_id": "CT_NIC", "ip_address": "10.0.0.10", "mac_address": "0A:00:00:00:00:10" }],
      "dicom_properties": {
        "ae_title": "CTSCAN01",
        "manufacturer": "RealWorld CT Systems",
        "model_name": "CT-UltraFast",
        "device_serial_number": "CTSN007"
      }
    },
    {
      "asset_id": "ASSET_PACS_001",
      "name": "Central PACS Archive",
      "asset_template_id_ref": "TEMPLATE_GENERIC_PACS_V1",
      "nodes": [{ "node_id": "PACS_NIC", "ip_address": "10.0.0.20", "mac_address": "0A:00:00:00:00:20", "dicom_port": 1040 }],
      "dicom_properties": { 
        "ae_title": "MAINPACS"
      }
    }
  ],
  "links": [
    {
      "link_id": "LINK_CT_PACS_STORE",
      "name": "CT Store to PACS",
      "source_asset_id_ref": "ASSET_CT_001",
      "source_node_id_ref": "CT_NIC",
      "destination_asset_id_ref": "ASSET_PACS_001",
      "destination_node_id_ref": "PACS_NIC",
      "dicom_config": {
        "scu_asset_id_ref": "ASSET_CT_001",
        "scp_asset_id_ref": "ASSET_PACS_001",
        "explicit_presentation_contexts": [ // Explicitly define PC for CT Image Storage
          {
            "id": 1,
            "abstract_syntax": "1.2.840.10008.5.1.4.1.1.2", // CT Image Storage
            "transfer_syntaxes": ["1.2.840.10008.1.2.1"] // Explicit VR Little Endian
          }
        ],
        "dimse_sequence": [
          {
            "operation_name": "Store CT Image",
            "message_type": "C-STORE-RQ",
            "presentation_context_id": 1,
            "command_set": {
              "MessageID": 1,
              "AffectedSOPClassUID": "1.2.840.10008.5.1.4.1.1.2",
              "AffectedSOPInstanceUID": "AUTO_GENERATE_UID_INSTANCE" 
            },
            "dataset_content_rules": {
              "SOPClassUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_CLASS_UID",
              "SOPInstanceUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_INSTANCE_UID",
              "PatientName": "AUTO_GENERATE_SAMPLE_PATIENT_NAME",
              "PatientID": "PATID-SCENE002",
              "StudyInstanceUID": "AUTO_GENERATE_UID_STUDY",
              "SeriesInstanceUID": "AUTO_GENERATE_UID_SERIES",
              "Modality": "CT",
              "Manufacturer": "AUTO_FROM_ASSET_SCU_MANUFACTURER", // Uses "RealWorld CT Systems"
              "ManufacturerModelName": "AUTO_FROM_ASSET_SCU_MODEL_NAME", // Uses "CT-UltraFast"
              "DeviceSerialNumber": "AUTO_FROM_ASSET_SCU_DEVICE_SERIAL_NUMBER", // Uses "CTSN007"
              "InstanceNumber": 1,
              "PixelData": null // Placeholder, actual pixel data generation is complex and not covered here
            }
          }
        ]
      }
    }
  ]
}
