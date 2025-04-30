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
from storage import store, get_rules, get_capture_path, SESSION_DIR # Ensure SESSION_DIR is defined/imported
from models import RuleInput, Rule # Assuming Rule is needed if RuleInput is

# --- Constants and Setup ---
# SESSION_DIR should be defined, either here or imported from storage
# SESSION_DIR = './sessions' # Example if not imported
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
        # Check against user rules first
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
                             return str(ipaddress.ip_address(new_ip_int))
                    # If offset doesn't fit or rule is otherwise unusable, continue to next rule
                    # or eventually fall back to random IP
            except ValueError as e:
                print(f"Warning: Skipping invalid CIDR rule ({src_key} -> {tgt_key}): {e}")
                continue # Skip rule if CIDRs are invalid

        # Fallback: random 10.x.x.x unique across the current ip_map values
        # Be careful with potential infinite loops if 10/8 is exhausted, though unlikely
        attempts = 0
        while attempts < 1000: # Limit attempts to prevent hangs
            rand_ip = f"10.{randint(0, 255)}.{randint(0, 255)}.{randint(1, 254)}"
            if rand_ip not in ip_map.values():
                return rand_ip
            attempts += 1
        # If we can't find a unique random IP after many attempts
        print(f"Warning: Could not generate unique random IP for {ip} after {attempts} attempts.")
        return f"10.255.255.{randint(1,254)}" # Last resort fallback

    except ValueError:
        print(f"Warning: Invalid original IP address format '{ip}'. Returning as is.")
        return ip # Return original if it's not a valid IP


# --- Core API Logic Functions ---

async def process_upload(file: UploadFile):
    """
    Handles uploaded PCAP file: saves it, extracts initial IP/MAC pairs,
    and initializes session data.
    """
    session_id = str(uuid.uuid4())
    path = get_capture_path(session_id) # Use storage function to get path

    # --- Debug prints removed, added robust error handling ---
    print(f"Processing upload for new session: {session_id}")
    print(f"Attempting to save uploaded file to: {os.path.abspath(path)}")

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
                # Ensure keys exist before accessing
                src_ip = pkt[IP].src if hasattr(pkt[IP], 'src') else None
                dst_ip = pkt[IP].dst if hasattr(pkt[IP], 'dst') else None
                src_mac = pkt[Ether].src if hasattr(pkt[Ether], 'src') else None
                dst_mac = pkt[Ether].dst if hasattr(pkt[Ether], 'dst') else None

                if all([src_ip, dst_ip, src_mac, dst_mac]): # Proceed only if all parts are valid
                    key = (src_ip, dst_ip, src_mac, dst_mac)
                    if key not in seen:
                        results.append({
                            'src_ip': src_ip,
                            'dst_ip': dst_ip,
                            'src_mac': src_mac,
                            'dst_mac': dst_mac,
                        })
                        seen.add(key)

        # Initialize empty rules for this session
        store(session_id, 'rules', [])
        print(f"Session {session_id} initialized successfully.")
        return {"session_id": session_id, "mappings": results}

    except FileNotFoundError:
        # This shouldn't happen if the save above succeeded, but handle defensively
        print(f"ERROR: PCAP file {path} not found after saving!")
        raise HTTPException(status_code=500, detail="Failed to process upload: File disappeared after save.")
    except Exception as e_read:
        # Handle potential errors during rdpcap or packet processing
        print(f"ERROR: Failed to read/process PCAP file {path} after saving. Error: {e_read}")
        # Clean up the potentially corrupted saved file
        try:
            os.remove(path)
            print(f"Cleaned up potentially corrupted file: {path}")
        except OSError:
            pass # Ignore error during cleanup
        raise HTTPException(status_code=400, detail=f"Failed to process uploaded PCAP file: {e_read}. Is it a valid PCAP?")


def save_rules(input: RuleInput):
    """Saves user-defined transformation rules."""
    try:
        # Store rules using canonical field names (source/target)
        # Ensure input.rules is a list of Pydantic Rule models
        if not isinstance(input.rules, list):
             raise ValueError("Invalid format for rules.")
        # Convert Pydantic models to dicts for JSON storage
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
    ip_map.clear()  # Clear global maps for a fresh preview
    mac_map.clear()

    try:
        rules_data = get_rules(session_id) # Load rules as dicts
        # Convert dicts back to Pydantic models for anon_ip consistency
        rules_models = [Rule(**rule_data) for rule_data in rules_data]
        path = get_capture_path(session_id)
        packets = rdpcap(path)
    except FileNotFoundError:
         raise HTTPException(status_code=404, detail="Session data or PCAP file not found.")
    except Exception as e:
         raise HTTPException(status_code=500, detail=f"Error loading data for preview: {e}")

    seen = set()
    preview = []
    for pkt in packets:
        if Ether in pkt and IP in pkt:
            # Extract fields safely
            src_ip = pkt[IP].src if hasattr(pkt[IP], 'src') else None
            dst_ip = pkt[IP].dst if hasattr(pkt[IP], 'dst') else None
            src_mac = pkt[Ether].src if hasattr(pkt[Ether], 'src') else None
            dst_mac = pkt[Ether].dst if hasattr(pkt[Ether], 'dst') else None

            if not all([src_ip, dst_ip, src_mac, dst_mac]):
                continue # Skip packets with missing fields

            key = (src_ip, dst_ip, src_mac, dst_mac)
            if key in seen:
                continue
            seen.add(key)

            original = {
                'src_ip': src_ip, 'dst_ip': dst_ip,
                'src_mac': src_mac, 'dst_mac': dst_mac,
            }
            anonymized = {
                'src_ip': ip_map.setdefault(src_ip, anon_ip(src_ip, rules_models)),
                'dst_ip': ip_map.setdefault(dst_ip, anon_ip(dst_ip, rules_models)),
                'src_mac': mac_map.setdefault(src_mac, anon_mac(src_mac)),
                'dst_mac': mac_map.setdefault(dst_mac, anon_mac(dst_mac)),
            }
            preview.append({'original': original, 'anonymized': anonymized})
    print(f"Preview generated for session {session_id}")
    return preview


# --- MODIFIED apply_anonymization with progress callback ---
def apply_anonymization(session_id: str, progress_callback: Optional[Callable[[int], None]] = None):
    """
    Applies anonymization rules to the PCAP file for the session.

    Args:
        session_id: The ID of the session.
        progress_callback: An optional function to call with progress percentage (0-100).
    """
    global ip_map, mac_map
    ip_map.clear()  # Clear global maps for a fresh anonymization run
    mac_map.clear()
    print(f"Starting anonymization for session {session_id}")

    try:
        rules_data = get_rules(session_id) # Load rules as dicts
        rules_models = [Rule(**rule_data) for rule_data in rules_data] # Convert to models
        path = get_capture_path(session_id)
        # Read packets - this can consume significant memory for large files
        print(f"Reading packets from {path}...")
        packets: PacketList = rdpcap(path)
        print(f"Read {len(packets)} packets.")
    except FileNotFoundError:
        print(f"Error in apply_anonymization: Session data or PCAP file not found for {session_id}")
        raise # Re-raise for run_apply to catch
    except Exception as e:
        print(f"Error loading data for anonymization ({session_id}): {e}")
        raise # Re-raise

    output_path = os.path.join(SESSION_DIR, f"{session_id}_anon.pcap")
    new_packets = []
    total_packets = len(packets)
    last_reported_progress = -1 # Track last reported percentage

    print(f"Processing {total_packets} packets for anonymization...")
    # Iterate through packets and apply anonymization
    for i, pkt in enumerate(packets):
        processed_packet = pkt # Start with original
        try:
            if Ether in pkt and IP in pkt:
                new_ether = pkt[Ether].copy() # Work on copies
                new_ip = pkt[IP].copy()

                # Anonymize MACs
                if hasattr(new_ether, 'src'):
                    new_ether.src = mac_map.setdefault(new_ether.src, anon_mac(new_ether.src))
                if hasattr(new_ether, 'dst'):
                    new_ether.dst = mac_map.setdefault(new_ether.dst, anon_mac(new_ether.dst))

                # Anonymize IPs
                if hasattr(new_ip, 'src'):
                    new_ip.src = ip_map.setdefault(new_ip.src, anon_ip(new_ip.src, rules_models))
                if hasattr(new_ip, 'dst'):
                    new_ip.dst = ip_map.setdefault(new_ip.dst, anon_ip(new_ip.dst, rules_models))

                # Reassemble the packet layers
                processed_packet = new_ether / new_ip / new_ip.payload # Rebuild packet

                # Reset checksums so Scapy recalculates them after serialization
                # Do this on the new 'processed_packet' object
                if IP in processed_packet:
                    processed_packet[IP].chksum = None # IPv4 header checksum
                if TCP in processed_packet:
                    processed_packet[TCP].chksum = None # TCP checksum
                if UDP in processed_packet:
                    processed_packet[UDP].chksum = None # UDP checksum
                if ICMP in processed_packet:
                    processed_packet[ICMP].chksum = None # ICMP checksum

                # Re-create packet from bytes to finalize changes and checksums
                processed_packet = processed_packet.__class__(bytes(processed_packet))

        except Exception as packet_err:
            # Log error for specific packet but continue processing others
             print(f"Warning: Error processing packet {i+1}/{total_packets} in session {session_id}: {packet_err}. Appending original.")
             processed_packet = pkt # Append original if processing failed


        new_packets.append(processed_packet)

        # --- Progress Reporting Logic ---
        if progress_callback and total_packets > 0:
            # Calculate progress (0-100)
            current_progress = int(((i + 1) / total_packets) * 100)
            # Call callback only if the integer percentage has changed
            if current_progress > last_reported_progress:
                try:
                    progress_callback(current_progress)
                    last_reported_progress = current_progress
                except Exception as cb_err:
                    # Log if the callback itself fails, but don't stop anonymization
                    print(f"Warning: Progress callback failed during anonymization: {cb_err}")

    # Write the anonymized packets to the output file
    try:
        print(f"Writing {len(new_packets)} processed packets to {output_path}...")
        wrpcap(output_path, new_packets)
        print(f"Successfully wrote anonymized file: {output_path}")
    except Exception as e:
        print(f"Error writing anonymized pcap file {output_path}: {e}")
        raise # Re-raise for run_apply to catch

    return output_path # Return the path to the anonymized file


# --- Backward Compatibility / Download Helper ---
# This function calls the modified apply_anonymization.
# If called directly (e.g., by /download endpoint), progress is not reported.
def apply_anonymization_response(session_id: str):
    """
    Generates the anonymized PCAP and returns a FastAPI FileResponse.
    If the anonymized file already exists, it serves it directly.
    If not, it calls apply_anonymization (without progress reporting) to create it.
    """
    output_path = os.path.join(SESSION_DIR, f"{session_id}_anon.pcap")

    # Check if file already exists (e.g., created by background task)
    if not os.path.exists(output_path):
        print(f"Anonymized file {output_path} not found. Generating on demand...")
        try:
            # Call apply_anonymization without a callback to generate it
            # This might take time and won't report progress to *this* caller.
            apply_anonymization(session_id, progress_callback=None)
            print(f"On-demand generation complete for {output_path}")
        except Exception as e:
            # Catch errors during on-demand generation
            print(f"Error during on-demand generation for {session_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to generate anonymized file: {e}")

    # Serve the (now existing) file
    if os.path.exists(output_path):
         return FileResponse(
             output_path,
             media_type='application/vnd.tcpdump.pcap',
             filename=os.path.basename(output_path) # Suggest filename to browser
         )
    else:
         # Should not happen if generation succeeded, but handle defensively
         print(f"ERROR: File {output_path} still not found after generation attempt.")
         raise HTTPException(status_code=500, detail="Failed to serve anonymized file after generation.")


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
            print(f"Warning: Invalid IP format encountered in get_subnets: {ip_str}")

    if invalid_ips_count > 0:
        print(f"Warning: Skipped {invalid_ips_count} invalid IP addresses in get_subnets for session {session_id}.")

    # Format results for the frontend
    return [{"cidr": cidr, "ip_count": count} for cidr, count in subnets.items()]