# --- Imports ---
import shutil
import uuid
import ipaddress
import traceback
from random import randint
from typing import Dict, List, Callable, Optional, Union # Added Callable, Optional, Union

# Scapy imports (ensure scapy[complete] is installed)
# Suppress Scapy IPv6 warning if problematic, but better to have IPv6 enabled
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
from scapy.all import rdpcap, wrpcap, Ether, IP, TCP, UDP, ICMP, PacketList, Raw, Packet # Removed TCPSession, Session

# FastAPI specific imports (needed for UploadFile, HTTPException, FileResponse)
from fastapi import UploadFile, HTTPException
from fastapi.responses import FileResponse

# Local imports
from pathlib import Path # Added for dummy storage - will be removed if __main__ is removed
import sys # Added for checking module import status in dummy - likely removable

# Use absolute imports assuming 'backend' is in sys.path
from backend import storage 
from backend import models
RuleInput = models.RuleInput
Rule = models.Rule
from backend.exceptions import JobCancelledException


# --- Constants and Setup ---
# SESSION_DIR is now managed by the storage module.
# os.makedirs(SESSION_DIR, exist_ok=True) # REMOVED

# --- Global Mappings (Consider if these should be session-specific) ---
# These dictionaries maintain mapping consistency *within a single run* of apply_anonymization
# or generate_preview. They reset if the backend restarts or between calls if not managed.
ip_map: Dict[str, str] = {}
mac_map: Dict[str, str] = {}

# --- Helper Functions ---

def anon_mac(mac: str) -> str:
    """Generates a randomized MAC address while preserving the OUI (vendor part)."""
    try:
        oui = mac.upper().split(':')[:3]
        if len(oui) != 3: # Basic validation
             raise ValueError("Invalid MAC format for OUI extraction")
        random_tail = ':'.join(f'{randint(0, 255):02X}' for _ in range(3))
        return f"{':'.join(oui)}:{random_tail}"
    except Exception:
        # Fallback for unexpected MAC formats
        logging.warning(f"Could not anonymize MAC '{mac}'. Using random MAC.")
        return ':'.join(f'{randint(0, 255):02X}' for _ in range(6))


def anon_ip(ip: str, rules: List[Rule], current_ip_map: Dict[str, str]) -> str:
    """
    Translates an IP address based on user-defined CIDR rules.
    Falls back to a unique random 10.x.x.x address for the session if no rule matches.
    Uses the provided current_ip_map to ensure uniqueness of fallback IPs.
    """
    try:
        ip_addr = ipaddress.ip_address(ip)
        # Check against user rules first (rules should be pre-sorted by specificity)
        for rule_model in rules:
            # Use .model_dump() or .dict() if using older Pydantic
            rule = rule_model.model_dump(by_alias=False)
            src_key = rule.get('source')
            tgt_key = rule.get('target')
            if not (src_key and tgt_key):
                continue # Skip invalid rules

            try:
                net_from = ipaddress.ip_network(src_key, strict=False)
                if ip_addr in net_from:
                    net_to = ipaddress.ip_network(tgt_key, strict=False)
                    # Calculate offset within the source network
                    offset = int(ip_addr) - int(net_from.network_address)
                    # Apply offset to the target network, handling network size differences
                    if offset < net_to.num_addresses:
                        new_ip_int = int(net_to.network_address) + offset
                        # Ensure the new IP is within the target network bounds
                        if new_ip_int <= int(net_to.broadcast_address):
                             new_ip_str = str(ipaddress.ip_address(new_ip_int))
                             return new_ip_str # Return the successfully translated IP
                    # If offset doesn't fit or rule is otherwise unusable
                    logging.debug(f"anon_ip: Offset issue or rule unusable for IP {ip} with rule {src_key} -> {tgt_key}. Falling back.")
                    # If the specific rule matched but offset failed, break the loop to force fallback
                    break # Exit the rule loop to force fallback below

            except ValueError as e:
                continue # Skip rule if CIDRs are invalid

        # Fallback: random 10.x.x.x unique across the current ip_map values
        # Reached ONLY if the loop completes without returning a translated IP or breaking due to offset issue
        attempts = 0
        while attempts < 1000: # Limit attempts to prevent hangs
            rand_ip = f"10.{randint(0, 255)}.{randint(0, 255)}.{randint(1, 254)}"
            # Ensure the generated random IP is not already a target value for another original IP
            if rand_ip not in current_ip_map.values(): # Use current_ip_map
                 return rand_ip
            attempts += 1
        # If we can't find a unique random IP after many attempts
        logging.warning(f"Could not generate unique random IP for {ip} after {attempts} attempts.")
        fallback_ip = f"10.255.255.{randint(1,254)}"
        return fallback_ip

    except ValueError:
        logging.warning(f"anon_ip: Invalid original IP address format '{ip}'. Returning as is.")
        return ip # Return original if it's not a valid IP

# --- Core API Logic Functions (IP/MAC Anonymization) ---

# --- MODIFIED save_rules to accept physical session ID and rules list ---
def save_rules(session_id: str, rules: List[Dict]):
    """
    Saves user-defined transformation rules to the specified session directory.

    Args:
        session_id: The actual physical session ID (directory ID) where rules should be saved.
        rules: A list of rule dictionaries (e.g., [{'source': '...', 'target': '...'}]).
    """
    logging.info(f"Attempting to save rules for physical session ID: {session_id}")
    try:
        if not isinstance(rules, list):
             raise ValueError("Invalid format for rules: input must be a list.")
        # The rules are expected to be dictionaries already, as passed from main.py
        # No need to call model_dump here if main.py already did it.
        # If rules were passed as Rule models, we would dump them:
        # canonical = [rule.model_dump(by_alias=False) if hasattr(rule, 'model_dump') else rule.dict(by_alias=False) for rule in rules]
        # Assuming 'rules' is already List[Dict]
        canonical = rules
        storage.store_rules(session_id, canonical) # Use the provided physical session_id
        logging.info(f"Rules saved successfully for physical session {session_id}")
        return {"status": "ok"}
    except Exception as e:
        logging.exception(f"Error saving rules for physical session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save rules: {e}")


def generate_preview(session_id: str, input_pcap_filename: str):
    """Generates a preview of anonymized data based on saved rules."""
    global ip_map, mac_map
    # Use temporary maps for preview to avoid polluting global state used by apply_anonymization
    temp_ip_map: Dict[str, str] = {}
    temp_mac_map: Dict[str, str] = {}

    try:
        rules_data = storage.get_rules(session_id) # Use new storage method
        if rules_data is None: # Handle case where rules might not exist
            rules_data = []
        rules_models = [Rule(**rule_data) for rule_data in rules_data]
        # Sort rules for preview consistency (same logic as apply)
        rules_models.sort(key=lambda rule: ipaddress.ip_network(rule.source, strict=False).prefixlen, reverse=True)
        # path = storage.get_capture_path(session_id) # No longer needed directly
        packets = storage.read_pcap_from_session(session_id, filename=input_pcap_filename) # Use new storage method
    except FileNotFoundError: # Raised by read_pcap_from_session if file not found
         raise HTTPException(status_code=404, detail=f"Session data or PCAP file '{input_pcap_filename}' not found for preview.")
    except Exception as e: # Other errors from storage or rule processing
         raise HTTPException(status_code=500, detail=f"Error loading data for preview (file '{input_pcap_filename}'): {e}")

    seen = set()
    preview = []
    # Limit preview to a reasonable number of unique flows to avoid large responses/long processing
    preview_limit = 100
    count = 0
    for pkt in packets:
        if count >= preview_limit:
            break
        if Ether in pkt and IP in pkt:
            src_ip = pkt[IP].src if hasattr(pkt[IP], 'src') else None
            dst_ip = pkt[IP].dst if hasattr(pkt[IP], 'dst') else None
            src_mac = pkt[Ether].src if hasattr(pkt[Ether], 'src') else None
            dst_mac = pkt[Ether].dst if hasattr(pkt[Ether], 'dst') else None

            if not all([src_ip, dst_ip, src_mac, dst_mac]):
                continue

            key = (src_ip, dst_ip, src_mac, dst_mac)
            if key in seen:
                continue
            seen.add(key)
            count += 1

            original = {
                'src_ip': src_ip, 'dst_ip': dst_ip,
                'src_mac': src_mac, 'dst_mac': dst_mac,
            }

            # Call anon_ip for preview, passing the temporary map
            anon_src_ip = temp_ip_map.setdefault(src_ip, anon_ip(src_ip, rules_models, temp_ip_map))
            anon_dst_ip = temp_ip_map.setdefault(dst_ip, anon_ip(dst_ip, rules_models, temp_ip_map))
            anon_src_mac = temp_mac_map.setdefault(src_mac, anon_mac(src_mac))
            anon_dst_mac = temp_mac_map.setdefault(dst_mac, anon_mac(dst_mac))

            anonymized = {
                'src_ip': anon_src_ip,
                'dst_ip': anon_dst_ip,
                'src_mac': anon_src_mac,
                'dst_mac': anon_dst_mac,
            }
            preview.append({'original': original, 'anonymized': anonymized})
    logging.info(f"Preview generated for session {session_id} from '{input_pcap_filename}' (limit: {preview_limit} flows)")
    return preview


# --- MODIFIED apply_anonymization with progress and cancellation callbacks ---
def apply_anonymization(
    input_trace_id: str,
    input_pcap_filename: str,
    new_output_trace_id: str,
    output_pcap_filename: str,
    progress_callback: Optional[Callable[[int], None]] = None,
    check_stop_requested: Optional[Callable[[], bool]] = None
) -> Dict[str, Union[Path, str]]:
    """
    Applies anonymization rules to the input PCAP file and saves the result to a new trace.

    Args:
        input_trace_id: The ID of the input trace.
        input_pcap_filename: The name of the PCAP file to process within the input trace.
        new_output_trace_id: The ID for the new output trace where the anonymized PCAP will be saved.
        output_pcap_filename: The name for the anonymized PCAP file in the new output trace.
        progress_callback: An optional function to call with progress percentage (0-100).
        check_stop_requested: An optional function to call to check if cancellation is requested.

    Returns:
        A dictionary containing information about the output.
    """
    global ip_map, mac_map
    ip_map.clear()
    mac_map.clear()
    logging.info(f"Starting IP/MAC anonymization: Input Trace ID {input_trace_id}, Input File '{input_pcap_filename}' -> Output Trace ID {new_output_trace_id}, Output File '{output_pcap_filename}'")

    try:
        rules_data = storage.get_rules(input_trace_id) # Use input_trace_id for rules
        if rules_data is None:
            rules_data = []
        rules_models = [Rule(**rule_data) for rule_data in rules_data]

        rules_models.sort(key=lambda rule: ipaddress.ip_network(rule.source, strict=False).prefixlen, reverse=True)

        logging.info(f"Reading packets for input trace {input_trace_id}, file '{input_pcap_filename}' using storage module...")
        packets: PacketList = storage.read_pcap_from_session(input_trace_id, filename=input_pcap_filename)
        logging.info(f"Read {len(packets)} packets from '{input_pcap_filename}'.")
    except FileNotFoundError as e:
        logging.error(f"Error in apply_anonymization: Session data or PCAP file '{input_pcap_filename}' not found for input trace {input_trace_id}. Details: {e}")
        raise
    except Exception as e:
        logging.error(f"Error loading data for anonymization (input trace {input_trace_id}, file '{input_pcap_filename}'): {e}")
        raise

    new_packets = []
    total_packets = len(packets)
    last_reported_progress = -1

    logging.info(f"Processing {total_packets} packets for anonymization...")
    for i, pkt in enumerate(packets):

        if check_stop_requested and (i % 100 == 0 or i == total_packets - 1):
            if check_stop_requested():
                logging.info(f"!!! [Anonymizer] Stop requested. Aborting transformation for input trace {input_trace_id} at packet {i+1}/{total_packets}.")
                raise JobCancelledException("Stop requested by user.")

        processed_packet = pkt
        original_src_ip = 'N/A'
        original_dst_ip = 'N/A'
        anon_src_ip_final = 'N/A (Not Processed)'
        anon_dst_ip_final = 'N/A (Not Processed)'

        try:
            if Ether in pkt and IP in pkt:
                processed_packet = pkt.copy()
                original_src_ip = processed_packet[IP].src if hasattr(processed_packet[IP], 'src') else 'N/A'
                original_dst_ip = processed_packet[IP].dst if hasattr(processed_packet[IP], 'dst') else 'N/A'

                if hasattr(processed_packet[Ether], 'src'):
                    processed_packet[Ether].src = mac_map.setdefault(processed_packet[Ether].src, anon_mac(processed_packet[Ether].src))
                if hasattr(processed_packet[Ether], 'dst'):
                    processed_packet[Ether].dst = mac_map.setdefault(processed_packet[Ether].dst, anon_mac(processed_packet[Ether].dst))

                resolved_src_ip = 'N/A'
                resolved_dst_ip = 'N/A'

                if hasattr(processed_packet[IP], 'src'):
                    resolved_src_ip = ip_map.setdefault(original_src_ip, anon_ip(original_src_ip, rules_models, ip_map))
                    processed_packet[IP].src = resolved_src_ip
                if hasattr(processed_packet[IP], 'dst'):
                    resolved_dst_ip = ip_map.setdefault(original_dst_ip, anon_ip(original_dst_ip, rules_models, ip_map))
                    processed_packet[IP].dst = resolved_dst_ip

                anon_src_ip_final = processed_packet[IP].src
                anon_dst_ip_final = processed_packet[IP].dst

                del processed_packet[IP].chksum
                if TCP in processed_packet: del processed_packet[TCP].chksum
                if UDP in processed_packet: del processed_packet[UDP].chksum
                if ICMP in processed_packet: del processed_packet[ICMP].chksum
            else:
                 if IP in processed_packet:
                      anon_src_ip_final = processed_packet[IP].src
                      anon_dst_ip_final = processed_packet[IP].dst
                 else:
                      anon_src_ip_final = 'N/A (No IP)'
                      anon_dst_ip_final = 'N/A (No IP)'
            new_packets.append(processed_packet)
        except Exception as packet_err:
             logging.warning(f"Error processing packet {i+1}/{total_packets} in input trace {input_trace_id}: {packet_err}. Appending original.")
             new_packets.append(pkt)

        if progress_callback and total_packets > 0:
            current_progress = int(((i + 1) / total_packets) * 100)
            if current_progress > last_reported_progress and (current_progress % 5 == 0 or current_progress == 100):
                try:
                    progress_callback(current_progress)
                    last_reported_progress = current_progress
                except Exception as cb_err:
                    logging.warning(f"Progress callback failed during anonymization: {cb_err}")

    try:
        logging.info(f"Writing {len(new_packets)} processed packets to '{output_pcap_filename}' for new output trace {new_output_trace_id} using storage module...")
        output_path_obj = storage.write_pcap_to_session(new_output_trace_id, output_pcap_filename, PacketList(new_packets)) # Ensure PacketList
        logging.info(f"Successfully wrote anonymized file: {str(output_path_obj)}")
    except Exception as e:
        logging.error(f"Error writing anonymized pcap file for new output trace {new_output_trace_id} to '{output_pcap_filename}': {e}")
        raise

    return {
        "output_trace_id": new_output_trace_id,
        "output_filename": output_pcap_filename,
        "full_output_path": str(output_path_obj)
    }


# --- Backward Compatibility / Download Helper ---
def apply_anonymization_response(session_id: str, filename: str):
    """
    Serves an already anonymized PCAP file from the specified session.
    This function assumes the file has already been processed by `apply_anonymization`.

    Args:
        session_id: The actual physical session ID (directory ID) where the file resides.
        filename: The name of the anonymized PCAP file to be served.
    """
    try:
        file_path = storage.get_session_filepath(session_id, filename)
        if not file_path.exists():
            logging.error(f"File not found for download: session {session_id}, filename {filename}")
            raise HTTPException(status_code=404, detail=f"File '{filename}' not found in session '{session_id}'.")

        logging.info(f"Serving file: {file_path} for session {session_id}")
        return FileResponse(
            str(file_path),
            media_type='application/vnd.tcpdump.pcap',
            filename=filename
        )
    except HTTPException: # Re-raise HTTPExceptions directly
        raise
    except Exception as e:
        logging.error(f"Error serving file {filename} for session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to serve file '{filename}': {e}")


def get_subnets(session_id: str, input_pcap_filename: str):
    """Identifies /24 subnets present in the specified PCAP file using storage module."""
    # path = storage.get_capture_path(session_id) # No longer needed directly
    try:
        packets = storage.read_pcap_from_session(session_id, filename=input_pcap_filename) # Use new storage method
    except FileNotFoundError: # Raised by read_pcap_from_session
        logging.error(f"Error in get_subnets: PCAP file '{input_pcap_filename}' not found for session {session_id}.")
        raise HTTPException(status_code=404, detail=f"PCAP file '{input_pcap_filename}' not found for this session.")
    except Exception as e: # Other errors from storage
        logging.error(f"Error reading PCAP '{input_pcap_filename}' for get_subnets ({session_id}): {e}")
        raise HTTPException(status_code=500, detail=f"Error reading PCAP file '{input_pcap_filename}': {e}")

    all_ips = set()
    for pkt in packets:
        if IP in pkt:
            # Add IPs safely, checking for attribute existence
            if hasattr(pkt[IP], 'src'): all_ips.add(pkt[IP].src)
            if hasattr(pkt[IP], 'dst'): all_ips.add(pkt[IP].dst)

    subnets = {}
    invalid_ips_count = 0
    for ip_str in all_ips:
        try:
            # Calculate the /24 network for each valid IP
            network = ipaddress.ip_network(f"{ip_str}/24", strict=False)
            cidr = str(network)
            subnets[cidr] = subnets.get(cidr, 0) + 1
        except ValueError:
            # Count invalid IP formats encountered
            invalid_ips_count += 1
            logging.warning(f"Invalid IP format encountered in get_subnets: {ip_str}")

    if invalid_ips_count > 0:
        logging.warning(f"Skipped {invalid_ips_count} invalid IP addresses in get_subnets for session {session_id}.")

    # Sort subnets by CIDR string for consistent output
    sorted_subnets = sorted(subnets.items())
    return [{"cidr": cidr, "ip_count": count} for cidr, count in sorted_subnets]
