"""
Test suite for the DICOM PCAP Generation FastAPI endpoint.

This module contains pytest-based integration tests to verify the
`/protocols/dicom/generate-pcap` endpoint. It checks if the endpoint
correctly processes a JSON payload, generates a PCAP file, and if
the contents of that PCAP file are as expected.
"""
import pytest
import os
import tempfile
from fastapi.testclient import TestClient
from scapy.all import Ether, IP, TCP, rdpcap

# Import the FastAPI app instance
from backend.main import app

# Import PDU creation utilities to verify payloads if necessary
from backend.protocols.dicom.utils import (
    create_associate_rq_pdu,
    create_associate_ac_pdu,
    create_p_data_tf_pdu,
    create_dicom_dataset
)
from backend.protocols.dicom.models import DicomPcapRequestPayload # To validate/construct payload

# --- Test Data ---

# Adapted from test_dicom_pcap_generation.py and json_input_definition.md
SAMPLE_API_PAYLOAD_DICT = {
  "connection_details": {
    "source_mac": "00:11:22:AA:BB:CC",
    "destination_mac": "00:11:22:DD:EE:FF",
    "source_ip": "192.168.1.110",
    "destination_ip": "192.168.1.210",
    "source_port": 56790,
    "destination_port": 11112 # Using a common alternative DICOM port
  },
  "association_request": {
    "calling_ae_title": "API_SCU_AET",
    "called_ae_title": "API_SCP_AET",
    "application_context_name": "1.2.840.10008.3.1.1.1",
    "presentation_contexts": [
      {
        "id": 1,
        "abstract_syntax": "1.2.840.10008.5.1.4.1.1.2", # CT Image Storage
        "transfer_syntaxes": [
          "1.2.840.10008.1.2.1", # Explicit VR Little Endian
          "1.2.840.10008.1.2"    # Implicit VR Little Endian
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
        "Priority": 1, # MEDIUM
        "AffectedSOPClassUID": "1.2.840.10008.5.1.4.1.1.2",
        "AffectedSOPInstanceUID": "1.3.6.1.4.1.9590.100.1.2.123456789.123456789.1" # Example UID
        # extra_fields can be added here if needed
      },
      "data_set": {
        "elements": {
            "SOPClassUID": "1.2.840.10008.5.1.4.1.1.2",
            "SOPInstanceUID": "1.3.6.1.4.1.9590.100.1.2.123456789.123456789.1",
            "PatientName": "API^Test^Patient",
            "PatientID": "API-PAT001",
            "StudyInstanceUID": "1.3.6.1.4.1.9590.100.1.2.123456789",
            "SeriesInstanceUID": "1.3.6.1.4.1.9590.100.1.2.123456789.123456789",
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
        # Priority, AffectedSOPClassUID, AffectedSOPInstanceUID are optional in CommandSetItem
        # and not typically part of C-ECHO-RQ command set, so they are omitted.
        # extra_fields can be added here if needed
      },
      "data_set": None # Explicitly None for C-ECHO
    }
  ]
}


# --- Test Functions ---

client = TestClient(app)

def test_generate_dicom_pcap_endpoint_success():
    """
    Test the /protocols/dicom/generate-pcap endpoint for successful PCAP generation.
    Verifies API response and basic PCAP content.
    """
    response = client.post("/protocols/dicom/generate-pcap", json=SAMPLE_API_PAYLOAD_DICT)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.tcpdump.pcap"
    assert len(response.content) > 0, "PCAP file content is empty."

    temp_pcap_file = None
    try:
        # Save the response content to a temporary file to read with Scapy
        with tempfile.NamedTemporaryFile(suffix=".pcap", delete=False) as tmp_f:
            tmp_f.write(response.content)
            temp_pcap_file = tmp_f.name
        
        packets = rdpcap(temp_pcap_file)
        assert packets is not None, "Scapy could not read the generated PCAP file from API response."

        # --- Basic Packet Count Assertion ---
        # Based on backend/main.py logic for generate_dicom_pcap_endpoint:
        # TCP Handshake (SYN, SYN-ACK, ACK) = 3 packets
        # A-ASSOCIATE-RQ + TCP ACK from SCP = 2 packets
        # A-ASSOCIATE-AC + TCP ACK from SCU = 2 packets
        # For C-STORE-RQ:
        #   P-DATA-TF (Command) + TCP ACK from SCP = 2 packets
        #   P-DATA-TF (DataSet) + TCP ACK from SCP = 2 packets
        # For C-ECHO-RQ:
        #   P-DATA-TF (Command) + TCP ACK from SCP = 2 packets
        # TCP Teardown (FINs, ACKs from both sides) = 4 packets
        # Total for C-STORE + C-ECHO: 3 + 2 + 2 + (2+2 for C-STORE) + (2 for C-ECHO) + 4 = 17 packets
        expected_packet_count = 17 
        assert len(packets) == expected_packet_count, \
            f"Expected {expected_packet_count} packets, but got {len(packets)}."

        # --- Header Verification (similar to test_dicom_pcap_generation.py) ---
        conn_details = SAMPLE_API_PAYLOAD_DICT['connection_details']
        src_mac = conn_details['source_mac']
        dst_mac = conn_details['destination_mac']
        src_ip = conn_details['source_ip']
        dst_ip = conn_details['destination_ip']
        src_port = conn_details['source_port']
        dst_port = conn_details['destination_port']

        # Check a packet from SCU (client) to SCP (server)
        scu_to_scp_packet_found = False
        for packet in packets:
            if Ether in packet and IP in packet and TCP in packet:
                if packet[Ether].src.lower() == src_mac.lower() and \
                   packet[IP].src == src_ip and \
                   packet[TCP].sport == src_port:
                    assert packet[Ether].dst.lower() == dst_mac.lower()
                    assert packet[IP].dst == dst_ip
                    assert packet[TCP].dport == dst_port
                    scu_to_scp_packet_found = True
                    break
        assert scu_to_scp_packet_found, "No SCU -> SCP packet matching config found."

        # Check a packet from SCP (server) to SCU (client) - e.g., A-ASSOCIATE-AC
        scp_to_scu_packet_found = False
        for packet in packets:
            if Ether in packet and IP in packet and TCP in packet:
                if packet[Ether].src.lower() == dst_mac.lower() and \
                   packet[IP].src == dst_ip and \
                   packet[TCP].sport == dst_port:
                    assert packet[Ether].dst.lower() == src_mac.lower()
                    assert packet[IP].dst == src_ip
                    assert packet[TCP].dport == src_port
                    scp_to_scu_packet_found = True
                    break
        assert scp_to_scu_packet_found, "No SCP -> SCU packet matching config found (e.g., A-ASSOCIATE-AC)."
        
        # --- DICOM PDU Payload Verification (Simplified for API test) ---
        # More detailed PDU byte-matching is in test_dicom_utils.py and test_dicom_pcap_generation.py.
        # Here, we'll just check for the presence of key PDUs by looking for their characteristic start bytes
        # or by attempting a high-level decode if simple.

        # Expected PDU Payloads (generated by the endpoint's logic)
        # A-ASSOCIATE-RQ (Type 0x01)
        # A-ASSOCIATE-AC (Type 0x02)
        # P-DATA-TF (Type 0x04)

        assoc_rq_found = False
        assoc_ac_found = False
        p_data_tf_store_cmd_found = False
        p_data_tf_store_data_found = False
        p_data_tf_echo_cmd_found = False

        # Crude check for PDU types in TCP payloads
        for packet in packets:
            if TCP in packet and packet[TCP].payload:
                payload_bytes = bytes(packet[TCP].payload)
                if len(payload_bytes) > 6: # Minimum PDU length
                    pdu_type = payload_bytes[0]
                    # Check source to ensure we are looking at the right direction for RQ/CMD
                    is_from_scu = IP in packet and packet[IP].src == src_ip

                    if pdu_type == 0x01 and is_from_scu: # A-ASSOCIATE-RQ
                        assoc_rq_found = True
                    elif pdu_type == 0x02 and not is_from_scu: # A-ASSOCIATE-AC
                        assoc_ac_found = True
                    elif pdu_type == 0x04 and is_from_scu: # P-DATA-TF
                        # This is a very rough check. A real P-DATA-TF has PDVs.
                        # We'd need to parse PDVs to distinguish command/data and message type.
                        # For this API test, we'll assume order or count for now.
                        # The endpoint sends C-STORE (Cmd, Data), then C-ECHO (Cmd)
                        if not p_data_tf_store_cmd_found:
                             p_data_tf_store_cmd_found = True
                        elif not p_data_tf_store_data_found and SAMPLE_API_PAYLOAD_DICT["dicom_messages"][0]["data_set"] is not None:
                             p_data_tf_store_data_found = True
                        elif not p_data_tf_echo_cmd_found:
                             p_data_tf_echo_cmd_found = True


        assert assoc_rq_found, "A-ASSOCIATE-RQ PDU type (0x01) not found in SCU->SCP packets."
        assert assoc_ac_found, "A-ASSOCIATE-AC PDU type (0x02) not found in SCP->SCU packets."
        assert p_data_tf_store_cmd_found, "P-DATA-TF for C-STORE-RQ command not indicated."
        assert p_data_tf_store_data_found, "P-DATA-TF for C-STORE-RQ data not indicated."
        assert p_data_tf_echo_cmd_found, "P-DATA-TF for C-ECHO-RQ command not indicated."

    finally:
        if temp_pcap_file and os.path.exists(temp_pcap_file):
            os.remove(temp_pcap_file)

def test_generate_dicom_pcap_endpoint_invalid_payload():
    """
    Test the endpoint with an invalid JSON payload (e.g., missing required fields).
    """
    invalid_payload = {
        "connection_details": {
            "source_ip": "192.168.1.1" 
            # Missing other required fields like destination_ip, ports, MACs
        }
        # Missing association_request, dicom_messages
    }
    response = client.post("/protocols/dicom/generate-pcap", json=invalid_payload)
    assert response.status_code == 422 # Unprocessable Entity for Pydantic validation errors

    response_json = response.json()
    assert "detail" in response_json
    # Check for some expected missing fields in the error details
    # This depends on Pydantic's error reporting structure
    found_dst_ip_error = False
    found_assoc_req_error = False
    # Pydantic's error location ('loc') for nested models is a tuple.
    # Example: ('body', 'connection_details', 'destination_ip')
    # Example: ('body', 'association_request')
    for error in response_json["detail"]:
        loc = error.get("loc", [])
        if isinstance(loc, list) and len(loc) > 1 and loc[0] == "body": # Ensure it's a list starting with 'body'
            # Convert to tuple for easier comparison if needed, or check elements
            loc_tuple = tuple(loc)
            if loc_tuple == ("body", "connection_details", "destination_ip"):
                found_dst_ip_error = True
            elif loc_tuple == ("body", "association_request"):
                found_assoc_req_error = True
            # Add more specific checks if other fields are expected to be missing
            # For the current invalid_payload, these are the primary missing top-level keys after 'body'
            # or nested keys that would cause validation failure.
            # The `invalid_payload` is missing `destination_mac`, `source_mac`, `destination_port`, `source_port`
            # under `connection_details`, and the entire `association_request` and `dicom_messages`.

    # Check for the specific errors we expect from the invalid_payload
    # 1. Missing fields in connection_details (e.g. destination_ip)
    # 2. Missing 'association_request'
    # 3. Missing 'dicom_messages'
    
    # Let's refine the check to be more robust based on Pydantic's typical output
    missing_fields_errors = {tuple(err.get("loc", ())): err for err in response_json.get("detail", [])}

    # Check for missing destination_ip within connection_details
    assert ("body", "connection_details", "destination_ip") in missing_fields_errors, \
        "Error detail for missing connection_details.destination_ip not found."
    
    # Check for missing association_request (which is a required top-level field in DicomPcapRequestPayload)
    assert ("body", "association_request") in missing_fields_errors, \
        "Error detail for missing association_request not found."
        
    # Check for missing dicom_messages (also a required top-level field)
    assert ("body", "dicom_messages") in missing_fields_errors, \
        "Error detail for missing dicom_messages not found."

# Add more tests:
# - Test with minimal valid payload (e.g., only C-ECHO, no data_set)
# - Test specific error conditions if the handler logic has them (e.g., invalid UIDs, though Pydantic might catch some)
