from scapy.all import Ether, IP, TCP, PacketList, wrpcap # Added PacketList and wrpcap
from typing import List, Dict, Any

# Assuming utils.py is in the same directory or accessible in the Python path
from .utils import (
    create_associate_rq_pdu,
    create_associate_ac_pdu,
    create_dicom_dataset,
    create_p_data_tf_pdu
)
# from .utils import create_network_layers # This specific util was for base layers, we'll define them directly for clarity in flow

def generate_dicom_pcap(json_config: Dict[str, Any], output_filepath: str) -> None:
    """
    Orchestrates the generation of a DICOM PCAP file based on a JSON configuration.

    Args:
        json_config: A dictionary containing the configuration for the PCAP generation,
                     including connection details, association parameters, and DICOM messages.
        output_filepath: The path (including filename) where the .pcap file will be saved.
    """
    # 1. Extract Network Parameters
    connection_details = json_config['connection_details']
    # network_params are directly passed to generate_dicom_session_packet_list

    # Extract TCP Initial Sequence Numbers (ISNs) if provided, else defaults in generate_dicom_session_packet_list will be used
    tcp_settings = json_config.get('tcp_settings', {})
    client_isn = tcp_settings.get('client_isn') # Will be None if not present, handled by generate_dicom_session_packet_list
    server_isn = tcp_settings.get('server_isn') # Will be None if not present, handled by generate_dicom_session_packet_list

    # 2. Generate A-ASSOCIATE-RQ PDU
    assoc_rq_config = json_config['association_request']
    assoc_rq_pdu_bytes = create_associate_rq_pdu(
        calling_ae_title=assoc_rq_config['calling_ae_title'],
        called_ae_title=assoc_rq_config['called_ae_title'],
        application_context_name=assoc_rq_config['application_context_name'],
        presentation_contexts_input=assoc_rq_config['presentation_contexts'],
        user_identity_input=assoc_rq_config.get('user_identity') # Optional, changed to user_identity_input
    )

    # 3. Generate A-ASSOCIATE-AC PDU (Conditional)
    assoc_ac_pdu_bytes = b'' # Default to empty if not simulated or no contexts
    simulate_scp_response = json_config.get("simulation_settings", {}).get("simulate_scp_response", True)

    if simulate_scp_response:
        presentation_contexts_rq = assoc_rq_config.get('presentation_contexts', [])
        presentation_contexts_results_ac = []
        if presentation_contexts_rq:
            for pc_rq in presentation_contexts_rq:
                if pc_rq.get('transfer_syntaxes') and len(pc_rq['transfer_syntaxes']) > 0:
                    presentation_contexts_results_ac.append({
                        'id': pc_rq['id'],
                        'result': 0,  # Acceptance
                        'transfer_syntax': pc_rq['transfer_syntaxes'][0] # Accept first proposed
                    })
                else:
                    # Reject if no transfer syntaxes proposed (should be caught by validation earlier)
                    presentation_contexts_results_ac.append({
                        'id': pc_rq['id'],
                        'result': 3,  # Abstract syntax not supported (provider rejection)
                        # Provide a default/common transfer syntax for the PDU structure, though it's rejected.
                        'transfer_syntax': '1.2.840.10008.1.2' # Implicit VR Little Endian
                    })
        
        if presentation_contexts_results_ac: # Only create AC if there were contexts to respond to
            app_context_name_ac = assoc_rq_config.get('application_context_name', "1.2.840.10008.3.1.1.1")
            # The create_associate_ac_pdu function in utils.py expects:
            # calling_ae_title, called_ae_title, application_context_name, presentation_contexts_results_input
            # The calling_ae_title and called_ae_title for an AC PDU are typically the *swapped* values from the RQ.
            # However, the current utils.create_associate_ac_pdu takes them as they should appear in the AC PDU.
            # The handler.py was passing app_context_name_ac (which is correct for the application_context_name param)
            # but it was missing calling_ae_title and called_ae_title.
            # The utils.create_associate_ac_pdu expects these.
            # For the AC PDU:
            # - its "Calling AE Title" is the original RQ's "Called AE Title"
            # - its "Called AE Title" is the original RQ's "Calling AE Title"
            assoc_ac_pdu_bytes = create_associate_ac_pdu(
                calling_ae_title=assoc_rq_config['called_ae_title'], # This system's AE as caller in AC
                called_ae_title=assoc_rq_config['calling_ae_title'],   # Original SCU's AE as called in AC
                application_context_name=app_context_name_ac,
                presentation_contexts_results_input=presentation_contexts_results_ac
            )

    # 4. Generate P-DATA-TF PDU List
    p_data_tf_pdu_list_bytes = []
    dicom_messages = json_config.get('dicom_messages', [])
    for msg_config in dicom_messages:
        # Command Set part of P-DATA-TF
        cmd_ds_dict = msg_config['command_set']
        cmd_ds = create_dicom_dataset(cmd_ds_dict)
        cmd_ds.is_implicit_VR = True # As per pynetdicom's default for network
        cmd_ds.is_little_endian = True

        # Determine CommandDataSetType: 0x0101 if data set is present, 0x0102 if not.
        if msg_config.get('data_set') is not None: # Check if 'data_set' key exists and is not None
            cmd_ds.CommandDataSetType = 0x0101 # Has data
        else:
            cmd_ds.CommandDataSetType = 0x0102 # No data

        p_data_cmd_bytes = create_p_data_tf_pdu(
            dimse_dataset=cmd_ds,
            presentation_context_id=msg_config['presentation_context_id'],
            is_command=True
        )
        p_data_tf_pdu_list_bytes.append(p_data_cmd_bytes)

        # Data Set part of P-DATA-TF (if present)
        if msg_config.get('data_set') is not None:
            data_ds_dict = msg_config['data_set']
            data_ds = create_dicom_dataset(data_ds_dict)
            data_ds.is_implicit_VR = True
            data_ds.is_little_endian = True
            
            p_data_ds_bytes = create_p_data_tf_pdu(
                dimse_dataset=data_ds,
                presentation_context_id=msg_config['presentation_context_id'],
                is_command=False
            )
            p_data_tf_pdu_list_bytes.append(p_data_ds_bytes)

    # 5. Call generate_dicom_session_packet_list
    # Prepare arguments for generate_dicom_session_packet_list, handling optional ISNs
    packet_list_args = {
        'network_params': connection_details,
        'associate_rq_pdu_bytes': assoc_rq_pdu_bytes,
        'associate_ac_pdu_bytes': assoc_ac_pdu_bytes,
        'p_data_tf_pdu_list': p_data_tf_pdu_list_bytes
    }
    if client_isn is not None:
        packet_list_args['client_isn'] = client_isn
    if server_isn is not None:
        packet_list_args['server_isn'] = server_isn
        
    packet_list = generate_dicom_session_packet_list(**packet_list_args)

    # 6. Write PCAP File
    wrpcap(output_filepath, packet_list)
    # print(f"DICOM PCAP file generated at: {output_filepath}") # Optional: for debugging or CLI tool


def generate_dicom_session_packet_list(
    network_params: Dict[str, Any],
    associate_rq_pdu_bytes: bytes,
    associate_ac_pdu_bytes: bytes,
    p_data_tf_pdu_list: List[bytes],
    client_isn: int = 1000,
    server_isn: int = 2000
) -> PacketList:
    """
    Generates a Scapy PacketList simulating a DICOM association and data transfer.

    Args:
        network_params: Dictionary with 'source_mac', 'destination_mac', 
                        'source_ip', 'destination_ip', 'source_port', 
                        'destination_port'.
        associate_rq_pdu_bytes: Bytes of the A-ASSOCIATE-RQ PDU.
        associate_ac_pdu_bytes: Bytes of the A-ASSOCIATE-AC PDU.
        p_data_tf_pdu_list: A list of P-DATA-TF PDU byte strings to be sent from client to server.
        client_isn: Client's initial TCP sequence number.
        server_isn: Server's initial TCP sequence number.
        
    Returns:
        A Scapy PacketList object.
    """
    packets = []
    
    # Extract network parameters
    src_mac = network_params['source_mac']
    dst_mac = network_params['destination_mac']
    src_ip = network_params['source_ip']
    dst_ip = network_params['destination_ip']
    src_port = network_params['source_port'] # Client/SCU port
    dst_port = network_params['destination_port'] # Server/SCP port

    # Define Ether and IP layers for both directions
    ether_scu_to_scp = Ether(src=src_mac, dst=dst_mac)
    ip_scu_to_scp = IP(src=src_ip, dst=dst_ip)
    
    ether_scp_to_scu = Ether(src=dst_mac, dst=src_mac)
    ip_scp_to_scu = IP(src=dst_ip, dst=src_ip)

    # TCP Sequence and Acknowledgment numbers
    scu_seq = client_isn
    scp_seq = server_isn
    
    # --- TCP Handshake ---
    # 1. SCU -> SCP: SYN
    tcp_syn = TCP(sport=src_port, dport=dst_port, flags='S', seq=scu_seq)
    packets.append(ether_scu_to_scp / ip_scu_to_scp / tcp_syn)
    scu_seq += 1

    # 2. SCP -> SCU: SYN/ACK
    tcp_syn_ack = TCP(sport=dst_port, dport=src_port, flags='SA', seq=scp_seq, ack=scu_seq)
    packets.append(ether_scp_to_scu / ip_scp_to_scu / tcp_syn_ack)
    scp_seq += 1

    # 3. SCU -> SCP: ACK
    tcp_ack_handshake = TCP(sport=src_port, dport=dst_port, flags='A', seq=scu_seq, ack=scp_seq)
    packets.append(ether_scu_to_scp / ip_scu_to_scp / tcp_ack_handshake)

    # --- A-ASSOCIATE-RQ (SCU -> SCP) ---
    tcp_assoc_rq = TCP(sport=src_port, dport=dst_port, flags='PA', seq=scu_seq, ack=scp_seq)
    packets.append(ether_scu_to_scp / ip_scu_to_scp / tcp_assoc_rq / associate_rq_pdu_bytes)
    scu_seq += len(associate_rq_pdu_bytes)

    # --- ACK for A-ASSOCIATE-RQ (SCP -> SCU) ---
    tcp_ack_for_assoc_rq = TCP(sport=dst_port, dport=src_port, flags='A', seq=scp_seq, ack=scu_seq)
    packets.append(ether_scp_to_scu / ip_scp_to_scu / tcp_ack_for_assoc_rq)
    
    # --- A-ASSOCIATE-AC (SCP -> SCU) ---
    tcp_assoc_ac = TCP(sport=dst_port, dport=src_port, flags='PA', seq=scp_seq, ack=scu_seq)
    packets.append(ether_scp_to_scu / ip_scp_to_scu / tcp_assoc_ac / associate_ac_pdu_bytes)
    scp_seq += len(associate_ac_pdu_bytes)

    # --- ACK for A-ASSOCIATE-AC (SCU -> SCP) ---
    tcp_ack_for_assoc_ac = TCP(sport=src_port, dport=dst_port, flags='A', seq=scu_seq, ack=scp_seq)
    packets.append(ether_scu_to_scp / ip_scu_to_scp / tcp_ack_for_assoc_ac)

    # --- P-DATA-TF (SCU -> SCP) ---
    for p_data_pdu_bytes in p_data_tf_pdu_list:
        tcp_p_data = TCP(sport=src_port, dport=dst_port, flags='PA', seq=scu_seq, ack=scp_seq)
        packets.append(ether_scu_to_scp / ip_scu_to_scp / tcp_p_data / p_data_pdu_bytes)
        scu_seq += len(p_data_pdu_bytes)

        # --- ACK for P-DATA-TF (SCP -> SCU) ---
        # Each P-DATA-TF from SCU should be ACKed by SCP
        tcp_ack_for_p_data = TCP(sport=dst_port, dport=src_port, flags='A', seq=scp_seq, ack=scu_seq)
        packets.append(ether_scp_to_scu / ip_scp_to_scu / tcp_ack_for_p_data)

    # --- TCP Teardown (SCU initiates FIN) ---
    # 1. SCU -> SCP: FIN/ACK
    tcp_fin_scu = TCP(sport=src_port, dport=dst_port, flags='FA', seq=scu_seq, ack=scp_seq)
    packets.append(ether_scu_to_scp / ip_scu_to_scp / tcp_fin_scu)
    scu_seq += 1
    
    # 2. SCP -> SCU: ACK (for SCU's FIN)
    tcp_ack_scp_fin = TCP(sport=dst_port, dport=src_port, flags='A', seq=scp_seq, ack=scu_seq)
    packets.append(ether_scp_to_scu / ip_scp_to_scu / tcp_ack_scp_fin)

    # 3. SCP -> SCU: FIN/ACK (SCP also closes its end)
    tcp_fin_scp = TCP(sport=dst_port, dport=src_port, flags='FA', seq=scp_seq, ack=scu_seq)
    packets.append(ether_scp_to_scu / ip_scp_to_scu / tcp_fin_scp)
    scp_seq += 1

    # 4. SCU -> SCP: ACK (for SCP's FIN)
    tcp_ack_scu_fin = TCP(sport=src_port, dport=dst_port, flags='A', seq=scu_seq, ack=scp_seq)
    packets.append(ether_scu_to_scp / ip_scu_to_scp / tcp_ack_scu_fin)

    # Return the list of packets
    return PacketList(packets)


# Example JSON config for testing generate_dicom_pcap directly
SAMPLE_JSON_CONFIG_FOR_HANDLER_TEST = {
    "connection_details": {
        "source_mac": "00:1A:2B:3C:4D:5E",
        "destination_mac": "00:5E:4D:3C:2B:1A",
        "source_ip": "192.168.1.101",
        "destination_ip": "192.168.1.201",
        "source_port": 11113,
        "destination_port": 11112 # Standard DICOM port often 104 or 11112
    },
    "tcp_settings": { # Optional
        "client_isn": 1000,
        "server_isn": 2000
    },
    "association_request": {
        "calling_ae_title": "TEST_SCU",
        "called_ae_title": "TEST_SCP",
        "application_context_name": "1.2.840.10008.3.1.1.1",
        "presentation_contexts": [
            {
                "id": 1,
                "abstract_syntax": "1.2.840.10008.5.1.4.1.1.2", # CT Image Storage
                "transfer_syntaxes": ["1.2.840.10008.1.2.1"] # Explicit VR Little Endian
            },
            {
                "id": 3,
                "abstract_syntax": "1.2.840.10008.5.1.4.1.1.4", # MR Image Storage
                "transfer_syntaxes": ["1.2.840.10008.1.2.1", "1.2.840.10008.1.2"] # EVRLE, IVRLE
            }
        ]
        # "user_identity": null # Optional
    },
    "simulation_settings": { # Optional
        "simulate_scp_response": True # If false, no A-ASSOCIATE-AC will be in PCAP
    },
    "dicom_messages": [
        { # Example: C-STORE-RQ for a CT Image
            "presentation_context_id": 1, # Must match one of the accepted PC IDs
            "command_set": {
                "AffectedSOPClassUID": "1.2.840.10008.5.1.4.1.1.2", # CT Image Storage
                "CommandField": 1, # C-STORE-RQ
                "MessageID": 1,
                "Priority": 0, # MEDIUM
                "AffectedSOPInstanceUID": "1.3.6.1.4.1.9590.100.1.2.123456789.123456789.1234567890",
                "MoveOriginatorApplicationEntityTitle": "TEST_SCU", # Optional for C-STORE
                "MoveOriginatorMessageID": 123 # Optional for C-STORE
                # For C-STORE-RSP, CommandDataSetType would be 0x8000 series
            },
            "data_set": { # The actual DICOM data to be "sent"
                "PatientName": "Doe^John",
                "PatientID": "123456",
                "Modality": "CT",
                "SOPClassUID": "1.2.840.10008.5.1.4.1.1.2",
                "SOPInstanceUID": "1.3.6.1.4.1.9590.100.1.2.123456789.123456789.1234567890"
                # ... other DICOM elements ...
            }
        },
        { # Example: C-ECHO-RQ (has no data set)
            "presentation_context_id": 3, # Assuming PC ID 3 was for Verification SOP Class
            "command_set": {
                "AffectedSOPClassUID": "1.2.840.10008.1.1", # Verification SOP Class
                "CommandField": 48, # C-ECHO-RQ (0x0030)
                "MessageID": 2
                # For C-ECHO-RSP, CommandDataSetType would be 0x8000 series, Status would be 0x0000
            }
            # No "data_set" for C-ECHO-RQ
        }
    ]
}


if __name__ == '__main__':
    # from scapy.all import wrpcap # Import wrpcap for testing only - moved to top
    # Example Usage (for testing this module directly)
    # This part would typically be orchestrated by the FastAPI endpoint (Task 3.1)
    
    # Dummy network parameters
    net_params = {
        "source_mac": "00:11:22:33:44:55", "destination_mac": "AA:BB:CC:DD:EE:FF",
        "source_ip": "192.168.1.100", "destination_ip": "192.168.1.200",
        "source_port": 11112, "destination_port": 104 # Standard DICOM port
    }

    # Dummy PDU bytes (replace with actual PDU bytes from utils.py functions)
    # These lengths are arbitrary for example. Real PDUs will have varying lengths.
    dummy_assoc_rq_bytes = b'\x01\x00' + b'\x00' * 150 # A-ASSOCIATE-RQ PDU Type 0x01
    dummy_assoc_ac_bytes = b'\x02\x00' + b'\x00' * 100 # A-ASSOCIATE-AC PDU Type 0x02
    dummy_p_data_tf_bytes_cstore = b'\x04\x00' + b'\x00' * 200 # P-DATA-TF PDU Type 0x04

    # Simulate a list of P-DATA-TF PDUs (e.g., one C-STORE-RQ)
    p_data_list = [dummy_p_data_tf_bytes_cstore]

    output_pcap_file = "dicom_test_session.pcap"

    print(f"Generating example PacketList for PCAP: {output_pcap_file}...")
    packet_list_for_pcap = generate_dicom_session_packet_list(
        network_params=net_params,
        associate_rq_pdu_bytes=dummy_assoc_rq_bytes,
        associate_ac_pdu_bytes=dummy_assoc_ac_bytes,
        p_data_tf_pdu_list=p_data_list
    )
    wrpcap(output_pcap_file, packet_list_for_pcap)
    print(f"Example PCAP '{output_pcap_file}' generated with {len(packet_list_for_pcap)} packets. Please inspect with Wireshark.")
