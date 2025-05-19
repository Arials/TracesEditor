"""
Test suite for DICOM PCAP generation functionality.

This module contains pytest-based tests to verify the correct construction
of Scapy packets, DICOM PDU encapsulation, and PCAP file writing.
It primarily tests the function responsible for generating a DICOM PCAP
based on a JSON configuration (assumed to be `generate_dicom_pcap` from
`backend.protocols.dicom.handler`).
"""
import pytest
import os
import tempfile
from scapy.all import Ether, IP, TCP, rdpcap

from backend.protocols.dicom.handler import generate_dicom_pcap

from backend.protocols.dicom.utils import (
    create_associate_rq_pdu,
    create_associate_ac_pdu,
    create_p_data_tf_pdu,
    create_dicom_dataset
)

# --- Test Data ---

SAMPLE_JSON_CONFIG = {
  "connection_details": {
    "source_mac": "00:00:00:AA:BB:CC",
    "destination_mac": "00:00:00:DD:EE:FF",
    "source_ip": "192.168.1.100",
    "destination_ip": "192.168.1.200",
    "source_port": 56789,
    "destination_port": 104
  },
  "association_request": {
    "calling_ae_title": "SCU_AET_TEST",
    "called_ae_title": "SCP_AET_TEST",
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
        "AffectedSOPInstanceUID": "1.2.826.0.1.3680043.9.1234.1.1.1" # Unique SOP Instance UID
      },
      "data_set": {
        "SOPClassUID": "1.2.840.10008.5.1.4.1.1.2",
        "SOPInstanceUID": "1.2.826.0.1.3680043.9.1234.1.1.1",
        "PatientName": "Test^PCAPGen",
        "PatientID": "PCAP001",
        "StudyInstanceUID": "1.2.826.0.1.3680043.9.1234.1",
        "SeriesInstanceUID": "1.2.826.0.1.3680043.9.1234.1.1",
        "Modality": "CT",
        "InstanceNumber": "1"
      }
    }
  ],
  "simulation_settings": { # Optional: to guide the generate_dicom_pcap function
      "simulate_association_rejection": False,
      "simulate_scp_response": True # Whether to include A-ASSOCIATE-AC and other SCP responses
  }
}

# --- Test Functions ---

def test_pcap_file_creation_and_packet_count():
    """
    Verify PCAP file creation and an expected number of packets for a basic DICOM exchange.
    """
    temp_file = None
    try:
        # Use NamedTemporaryFile to get a path, ensure it's deleted afterwards
        with tempfile.NamedTemporaryFile(suffix=".pcap", delete=False) as tmp_f:
            temp_pcap_path = tmp_f.name
        
        # Call the PCAP generation function (from Task 2.6)
        generate_dicom_pcap(SAMPLE_JSON_CONFIG, temp_pcap_path)

        assert os.path.exists(temp_pcap_path), "PCAP file was not created."
        assert os.path.getsize(temp_pcap_path) > 0, "PCAP file is empty."

        packets = rdpcap(temp_pcap_path)
        assert packets is not None, "Scapy could not read the generated PCAP file."
        
        # Expected packet count:
        # TCP Handshake: SYN, SYN-ACK, ACK (3 packets)
        # A-ASSOCIATE-RQ: 1 packet (SCU -> SCP)
        # A-ASSOCIATE-AC: 1 packet (SCP -> SCU, if simulate_scp_response is True)
        # P-DATA-TF (Command): 1 packet (SCU -> SCP)
        # P-DATA-TF (DataSet): 1 packet (SCU -> SCP)
        # TCP ACK for P-DATA-TF from SCP: 1-2 packets (if simulated)
        # TCP Teardown (FINs, ACKs): ~4 packets
        # Lower bound: 3 (HS) + 1 (RQ) + 1 (PDataCmd) + 1 (PDataDS) + ~2 (FINs/ACKs) = ~8
        # Upper bound if AC and ACKs for PData are included: 3 + 1 + 1 + 1 + 1 + 2 + 4 = ~13
        # This is a rough estimate and depends heavily on generate_dicom_pcap implementation.
        # For a very basic SCU-only C-STORE (no SCP response, minimal TCP):
        # SYN, (SYN-ACK from SCP implied for RQ to proceed), ACK
        # A-ASSOCIATE-RQ
        # P-DATA-TF (Cmd)
        # P-DATA-TF (DS)
        # FIN, ACK
        # A more robust test would be to check for specific PDU types rather than exact count.
        # For now, let's check a reasonable minimum.
        # If generate_dicom_pcap only generates the SCU side of C-STORE without full TCP/AC:
        # A-ASSOCIATE-RQ (1) + P-DATA-TF Cmd (1) + P-DATA-TF DS (1) = 3 packets minimum carrying DICOM.
        # With TCP layers, each of these would be wrapped.
        # Let's assume a minimal flow: SYN, SYN_ACK, ACK, RQ, AC, P_DATA_CMD, P_DATA_DS, FIN, FIN_ACK, ACK
        # This is highly dependent on the implementation of generate_dicom_pcap.
        # For now, a loose check:
        # Based on generate_dicom_session_packet_list:
        # TCP Handshake (3)
        # A-ASSOC-RQ + ACK (2)
        # A-ASSOC-AC + ACK (2) (if simulated)
        # P-DATA-TF (Cmd) + ACK (2)
        # P-DATA-TF (DS) + ACK (2) (if data_set present)
        # TCP Teardown (4)
        # Min for C-STORE: 3 + 2 + 2 + 2 + 2 + 4 = 15 packets
        # Min for C-ECHO (no DS): 3 + 2 + 2 + 2 + 4 = 13 packets
        # The SAMPLE_JSON_CONFIG has one C-STORE message.
        # So, expected count is 15 if simulate_scp_response is True.
        if SAMPLE_JSON_CONFIG.get("simulation_settings", {}).get("simulate_scp_response", True) and \
           SAMPLE_JSON_CONFIG["dicom_messages"][0].get("data_set"):
            expected_min_packets = 15
        elif SAMPLE_JSON_CONFIG.get("simulation_settings", {}).get("simulate_scp_response", True): # No data set
            expected_min_packets = 13
        else: # No SCP response at all
            # SYN, ACK (from SCP for SYN), RQ, FIN, ACK (from SCP for FIN) - very minimal
            expected_min_packets = 5 # This is a rough guess if SCP is not responsive
        
        assert len(packets) >= expected_min_packets, f"Expected at least {expected_min_packets} packets, got {len(packets)}."

    finally:
        if temp_pcap_path and os.path.exists(temp_pcap_path):
            os.remove(temp_pcap_path)

def test_ethernet_ip_tcp_headers_match_config():
    """
    Verify that Ethernet, IP, and TCP headers in generated packets match the JSON input.
    """
    temp_pcap_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pcap", delete=False) as tmp_f:
            temp_pcap_path = tmp_f.name
        
        generate_dicom_pcap(SAMPLE_JSON_CONFIG, temp_pcap_path)
        packets = rdpcap(temp_pcap_path)

        assert len(packets) > 0, "PCAP file contains no packets."

        conn_details = SAMPLE_JSON_CONFIG['connection_details']
        src_mac = conn_details['source_mac']
        dst_mac = conn_details['destination_mac']
        src_ip = conn_details['source_ip']
        dst_ip = conn_details['destination_ip']
        src_port = conn_details['source_port']
        dst_port = conn_details['destination_port']

        # Check at least one packet presumably from SCU to SCP
        # More sophisticated checks might try to identify specific packets (e.g., A-ASSOCIATE-RQ)
        scu_to_scp_packet_found = False
        for packet in packets:
            if Ether in packet and IP in packet and TCP in packet:
                # Check for SCU -> SCP direction
                if packet[Ether].src.lower() == src_mac.lower() and \
                   packet[Ether].dst.lower() == dst_mac.lower() and \
                   packet[IP].src == src_ip and \
                   packet[IP].dst == dst_ip and \
                   packet[TCP].sport == src_port and \
                   packet[TCP].dport == dst_port:
                    scu_to_scp_packet_found = True
                    # Basic assertions for the first such packet found
                    assert packet[Ether].src.lower() == src_mac.lower()
                    assert packet[Ether].dst.lower() == dst_mac.lower()
                    assert packet[IP].src == src_ip
                    assert packet[IP].dst == dst_ip
                    assert packet[TCP].sport == src_port
                    assert packet[TCP].dport == dst_port
                    break 
        
        assert scu_to_scp_packet_found, "No SCU -> SCP packet matching config found."

        # If SCP responses are simulated, check a packet from SCP to SCU
        if SAMPLE_JSON_CONFIG.get("simulation_settings", {}).get("simulate_scp_response", True): # Corrected this condition to True
            scp_to_scu_packet_found = False
            for packet in packets:
                if Ether in packet and IP in packet and TCP in packet:
                    # Check for SCP -> SCU direction (ports and IPs/MACs swapped)
                    if packet[Ether].src.lower() == dst_mac.lower() and \
                       packet[Ether].dst.lower() == src_mac.lower() and \
                       packet[IP].src == dst_ip and \
                       packet[IP].dst == src_ip and \
                       packet[TCP].sport == dst_port and \
                       packet[TCP].dport == src_port:
                        scp_to_scu_packet_found = True
                        assert packet[Ether].src.lower() == dst_mac.lower()
                        assert packet[Ether].dst.lower() == src_mac.lower()
                        assert packet[IP].src == dst_ip
                        assert packet[IP].dst == src_ip
                        assert packet[TCP].sport == dst_port
                        assert packet[TCP].dport == src_port
                        break
            assert scp_to_scu_packet_found, "No SCP -> SCU packet matching config found (SCP response expected)."

    finally:
        if temp_pcap_path and os.path.exists(temp_pcap_path):
            os.remove(temp_pcap_path)

def test_dicom_pdu_payloads_are_correct():
    """
    Verify that TCP payloads of relevant packets contain correctly serialized DICOM PDUs.
    """
    temp_pcap_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pcap", delete=False) as tmp_f:
            temp_pcap_path = tmp_f.name
        
        generate_dicom_pcap(SAMPLE_JSON_CONFIG, temp_pcap_path)
        packets = rdpcap(temp_pcap_path)
        assert len(packets) > 0, "PCAP file contains no packets."

        # 1. Generate expected PDU byte strings
        assoc_req_config = SAMPLE_JSON_CONFIG['association_request']
        expected_assoc_rq_bytes = create_associate_rq_pdu(
            calling_ae_title=assoc_req_config['calling_ae_title'],
            called_ae_title=assoc_req_config['called_ae_title'],
            application_context_name=assoc_req_config['application_context_name'],
            presentation_contexts_input=assoc_req_config['presentation_contexts'],
            user_identity_input=assoc_req_config.get('user_identity') # Add user_identity_input if present in config
        )

        expected_assoc_ac_bytes = None
        if SAMPLE_JSON_CONFIG.get("simulation_settings", {}).get("simulate_scp_response", True): # Default is True now
            # Construct a plausible A-ASSOCIATE-AC based on the RQ
            pc_results_ac_data = []
            for pc_rq in assoc_req_config.get('presentation_contexts', []):
                if pc_rq.get('transfer_syntaxes') and len(pc_rq['transfer_syntaxes']) > 0:
                    pc_results_ac_data.append({
                        'id': pc_rq['id'],
                        'result': 0,  # Acceptance
                        'transfer_syntax': pc_rq['transfer_syntaxes'][0] # Accept first proposed
                    })
                else: # Should not happen if JSON is valid, but handle defensively
                     pc_results_ac_data.append({
                        'id': pc_rq['id'],
                        'result': 3, 
                        'transfer_syntax': '1.2.840.10008.1.2' 
                    })

            if pc_results_ac_data: # Only create if there are results
                expected_assoc_ac_bytes = create_associate_ac_pdu(
                    calling_ae_title=assoc_req_config['called_ae_title'], # Swapped for AC
                    called_ae_title=assoc_req_config['calling_ae_title'],   # Swapped for AC
                    application_context_name=assoc_req_config['application_context_name'],
                    presentation_contexts_results_input=pc_results_ac_data
                )

        dicom_msg_config = SAMPLE_JSON_CONFIG['dicom_messages'][0]
        cmd_set_input = dicom_msg_config['command_set']
        dataset_input = dicom_msg_config['data_set']

        # Create Command Dataset for P-DATA-TF (Command)
        cmd_ds = create_dicom_dataset(cmd_set_input)
        # pynetdicom utils for P-DATA-TF expect is_implicit_VR and is_little_endian
        # to be set on the dataset to correctly encode it.
        cmd_ds.is_implicit_VR = True 
        cmd_ds.is_little_endian = True
        # Add CommandDataSetType if not present, C-STORE-RQ has a dataset
        if 'CommandDataSetType' not in cmd_ds:
             cmd_ds.CommandDataSetType = 0x0000 # Presence of data_set means this will be non-zero (0x0101)
                                               # but pynetdicom might fill this. For C-STORE, it's type 0x0101 (has data)
                                               # If data_set is None, it's 0x0102.
                                               # Let's assume create_p_data_tf_pdu or underlying pynetdicom handles this.
                                               # For C-STORE-RQ, it must indicate a following data set.
                                               # The `create_p_data_tf_pdu` in utils.py does not auto-set this.
                                               # The command_set from JSON should include it or it should be added.
                                               # For C-STORE-RQ, CommandDataSetType should be 0x0101 (has dataset)
        if dicom_msg_config['message_type'] == "C-STORE-RQ" and dataset_input:
            cmd_ds.CommandDataSetType = 0x0101 # Has dataset
        elif not dataset_input : # e.g. C-ECHO
            cmd_ds.CommandDataSetType = 0x0102 # No dataset


        expected_pdata_cmd_bytes = create_p_data_tf_pdu(
            dimse_dataset=cmd_ds,
            presentation_context_id=dicom_msg_config['presentation_context_id'],
            is_command=True
        )
        
        expected_pdata_ds_bytes = None
        if dataset_input:
            data_ds = create_dicom_dataset(dataset_input)
            data_ds.is_implicit_VR = True
            data_ds.is_little_endian = True
            expected_pdata_ds_bytes = create_p_data_tf_pdu(
                dimse_dataset=data_ds,
                presentation_context_id=dicom_msg_config['presentation_context_id'],
                is_command=False # This is data
            )

        # 2. Find these PDUs in the packet list
        found_assoc_rq = False
        # If simulate_scp_response is False in JSON, expected_assoc_ac_bytes will be None.
        # So, found_assoc_ac should start as True if we are NOT expecting AC.
        # If simulate_scp_response is True, expected_assoc_ac_bytes will be populated,
        # and found_assoc_ac should start as False.
        simulate_scp_response_in_config = SAMPLE_JSON_CONFIG.get("simulation_settings", {}).get("simulate_scp_response", True)
        found_assoc_ac = not simulate_scp_response_in_config # True if not expecting AC, False if expecting AC

        found_pdata_cmd = False
        found_pdata_ds = not expected_pdata_ds_bytes # True if we are not expecting it

        for packet in packets:
            if TCP in packet and packet[TCP].payload:
                payload_bytes = bytes(packet[TCP].payload)
                if not found_assoc_rq and payload_bytes == expected_assoc_rq_bytes:
                    found_assoc_rq = True
                    # print("Found A-RQ")
                    continue
                if simulate_scp_response_in_config and expected_assoc_ac_bytes and not found_assoc_ac and payload_bytes == expected_assoc_ac_bytes:
                    found_assoc_ac = True
                    # print("Found A-AC")
                    continue
                if not found_pdata_cmd and payload_bytes == expected_pdata_cmd_bytes:
                    found_pdata_cmd = True
                    # print("Found P-DATA CMD")
                    continue
                if expected_pdata_ds_bytes and not found_pdata_ds and payload_bytes == expected_pdata_ds_bytes:
                    found_pdata_ds = True
                    # print("Found P-DATA DS")
                    continue
        
        assert found_assoc_rq, "A-ASSOCIATE-RQ PDU not found in PCAP."
        if simulate_scp_response_in_config:
            assert found_assoc_ac, "A-ASSOCIATE-AC PDU was expected but not found in PCAP."
        else:
            assert found_assoc_ac, "A-ASSOCIATE-AC PDU was not expected but was found (or logic error)." # Should be true if not expected
        assert found_pdata_cmd, "P-DATA-TF (Command) PDU not found in PCAP."
        assert found_pdata_ds, "P-DATA-TF (DataSet) PDU not found or not expected but found."

    finally:
        if temp_pcap_path and os.path.exists(temp_pcap_path):
            os.remove(temp_pcap_path)
