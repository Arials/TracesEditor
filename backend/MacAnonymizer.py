# backend/MacAnonymizer.py
import os
import csv
import json # Added for loading rules
import random # Added for generating random MAC parts
import requests
import logging
logging.basicConfig(level=logging.DEBUG)
from typing import Dict, List, Optional, Set, Tuple, Callable, Union # Added Callable, Union
from datetime import datetime

# Scapy imports (ensure scapy[complete] is installed)
logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
try:
    # Added more specific Scapy types needed for transformation
    from scapy.all import rdpcap, wrpcap, Ether, IP, TCP, UDP, ICMP, Packet, PacketList
except ImportError:
    logging.warning("Scapy is not installed or could not be imported. MAC/IP/Packet processing will fail.")
    # Define dummy classes/functions if needed to prevent import errors elsewhere
    # Ensure PacketList is defined if Scapy fails
    class PacketList(list): pass
    class Packet: pass
    class Ether: pass
    class IP: pass
    def rdpcap(filename: str): raise ImportError("Scapy not available")

# Local imports
from pathlib import Path
import uuid

# Use absolute imports assuming 'backend' is in sys.path
try:
    from . import storage
    from . import models # Import the models module
    
    # Access specific models via the module
    IpMacPair = models.IpMacPair # Correctly assign IpMacPair
    MacSettings = models.MacSettings
    MacRule = models.MacRule # <--- FIX: Correctly assign MacRule from models module
    
    logging.info("Successfully imported backend.storage and backend.models in MacAnonymizer.py")

    # Import JobCancelledException from the central exceptions module
    try:
        from backend.exceptions import (
            JobCancelledException,
            OuiCsvValidationError,
            OuiCsvParseError
        )
        # Alias for use within this module if needed, or just use JobCancelledException directly
        MacJobCancelledException = JobCancelledException
        logging.info("Successfully imported JobCancelledException and OUI CSV exceptions from backend.exceptions in MacAnonymizer.py")
    except ImportError:
        logging.error("CRITICAL ERROR: Could not import exceptions from backend.exceptions in MacAnonymizer.py.")
        # Define dummy exceptions if import fails
        MacJobCancelledException = type('MacJobCancelledException', (Exception,), {})
        OuiCsvValidationError = type('OuiCsvValidationError', (Exception,), {})
        OuiCsvParseError = type('OuiCsvParseError', (Exception,), {})
        logging.info("Defined dummy exceptions in MacAnonymizer.py fallback.")

except ImportError as e:
    # This outer except block catches failures for storage or models import
    logging.error(f"CRITICAL ERROR: Failed to import backend.storage or backend.models in MacAnonymizer.py: {e}")
    logging.warning("Ensure the project structure allows 'from backend import ...' and models.py exists.")
    # Define dummy models and storage placeholder if primary import fails
    class IpMacPair: pass
    class MacSettings: pass
    class MacRule: pass
    # Define dummy storage placeholder
    class DummyStoragePlaceholder:
         def get_capture_path(session_id): return Path(f"./MAC_ANONYMIZER_FALLBACK_PATH/{session_id}/capture.pcap")
         def get_session_filepath(session_id, filename): return Path(f"./MAC_ANONYMIZER_FALLBACK_PATH/{session_id}/{filename}")
         def load_json(session_id, filename): logging.info("DUMMY_STORAGE_PLACEHOLDER (MacAnonymizer): load_json called - returning None"); return None
    storage = DummyStoragePlaceholder()
    logging.warning("CRITICAL WARNING: MacAnonymizer.py using DUMMY storage/models due to import failure.")
    # Define dummy exceptions if not already defined
    if 'MacJobCancelledException' not in locals(): # Should be caught by inner try-except
        MacJobCancelledException = type('MacJobCancelledException', (Exception,), {})
        logging.info("Defined dummy MacJobCancelledException in outer fallback.")
    if 'OuiCsvValidationError' not in locals():
        OuiCsvValidationError = type('OuiCsvValidationError', (Exception,), {})
        logging.info("Defined dummy OuiCsvValidationError in outer fallback.")
    if 'OuiCsvParseError' not in locals():
        OuiCsvParseError = type('OuiCsvParseError', (Exception,), {})
        logging.info("Defined dummy OuiCsvParseError in outer fallback.")


# Constants
# SCRIPT_DIR and related paths are no longer needed here as storage.py handles session paths
# and global resource paths can be defined directly or relative to a known project structure.

# Define RESOURCES_DIR relative to the script's directory (backend/resources)
# This assumes MacAnonymizer.py is in backend/
# If resources are truly global, their paths might be better configured or passed.
# For now, let's keep them relative to this script's parent's 'resources' subdir.
_BACKEND_DIR = Path(__file__).parent.resolve()
RESOURCES_DIR = _BACKEND_DIR / 'resources'
RESOURCES_DIR.mkdir(parents=True, exist_ok=True) # Ensure it exists

OUI_CSV_PATH = str(RESOURCES_DIR / 'oui.csv')
MAC_SETTINGS_PATH = str(RESOURCES_DIR / 'mac_settings.json')

# SESSION_DIR is now managed by storage.py


# --- OUI CSV Handling ---

def download_oui_csv(url: str, output_path: str):
    """Downloads the OUI CSV file from the specified URL."""
    logging.info(f"Attempting to download OUI CSV from: {url}")
    try:
        response = requests.get(url, stream=True, timeout=60) # Add timeout
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        # Ensure the directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logging.info(f"Successfully downloaded OUI CSV to: {output_path}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Error downloading OUI CSV from {url}: {e}")
        raise # Re-raise the exception to be handled by the caller (e.g., background task)
    except Exception as e:
        logging.error(f"An unexpected error occurred during OUI CSV download: {e}")
        raise

def validate_oui_csv(csv_path: str) -> bool:
    """
    Validates the structure of the downloaded OUI CSV file.
    Checks for the expected header columns.
    """
    logging.info(f"Validating OUI CSV file: {csv_path}")
    # Expected columns based on common OUI CSV formats (e.g., Wireshark's manuf)
    # Adjust these based on the actual format of the CSV from the chosen URL
    EXPECTED_COLUMNS = ["Registry", "Assignment", "Organization Name", "Organization Address"]
    # Alternative common header: "MA-L", "Organization", "Address"

    try:
        with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
            # Skip potential comment lines at the beginning
            line = f.readline()
            while line.startswith('#') or not line.strip():
                line = f.readline()
                if not line: # Reached end of file without finding header
                    msg = "Validation Error: OUI CSV file seems empty or contains only comments."
                    logging.warning(msg)
                    raise OuiCsvValidationError(msg)

            # Use the first non-comment line as the header
            # Reset file pointer and read header using csv.reader
            f.seek(0)
            reader = csv.reader(f)
            # Skip comments again for the reader
            header = next(reader)
            while header and (not header[0].strip() or header[0].strip().startswith('#')):
                 header = next(reader)

            if not header:
                 msg = "Validation Error: Could not read header row from OUI CSV."
                 logging.warning(msg)
                 raise OuiCsvValidationError(msg)

            logging.debug(f"Detected Header: {header}")

            # Simple validation: Check if the first few expected columns are present
            # This is flexible if the exact number/order varies slightly
            if len(header) >= 3 and header[0].strip() == EXPECTED_COLUMNS[0] and header[2].strip() == EXPECTED_COLUMNS[2]:
                 logging.info("CSV header validation successful (Standard Format).")
                 return True
            elif len(header) >= 2 and header[0].strip() == "MA-L" and header[1].strip() == "Organization":
                 logging.info("CSV header validation successful (MA-L Format).")
                 return True
            else:
                 msg = f"Validation Error: OUI CSV header does not match expected formats. Expected like: {EXPECTED_COLUMNS} or ['MA-L', 'Organization', ...]"
                 logging.warning(msg)
                 raise OuiCsvValidationError(msg)

    except FileNotFoundError as e:
        msg = f"Validation Error: OUI CSV file not found at {csv_path}"
        logging.error(msg)
        raise OuiCsvValidationError(msg) from e
    except StopIteration as e: # Handles empty file after comments
        msg = "Validation Error: OUI CSV file is empty or contains no data rows after comments."
        logging.warning(msg)
        raise OuiCsvValidationError(msg) from e
    except OuiCsvValidationError: # Re-raise if already this type
        raise
    except Exception as e:
        msg = f"Validation Error: An unexpected error occurred during OUI CSV validation: {e}"
        logging.error(msg)
        raise OuiCsvValidationError(msg) from e


def parse_oui_csv(csv_path: str) -> Dict[str, str]:
    """
    Parses the OUI CSV file into a dictionary mapping OUI prefixes to vendor names.
    Assumes validation has already passed. Handles different common formats.
    """
    oui_map: Dict[str, str] = {}
    logging.info(f"Parsing OUI CSV: {csv_path}")
    try:
        with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f)
            try:
                header = next(reader) # Read header row
                logging.debug(f"OUI_CSV Raw Header Read: {header}")
                # Skip potential comment lines after header or blank lines
                while header and (not header[0].strip() or header[0].strip().startswith('#')):
                    header = next(reader)
                    logging.debug(f"OUI_CSV Header Read (after skipping comments): {header}")
            except StopIteration:
                msg = "Parsing Error: OUI CSV file is empty or contains no header row after comments."
                logging.warning(msg)
                raise OuiCsvParseError(msg)


            if not header: # Should be caught by StopIteration if file ends before valid header
                 msg = "Parsing Error: No valid header found in OUI CSV (header is empty list)."
                 logging.warning(msg)
                 raise OuiCsvParseError(msg)

            # Determine format based on header
            is_standard_format = len(header) >= 3 and header[0].strip() == "Registry" and header[2].strip() == "Organization Name"
            is_mal_format = len(header) >= 2 and header[0].strip() == "MA-L" and header[1].strip() == "Organization"
            logging.debug(f"OUI_CSV Format Check: is_standard_format={is_standard_format}, is_mal_format={is_mal_format}. Actual Header: {header}")

            assignment_col = -1
            org_name_col = -1

            if is_standard_format:
                assignment_col = 1 # "Assignment" column (contains OUI)
                org_name_col = 2   # "Organization Name" column
                logging.debug("Parsing OUI_CSV using Standard Format (Registry, Assignment, Org Name, ...)")
            elif is_mal_format:
                assignment_col = 0 # "MA-L" column (contains OUI)
                org_name_col = 1   # "Organization" column
                logging.debug("Parsing OUI_CSV using MA-L Format (MA-L, Organization, ...)")
            else:
                msg = f"Parsing Error: Unrecognized OUI CSV header format. Header found: {header}" # Log the header found
                logging.error(msg)
                raise OuiCsvParseError(msg)

            parsed_count = 0
            skipped_count = 0
            for row_idx, row in enumerate(reader): # Added row_idx for logging
                # Skip blank rows or comment rows
                if not row or not row[0].strip() or row[0].strip().startswith('#'):
                    logging.debug(f"OUI_CSV Skipping row {row_idx + 1} (comment/blank): {row}")
                    skipped_count += 1
                    continue

                if len(row) > max(assignment_col, org_name_col):
                    oui_assignment = row[assignment_col].strip()
                    vendor_name = row[org_name_col].strip()

                    # OUI assignment is usually hex, e.g., "001A2B" or "00-1A-2B"
                    # Normalize to "00:1A:2B" format for lookup
                    oui_prefix = oui_assignment.replace('-', '').replace(':', '')
                    if len(oui_prefix) == 6: # Expecting 6 hex digits for OUI
                        normalized_oui = f"{oui_prefix[0:2]}:{oui_prefix[2:4]}:{oui_prefix[4:6]}".upper()
                        oui_map[normalized_oui] = vendor_name
                        parsed_count += 1
                    else:
                        logging.warning(f"OUI_CSV Skipping row {row_idx + 1} due to unexpected OUI assignment format ('{oui_assignment}', normalized to '{oui_prefix}'). Row: {row}")
                        skipped_count += 1
                else:
                    logging.warning(f"OUI_CSV Skipping malformed row {row_idx + 1} (not enough columns: {len(row)}, expected > {max(assignment_col, org_name_col)}). Row: {row}")
                    skipped_count += 1

        logging.info(f"Successfully parsed {parsed_count} OUI entries. Skipped {skipped_count} rows from {csv_path}.")
        return oui_map

    except FileNotFoundError as e: # This should ideally be caught before calling parse_oui_csv
        msg = f"Parsing Error: OUI CSV file not found at {csv_path} (this check should be before parse_oui_csv is called)."
        logging.error(msg)
        raise OuiCsvParseError(msg) from e
    except StopIteration as e:
        msg = "Parsing Error: OUI CSV file is empty or contains no data rows."
        logging.warning(msg)
        raise OuiCsvParseError(msg) from e
    except OuiCsvParseError: # Re-raise if already this type
        raise
    except Exception as e:
        msg = f"Parsing Error: An unexpected error occurred during OUI CSV parsing: {e}"
        logging.error(msg)
        raise OuiCsvParseError(msg) from e


# --- IP-MAC Extraction ---

def extract_ip_mac_pairs(session_id: str, input_pcap_filename: str, oui_map: Dict[str, str]) -> List[models.IpMacPair]: # Use models.IpMacPair directly
    """
    Extracts unique IP-MAC pairs from a PCAP file for a given session using storage module
    and identifies vendors using the OUI map.
    """
    logging.info(f"Extracting IP-MAC pairs for session: {session_id}, file: {input_pcap_filename}")
    pairs: Dict[Tuple[str, str], Optional[str]] = {} # Use dict to ensure uniqueness: (ip, mac) -> vendor
    processed_packets = 0
    extracted_pairs_count = 0

    try:
        # Read packets using storage helper
        packets = storage.read_pcap_from_session(session_id, filename=input_pcap_filename)
        total_packets = len(packets)
        logging.info(f"Read {total_packets} packets from '{input_pcap_filename}' using storage.read_pcap_from_session.")

        for pkt in packets:
            processed_packets += 1
            if Ether in pkt and IP in pkt:
                src_ip = pkt[IP].src
                dst_ip = pkt[IP].dst
                src_mac = pkt[Ether].src
                dst_mac = pkt[Ether].dst

                # Process source pair
                if (src_ip, src_mac) not in pairs:
                    oui_prefix = ':'.join(src_mac.upper().split(':')[:3])
                    vendor = oui_map.get(oui_prefix)
                    pairs[(src_ip, src_mac)] = vendor
                    extracted_pairs_count += 1

                # Process destination pair
                if (dst_ip, dst_mac) not in pairs:
                    oui_prefix = ':'.join(dst_mac.upper().split(':')[:3])
                    vendor = oui_map.get(oui_prefix)
                    pairs[(dst_ip, dst_mac)] = vendor
                    extracted_pairs_count += 1

        logging.info(f"Finished processing {processed_packets} packets.")
        logging.info(f"Extracted {len(pairs)} unique IP-MAC pairs.")

        # Convert the dictionary to a list of IpMacPair objects
        result_list = [
            models.IpMacPair(ip_address=ip, mac_address=mac, vendor=vendor) # Use models.IpMacPair directly
            for (ip, mac), vendor in pairs.items()
        ]
        return result_list

    except FileNotFoundError: # Can be raised by storage.read_pcap_from_session
        logging.error(f"Extraction Error: PCAP file '{input_pcap_filename}' not found for session {session_id}")
        return [] # Return empty list if file not found
    except ImportError:
         logging.error("Extraction Error: Scapy is not available.")
         return []
    except Exception as e:
        logging.error(f"Extraction Error: An unexpected error occurred during IP-MAC extraction: {e}")
        # Consider logging the traceback here
        return [] # Return empty list on other errors

# --- Settings Handling (Example - adjust as needed) ---

def load_mac_settings() -> Optional[MacSettings]:
    """Loads MAC settings from the JSON file."""
    if not os.path.exists(MAC_SETTINGS_PATH):
        logging.warning(f"MAC settings file not found: {MAC_SETTINGS_PATH}")
        return None
    try:
        with open(MAC_SETTINGS_PATH, 'r') as f:
            data = json.load(f)
            return MacSettings(**data)
    except (json.JSONDecodeError, TypeError, FileNotFoundError) as e:
        logging.error(f"Error loading MAC settings from {MAC_SETTINGS_PATH}: {e}")
        return None

def save_mac_settings(settings: MacSettings):
    """Saves MAC settings to the JSON file."""
    try:
        os.makedirs(os.path.dirname(MAC_SETTINGS_PATH), exist_ok=True)
        with open(MAC_SETTINGS_PATH, 'w') as f:
            json.dump(settings.model_dump(mode='json'), f, indent=2) # Use model_dump for Pydantic v2
        logging.info(f"Successfully saved MAC settings to {MAC_SETTINGS_PATH}")
    except Exception as e:
        logging.error(f"Error saving MAC settings to {MAC_SETTINGS_PATH}: {e}")
        # Decide if this should raise an exception or just log


# --- MAC Transformation Logic ---

def generate_mac_with_new_oui(original_mac: str, target_oui: str) -> str:
    """
    Generates a new MAC address using the target OUI prefix and the device-specific
    part (last 3 octets) of the original MAC address.
    """
    if not isinstance(target_oui, str) or len(target_oui.split(':')) != 3:
        logging.warning(f"Warning: Invalid target OUI '{target_oui}'. Returning original MAC '{original_mac}'.")
        return original_mac # Or generate fully random as a fallback if preferred

    original_mac_parts = original_mac.split(':')
    if len(original_mac_parts) != 6:
        logging.warning(f"Warning: Invalid original MAC format '{original_mac}'. Generating MAC with random tail for OUI '{target_oui}'.")
        # Fallback to random tail if original MAC is malformed
        random_tail = ':'.join(f'{random.randint(0, 255):02X}' for _ in range(3))
        return f"{target_oui.upper()}:{random_tail}"

    # Preserve the last 3 octets (device-specific part) from the original MAC
    device_specific_part = ':'.join(original_mac_parts[3:])
    return f"{target_oui.upper()}:{device_specific_part}"


def apply_mac_transformation(
    input_trace_id: str,
    input_pcap_filename: str,
    new_output_trace_id: str,
    output_pcap_filename: str,
    progress_callback: Optional[Callable[[int], None]] = None,
    check_stop_requested: Optional[Callable[[], bool]] = None
) -> Dict[str, Union[Path, str]]:
    """
    Applies MAC transformation rules to the input PCAP file and saves the result to a new trace.
    Modifies MAC addresses based on rules, preserving target vendor OUI.

    Args:
        input_trace_id: The ID of the input trace.
        input_pcap_filename: The name of the PCAP file to process within the input trace.
        new_output_trace_id: The ID for the new output trace where the transformed PCAP will be saved.
        output_pcap_filename: The name for the transformed PCAP file in the new output trace.
        progress_callback: An optional function to call with progress percentage (0-100).
        check_stop_requested: An optional function to call to check if cancellation is requested.

    Returns:
        A dictionary containing information about the output.

    Raises:
        FileNotFoundError: If input PCAP or rules file is not found.
        JobCancelledException: If cancellation is requested during processing.
        Exception: For other processing errors (e.g., Scapy issues, file writing).
    """
    logging.info(f"Starting MAC transformation: Input Trace ID {input_trace_id}, Input File '{input_pcap_filename}' -> Output Trace ID {new_output_trace_id}, Output File '{output_pcap_filename}'")

    # 1. Define Paths using storage.py (Only needed for rules)
    rules_path_obj = storage.get_session_filepath(input_trace_id, "mac_rules.json") # Load rules from input trace
    rules_path = str(rules_path_obj) # Keep for loading rules JSON

    # 2. Load Data
    # Load PCAP using storage helper
    try:
        logging.info(f"Reading packets for input trace {input_trace_id}, file '{input_pcap_filename}' using storage module...")
        packets: PacketList = storage.read_pcap_from_session(input_trace_id, filename=input_pcap_filename)
        logging.info(f"Read {len(packets)} packets from '{input_pcap_filename}'.")
    except FileNotFoundError as e:
        logging.error(f"Error reading input PCAP for input trace {input_trace_id}: {e}")
        raise # Re-raise FileNotFoundError
    except Exception as e:
        logging.error(f"Error reading input PCAP for input trace {input_trace_id} using storage module: {e}")
        raise # Re-raise other read errors

    # Load MAC Rules
    rules: List[MacRule] = []
    logging.debug(f"[MacAnonymizer] Attempting to load rules using storage.load_json for input trace {input_trace_id}, file 'mac_rules.json'")
    rules_data = storage.load_json(input_trace_id, "mac_rules.json") # Load rules from input trace

    if rules_data is not None:
        if isinstance(rules_data, list):
            try:
                rules = [MacRule(**item) for item in rules_data] # Validate structure
                logging.info(f"Loaded {len(rules)} MAC rules from 'mac_rules.json' for input trace {input_trace_id}")
            except Exception as e: # Catch Pydantic validation errors etc.
                logging.warning(f"Error validating MAC rules from 'mac_rules.json' for input trace {input_trace_id}: {e}. Proceeding without rules.")
        else:
            logging.warning(f"Invalid format in MAC rules file 'mac_rules.json' for input trace {input_trace_id}. Expected a list. Proceeding without rules.")
    else:
        logging.warning(f"MAC rules file 'mac_rules.json' not found or failed to load for input trace {input_trace_id}. Proceeding without rules.")

    # Load OUI Map and build reverse lookup (Vendor Name -> OUI)
    oui_map: Dict[str, str] = {} # OUI_prefix -> Vendor Name
    vendor_to_oui_map = {} # Vendor Name (UPPERCASE) -> OUI_prefix
    if os.path.exists(OUI_CSV_PATH):
        try:
            oui_map = parse_oui_csv(OUI_CSV_PATH)
            if not oui_map:
                logging.warning(f"OUI map parsed from {OUI_CSV_PATH} is empty.")
            else:
                logging.info(f"Loaded {len(oui_map)} entries from OUI map.")
                # Pre-build the reverse map (Vendor -> OUI)
                # Handles potential duplicate vendor names by taking the first OUI encountered.
                for oui_prefix, vendor_name in oui_map.items():
                    normalized_vendor = vendor_name.strip().upper()
                    if normalized_vendor not in vendor_to_oui_map: # Keep first OUI for a vendor
                        vendor_to_oui_map[normalized_vendor] = oui_prefix
                logging.debug(f"Built reverse map for {len(vendor_to_oui_map)} unique vendor names to OUIs.")
                # Log a few examples from vendor_to_oui_map
                if vendor_to_oui_map:
                    logging.debug("vendor_to_oui_map (first 5 examples):")
                    count = 0
                    for vendor, oui in vendor_to_oui_map.items():
                        logging.debug(f"  '{vendor}': '{oui}'")
                        count += 1
                        if count >= 5:
                            break
        except Exception as e:
            logging.warning(f"Failed to load or parse OUI map {OUI_CSV_PATH}: {e}. Vendor lookup for rules will fail.")
    else:
        logging.warning(f"OUI CSV file not found at {OUI_CSV_PATH}. Vendor lookup for rules will fail.")

    # 3. Initialization and Pre-computation of MAC Transformation Map
    # This map will store: original_mac_from_rule (UPPERCASE) -> new_transformed_mac
    mac_to_new_mac_map = {}
    logging.debug("Pre-computing MAC transformation map based on rules...")
    if not rules:
        logging.debug("No MAC transformation rules provided.")
    # REMOVED: No longer need vendor_to_oui_map check here, as OUI comes from the rule itself.
    # elif not vendor_to_oui_map: # Check if OUI data is available for rule processing
    #     print("DEBUG: Warning: OUI data (vendor_to_oui_map) is not available. Cannot process MAC rules that require vendor to OUI lookup.")
    else:
        logging.debug(f"Processing {len(rules)} rules...")
        for idx, rule in enumerate(rules):
            # Log rule content, now including target_oui
            logging.debug(f"Rule {idx + 1}/{len(rules)}: Original MAC='{getattr(rule, 'original_mac', 'N/A')}', Target Vendor='{getattr(rule, 'target_vendor', 'N/A')}', Target OUI='{getattr(rule, 'target_oui', 'N/A')}'")
            try:
                # Check for required fields: original_mac and target_oui
                if not hasattr(rule, 'original_mac') or not hasattr(rule, 'target_oui'):
                    logging.warning(f"Skipping invalid rule object: {rule}. Missing 'original_mac' or 'target_oui'.")
                    continue

                original_mac_norm = rule.original_mac.strip().upper()
                target_oui_norm = rule.target_oui.strip().upper() # Normalize target OUI as well
                logging.debug(f"  Normalized Original MAC: '{original_mac_norm}', Normalized Target OUI: '{target_oui_norm}'")

                if not original_mac_norm:
                    logging.debug(f"  Warning: Skipping rule with empty original_mac: {rule}")
                    continue
                if not target_oui_norm: # Check if target_oui is present and not empty
                    logging.warning(f"  Skipping rule for MAC '{original_mac_norm}' due to missing or empty target_oui: {rule}")
                    continue

                # Directly use the target_oui from the rule
                # Basic validation of OUI format (3 hex pairs separated by colons)
                oui_parts = target_oui_norm.split(':')
                if len(oui_parts) == 3 and all(len(part) == 2 and all(c in '0123456789ABCDEF' for c in part) for part in oui_parts):
                    # Generate the new MAC using the provided target_oui
                    new_mac = generate_mac_with_new_oui(original_mac_norm, target_oui_norm)
                    mac_to_new_mac_map[original_mac_norm] = new_mac
                    logging.debug(f"  Successfully mapped Original MAC '{original_mac_norm}' to New MAC '{new_mac}' (Using Target OUI: {target_oui_norm})")
                else:
                    logging.warning(f"  Invalid Target OUI format '{target_oui_norm}' for original MAC '{original_mac_norm}'. Rule will be skipped.")

            except AttributeError as ae:
                # This might happen if a rule object doesn't have expected fields,
                # though Pydantic validation during rule loading should catch this.
                logging.warning(f"  Skipping rule due to AttributeError (likely malformed rule object: {rule}): {ae}")
            except Exception as e_rule:
                logging.warning(f"  Error processing rule '{rule}': {e_rule}. Skipping this rule.")

    logging.debug(f"Finished pre-computing MAC transformation map. {len(mac_to_new_mac_map)} MACs are targeted for transformation.")
    if mac_to_new_mac_map:
        logging.debug("mac_to_new_mac_map content (first 5 entries):")
        count = 0
        for orig_mac, new_mac_val in mac_to_new_mac_map.items():
            logging.debug(f"  '{orig_mac}' -> '{new_mac_val}'")
            count += 1
            if count >= 5:
                break

    # 4. Packet Processing Loop
    new_packets = []
    total_packets = len(packets)
    last_reported_progress = -1
    transformed_packet_count = 0

    logging.info(f"Processing {total_packets} packets for MAC transformation...")
    for i in range(total_packets):
        pkt = packets[i]
        # --- Cancellation Check ---
        if check_stop_requested and (i % 100 == 0 or i == total_packets - 1):
            if check_stop_requested():
                logging.info(f"!!! [MAC Transformer] Stop requested. Aborting transformation for input trace {input_trace_id} at packet {i+1}/{total_packets}.")
                raise MacJobCancelledException("Stop requested by user.") # Use the (potentially dummy) imported exception
        # ------------------------

        processed_packet = pkt # Default to original packet
        mac_changed_in_packet = False
        try:
            if Ether in pkt:
                # Work on the copy only if a transformation is likely
                current_src_mac_norm = pkt[Ether].src.upper()
                current_dst_mac_norm = pkt[Ether].dst.upper()

                new_src_mac = mac_to_new_mac_map.get(current_src_mac_norm)
                new_dst_mac = mac_to_new_mac_map.get(current_dst_mac_norm)

                if new_src_mac or new_dst_mac:
                    # Only copy if we are actually changing something
                    if not mac_changed_in_packet: # Avoid multiple copies if already copied
                        processed_packet = pkt.copy()
                        mac_changed_in_packet = True
                    
                    if new_src_mac:
                        logging.debug(f"Packet {i+1}: Transforming SRC MAC '{pkt[Ether].src}' to '{new_src_mac}'")
                        processed_packet[Ether].src = new_src_mac
                    if new_dst_mac:
                        logging.debug(f"Packet {i+1}: Transforming DST MAC '{pkt[Ether].dst}' to '{new_dst_mac}'")
                        processed_packet[Ether].dst = new_dst_mac
                
                if mac_changed_in_packet: # If any MAC was changed in this packet
                    transformed_packet_count +=1 # Increment count of packets that had at least one MAC changed
                    # Delete checksums if MACs were changed and relevant layers exist
                    if IP in processed_packet: del processed_packet[IP].chksum
                    if TCP in processed_packet: del processed_packet[TCP].chksum
                    if UDP in processed_packet: del processed_packet[UDP].chksum
                    if ICMP in processed_packet: del processed_packet[ICMP].chksum

            # Append the processed packet (either modified copy or original)
            new_packets.append(processed_packet)

        except Exception as packet_err:
             logging.warning(f"Error processing packet {i+1}/{total_packets} in input trace {input_trace_id}: {packet_err}. Appending original.")
             # Append the ORIGINAL packet if an error occurred during processing
             new_packets.append(pkt) # Use pkt (original)

        # --- Progress Reporting Logic ---
        if progress_callback and total_packets > 0:
            current_progress = int(((i + 1) / total_packets) * 100)
            # Report progress more frequently or at least at 5% intervals and always at 100%
            if current_progress > last_reported_progress and (current_progress % 5 == 0 or current_progress == 100 or i == total_packets - 1):
                try:
                    progress_callback(current_progress)
                    last_reported_progress = current_progress
                except Exception as cb_err:
                    logging.warning(f"Progress callback failed during MAC transformation: {cb_err}")

    # 5. Write Output using storage helper
    try:
        logging.info(f"Writing {len(new_packets)} processed packets to '{output_pcap_filename}' for new output trace {new_output_trace_id} using storage module...")
        output_path_obj = storage.write_pcap_to_session(new_output_trace_id, output_pcap_filename, new_packets)
        logging.info(f"Successfully wrote transformed file: {str(output_path_obj)}")
    except Exception as e:
        logging.error(f"Error writing transformed pcap file '{output_pcap_filename}' for new output trace {new_output_trace_id}: {e}")
        raise # Re-raise write errors

    # 6. Return dictionary with output path and filename
    return {
        "output_trace_id": new_output_trace_id,
        "output_filename": output_pcap_filename,
        "full_output_path": str(output_path_obj)
    }


# Example usage (optional)
