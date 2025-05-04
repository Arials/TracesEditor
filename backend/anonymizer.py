# --- Imports ---
import os
import shutil
import uuid
import ipaddress
from random import randint
from typing import Dict, List, Callable, Optional # Added Callable, Optional

# Scapy imports (ensure scapy[complete] is installed)
# Suppress Scapy IPv6 warning if problematic, but better to have IPv6 enabled
import logging
logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
from scapy.all import rdpcap, wrpcap, Ether, IP, TCP, UDP, ICMP, PacketList

# FastAPI specific imports (needed for UploadFile, HTTPException, FileResponse)
from fastapi import UploadFile, HTTPException
from fastapi.responses import FileResponse

# Local imports
# Make sure these modules exist and SESSION_DIR is correctly defined/exported
try:
    # Ensure SESSION_DIR is correctly defined/imported, e.g. from storage or defined below
    from storage import store, get_rules, get_capture_path, SESSION_DIR
    from models import RuleInput, Rule
except ImportError as e:
    print(f"ERROR: Failed to import local modules (storage, models): {e}")
    print("Please ensure storage.py and models.py are in the same directory or accessible")
    # Provide default SESSION_DIR if import fails, for basic functionality
    SESSION_DIR = './sessions'
    print(f"WARNING: Using default SESSION_DIR: {SESSION_DIR}")
    # Define dummy models/functions if needed, or raise the error
    # Example dummy Rule model if models.py is missing
    class Rule:
        def __init__(self, source: str, target: str):
            self.source = source
            self.target = target
        def model_dump(self, by_alias=False):
            return {"source": self.source, "target": self.target}
    class RuleInput:
         def __init__(self, session_id: str, rules: List[Rule]):
             self.session_id = session_id
             self.rules = rules
    # Define dummy storage if storage.py is missing
    _dummy_storage = {}
    def store(sid, key, value): _dummy_storage[f"{sid}_{key}"] = value
    def get_rules(sid): return _dummy_storage.get(f"{sid}_rules", [])
    def get_capture_path(sid): return os.path.join(SESSION_DIR, f"{sid}_original.pcap")
    # raise e # Or exit, depending on desired behavior

# --- Custom Exception for Cancellation ---
class JobCancelledException(Exception):
    """Custom exception to signal job cancellation."""
    pass

# --- Constants and Setup ---
# Ensure SESSION_DIR exists
os.makedirs(SESSION_DIR, exist_ok=True)

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
        # Keep this warning print as it's not debug-specific
        print(f"Warning: Could not anonymize MAC '{mac}'. Using random MAC.")
        return ':'.join(f'{randint(0, 255):02X}' for _ in range(6))


def anon_ip(ip: str, rules: List[Rule]) -> str:
    """
    Translates an IP address based on user-defined CIDR rules.
    Falls back to a unique random 10.x.x.x address for the session if no rule matches.
    """
    global ip_map # Needs access to maintain uniqueness for fallback
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
                    # DEBUG: Temporary testing line - Print offset/rule issue
                    print(f"DEBUG anon_ip: Offset issue or rule unusable for {ip} with rule {src_key} -> {tgt_key}.")
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
            if rand_ip not in ip_map.values():
                 return rand_ip
            attempts += 1
        # If we can't find a unique random IP after many attempts
        # Keep this warning print
        print(f"Warning: Could not generate unique random IP for {ip} after {attempts} attempts.")
        fallback_ip = f"10.255.255.{randint(1,254)}"
        return fallback_ip

    except ValueError:
        # DEBUG: Temporary testing line - Print invalid input IP warning
        print(f"DEBUG anon_ip: Invalid original IP address format '{ip}'. Returning as is.")
        return ip # Return original if it's not a valid IP


# --- Core API Logic Functions ---

async def process_upload(file: UploadFile):
    """
    Handles uploaded PCAP file: saves it, extracts initial IP/MAC pairs,
    and initializes session data.
    """
    session_id = str(uuid.uuid4())
    path = get_capture_path(session_id) # Use storage function to get path

    print(f"Processing upload for new session: {session_id}")
    # print(f"Attempting to save uploaded file to: {os.path.abspath(path)}") # Optional print

    try:
        # Save the uploaded file
        with open(path, 'wb') as f:
            shutil.copyfileobj(file.file, f)
        print(f"SUCCESS: File successfully saved to: {path}")

    except Exception as e:
        print(f"ERROR: Failed to save file to {path}. Error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {e}")

    try:
        # Read the saved file to extract initial mappings
        packets = rdpcap(path)
        seen = set()
        results = []
        for pkt in packets:
            if Ether in pkt and IP in pkt:
                src_ip = pkt[IP].src if hasattr(pkt[IP], 'src') else None
                dst_ip = pkt[IP].dst if hasattr(pkt[IP], 'dst') else None
                src_mac = pkt[Ether].src if hasattr(pkt[Ether], 'src') else None
                dst_mac = pkt[Ether].dst if hasattr(pkt[Ether], 'dst') else None

                if all([src_ip, dst_ip, src_mac, dst_mac]):
                    key = (src_ip, dst_ip, src_mac, dst_mac)
                    if key not in seen:
                        results.append({
                            'src_ip': src_ip,
                            'dst_ip': dst_ip,
                            'src_mac': src_mac,
                            'dst_mac': dst_mac,
                        })
                        seen.add(key)

        store(session_id, 'rules', []) # Initialize with empty rules
        print(f"Session {session_id} initialized successfully.")
        return {"session_id": session_id, "mappings": results}

    except FileNotFoundError:
        print(f"ERROR: PCAP file {path} not found after saving!")
        raise HTTPException(status_code=500, detail="Failed to process upload: File disappeared after save.")
    except Exception as e_read:
        print(f"ERROR: Failed to read/process PCAP file {path} after saving. Error: {e_read}")
        # Clean up potentially corrupted file
        try:
            if os.path.exists(path):
                os.remove(path)
                print(f"Cleaned up potentially corrupted file: {path}")
        except OSError as rm_err:
             print(f"Error cleaning up file {path}: {rm_err}")
        raise HTTPException(status_code=400, detail=f"Failed to process uploaded PCAP file: {e_read}. Is it a valid PCAP?")


def save_rules(input: RuleInput):
    """Saves user-defined transformation rules."""
    try:
        if not isinstance(input.rules, list):
             raise ValueError("Invalid format for rules.")
        # Ensure rules are actually Rule model instances before dumping if necessary
        canonical = [rule.model_dump(by_alias=False) for rule in input.rules]
        store(input.session_id, 'rules', canonical)
        print(f"Rules saved for session {input.session_id}")
        return {"status": "ok"}
    except Exception as e:
        print(f"Error saving rules for session {input.session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save rules: {e}")


def generate_preview(session_id: str):
    """Generates a preview of anonymized data based on saved rules."""
    global ip_map, mac_map
    # Use temporary maps for preview to avoid polluting global state used by apply_anonymization
    temp_ip_map: Dict[str, str] = {}
    temp_mac_map: Dict[str, str] = {}

    try:
        rules_data = get_rules(session_id)
        rules_models = [Rule(**rule_data) for rule_data in rules_data]
        # Sort rules for preview consistency (same logic as apply)
        rules_models.sort(key=lambda rule: ipaddress.ip_network(rule.source, strict=False).prefixlen, reverse=True)
        path = get_capture_path(session_id)
        packets = rdpcap(path)
    except FileNotFoundError:
         raise HTTPException(status_code=404, detail="Session data or PCAP file not found.")
    except Exception as e:
         raise HTTPException(status_code=500, detail=f"Error loading data for preview: {e}")

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

            # Call anon_ip for preview using the temporary map (Modify anon_ip if needed)
            # NOTE: Current anon_ip uses global ip_map for fallback uniqueness check.
            # This might slightly skew preview if many fallbacks occur, but unlikely for limited preview.
            # A cleaner solution would make anon_ip accept the map as a parameter.
            anon_src_ip = temp_ip_map.setdefault(src_ip, anon_ip(src_ip, rules_models))
            anon_dst_ip = temp_ip_map.setdefault(dst_ip, anon_ip(dst_ip, rules_models))
            anon_src_mac = temp_mac_map.setdefault(src_mac, anon_mac(src_mac))
            anon_dst_mac = temp_mac_map.setdefault(dst_mac, anon_mac(dst_mac))

            anonymized = {
                'src_ip': anon_src_ip,
                'dst_ip': anon_dst_ip,
                'src_mac': anon_src_mac,
                'dst_mac': anon_dst_mac,
            }
            preview.append({'original': original, 'anonymized': anonymized})
    print(f"Preview generated for session {session_id} (limit: {preview_limit} flows)")
    return preview


# --- MODIFIED apply_anonymization with progress and cancellation callbacks ---
def apply_anonymization(
    session_id: str,
    progress_callback: Optional[Callable[[int], None]] = None,
    check_stop_requested: Optional[Callable[[], bool]] = None # Added cancellation check callback
):
    """
    Applies anonymization rules to the PCAP file for the session.

    Args:
        session_id: The ID of the session.
        progress_callback: An optional function to call with progress percentage (0-100).
        check_stop_requested: An optional function to call to check if cancellation is requested.
    """
    global ip_map, mac_map
    ip_map.clear()
    mac_map.clear()
    print(f"Starting anonymization for session {session_id}")

    try:
        rules_data = get_rules(session_id) # Load rules as dicts
        rules_models = [Rule(**rule_data) for rule_data in rules_data] # Convert to models

        # --- SORTING RULES BY SPECIFICITY ---
        rules_models.sort(key=lambda rule: ipaddress.ip_network(rule.source, strict=False).prefixlen, reverse=True)
        # -------------------------------------

        path = get_capture_path(session_id)
        print(f"Reading packets from {path}...")
        packets: PacketList = rdpcap(path)
        print(f"Read {len(packets)} packets.")
    except FileNotFoundError as e:
        print(f"Error in apply_anonymization: Session data or PCAP file not found for {session_id}. Details: {e}")
        raise # Re-raise for caller to handle
    except Exception as e:
        print(f"Error loading data for anonymization ({session_id}): {e}")
        raise # Re-raise

    output_path = os.path.join(SESSION_DIR, f"{session_id}_anon.pcap")
    new_packets = []
    total_packets = len(packets)
    last_reported_progress = -1

    print(f"Processing {total_packets} packets for anonymization...")
    # Iterate through packets and apply anonymization
    for i, pkt in enumerate(packets):

        # --- Cancellation Check ---
        # Check roughly every 100 packets or at the start/end to avoid excessive DB calls
        if check_stop_requested and (i % 100 == 0 or i == total_packets - 1):
            if check_stop_requested():
                print(f"!!! [Anonymizer] Stop requested. Aborting transformation for session {session_id} at packet {i+1}/{total_packets}.")
                raise JobCancelledException("Stop requested by user.")
        # ------------------------

        # Default to original packet, only change if modification is successful
        processed_packet = pkt
        original_src_ip = 'N/A' # Initialize for logging
        original_dst_ip = 'N/A'
        # These track the *final* IPs assigned to the packet layers for logging
        anon_src_ip_final = 'N/A (Not Processed)'
        anon_dst_ip_final = 'N/A (Not Processed)'

        try:
            if Ether in pkt and IP in pkt:
                # 1. Copy the ENTIRE packet first
                processed_packet = pkt.copy() # Work on the copy

                # Store original IPs from the copy BEFORE modification
                original_src_ip = processed_packet[IP].src if hasattr(processed_packet[IP], 'src') else 'N/A'
                original_dst_ip = processed_packet[IP].dst if hasattr(processed_packet[IP], 'dst') else 'N/A'

                # 2. Modify MACs directly in the copy
                if hasattr(processed_packet[Ether], 'src'):
                    processed_packet[Ether].src = mac_map.setdefault(processed_packet[Ether].src, anon_mac(processed_packet[Ether].src))
                if hasattr(processed_packet[Ether], 'dst'):
                    processed_packet[Ether].dst = mac_map.setdefault(processed_packet[Ether].dst, anon_mac(processed_packet[Ether].dst))

                # 3. Modify IPs directly in the copy
                resolved_src_ip = 'N/A' # Track resolved IP
                resolved_dst_ip = 'N/A'

                if hasattr(processed_packet[IP], 'src'):
                    resolved_src_ip = ip_map.setdefault(original_src_ip, anon_ip(original_src_ip, rules_models))
                    processed_packet[IP].src = resolved_src_ip # Modify IP layer IN THE COPIED PACKET

                if hasattr(processed_packet[IP], 'dst'):
                    resolved_dst_ip = ip_map.setdefault(original_dst_ip, anon_ip(original_dst_ip, rules_models))
                    processed_packet[IP].dst = resolved_dst_ip # Modify IP layer IN THE COPIED PACKET


                # Store final IPs for logging
                anon_src_ip_final = processed_packet[IP].src
                anon_dst_ip_final = processed_packet[IP].dst

                # 4. Delete checksums in the modified copy
                del processed_packet[IP].chksum
                if TCP in processed_packet: del processed_packet[TCP].chksum
                if UDP in processed_packet: del processed_packet[UDP].chksum
                if ICMP in processed_packet: del processed_packet[ICMP].chksum

                # 5. NO reassembly needed, NO rebuild from bytes needed
                # processed_packet = new_ether / new_ip / new_ip.payload  <- REMOVED
                # processed_packet = processed_packet.__class__(bytes(processed_packet)) <- REMAINS COMMENTED

            # If original packet didn't have Ether/IP, processed_packet remains the original pkt copy
            # Update final IPs for logging in this case too
            else:
                 if IP in processed_packet:
                      anon_src_ip_final = processed_packet[IP].src
                      anon_dst_ip_final = processed_packet[IP].dst
                 else:
                      anon_src_ip_final = 'N/A (No IP)'
                      anon_dst_ip_final = 'N/A (No IP)'

            # Append the processed packet (which is the modified copy or original if no Ether/IP)
            new_packets.append(processed_packet)

        except Exception as packet_err:
             # Keep this warning print
             print(f"Warning: Error processing packet {i+1}/{total_packets} in session {session_id}: {packet_err}. Appending original.")
             # Append the ORIGINAL packet if an error occurred during processing
             new_packets.append(pkt) # Use pkt (original) not processed_packet here

        # --- Progress Reporting Logic ---
        if progress_callback and total_packets > 0:
            current_progress = int(((i + 1) / total_packets) * 100)
            # Report only on change or every few percent to avoid spamming logs/callbacks
            if current_progress > last_reported_progress and (current_progress % 5 == 0 or current_progress == 100):
                try:
                    progress_callback(current_progress)
                    last_reported_progress = current_progress
                except Exception as cb_err:
                    print(f"Warning: Progress callback failed during anonymization: {cb_err}")

    try:
        print(f"Writing {len(new_packets)} processed packets to {output_path}...")
        wrpcap(output_path, new_packets)
        print(f"Successfully wrote anonymized file: {output_path}")
    except Exception as e:
        print(f"Error writing anonymized pcap file {output_path}: {e}")
        raise

    return output_path


# --- Backward Compatibility / Download Helper ---
def apply_anonymization_response(session_id: str):
    """
    Generates the anonymized PCAP and returns a FastAPI FileResponse.
    (Assumes this is called by a route that does not need progress)
    """
    try:
        # Call apply_anonymization without a progress callback
        output_path = apply_anonymization(session_id, progress_callback=None)
        print(f"Anonymization complete for response: {output_path}")
        # Serve the generated file
        return FileResponse(
             output_path,
             media_type='application/vnd.tcpdump.pcap',
             filename=os.path.basename(output_path) # Suggest a filename for download
         )
    except FileNotFoundError:
        # If the session or original pcap was missing
        raise HTTPException(status_code=404, detail="Session data or original PCAP file not found.")
    except Exception as e:
        # Catch other errors during anonymization or file serving
        print(f"Error during final anonymization for download ({session_id}): {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate or serve anonymized file: {e}")


def get_subnets(session_id: str):
    """Identifies /24 subnets present in the original PCAP file."""
    path = get_capture_path(session_id)
    try:
        packets = rdpcap(path)
    except FileNotFoundError:
        print(f"Error in get_subnets: PCAP file not found for {session_id} at {path}")
        raise HTTPException(status_code=404, detail="Original PCAP file not found for this session.")
    except Exception as e:
        print(f"Error reading PCAP for get_subnets ({session_id}): {e}")
        raise HTTPException(status_code=500, detail=f"Error reading PCAP file: {e}")

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
            # Keep this warning print
            print(f"Warning: Invalid IP format encountered in get_subnets: {ip_str}")

    if invalid_ips_count > 0:
        # Keep this warning print
        print(f"Warning: Skipped {invalid_ips_count} invalid IP addresses in get_subnets for session {session_id}.")

    # Sort subnets by CIDR string for consistent output
    sorted_subnets = sorted(subnets.items())
    return [{"cidr": cidr, "ip_count": count} for cidr, count in sorted_subnets]


# --- Example Usage (if run directly, requires dummy data/setup) ---
if __name__ == '__main__':
    # This block is for basic testing if the script is run directly.
    # It won't work without setting up dummy files and models/storage.
    print("Running anonymizer.py directly (requires dummy setup)")

    # Example: Create dummy files and data for testing (replace with actual setup)
    DUMMY_SESSION = 'test-session-main'
    # Ensure storage module works or mock it
    if 'SESSION_DIR' not in locals(): SESSION_DIR = './sessions_main_test'
    os.makedirs(SESSION_DIR, exist_ok=True)

    # Mock storage if not available
    if 'store' not in locals():
        _storage = {}
        def store(sid, key, value): _storage[f"{sid}_{key}"] = value
        def get_rules(sid): return _storage.get(f"{sid}_rules", [])
        def get_capture_path(sid): return os.path.join(SESSION_DIR, f"{sid}_original.pcap")
        print("INFO: Using mocked storage functions.")

    # Mock models if not available
    if 'Rule' not in locals():
        from pydantic import BaseModel # Assuming Pydantic is installed
        class Rule(BaseModel):
             source: str
             target: str
        print("INFO: Using mocked Rule model.")

    DUMMY_PCAP_ORIGINAL = get_capture_path(DUMMY_SESSION)

    # Create a dummy pcap if it doesn't exist (requires scapy)
    if not os.path.exists(DUMMY_PCAP_ORIGINAL):
        print(f"Creating dummy pcap: {DUMMY_PCAP_ORIGINAL}")
        try:
            from scapy.all import Ether, IP, TCP, wrpcap
            # Include IPs from the problematic subnets for testing
            dummy_pkts = [
                Ether(src='00:01:02:03:04:05', dst='AA:BB:CC:DD:EE:FF') / IP(src='192.168.1.1', dst='172.18.121.5') / TCP(),
                Ether(src='00:01:02:03:04:06', dst='AA:BB:CC:DD:EE:FE') / IP(src='10.193.145.10', dst='8.8.8.8') / TCP(),
                Ether(src='AA:BB:CC:DD:EE:FF', dst='00:01:02:03:04:05') / IP(src='172.18.121.5', dst='192.168.1.1') / TCP(),
            ]
            wrpcap(DUMMY_PCAP_ORIGINAL, dummy_pkts)
            print("Dummy pcap created.")
        except Exception as e:
            print(f"ERROR: Failed to create dummy pcap: {e}. Install scapy[complete]?")


    # Setup dummy rules
    dummy_rules_list = [
        {'source': '172.18.121.0/24', 'target': '10.3.0.0/24'},
        {'source': '10.193.145.0/24', 'target': '10.4.0.0/24'},
        {'source': '192.168.1.0/24', 'target': '10.99.1.0/24'},
    ]
    store(DUMMY_SESSION, 'rules', dummy_rules_list)
    print(f"Stored dummy rules for session {DUMMY_SESSION}: {dummy_rules_list}")

    print(f"\nAttempting to anonymize dummy file for session {DUMMY_SESSION}...")
    try:
        # Define a simple progress callback for testing
        def test_progress(p):
            print(f"Progress: {p}%")
        # Call anonymization with the test callback
        output_file = apply_anonymization(DUMMY_SESSION, progress_callback=test_progress)
        print(f"Dummy anonymization finished. Output: {output_file}")
        # Add code here to read DUMMY_PCAP_ANON and verify results if needed
        if os.path.exists(output_file):
            print("\nVerifying output PCAP...")
            try:
                anon_packets = rdpcap(output_file)
                for i, pkt in enumerate(anon_packets):
                    if IP in pkt:
                        print(f"  Packet {i+1}: {pkt[IP].src} -> {pkt[IP].dst}")
                print("Verification complete.")
            except Exception as read_err:
                print(f"Error reading anonymized output file: {read_err}")

    except Exception as e:
         print(f"Error during dummy anonymization test: {e}")
