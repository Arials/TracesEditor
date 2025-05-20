"""
Test suite for the Advanced DICOM Scene Generation FastAPI endpoint.

This module contains pytest-based integration tests to verify the
`/protocols/dicom/v2/generate-pcap-from-scene` endpoint.
It checks if the endpoint correctly processes a Scene JSON payload,
generates a PCAP file, and if the contents of that PCAP file accurately
reflect the defined scene, including multi-asset interactions,
dynamic data injection, and auto-default behaviors.
"""
import pytest
import os
import tempfile
import json # For loading/dumping JSON if needed for complex payloads from files
from typing import List, Dict, Any, Tuple
from fastapi.testclient import TestClient
from scapy.all import rdpcap, Packet, Ether, IP, TCP
from pydicom import dcmread
from pydicom.filebase import DicomBytesIO
from pydicom.dataset import Dataset

# Import the FastAPI app instance
from backend.main import app

# Import models for payload construction and validation
from backend.protocols.dicom.models import Scene # Main payload model

# Client for making API requests
client = TestClient(app)

# --- Helper Functions for PCAP Analysis (to be expanded) ---

def get_dicom_pdv_details(packet: Packet) -> List[Tuple[bytes, int, bool]]:
    """
    Extracts DICOM PDV details from a P-DATA-TF PDU within a Scapy packet.
    A P-DATA-TF PDU can contain multiple PDVs.
    Returns a list of tuples: (pdv_data_bytes, presentation_context_id, is_command).
    """
    pdv_details_list = []
    if TCP in packet and packet[TCP].payload:
        tcp_payload_bytes = bytes(packet[TCP].payload)
        # P-DATA-TF PDU type is 0x04
        if len(tcp_payload_bytes) > 0 and tcp_payload_bytes[0] == 0x04:
            print(f"[get_dicom_pdv_details] Processing P-DATA-TF PDU. Raw PDU (first 64 bytes): {tcp_payload_bytes[:64].hex()}")
            # PDU Header: Type (1), Reserved (1), Length (4) = 6 bytes
            current_offset = 6 # Skip PDU header
            pdu_length = int.from_bytes(tcp_payload_bytes[2:6], 'big')
            print(f"[get_dicom_pdv_details] PDU Type: 0x04, Declared PDU Length: {pdu_length}")
            
            # Ensure we only process bytes belonging to this PDU
            # The actual data for PDVs starts after the PDU header
            pdv_stream_bytes = tcp_payload_bytes[current_offset : current_offset + pdu_length] # Corrected slicing
            print(f"[get_dicom_pdv_details] Extracted PDV Stream Length: {len(pdv_stream_bytes)}, Expected from PDU Length: {pdu_length}")
            if len(pdv_stream_bytes) != pdu_length:
                print(f"[get_dicom_pdv_details] WARNING: Mismatch between PDU length and extracted PDV stream bytes length.")

            pdv_offset = 0
            pdv_counter = 0
            while pdv_offset < len(pdv_stream_bytes):
                pdv_counter += 1
                print(f"\n[get_dicom_pdv_details] --- PDV Item #{pdv_counter} ---")
                print(f"[get_dicom_pdv_details] Current pdv_offset: {pdv_offset}")
                # PDV Item: Length (4), PCID (1), Message Control Header (1), Data (variable)
                if len(pdv_stream_bytes) < pdv_offset + 6: # Min length for PDV header (len+pcid+mch)
                    print(f"[get_dicom_pdv_details] Not enough bytes remaining for PDV header ({len(pdv_stream_bytes) - pdv_offset} bytes left). Breaking loop.")
                    break 
                
                # Log raw bytes for PDV header
                raw_pdv_header_bytes = pdv_stream_bytes[pdv_offset : pdv_offset + 6]
                print(f"[get_dicom_pdv_details] Raw PDV Header Bytes: {raw_pdv_header_bytes.hex()}")

                pdv_item_length = int.from_bytes(pdv_stream_bytes[pdv_offset : pdv_offset + 4], 'big')
                print(f"[get_dicom_pdv_details] Parsed PDV Item Length (from header): {pdv_item_length}")
                
                # Check if the entire PDV item (header + data) is within bounds
                # The pdv_item_length INCLUDES the PCID and MCH bytes (2 bytes)
                # So, data length is pdv_item_length - 2
                # Total length of this PDV item on the wire is 4 (for length field) + pdv_item_length
                if pdv_offset + 4 + pdv_item_length > len(pdv_stream_bytes):
                    print(f"[get_dicom_pdv_details] PDV item claims to be longer than remaining buffer. "
                          f"pdv_offset ({pdv_offset}) + 4 (len field) + pdv_item_length ({pdv_item_length}) = {pdv_offset + 4 + pdv_item_length} "
                          f"vs. pdv_stream_bytes_len ({len(pdv_stream_bytes)}). Breaking loop.")
                    break # PDV claims to be longer than remaining buffer

                presentation_context_id = pdv_stream_bytes[pdv_offset + 4]
                message_control_header = pdv_stream_bytes[pdv_offset + 5]
                print(f"[get_dicom_pdv_details] Parsed PCID: {presentation_context_id}")
                print(f"[get_dicom_pdv_details] Parsed MCH: {message_control_header:02x} (binary: {message_control_header:08b})")
                
                is_command = (message_control_header & 0x01) == 0x01
                is_last_fragment = (message_control_header & 0x02) == 0x02
                print(f"[get_dicom_pdv_details] Interpreted is_command: {is_command}")
                print(f"[get_dicom_pdv_details] Interpreted is_last_fragment: {is_last_fragment}")

                # The actual DICOM data part of the PDV starts after the MCH
                # pdv_item_length is the length of (PCID + MCH + Data)
                # So, data_length = pdv_item_length - 1 (for PCID) - 1 (for MCH)
                pdv_data_start_offset = pdv_offset + 6 # After Length field (4), PCID (1), MCH (1)
                # The end of data is pdv_data_start_offset + (pdv_item_length - 2)
                # which is pdv_offset + 6 + pdv_item_length - 2 = pdv_offset + 4 + pdv_item_length
                pdv_data_end_offset = pdv_offset + 4 + pdv_item_length 
                
                pdv_data = pdv_stream_bytes[pdv_data_start_offset:pdv_data_end_offset]
                print(f"[get_dicom_pdv_details] Extracted PDV Data Length: {len(pdv_data)} (Expected: {max(0, pdv_item_length - 2)})")
                print(f"[get_dicom_pdv_details] PDV Data (first 64 bytes): {pdv_data[:64].hex()}")
                
                pdv_details_list.append((pdv_data, presentation_context_id, is_command))
                
                # Move to the next PDV item. The total length of this PDV item is 4 (length field) + pdv_item_length.
                pdv_offset += (4 + pdv_item_length) 
            
            if pdv_offset == len(pdv_stream_bytes):
                print(f"[get_dicom_pdv_details] Successfully parsed all PDV items in the stream (pdv_offset {pdv_offset} == stream_len {len(pdv_stream_bytes)}).")
            else:
                print(f"[get_dicom_pdv_details] Loop finished. pdv_offset ({pdv_offset}) != stream_len ({len(pdv_stream_bytes)}). Remaining bytes: {pdv_stream_bytes[pdv_offset:].hex()}")

    return pdv_details_list

def parse_dicom_dataset_from_bytes(data_bytes: bytes) -> Dataset:
    """Parses a DICOM dataset from a byte string."""
    try:
        dicom_file_like = DicomBytesIO(data_bytes)
        dataset = dcmread(dicom_file_like, force=True)
        # Ensure is_little_endian and is_implicit_VR are set if known,
        # though dcmread tries to infer. For datasets from P-DATA-TF,
        # transfer syntax negotiation determines this. Assume Implicit VR LE for now if not specified.
        if not hasattr(dataset.file_meta, 'TransferSyntaxUID'):
             dataset.is_little_endian = True
             dataset.is_implicit_VR = True
        return dataset
    except Exception as e:
        print(f"Failed to parse DICOM dataset: {e}")
        return Dataset() # Return empty dataset on failure

# --- Test Scenarios ---

def test_scene_api_scenario_1_ct_to_pacs_cstore_explicit():
    """
    Scenario 1: Basic CT to PACS (C-STORE) with Explicit Config.
    - Asset 1 (SCU): GE HealthCare Revolution Apex (CT Scanner)
    - Asset 2 (SCP): Sectra PACS
    - Link: Explicit LinkDicomConfiguration for CT Image Storage.
    - Test Focus:
        - Correct A-ASSOCIATE-RQ/AC.
        - C-STORE-RQ with data injection: Manufacturer, Model, generated UIDs, explicit PatientName.
        - Validate these values in the generated PCAP.
    """
    scene_payload_s1: Dict[str, Any] = {
        "scene_id": "SCENE_S1_CT_PACS_EXPLICIT",
        "name": "Test Scenario 1: CT to PACS C-STORE Explicit",
        "assets": [
            {
                "asset_id": "ASSET_CT_GE_APEX",
                "name": "GE Revolution Apex CT",
                "nodes": [
                    {
                        "node_id": "CT_NIC1",
                        "ip_address": "192.168.1.10",
                        "mac_address": "00:0A:95:9D:68:16", # Example GE MAC
                        "dicom_port": 10401 # Can be anything for SCU initiating node
                    }
                ],
                "dicom_properties": {
                    "ae_title": "GE_CT_SCU",
                    "implementation_class_uid": "1.2.840.113619.6.336", # Example GE UID
                    "manufacturer": "GE HealthCare",
                    "model_name": "Revolution Apex",
                    "software_versions": ["CT_App_v2.1"],
                    "device_serial_number": "GE_CT_SN123",
                    "supported_sop_classes": [
                        { # CT Image Storage as SCU
                            "sop_class_uid": "1.2.840.10008.5.1.4.1.1.2", 
                            "role": "SCU",
                            "transfer_syntaxes": ["1.2.840.10008.1.2.1", "1.2.840.10008.1.2"]
                        },
                        { # Verification as SCU
                            "sop_class_uid": "1.2.840.10008.1.1",
                            "role": "SCU",
                            "transfer_syntaxes": ["1.2.840.10008.1.2"]
                        }
                    ]
                }
            },
            {
                "asset_id": "ASSET_PACS_SECTRA",
                "name": "Sectra PACS",
                "nodes": [
                    {
                        "node_id": "PACS_NIC1",
                        "ip_address": "192.168.1.20",
                        "mac_address": "00:1B:C5:01:02:03", # Example Sectra MAC (fictional)
                        "dicom_port": 104 
                    }
                ],
                "dicom_properties": {
                    "ae_title": "SECTRA_PACS_SCP",
                    "implementation_class_uid": "2.16.756.5.30.1.123.3.1.1", # Example Sectra UID
                    "manufacturer": "Sectra AB",
                    "model_name": "IDS7 PACS",
                    "supported_sop_classes": [
                        { # CT Image Storage as SCP
                            "sop_class_uid": "1.2.840.10008.5.1.4.1.1.2", 
                            "role": "SCP",
                            "transfer_syntaxes": ["1.2.840.10008.1.2.1", "1.2.840.10008.1.2"]
                        },
                        { # Verification as SCP
                            "sop_class_uid": "1.2.840.10008.1.1",
                            "role": "SCP",
                            "transfer_syntaxes": ["1.2.840.10008.1.2"]
                        }
                    ]
                }
            }
        ],
        "links": [
            {
                "link_id": "LINK_CT_TO_PACS_CSTORE",
                "name": "CT sends CT Image to PACS",
                "source_asset_id_ref": "ASSET_CT_GE_APEX",
                "source_node_id_ref": "CT_NIC1",
                "destination_asset_id_ref": "ASSET_PACS_SECTRA",
                "destination_node_id_ref": "PACS_NIC1",
                # connection_details will be derived by scene_processor
                "dicom_config": {
                    "scu_asset_id_ref": "ASSET_CT_GE_APEX",
                    "scp_asset_id_ref": "ASSET_PACS_SECTRA",
                    "explicit_presentation_contexts": [
                        {
                            "id": 1,
                            "abstract_syntax": "1.2.840.10008.5.1.4.1.1.2", # CT Image Storage
                            "transfer_syntaxes": ["1.2.840.10008.1.2.1"] # Explicit VR LE
                        }
                    ],
                    "dimse_sequence": [
                        {
                            "operation_name": "Store CT Image",
                            "message_type": "C-STORE-RQ",
                            "presentation_context_id": 1,
                            "command_set": {
                                "MessageID": 1,
                                "Priority": 0, # MEDIUM
                                "AffectedSOPClassUID": "1.2.840.10008.5.1.4.1.1.2",
                                "AffectedSOPInstanceUID": "AUTO_GENERATE_UID_INSTANCE"
                            },
                            "dataset_content_rules": {
                                "SOPClassUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_CLASS_UID",
                                "SOPInstanceUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_INSTANCE_UID",
                                "PatientName": "Test^Explicit^PatientOne",
                                "PatientID": "PATID_S1_001",
                                "StudyInstanceUID": "AUTO_GENERATE_UID_STUDY",
                                "SeriesInstanceUID": "AUTO_GENERATE_UID_SERIES",
                                "Modality": "CT",
                                "Manufacturer": "AUTO_FROM_ASSET_SCU_MANUFACTURER", # Should be GE HealthCare
                                "ModelName": "AUTO_FROM_ASSET_SCU_MODEL_NAME",       # Should be Revolution Apex
                                "DeviceSerialNumber": "AUTO_FROM_ASSET_SCU_DEVICE_SERIAL_NUMBER", # Should be GE_CT_SN123
                                "SoftwareVersions": "AUTO_FROM_ASSET_SCU_SOFTWARE_VERSIONS" # Should be ["CT_App_v2.1"]
                            }
                        }
                    ]
                }
            }
        ]
    }

    response = client.post("/protocols/dicom/v2/generate-pcap-from-scene", json=scene_payload_s1)

    assert response.status_code == 200, f"API Error: {response.text}"
    assert response.headers["content-type"] == "application/vnd.tcpdump.pcap"
    assert len(response.content) > 0, "PCAP file content is empty."

    temp_pcap_file = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pcap", delete=False) as tmp_f:
            tmp_f.write(response.content)
            temp_pcap_file = tmp_f.name
        
        packets = rdpcap(temp_pcap_file)
        assert packets is not None, "Scapy could not read the generated PCAP file."

        # Expected packets: TCP Handshake (3), A-ASSOC-RQ (1), A-ASSOC-AC (1), 
        # P-DATA-TF (Cmd) (1), P-DATA-TF (Data) (1), TCP ACKs for each (4), TCP Teardown (4)
        # Total: 3 + 1+1 + 1+1 + 1+1 + 4 = 13 (approx, depends on ACK strategy in handler)
        # The handler's generate_dicom_session_packet_list includes ACKs.
        # TCP Handshake (SYN, SYN-ACK, ACK) = 3
        # A-ASSOCIATE-RQ + TCP ACK = 2
        # A-ASSOCIATE-AC + TCP ACK = 2
        # P-DATA-TF (Cmd for C-STORE) + TCP ACK = 2
        # P-DATA-TF (Data for C-STORE) + TCP ACK = 2
        # TCP Teardown (FIN, ACK, FIN, ACK) = 4
        # Expected: 3 + 2 + 2 + 2 + 2 + 4 = 15 packets
        assert len(packets) >= 10, f"Expected at least 10 packets for a C-STORE, got {len(packets)}" # Looser check for now

        cstore_rq_dataset_found = False
        # Expected Presentation Context ID for C-STORE-RQ in this test
        expected_cstore_pc_id = 1

        # --- BEGIN GENERAL PACKET DUMP ---
        print("\n[Test 1] --- BEGIN GENERAL PACKET DUMP ---")
        for i, pkt_dump in enumerate(packets):
            print(f"[Test 1] Raw Packet #{i}: {pkt_dump.summary()}")
            if IP in pkt_dump:
                print(f"  IP Src: {pkt_dump[IP].src}, IP Dst: {pkt_dump[IP].dst}")
            if TCP in pkt_dump:
                print(f"  TCP Sport: {pkt_dump[TCP].sport}, TCP Dport: {pkt_dump[TCP].dport}")
                if pkt_dump[TCP].payload:
                    raw_payload_dump = bytes(pkt_dump[TCP].payload)
                    payload_len_dump = len(raw_payload_dump)
                    pdu_type_dump = raw_payload_dump[0] if payload_len_dump > 0 else "N/A"
                    pdu_type_str = f"{pdu_type_dump:02x}" if isinstance(pdu_type_dump, int) else str(pdu_type_dump)
                    print(f"  TCP Payload: Exists, Length: {payload_len_dump}, First Byte (PDU Type): {pdu_type_str}")
                else:
                    print("  TCP Payload: None or empty")
        print("[Test 1] --- END GENERAL PACKET DUMP ---\n")
        # --- END GENERAL PACKET DUMP ---

        for packet_idx, packet in enumerate(packets): # Added packet_idx for logging
            if IP in packet and packet[IP].src == "192.168.1.10" and packet[IP].dst == "192.168.1.20" and TCP in packet and packet[TCP].dport == 104: # SCU to SCP
                print(f"\n[Test 1] Processing packet {packet_idx} from SCU to SCP (ports {packet[TCP].sport}->{packet[TCP].dport})")
                # --- BEGIN ADDED LOGGING ---
                if packet[TCP].payload:
                    tcp_payload_bytes_for_log = bytes(packet[TCP].payload)
                    print(f"[Test 1] Packet {packet_idx}: TCP payload exists. Length: {len(tcp_payload_bytes_for_log)}")
                    if len(tcp_payload_bytes_for_log) > 0:
                        print(f"[Test 1] Packet {packet_idx}: TCP payload first byte (PDU Type): {tcp_payload_bytes_for_log[0]:02x}")
                        print(f"[Test 1] Packet {packet_idx}: TCP payload first 10 bytes: {tcp_payload_bytes_for_log[:10].hex()}")
                    else:
                        print(f"[Test 1] Packet {packet_idx}: TCP payload is empty.")
                else:
                    print(f"[Test 1] Packet {packet_idx}: No TCP payload (packet[TCP].payload is None or empty).")
                # --- END ADDED LOGGING ---
                pdv_details_list = get_dicom_pdv_details(packet)
                if not pdv_details_list:
                    print(f"[Test 1] Packet {packet_idx}: No PDVs found by get_dicom_pdv_details (returned empty list).")
                for pdv_idx, (pdv_data, pc_id, is_command) in enumerate(pdv_details_list): # Added pdv_idx for logging
                    print(f"[Test 1] Packet {packet_idx}, PDV {pdv_idx}: pc_id={pc_id}, is_command={is_command}, len={len(pdv_data)}")
                    if not is_command and pc_id == expected_cstore_pc_id:
                        print(f"[Test 1] Packet {packet_idx}, PDV {pdv_idx}: Matched expected C-STORE data conditions (not command, pc_id={expected_cstore_pc_id}). Parsing dataset...")
                        # This should be the C-STORE-RQ data dataset
                        dataset = parse_dicom_dataset_from_bytes(pdv_data)
                        if dataset and dataset.get("SOPClassUID") == "1.2.840.10008.5.1.4.1.1.2": # CT Image Storage
                            print(f"[Test 1] Packet {packet_idx}, PDV {pdv_idx}: Dataset parsed. SOPClassUID matches. Validating fields...")
                            print(f"  PatientName: {dataset.get('PatientName')}")
                            print(f"  PatientID: {dataset.get('PatientID')}")
                            print(f"  Manufacturer: {dataset.get('Manufacturer')}")
                            print(f"  ManufacturerModelName: {dataset.get('ManufacturerModelName')}")
                            print(f"  DeviceSerialNumber: {dataset.get('DeviceSerialNumber')}")
                            print(f"  SoftwareVersions: {dataset.get('SoftwareVersions')}")
                            print(f"  SOPInstanceUID: {dataset.get('SOPInstanceUID')}")
                            print(f"  StudyInstanceUID: {dataset.get('StudyInstanceUID')}")
                            print(f"  SeriesInstanceUID: {dataset.get('SeriesInstanceUID')}")
                            assert dataset.PatientName == "Test^Explicit^PatientOne"
                            assert dataset.PatientID == "PATID_S1_001"
                            assert dataset.Manufacturer == "GE HealthCare"
                            # After dataset_builder fix, ModelName rule maps to ManufacturerModelName
                            assert dataset.ManufacturerModelName == "Revolution Apex"
                            assert dataset.DeviceSerialNumber == "GE_CT_SN123"
                            assert dataset.SoftwareVersions == "CT_App_v2.1" # pydicom stores multi-value as list (single as scalar for LO)
                            assert "SOPInstanceUID" in dataset
                            assert "StudyInstanceUID" in dataset
                            assert "SeriesInstanceUID" in dataset
                            cstore_rq_dataset_found = True
                            print(f"[Test 1] Packet {packet_idx}, PDV {pdv_idx}: All assertions passed. cstore_rq_dataset_found = True.")
                            break
                        elif dataset:
                             print(f"[Test 1] Packet {packet_idx}, PDV {pdv_idx}: Dataset parsed but SOPClassUID ({dataset.get('SOPClassUID')}) did not match expected ({'1.2.840.10008.5.1.4.1.1.2'}).")
                        else:
                            print(f"[Test 1] Packet {packet_idx}, PDV {pdv_idx}: Dataset parsing failed or returned empty.")
                    elif not is_command:
                        print(f"[Test 1] Packet {packet_idx}, PDV {pdv_idx}: Data PDV but pc_id ({pc_id}) did not match expected ({expected_cstore_pc_id}).")
                    else: # is_command
                        print(f"[Test 1] Packet {packet_idx}, PDV {pdv_idx}: Command PDV, skipping for data check.")
            if cstore_rq_dataset_found:
                print("[Test 1] C-STORE RQ Dataset found, breaking from packet loop.")
                break
            else:
                print(f"[Test 1] Packet {packet_idx} processed, C-STORE RQ data dataset not yet found.")
        
        assert cstore_rq_dataset_found, "C-STORE-RQ data dataset with correct injected values not found."

    finally:
        if temp_pcap_file and os.path.exists(temp_pcap_file):
            os.remove(temp_pcap_file)

def test_scene_api_scenario_2_mwl_auto_negotiate():
    """
    Scenario 2: Modality Worklist (MWL) Query (C-FIND) with Auto-Negotiated Presentation Contexts.
    - Asset 1 (SCU): Philips DigitalDiagnost C90 (DR)
    - Asset 2 (SCP): Agfa Enterprise Imaging (PACS/RIS)
    - Link: explicit_presentation_contexts = None (triggers auto-negotiation for MWL).
    - Test Focus:
        - Successful auto-negotiation of MWL SOP Class.
        - Correct A-ASSOCIATE-RQ/AC.
        - C-FIND-RQ generation.
    """
    scene_payload_s2: Dict[str, Any] = {
        "scene_id": "SCENE_S2_MWL_AUTO_NEG",
        "name": "Test Scenario 2: MWL C-FIND Auto-Negotiation",
        "assets": [
            {
                "asset_id": "ASSET_DR_PHILIPS_C90",
                "name": "Philips DigitalDiagnost C90 DR",
                "nodes": [
                    {
                        "node_id": "DR_NIC1",
                        "ip_address": "192.168.2.10",
                        "mac_address": "00:17:A4:12:34:56", # Example Philips MAC
                        "dicom_port": 10402
                    }
                ],
                "dicom_properties": {
                    "ae_title": "DR_PHILIPS_SCU",
                    "implementation_class_uid": "1.2.276.0.7230010.3.0.3.6.4", # Example Philips UID
                    "manufacturer": "Philips Healthcare",
                    "model_name": "DigitalDiagnost C90",
                    "supported_sop_classes": [
                        { # Modality Worklist Information Model FIND as SCU
                            "sop_class_uid": "1.2.840.10008.5.1.4.31", 
                            "role": "SCU",
                            "transfer_syntaxes": ["1.2.840.10008.1.2.1", "1.2.840.10008.1.2"]
                        },
                        { # Verification as SCU
                            "sop_class_uid": "1.2.840.10008.1.1",
                            "role": "SCU",
                            "transfer_syntaxes": ["1.2.840.10008.1.2"]
                        }
                    ]
                }
            },
            {
                "asset_id": "ASSET_RIS_AGFA_EI",
                "name": "Agfa Enterprise Imaging RIS",
                "nodes": [
                    {
                        "node_id": "RIS_NIC1",
                        "ip_address": "192.168.2.20",
                        "mac_address": "00:0C:29:AB:CD:EF", # Example Agfa MAC (fictional)
                        "dicom_port": 11112 
                    }
                ],
                "dicom_properties": {
                    "ae_title": "AGFA_RIS_SCP",
                    "implementation_class_uid": "1.2.826.0.1.3680043.2.1143.107.104.103.1", # Generic for testing
                    "manufacturer": "Agfa HealthCare",
                    "model_name": "Enterprise Imaging",
                    "supported_sop_classes": [
                        { # Modality Worklist Information Model FIND as SCP
                            "sop_class_uid": "1.2.840.10008.5.1.4.31", 
                            "role": "SCP",
                            "transfer_syntaxes": ["1.2.840.10008.1.2.1", "1.2.840.10008.1.2"]
                        },
                        { # Verification as SCP
                            "sop_class_uid": "1.2.840.10008.1.1",
                            "role": "SCP",
                            "transfer_syntaxes": ["1.2.840.10008.1.2"]
                        }
                    ]
                }
            }
        ],
        "links": [
            {
                "link_id": "LINK_DR_TO_RIS_MWL_FIND",
                "name": "DR queries RIS for Modality Worklist",
                "source_asset_id_ref": "ASSET_DR_PHILIPS_C90",
                "source_node_id_ref": "DR_NIC1",
                "destination_asset_id_ref": "ASSET_RIS_AGFA_EI",
                "destination_node_id_ref": "RIS_NIC1",
                "dicom_config": {
                    "scu_asset_id_ref": "ASSET_DR_PHILIPS_C90",
                    "scp_asset_id_ref": "ASSET_RIS_AGFA_EI",
                    "explicit_presentation_contexts": None, # Trigger auto-negotiation
                    "dimse_sequence": [
                        {
                            "operation_name": "Query Modality Worklist",
                            "message_type": "C-FIND-RQ",
                            # presentation_context_id will be determined by auto-negotiation.
                            # The DicomSceneProcessor should select the PC ID for MWL.
                            # We need a way to refer to the auto-negotiated PC ID or assume it's the first one.
                            # For now, let's assume the processor handles this by finding the MWL PC.
                            # If MWL is PC ID 1 (likely if it's the first common SOP class):
                            "presentation_context_id": 1, # Placeholder, test needs to verify this was chosen for MWL
                            "command_set": {
                                "MessageID": 1,
                                "Priority": 1, # MEDIUM
                                "AffectedSOPClassUID": "1.2.840.10008.5.1.4.31" # MWL SOP Class
                            },
                            "dataset_content_rules": { # Example C-FIND-RQ identifier
                                "PatientName": "*", # Wildcard query
                                "ScheduledProcedureStepSequence": { # Sequence for query keys
                                    "ScheduledStationAETitle": "DR_PHILIPS_SCU", # Query for this modality
                                    "ScheduledProcedureStepStartDate": "AUTO_GENERATE_SAMPLE_DATE_TODAY", # Placeholder for dynamic date
                                    "Modality": "DR"
                                }
                            }
                        }
                    ]
                }
            }
        ]
    }

    response = client.post("/protocols/dicom/v2/generate-pcap-from-scene", json=scene_payload_s2)

    assert response.status_code == 200, f"API Error: {response.text}"
    assert response.headers["content-type"] == "application/vnd.tcpdump.pcap"
    assert len(response.content) > 0, "PCAP file content is empty."

    temp_pcap_file = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pcap", delete=False) as tmp_f:
            tmp_f.write(response.content)
            temp_pcap_file = tmp_f.name
        
        packets = rdpcap(temp_pcap_file)
        assert packets is not None, "Scapy could not read the generated PCAP file."

        # Expected packets for C-FIND:
        # TCP Handshake (3), A-ASSOC-RQ (1), A-ASSOC-AC (1), 
        # P-DATA-TF (Cmd for C-FIND-RQ) (1), TCP ACKs for each (3), TCP Teardown (4)
        # Total: 3 + 1+1 + 1+1 + 3 + 4 = 14 (approx, C-FIND-RSP not simulated by this endpoint)
        # Expected: 3 + 2 + 2 + 2 + 4 = 13 packets (if only one C-FIND-RQ and no data in response)
        assert len(packets) >= 10, f"Expected at least 10 packets for a C-FIND, got {len(packets)}"

        assoc_rq_found = False
        assoc_ac_found = False
        cfind_rq_cmd_found = False
        mwl_pc_id_in_rq = -1
        mwl_pc_id_accepted_in_ac = -1

        for packet in packets:
            if TCP in packet and packet[TCP].payload:
                payload_bytes = bytes(packet[TCP].payload)
                pdu_type = payload_bytes[0] if len(payload_bytes) > 0 else -1

                if pdu_type == 0x01: # A-ASSOCIATE-RQ
                    assoc_rq_found = True
                    # Crude check for MWL PC (1.2.840.10008.5.1.4.31)
                    # A real parser would be needed here. For now, we assume it's proposed.
                    # We need to confirm the DicomSceneProcessor correctly adds it.
                    # The test for DicomSceneProcessor logic itself should verify this more deeply.
                    # Here, we'll check if the C-FIND-RQ uses a PC ID that was accepted for MWL.
                    # For now, let's assume PC ID 1 is used if MWL is the first/only auto-negotiated context.
                    # This part of the test is a bit weak without parsing the A-ASSOCIATE-RQ PDU fully.
                    # We'll infer from the C-FIND-RQ's PC ID later.
                    # Example: if payload_bytes contains "1.2.840.10008.5.1.4.31".encode('ascii')
                    # For now, we'll assume the `presentation_context_id: 1` in the payload was correct.

                elif pdu_type == 0x02: # A-ASSOCIATE-AC
                    assoc_ac_found = True
                    # Crude check if PC ID 1 (used by C-FIND-RQ in payload) was accepted.
                    # A real parser would check the result for PC ID 1.
                    # Example: if b'\x01\x00\x00\x00' (PC ID 1, result 0, transfer syntax) is in AC results.
                    # This is also weak without full AC PDU parsing.

                elif pdu_type == 0x04: # P-DATA-TF
                    pdv_details_list = get_dicom_pdv_details(packet)
                    for pdv_data, pc_id, is_command in pdv_details_list:
                        if is_command: 
                            # The scene payload for C-FIND-RQ specifies presentation_context_id: 1.
                            # This test checks if the scene processor correctly uses this PC ID
                            # for the C-FIND-RQ command, assuming auto-negotiation was successful for MWL on this PC ID.
                            cmd_dataset = parse_dicom_dataset_from_bytes(pdv_data)
                            if cmd_dataset and \
                               cmd_dataset.get("AffectedSOPClassUID") == "1.2.840.10008.5.1.4.31" and \
                               pc_id == 1: # Ensure command is on the expected PC ID
                                cfind_rq_cmd_found = True
                                break
                    if cfind_rq_cmd_found: break
        
        assert assoc_rq_found, "A-ASSOCIATE-RQ PDU not found."
        assert assoc_ac_found, "A-ASSOCIATE-AC PDU not found."
        # Stronger assertion: The DicomSceneProcessor should have created a presentation context for MWL.
        # And the C-FIND-RQ in the link should have used that presentation context ID.
        # This test relies on the scene_payload's "presentation_context_id": 1 for C-FIND-RQ to be correct
        # after auto-negotiation. A more robust test would parse the A-ASSOCIATE-AC to find the accepted PC ID for MWL
        # and then ensure the C-FIND-RQ used that ID.
        assert cfind_rq_cmd_found, "C-FIND-RQ command for MWL SOP Class not found."

    finally:
        if temp_pcap_file and os.path.exists(temp_pcap_file):
            os.remove(temp_pcap_file)

def test_scene_api_scenario_3_auto_default_link():
    """
    Scenario 3: Auto-Default Link Configuration (CT to PACS).
    - Asset 1 (SCU): Canon Aquilion Prime SP (CT), using TEMPLATE_GENERIC_CT_V1
    - Asset 2 (SCP): GE Centricity PACS, using TEMPLATE_GENERIC_PACS_V1
    - Link: explicit_presentation_contexts = None, dimse_sequence = []
    - Test Focus:
        - Auto-negotiation of presentation contexts (likely CT Image Storage and Verification).
        - DicomSceneProcessor auto-generates a default DIMSE sequence (e.g., C-ECHO-RQ).
        - Data injection from templates.
    """
    scene_payload_s3: Dict[str, Any] = {
        "scene_id": "SCENE_S3_AUTO_DEFAULT_LINK",
        "name": "Test Scenario 3: Auto-Default Link CT to PACS",
        "assets": [
            {
                "asset_id": "ASSET_CT_CANON_TEMPLATE",
                "name": "Canon Aquilion CT (from Template)",
                "asset_template_id_ref": "TEMPLATE_GENERIC_CT_V1", # Uses generic CT template
                "nodes": [
                    {
                        "node_id": "CT_CANON_NIC1",
                        "ip_address": "192.168.3.10",
                        "mac_address": "00:00:0E:11:22:33", # Example Canon MAC
                        "dicom_port": 10403
                    }
                ],
                "dicom_properties": { # Overrides for template if needed, or use template's
                    "ae_title": "CT_CANON_AE", # Override template AE
                    "manufacturer": "Canon Medical Systems", # Override template manufacturer
                    "model_name": "Aquilion Prime SP"      # Override template model
                    # supported_sop_classes will come from TEMPLATE_GENERIC_CT_V1
                }
            },
            {
                "asset_id": "ASSET_PACS_GE_TEMPLATE",
                "name": "GE Centricity PACS (from Template)",
                "asset_template_id_ref": "TEMPLATE_GENERIC_PACS_V1", # Uses generic PACS template
                "nodes": [
                    {
                        "node_id": "PACS_GE_NIC1",
                        "ip_address": "192.168.3.20",
                        "mac_address": "00:0A:95:AA:BB:CC", # Example GE MAC
                        "dicom_port": 11113 
                    }
                ],
                "dicom_properties": { # Overrides for template
                    "ae_title": "GE_PACS_AE", # Override template AE
                    "manufacturer": "GE HealthCare", # Override template manufacturer
                    "model_name": "Centricity PACS" # Override template model
                     # supported_sop_classes will come from TEMPLATE_GENERIC_PACS_V1
                }
            }
        ],
        "links": [
            {
                "link_id": "LINK_AUTO_CT_TO_PACS",
                "name": "Auto-configured link from CT to PACS",
                "source_asset_id_ref": "ASSET_CT_CANON_TEMPLATE",
                "source_node_id_ref": "CT_CANON_NIC1",
                "destination_asset_id_ref": "ASSET_PACS_GE_TEMPLATE",
                "destination_node_id_ref": "PACS_GE_NIC1",
                "dicom_config": {
                    "scu_asset_id_ref": "ASSET_CT_CANON_TEMPLATE",
                    "scp_asset_id_ref": "ASSET_PACS_GE_TEMPLATE",
                    "explicit_presentation_contexts": None, # Trigger auto-negotiation
                    "dimse_sequence": [] # Trigger auto-DIMSE sequence generation (e.g., C-ECHO)
                }
            }
        ]
    }

    response = client.post("/protocols/dicom/v2/generate-pcap-from-scene", json=scene_payload_s3)

    assert response.status_code == 200, f"API Error: {response.text}"
    assert response.headers["content-type"] == "application/vnd.tcpdump.pcap"
    assert len(response.content) > 0, "PCAP file content is empty."

    temp_pcap_file = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pcap", delete=False) as tmp_f:
            tmp_f.write(response.content)
            temp_pcap_file = tmp_f.name
        
        packets = rdpcap(temp_pcap_file)
        assert packets is not None, "Scapy could not read the generated PCAP file."

        # Expected: TCP Handshake (3), A-ASSOC-RQ (1), A-ASSOC-AC (1), 
        # P-DATA-TF (Cmd for C-ECHO-RQ) (1), TCP ACKs (3), TCP Teardown (4)
        # Total: 3 + 2 + 2 + 2 + 4 = 13 packets if C-ECHO is auto-generated
        assert len(packets) >= 10, f"Expected at least 10 packets for an auto-link, got {len(packets)}"

        assoc_rq_found = False
        assoc_ac_found = False
        cecho_rq_cmd_found = False
        
        # Verification SOP Class UID
        verification_sop_class_uid = "1.2.840.10008.1.1"

        for packet in packets:
            if TCP in packet and packet[TCP].payload:
                payload_bytes = bytes(packet[TCP].payload)
                pdu_type = payload_bytes[0] if len(payload_bytes) > 0 else -1

                if pdu_type == 0x01: # A-ASSOCIATE-RQ
                    assoc_rq_found = True
                    # TODO: Add more detailed parsing of A-ASSOCIATE-RQ to confirm
                    # that presentation contexts for Verification and CT Image Storage were proposed
                    # based on TEMPLATE_GENERIC_CT_V1 and TEMPLATE_GENERIC_PACS_V1.

                elif pdu_type == 0x02: # A-ASSOCIATE-AC
                    assoc_ac_found = True
                    # TODO: Add more detailed parsing of A-ASSOCIATE-AC to confirm
                    # that presentation contexts for Verification (and possibly CT Image Storage) were accepted.

                elif pdu_type == 0x04: # P-DATA-TF
                    pdv_details_list = get_dicom_pdv_details(packet)
                    for pdv_data, pc_id, is_command in pdv_details_list:
                        if is_command: # Check only command PDVs for C-ECHO-RQ
                            cmd_dataset = parse_dicom_dataset_from_bytes(pdv_data)
                            # Check if it's a C-ECHO-RQ command
                            if cmd_dataset and cmd_dataset.get("AffectedSOPClassUID") == verification_sop_class_uid:
                                # Further checks could include MessageID or CommandField if necessary
                                cecho_rq_cmd_found = True
                                break
                    if cecho_rq_cmd_found: break
        
        assert assoc_rq_found, "A-ASSOCIATE-RQ PDU not found in auto-default link."
        assert assoc_ac_found, "A-ASSOCIATE-AC PDU not found in auto-default link."
        assert cecho_rq_cmd_found, "Auto-generated C-ECHO-RQ command not found."

    finally:
        if temp_pcap_file and os.path.exists(temp_pcap_file):
            os.remove(temp_pcap_file)

def test_scene_api_scenario_4_complex_dimse_mri_vna():
    """
    Scenario 4: Complex DIMSE Sequence & Data Injection (MRI to VNA).
    - Asset 1 (SCU): Siemens MAGNETOM Vida (MRI)
    - Asset 2 (SCP): Fujifilm Synapse VNA
    - Link: DIMSE sequence with C-STORE-RQ then N-ACTION-RQ (Storage Commitment).
    - Test Focus:
        - Correct sequence of PDUs for C-STORE and N-ACTION.
        - Data injection for C-STORE: DeviceSerialNumber, SoftwareVersions.
        - Correct command set for N-ACTION.
    """
    scene_payload_s4: Dict[str, Any] = {
        "scene_id": "SCENE_S4_MRI_VNA_COMPLEX",
        "name": "Test Scenario 4: MRI to VNA - Complex DIMSE & Injection",
        "assets": [
            {
                "asset_id": "ASSET_MRI_SIEMENS_VIDA",
                "name": "Siemens MAGNETOM Vida MRI",
                "nodes": [
                    {
                        "node_id": "MRI_NIC1",
                        "ip_address": "192.168.4.10",
                        "mac_address": "00:01:C0:12:34:56", # Example Siemens MAC
                        "dicom_port": 10404
                    }
                ],
                "dicom_properties": {
                    "ae_title": "MRI_VIDA_SCU",
                    "implementation_class_uid": "1.3.12.2.1107.5.2.3.45678", # Example Siemens UID
                    "manufacturer": "Siemens Healthineers",
                    "model_name": "MAGNETOM Vida",
                    "software_versions": ["syngoMR_XA50", "NumarisX_VA10A"],
                    "device_serial_number": "MRI_SN78901",
                    "supported_sop_classes": [
                        { # MR Image Storage as SCU
                            "sop_class_uid": "1.2.840.10008.5.1.4.1.1.4", 
                            "role": "SCU",
                            "transfer_syntaxes": ["1.2.840.10008.1.2.1"]
                        },
                        { # Storage Commitment Push Model as SCU
                            "sop_class_uid": "1.2.840.10008.1.20.1", 
                            "role": "SCU",
                            "transfer_syntaxes": ["1.2.840.10008.1.2.1"]
                        },
                        { # Verification as SCU
                            "sop_class_uid": "1.2.840.1.1",
                            "role": "SCU",
                            "transfer_syntaxes": ["1.2.840.10008.1.2"]
                        }
                    ]
                }
            },
            {
                "asset_id": "ASSET_VNA_FUJI_SYNAPSE",
                "name": "Fujifilm Synapse VNA",
                "nodes": [
                    {
                        "node_id": "VNA_NIC1",
                        "ip_address": "192.168.4.20",
                        "mac_address": "00:10:B5:AA:BB:CC", # Example Fuji MAC
                        "dicom_port": 10405 
                    }
                ],
                "dicom_properties": {
                    "ae_title": "FUJI_VNA_SCP",
                    "implementation_class_uid": "1.2.392.200036.9125.1.1.1", # Example Fuji UID
                    "manufacturer": "Fujifilm",
                    "model_name": "Synapse VNA",
                    "supported_sop_classes": [
                        { # MR Image Storage as SCP
                            "sop_class_uid": "1.2.840.10008.5.1.4.1.1.4", 
                            "role": "SCP",
                            "transfer_syntaxes": ["1.2.840.10008.1.2.1"]
                        },
                        { # Storage Commitment Push Model as SCP
                            "sop_class_uid": "1.2.840.10008.1.20.1", 
                            "role": "SCP",
                            "transfer_syntaxes": ["1.2.840.10008.1.2.1"]
                        },
                        { # Verification as SCP
                            "sop_class_uid": "1.2.840.10008.1.1",
                            "role": "SCP",
                            "transfer_syntaxes": ["1.2.840.10008.1.2"]
                        }
                    ]
                }
            }
        ],
        "links": [
            {
                "link_id": "LINK_MRI_TO_VNA_STORE_COMMIT",
                "name": "MRI sends MR Image to VNA and requests Storage Commitment",
                "source_asset_id_ref": "ASSET_MRI_SIEMENS_VIDA",
                "source_node_id_ref": "MRI_NIC1",
                "destination_asset_id_ref": "ASSET_VNA_FUJI_SYNAPSE",
                "destination_node_id_ref": "VNA_NIC1",
                "dicom_config": {
                    "scu_asset_id_ref": "ASSET_MRI_SIEMENS_VIDA",
                    "scp_asset_id_ref": "ASSET_VNA_FUJI_SYNAPSE",
                    "explicit_presentation_contexts": [
                        {
                            "id": 1, # For MR Image Storage
                            "abstract_syntax": "1.2.840.10008.5.1.4.1.1.4",
                            "transfer_syntaxes": ["1.2.840.10008.1.2.1"]
                        },
                        {
                            "id": 3, # For Storage Commitment
                            "abstract_syntax": "1.2.840.10008.1.20.1",
                            "transfer_syntaxes": ["1.2.840.10008.1.2.1"]
                        }
                    ],
                    "dimse_sequence": [
                        {
                            "operation_name": "Store MR Image",
                            "message_type": "C-STORE-RQ",
                            "presentation_context_id": 1,
                            "command_set": {
                                "MessageID": 1,
                                "AffectedSOPClassUID": "1.2.840.10008.5.1.4.1.1.4",
                                "AffectedSOPInstanceUID": "AUTO_GENERATE_UID_INSTANCE",
                                "Priority": 0 # MEDIUM
                            },
                            "dataset_content_rules": {
                                "SOPClassUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_CLASS_UID",
                                "SOPInstanceUID": "AUTO_FROM_COMMAND_AFFECTED_SOP_INSTANCE_UID",
                                "PatientName": "Test^Complex^MRI",
                                "PatientID": "PATID_S4_MRI",
                                "StudyInstanceUID": "AUTO_GENERATE_UID_STUDY",
                                "SeriesInstanceUID": "AUTO_GENERATE_UID_SERIES",
                                "Modality": "MR",
                                "Manufacturer": "AUTO_FROM_ASSET_SCU_MANUFACTURER",
                                "ModelName": "AUTO_FROM_ASSET_SCU_MODEL_NAME",
                                "DeviceSerialNumber": "AUTO_FROM_ASSET_SCU_DEVICE_SERIAL_NUMBER", # MRI_SN78901
                                "SoftwareVersions": "AUTO_FROM_ASSET_SCU_SOFTWARE_VERSIONS" # ["syngoMR_XA50", "NumarisX_VA10A"]
                            }
                        },
                        {
                            "operation_name": "Request Storage Commitment",
                            "message_type": "N-ACTION-RQ",
                            "presentation_context_id": 3,
                            "command_set": {
                                "MessageID": 2, # Next MessageID
                                "RequestedSOPClassUID": "1.2.840.10008.1.20.1", # Storage Commitment SOP Class
                                "RequestedSOPInstanceUID": "AUTO_GENERATE_UID_INSTANCE", # UID for the N-ACTION transaction itself
                                "ActionTypeID": 1 # For Storage Commitment
                            },
                            "dataset_content_rules": { # Dataset for N-ACTION (Storage Commitment)
                                "TransactionUID": "AUTO_GENERATE_UID", # Specific for Storage Commitment
                                "ReferencedSOPSequence": [ # Sequence of items
                                    { # One item in the sequence
                                        "ReferencedSOPClassUID": "1.2.840.10008.5.1.4.1.1.4", # MR Image Storage
                                        # This should match the SOPInstanceUID of the C-STORE-RQ above.
                                        # This requires a mechanism to reference previously generated UIDs.
                                        # For now, we'll use a placeholder or a new UID.
                                        # A more advanced feature would be "AUTO_REF_PREVIOUS_SOP_INSTANCE_UID:MessageID:1"
                                        "ReferencedSOPInstanceUID": "AUTO_GENERATE_UID_INSTANCE" # Placeholder
                                    }
                                ]
                            }
                        }
                    ]
                }
            }
        ]
    }

    response = client.post("/protocols/dicom/v2/generate-pcap-from-scene", json=scene_payload_s4)

    assert response.status_code == 200, f"API Error: {response.text}"
    assert response.headers["content-type"] == "application/vnd.tcpdump.pcap"
    assert len(response.content) > 0, "PCAP file content is empty."

    temp_pcap_file = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pcap", delete=False) as tmp_f:
            tmp_f.write(response.content)
            temp_pcap_file = tmp_f.name
        
        packets = rdpcap(temp_pcap_file)
        assert packets is not None, "Scapy could not read the generated PCAP file."

        # Expected packets: TCP Handshake (3), A-ASSOC-RQ (1), A-ASSOC-AC (1), 
        # C-STORE-RQ (Cmd+Data) (2 PDUs), N-ACTION-RQ (Cmd+Data) (2 PDUs), TCP ACKs (approx 6), TCP Teardown (4)
        # Total: 3 + 2 + 2 + (2+2) + (2+2) + 4 = 19 (approx)
        assert len(packets) >= 15, f"Expected at least 15 packets for C-STORE + N-ACTION, got {len(packets)}"

        cstore_rq_dataset_found = False
        naction_rq_dataset_found = False
        
        parsed_cstore_sop_instance_uid = None
        # Expected PC IDs for C-STORE-RQ and N-ACTION-RQ in this test
        expected_cstore_pc_id_s4 = 1
        expected_naction_pc_id_s4 = 3

        # --- BEGIN GENERAL PACKET DUMP ---
        print("\n[Test 4] --- BEGIN GENERAL PACKET DUMP ---")
        for i_s4, pkt_dump_s4 in enumerate(packets):
            print(f"[Test 4] Raw Packet #{i_s4}: {pkt_dump_s4.summary()}")
            if IP in pkt_dump_s4:
                print(f"  IP Src: {pkt_dump_s4[IP].src}, IP Dst: {pkt_dump_s4[IP].dst}")
            if TCP in pkt_dump_s4:
                print(f"  TCP Sport: {pkt_dump_s4[TCP].sport}, TCP Dport: {pkt_dump_s4[TCP].dport}")
                if pkt_dump_s4[TCP].payload:
                    raw_payload_dump_s4 = bytes(pkt_dump_s4[TCP].payload)
                    payload_len_dump_s4 = len(raw_payload_dump_s4)
                    pdu_type_dump_s4 = raw_payload_dump_s4[0] if payload_len_dump_s4 > 0 else "N/A"
                    pdu_type_str_s4 = f"{pdu_type_dump_s4:02x}" if isinstance(pdu_type_dump_s4, int) else str(pdu_type_dump_s4)
                    print(f"  TCP Payload: Exists, Length: {payload_len_dump_s4}, First Byte (PDU Type): {pdu_type_str_s4}")
                else:
                    print("  TCP Payload: None or empty")
        print("[Test 4] --- END GENERAL PACKET DUMP ---\n")
        # --- END GENERAL PACKET DUMP ---

        for packet_idx, packet in enumerate(packets): # Added packet_idx for logging
                if IP in packet and packet[IP].src == "192.168.4.10" and packet[IP].dst == "192.168.4.20" and TCP in packet and packet[TCP].dport == 10405: # SCU to SCP
                    print(f"\n[Test 4] Processing packet {packet_idx} from SCU to SCP (ports {packet[TCP].sport}->{packet[TCP].dport})")
                    # --- BEGIN ADDED LOGGING ---
                    if packet[TCP].payload:
                        tcp_payload_bytes_for_log_s4 = bytes(packet[TCP].payload)
                        print(f"[Test 4] Packet {packet_idx}: TCP payload exists. Length: {len(tcp_payload_bytes_for_log_s4)}")
                        if len(tcp_payload_bytes_for_log_s4) > 0:
                            print(f"[Test 4] Packet {packet_idx}: TCP payload first byte (PDU Type): {tcp_payload_bytes_for_log_s4[0]:02x}")
                            print(f"[Test 4] Packet {packet_idx}: TCP payload first 10 bytes: {tcp_payload_bytes_for_log_s4[:10].hex()}")
                        else:
                            print(f"[Test 4] Packet {packet_idx}: TCP payload is empty.")
                    else:
                        print(f"[Test 4] Packet {packet_idx}: No TCP payload (packet[TCP].payload is None or empty).")
                    # --- END ADDED LOGGING ---
                    pdv_details_list = get_dicom_pdv_details(packet)
                    if not pdv_details_list:
                        print(f"[Test 4] Packet {packet_idx}: No PDVs found by get_dicom_pdv_details (returned empty list).")
                    for pdv_idx, (pdv_data, pc_id, is_command) in enumerate(pdv_details_list): # Added pdv_idx for logging
                        print(f"[Test 4] Packet {packet_idx}, PDV {pdv_idx}: pc_id={pc_id}, is_command={is_command}, len={len(pdv_data)}")
                        if is_command:
                            print(f"[Test 4] Packet {packet_idx}, PDV {pdv_idx}: Command PDV, skipping for data checks.")
                            continue 
                        
                        dataset = parse_dicom_dataset_from_bytes(pdv_data)
                        if not dataset:
                            print(f"[Test 4] Packet {packet_idx}, PDV {pdv_idx}: Dataset parsing failed or returned empty.")
                            continue
    
                        # Check for C-STORE-RQ Data Dataset
                        if pc_id == expected_cstore_pc_id_s4 and \
                           dataset.get("SOPClassUID") == "1.2.840.10008.5.1.4.1.1.4" and \
                           dataset.get("PatientID") == "PATID_S4_MRI":
                            print(f"[Test 4] Packet {packet_idx}, PDV {pdv_idx}: Matched expected C-STORE data conditions (pc_id={expected_cstore_pc_id_s4}). Validating fields...")
                            print(f"  Manufacturer: {dataset.get('Manufacturer')}")
                            print(f"  ManufacturerModelName: {dataset.get('ManufacturerModelName')}")
                            print(f"  DeviceSerialNumber: {dataset.get('DeviceSerialNumber')}")
                            print(f"  SoftwareVersions: {dataset.get('SoftwareVersions')}")
                            assert dataset.Manufacturer == "Siemens Healthineers"
                            assert dataset.ManufacturerModelName == "MAGNETOM Vida"
                            assert dataset.DeviceSerialNumber == "MRI_SN78901"
                            assert dataset.SoftwareVersions == ["syngoMR_XA50", "NumarisX_VA10A"]
                            parsed_cstore_sop_instance_uid = dataset.SOPInstanceUID 
                            cstore_rq_dataset_found = True
                            print(f"[Test 4] Packet {packet_idx}, PDV {pdv_idx}: C-STORE assertions passed. cstore_rq_dataset_found = True. SOPInstanceUID: {parsed_cstore_sop_instance_uid}")
    
                        # Check for N-ACTION-RQ Data Dataset (Storage Commitment)
                        elif pc_id == expected_naction_pc_id_s4 and \
                             dataset.get("TransactionUID"): # Removed cstore_rq_dataset_found from here to allow independent check
                            print(f"[Test 4] Packet {packet_idx}, PDV {pdv_idx}: Matched N-ACTION data conditions (pc_id={expected_naction_pc_id_s4}). Validating fields...")
                            print(f"  TransactionUID: {dataset.get('TransactionUID')}")
                            print(f"  ReferencedSOPSequence: {dataset.get('ReferencedSOPSequence')}")
                            assert "ReferencedSOPSequence" in dataset
                            ref_seq = dataset.ReferencedSOPSequence
                            assert len(ref_seq) == 1
                            assert ref_seq[0].ReferencedSOPClassUID == "1.2.840.10008.5.1.4.1.1.4" # MR Image Storage
                            # UID matching for ReferencedSOPInstanceUID is still a known challenge
                            print(f"[Test 4] Packet {packet_idx}, PDV {pdv_idx}: N-ACTION assertions passed. naction_rq_dataset_found = True.")
                            naction_rq_dataset_found = True
                        else:
                            print(f"[Test 4] Packet {packet_idx}, PDV {pdv_idx}: Data PDV did not match C-STORE or N-ACTION conditions. SOPClassUID: {dataset.get('SOPClassUID')}, PatientID: {dataset.get('PatientID')}, TransactionUID: {dataset.get('TransactionUID')}")

                if cstore_rq_dataset_found and naction_rq_dataset_found:
                    print("[Test 4] Both C-STORE and N-ACTION RQ Datasets found, breaking from packet loop.")
                    break
                # else:
                # print(f"[Test 4] Packet {packet_idx} processed. C-STORE found: {cstore_rq_dataset_found}, N-ACTION found: {naction_rq_dataset_found}")
        
        assert cstore_rq_dataset_found, "C-STORE-RQ data dataset with correct MRI injected values not found."
        assert naction_rq_dataset_found, "N-ACTION-RQ data dataset for Storage Commitment not found or incorrect."

    finally:
        if temp_pcap_file and os.path.exists(temp_pcap_file):
            os.remove(temp_pcap_file)

def test_scene_api_scenario_5_error_asset_not_found():
    """
    Scenario 5: Error Case - Asset Not Found in Link.
    - Scene defines one asset.
    - Link references a non-existent asset ID for SCP.
    - Test Focus: API should return a 400 Bad Request with an appropriate error message.
    """
    scene_payload_s5: Dict[str, Any] = {
        "scene_id": "SCENE_S5_ERROR_ASSET_NOT_FOUND",
        "name": "Test Scenario 5: Error - Asset Not Found",
        "assets": [
            { # Only one asset defined
                "asset_id": "ASSET_CT_ONLY_ONE",
                "name": "The Only CT Scanner",
                "nodes": [
                    {
                        "node_id": "CT_ONLY_NIC1",
                        "ip_address": "192.168.5.10",
                        "mac_address": "00:AA:BB:CC:DD:EE",
                        "dicom_port": 10405
                    }
                ],
                "dicom_properties": {
                    "ae_title": "CT_ONLY_AE",
                    "implementation_class_uid": "1.2.826.0.1.3680043.2.1143.107.104.103.0",
                    "manufacturer": "Test Systems",
                    "model_name": "ErrorMaker 100",
                    "supported_sop_classes": [
                        { 
                            "sop_class_uid": "1.2.840.10008.1.1", # Verification
                            "role": "SCU",
                            "transfer_syntaxes": ["1.2.840.10008.1.2"]
                        }
                    ]
                }
            }
        ],
        "links": [
            {
                "link_id": "LINK_TO_NON_EXISTENT_SCP",
                "name": "Link referencing a non-existent SCP asset",
                "source_asset_id_ref": "ASSET_CT_ONLY_ONE",
                "source_node_id_ref": "CT_ONLY_NIC1",
                "destination_asset_id_ref": "ASSET_NON_EXISTENT_PACS", # This asset is not defined
                "destination_node_id_ref": "PACS_GHOST_NIC1",
                "dicom_config": {
                    "scu_asset_id_ref": "ASSET_CT_ONLY_ONE",
                    "scp_asset_id_ref": "ASSET_NON_EXISTENT_PACS", # Error here
                    "explicit_presentation_contexts": [
                         {
                            "id": 1,
                            "abstract_syntax": "1.2.840.10008.1.1", 
                            "transfer_syntaxes": ["1.2.840.10008.1.2"]
                        }
                    ],
                    "dimse_sequence": [
                        {
                            "operation_name": "Echo to Ghost",
                            "message_type": "C-ECHO-RQ",
                            "presentation_context_id": 1,
                            "command_set": {"MessageID": 1}
                        }
                    ]
                }
            }
        ]
    }

    response = client.post("/protocols/dicom/v2/generate-pcap-from-scene", json=scene_payload_s5)

    assert response.status_code == 400, f"Expected HTTP 400 Bad Request, got {response.status_code}. Response: {response.text}"
    response_json = response.json()
    assert "detail" in response_json
    # DicomSceneProcessor raises AssetNotFoundError, which should translate to a 400 error detail.
    # The exact message might vary based on how DicomSceneProcessorError is handled by the FastAPI endpoint.
    # We expect the detail to mention the missing asset ID.
    assert "ASSET_NON_EXISTENT_PACS" in response_json["detail"], \
        f"Error detail should mention the missing asset ID. Got: {response_json['detail']}"
    assert "Asset with ID" in response_json["detail"] and "not found" in response_json["detail"], \
        f"Error detail message mismatch. Got: {response_json['detail']}"
