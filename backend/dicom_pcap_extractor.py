# dicom_pcap_extractor.py
# MODIFIED VERSION: Makes metadata extraction less strict regarding
# presentation context negotiation acceptance. Extracts AE Titles if found,
# regardless of negotiation outcome, and adds an optional flag indicating success.

# PROPERTIES FROM DICOM SEARCHED:
# 1. Transducer type
# 2. Software version
# 3. Device Serial Number
# 4. Manufacturer
# 5. Manufacturer’s Model Name
# 6. A-Associated

import io
import logging
import struct
import os
import traceback
from collections import defaultdict
from typing import Dict, List, Optional, Tuple, Any

import re # Import regex module
import pydicom
from pydicom.errors import InvalidDicomError
# from pydicom.uid import UID, ImplicitVRLittleEndian, ExplicitVRLittleEndian, DeflatedExplicitVRLittleEndian, ExplicitVRBigEndian # Not strictly needed for this logic

# Scapy imports
logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
try:
    # Try importing DICOM layer if available in Scapy contrib
    from scapy.all import rdpcap, TCP, IP, Raw # type: ignore
    from scapy.sessions import TCPSession # type: ignore
    try:
        from scapy.contrib.dicom import DicomAssociateRQ, DicomAssociateAC # type: ignore
        HAS_SCAPY_DICOM = True
        print("INFO: Scapy DICOM contrib layer found.")
    except ImportError:
        HAS_SCAPY_DICOM = False
        print("WARN: Scapy DICOM contrib layer not found. Will rely on regex parsing of summary.")
except ImportError as e:
    print(f"!!! [Extractor] Failed to import Scapy components: {e}. Ensure Scapy is installed.")
    HAS_SCAPY_DICOM = False # Ensure flag is false if base import fails
    pass


# Import storage utilities and necessary models
try:
    from storage import get_capture_path, SESSION_DIR # type: ignore
    # *** IMPORTANT: Assume DicomExtractedMetadata is defined elsewhere (e.g., models.py) ***
    # *** You MUST add `negotiation_successful: Optional[bool] = None` AND the fields below to its definition ***
    # Example placeholder if models.py is not available:
    class DicomExtractedMetadata:
        def __init__(self, CallingAE=None, CalledAE=None, ImplementationClassUID=None, ImplementationVersionName=None, negotiation_successful=None,
                     Manufacturer=None, ManufacturerModelName=None, DeviceSerialNumber=None, SoftwareVersions=None, TransducerData=None, StationName=None, # Added fields
                     **kwargs):
            self.CallingAE = CallingAE
            self.CalledAE = CalledAE
            self.ImplementationClassUID = ImplementationClassUID
            self.ImplementationVersionName = ImplementationVersionName
            self.negotiation_successful = negotiation_successful
            # --- Added Fields for P-DATA extraction ---
            self.Manufacturer = Manufacturer
            self.ManufacturerModelName = ManufacturerModelName
            self.DeviceSerialNumber = DeviceSerialNumber
            self.SoftwareVersions = SoftwareVersions # Note: DICOM tag (0018,1020) can be multi-valued
            self.TransducerData = TransducerData     # Note: DICOM tag (0018,5010) can be multi-valued
            self.StationName = StationName           # Note: DICOM tag (0008,1010)
            # -----------------------------------------
            # Store any other kwargs for flexibility
            for key, value in kwargs.items():
                setattr(self, key, value)
    print("WARN: Using placeholder DicomExtractedMetadata model. Ensure the actual model from models.py is used and includes 'negotiation_successful' and the other extracted fields.")

except ImportError:
    SESSION_DIR = './sessions'
    def get_capture_path(session_id: str):
        return os.path.join(SESSION_DIR, f"{session_id}.pcap")
    print("WARN: Using fallback get_capture_path and placeholder DicomExtractedMetadata.")
    class DicomExtractedMetadata: # Duplicate placeholder definition
         def __init__(self, CallingAE=None, CalledAE=None, ImplementationClassUID=None, ImplementationVersionName=None, negotiation_successful=None, **kwargs):
            self.CallingAE = CallingAE
            self.CalledAE = CalledAE
            self.ImplementationClassUID = ImplementationClassUID
            self.ImplementationVersionName = ImplementationVersionName
            self.negotiation_successful = negotiation_successful
             # --- Added Fields for P-DATA extraction ---
            self.Manufacturer = Manufacturer
            self.ManufacturerModelName = ManufacturerModelName
            self.DeviceSerialNumber = DeviceSerialNumber
            self.SoftwareVersions = SoftwareVersions
            self.TransducerData = TransducerData
            self.StationName = StationName
            # -----------------------------------------
            for key, value in kwargs.items():
                setattr(self, key, value)

# --- Custom Exception for Cancellation ---
class JobCancelledException(Exception):
    """Custom exception to signal job cancellation."""
    pass

# --- PDU Reading Logic (Helper Function) ---
def read_pdu(stream: io.BytesIO) -> Optional[Tuple[int, int, bytes]]:
    """Reads the next PDU (Protocol Data Unit) from the stream."""
    header_bytes = stream.read(6) # PDU type (1 byte) + Reserved (1 byte) + Length (4 bytes)
    if len(header_bytes) < 6:
        # Not enough data for a header
        # print("Debug: Not enough data for PDU header.")
        return None

    try:
        pdu_type, reserved, pdu_length = struct.unpack('>B B I', header_bytes) # Big Endian
        # print(f"Debug: Read PDU header: type={pdu_type}, reserved={reserved}, length={pdu_length}")

        pdu_data = stream.read(pdu_length)
        if len(pdu_data) < pdu_length:
            print(f"WARN: Incomplete PDU data. Expected {pdu_length} bytes, got {len(pdu_data)}.")
             # Rewind the stream to before reading this incomplete PDU's data and header
            stream.seek(stream.tell() - len(pdu_data) - 6)
            return None # Indicate failure to read complete PDU

        # print(f"Debug: Successfully read PDU data ({pdu_length} bytes).")
        return pdu_type, pdu_length, pdu_data
    except struct.error as e:
        print(f"ERROR unpacking PDU header: {e}. Header bytes: {header_bytes!r}")
         # Rewind stream before the failed header read attempt
        stream.seek(stream.tell() - len(header_bytes))
        return None
    except Exception as e:
        print(f"ERROR reading PDU: {e}\n{traceback.format_exc()}")
         # Rewind stream to before the header read attempt
        stream.seek(stream.tell() - len(header_bytes))
        return None


# --- Metadata Extraction Logic ---
def extract_relevant_metadata(stream: io.BytesIO, key: Tuple[str, str, int]) -> Optional[DicomExtractedMetadata]:
    """
    Parses a DICOM TCP stream (from BytesIO) and extracts relevant metadata
    like AE Titles and Implementation details from Association PDUs.

    MODIFIED: Extracts basic info even if context negotiation fails.
    """
    client_ip, server_ip, server_port = key
    # --- DEBUG LOGGING START ---
    target_client_ip = "172.18.121.241"
    target_server_ip = "10.193.145.168"
    is_target_stream = (client_ip == target_client_ip and server_ip == target_server_ip) or \
                       (client_ip == target_server_ip and server_ip == target_client_ip) # Check both directions

    if is_target_stream:
        print(f"--- DEBUG DICOM: Processing target stream {key} ---")
    # --- DEBUG LOGGING END ---
    print(f">>> [Extractor] Attempting to decode stream for key: {key}")

    # Stores metadata found across different PDUs in the stream
    found_metadata: Dict[str, Any] = {}
    # Stores proposed presentation contexts from A-ASSOCIATE-RQ
    assoc_rq_contexts: Dict[int, Dict[str, Any]] = {}
    # Stores presentation context results from A-ASSOCIATE-AC
    current_context_results: Dict[int, Dict[str, Any]] = {}
    # Stores reassembled P-DATA fragments per presentation context ID
    p_data_fragments: Dict[int, bytes] = defaultdict(bytes)
    # Flag to track if we have successfully parsed any P-DATA dataset
    parsed_p_data_success = False

    # Ensure stream is at the beginning
    stream.seek(0)
    initial_buffer_len = len(stream.getbuffer())
    print(f"Debug: Stream buffer length: {initial_buffer_len} bytes.")

    # --- Main PDU Processing Loop ---
    while stream.tell() < initial_buffer_len:
        current_pos = stream.tell()
        # print(f"Debug: Reading PDU at stream position {current_pos}/{initial_buffer_len}")
        pdu_info = read_pdu(stream)

        if pdu_info is None:
            # Failed to read a complete PDU, likely end of stream or garbage data
            print(f"Debug: read_pdu returned None at position {current_pos}. Assuming end of relevant PDUs.")
            break # Exit loop

        pdu_type, pdu_length, pdu_data = pdu_info
        pdu_data_stream = io.BytesIO(pdu_data) # Use BytesIO for pydicom

        # --- Process specific PDU types ---
        if pdu_type == 0x01: # A-ASSOCIATE-RQ
             print(f"Debug: Found A-ASSOCIATE-RQ PDU (Length: {pdu_length})")
             # --- DEBUG LOGGING START ---
             if is_target_stream: print(f"--- DEBUG DICOM: Found A-ASSOCIATE-RQ in target stream ---")
             # --- DEBUG LOGGING END ---
             try:
                 # force=True allows reading even if preamble/prefix is missing
                 assoc_ds = pydicom.dcmread(pdu_data_stream, force=True)
                 print(f"Successfully parsed A-ASSOCIATE-RQ PDU.")
                 # --- DEBUG LOGGING START ---
                 if is_target_stream: print(f"--- DEBUG DICOM: Successfully parsed A-ASSOCIATE-RQ ---")
                 # --- DEBUG LOGGING END ---

                 # --- STEP 2 (Modified): Extract Metadata Early ---
                 calling_ae_rq = assoc_ds.get("CallingAETitle", "").strip()
                 called_ae_rq = assoc_ds.get("CalledAETitle", "").strip()
                 found_metadata['CallingAE'] = calling_ae_rq
                 found_metadata['CalledAE'] = called_ae_rq
                 # --- DEBUG LOGGING START ---
                 if is_target_stream: print(f"--- DEBUG DICOM: Extracted from RQ: CallingAE='{calling_ae_rq}', CalledAE='{called_ae_rq}' ---")
                 # --- DEBUG LOGGING END ---
                 user_info = assoc_ds.get("UserInformation", None)
                 if user_info:
                      found_metadata['ImplementationClassUID'] = user_info.get("ImplementationClassUID")
                      found_metadata['ImplementationVersionName'] = user_info.get("ImplementationVersionName")

                 # Store proposed contexts
                 assoc_rq_contexts = {}
                 if hasattr(assoc_ds, 'PresentationContext'):
                     for pres_context in assoc_ds.PresentationContext:
                        # Check if TransferSyntax is a list or single item
                        transfer_syntaxes = pres_context.TransferSyntax
                        if not isinstance(transfer_syntaxes, list):
                            transfer_syntaxes = [transfer_syntaxes] # Ensure it's a list
                        assoc_rq_contexts[pres_context.PresentationContextID] = {
                            'AbstractSyntax': pres_context.AbstractSyntax,
                            'TransferSyntaxes': transfer_syntaxes
                        }
                 print(f"Extracted from RQ: Calling='{found_metadata.get('CallingAE')}', Called='{found_metadata.get('CalledAE')}', UID='{found_metadata.get('ImplementationClassUID')}', Version='{found_metadata.get('ImplementationVersionName')}'")
                 print(f"Parsed RQ Contexts: {assoc_rq_contexts}")


             except InvalidDicomError as e:
                 print(f"Error parsing A-ASSOCIATE-RQ: {e}")
                 # --- DEBUG LOGGING START ---
                 if is_target_stream: print(f"--- DEBUG DICOM: FAILED to parse A-ASSOCIATE-RQ (InvalidDicomError): {e} ---")
                 # --- DEBUG LOGGING END ---
             except Exception as e:
                 print(f"ERROR processing A-ASSOCIATE-RQ: {e}\n{traceback.format_exc()}")
                 # --- DEBUG LOGGING START ---
                 if is_target_stream: print(f"--- DEBUG DICOM: FAILED to parse A-ASSOCIATE-RQ (Exception): {e} ---")
                 # --- DEBUG LOGGING END ---

        elif pdu_type == 0x02: # A-ASSOCIATE-AC
             print(f"Debug: Found A-ASSOCIATE-AC PDU (Length: {pdu_length})")
             # --- DEBUG LOGGING START ---
             if is_target_stream: print(f"--- DEBUG DICOM: Found A-ASSOCIATE-AC in target stream ---")
             # --- DEBUG LOGGING END ---
             try:
                 assoc_ds = pydicom.dcmread(pdu_data_stream, force=True)
                 print(f"Successfully parsed A-ASSOCIATE-AC PDU.")
                 # --- DEBUG LOGGING START ---
                 if is_target_stream: print(f"--- DEBUG DICOM: Successfully parsed A-ASSOCIATE-AC ---")
                 # --- DEBUG LOGGING END ---

                 # --- STEP 2 (Modified): Extract/Update Metadata Early ---
                 # Update AE Titles if different (unlikely), prioritize AC for implementation info
                 calling_ae_ac = assoc_ds.get("CallingAETitle", "").strip()
                 called_ae_ac = assoc_ds.get("CalledAETitle", "").strip()
                 # Update only if not empty and potentially different from RQ
                 if calling_ae_ac: found_metadata['CallingAE'] = calling_ae_ac
                 if called_ae_ac: found_metadata['CalledAE'] = called_ae_ac
                 # --- DEBUG LOGGING START ---
                 if is_target_stream: print(f"--- DEBUG DICOM: Extracted from AC: CallingAE='{calling_ae_ac}', CalledAE='{called_ae_ac}' ---")
                 if is_target_stream: print(f"--- DEBUG DICOM: Metadata AE Titles after AC: Calling='{found_metadata.get('CallingAE')}', Called='{found_metadata.get('CalledAE')}' ---")
                 # --- DEBUG LOGGING END ---
                 user_info = assoc_ds.get("UserInformation", None)
                 if user_info:
                      found_metadata['ImplementationClassUID'] = user_info.get("ImplementationClassUID", found_metadata.get('ImplementationClassUID'))
                      found_metadata['ImplementationVersionName'] = user_info.get("ImplementationVersionName", found_metadata.get('ImplementationVersionName'))

                 # --- STEP 1 (Modified): Locate Context Logic & Store Results ---
                 current_context_results = {}
                 if hasattr(assoc_ds, 'PresentationContext'):
                     for pres_context in assoc_ds.PresentationContext:
                         current_context_results[pres_context.PresentationContextID] = {
                             'Result': pres_context.Result,
                             'TransferSyntax': pres_context.TransferSyntax # Accepted TS UID
                         }
                         # Optional: Log rejection during parsing
                         if pres_context.Result != 0:
                            print(f"Info: AC reports Context ID {pres_context.PresentationContextID} rejected/no-negotiation (Result: {pres_context.Result}).")

                 print(f"Extracted from AC: UID='{found_metadata.get('ImplementationClassUID')}', Version='{found_metadata.get('ImplementationVersionName')}'")
                 print(f"Parsed AC Context Results: {current_context_results}")


             except InvalidDicomError as e:
                 print(f"Error parsing A-ASSOCIATE-AC: {e}")
                 # --- DEBUG LOGGING START ---
                 if is_target_stream: print(f"--- DEBUG DICOM: FAILED to parse A-ASSOCIATE-AC (InvalidDicomError): {e} ---")
                 # --- DEBUG LOGGING END ---
             except Exception as e:
                 print(f"ERROR processing A-ASSOCIATE-AC: {e}\n{traceback.format_exc()}")
                 # --- DEBUG LOGGING START ---
                 if is_target_stream: print(f"--- DEBUG DICOM: FAILED to parse A-ASSOCIATE-AC (Exception): {e} ---")
                 # --- DEBUG LOGGING END ---

        elif pdu_type == 0x04: # P-DATA-TF
            # print(f"Debug: Found P-DATA-TF PDU (Length: {pdu_length})")
            # P-DATA-TF contains one or more PDVs (Presentation Data Values)
            pdv_stream = io.BytesIO(pdu_data)
            while pdv_stream.tell() < pdu_length:
                # Read PDV header: Length (4 bytes, Big Endian), Context ID (1 byte)
                pdv_header = pdv_stream.read(5)
                if len(pdv_header) < 5:
                    print(f"WARN: Incomplete PDV header in P-DATA-TF at pos {pdv_stream.tell()}. Stopping parse.")
                    break
                try:
                    pdv_item_len, pdv_context_id = struct.unpack('>IB', pdv_header)
                    # Read PDV data (Message Control Header (1 byte) + Data)
                    pdv_data_field = pdv_stream.read(pdv_item_len - 1) # Length includes context ID byte
                    if len(pdv_data_field) < (pdv_item_len - 1):
                         print(f"WARN: Incomplete PDV data. Expected {pdv_item_len - 1}, got {len(pdv_data_field)}. Stopping parse.")
                         break

                    # The first byte of pdv_data_field is the Message Control Header
                    # Bit 1 indicates if it's Command (1) or Data (0)
                    # Bit 0 indicates if it's the last fragment (1) or not (0)
                    message_control_header = pdv_data_field[0]
                    is_command = (message_control_header & 0x02) != 0
                    is_last_fragment = (message_control_header & 0x01) != 0
                    actual_data = pdv_data_field[1:]

                    # print(f"Debug: PDV ContextID={pdv_context_id}, Length={pdv_item_len}, IsCommand={is_command}, IsLast={is_last_fragment}, DataLen={len(actual_data)}")

                    # Append data fragment to the buffer for this context ID
                    p_data_fragments[pdv_context_id] += actual_data

                    # If this is the last fragment, try to parse the reassembled data
                    if is_last_fragment:
                        # print(f"Debug: Last fragment received for Context ID {pdv_context_id}. Total size: {len(p_data_fragments[pdv_context_id])}")
                        fragment_data = p_data_fragments[pdv_context_id]
                        if fragment_data:
                            try:
                                # Use BytesIO for pydicom
                                fragment_stream = io.BytesIO(fragment_data)
                                # force=True might be needed if data is slightly malformed
                                # stop_before_pixels=True can speed up parsing if pixel data isn't needed
                                p_data_ds = pydicom.dcmread(fragment_stream, force=True, stop_before_pixels=True)
                                print(f"Successfully parsed DICOM dataset from P-DATA (Context ID: {pdv_context_id})")
                                parsed_p_data_success = True # Mark success

                                # --- Extract Desired Tags ---
                                # Only update if not already found, taking the first occurrence
                                if 'Manufacturer' not in found_metadata or found_metadata['Manufacturer'] is None:
                                    found_metadata['Manufacturer'] = p_data_ds.get("Manufacturer")
                                if 'ManufacturerModelName' not in found_metadata or found_metadata['ManufacturerModelName'] is None:
                                    found_metadata['ManufacturerModelName'] = p_data_ds.get("ManufacturerModelName")
                                if 'DeviceSerialNumber' not in found_metadata or found_metadata['DeviceSerialNumber'] is None:
                                    found_metadata['DeviceSerialNumber'] = p_data_ds.get("DeviceSerialNumber")
                                if 'SoftwareVersions' not in found_metadata or found_metadata['SoftwareVersions'] is None:
                                    found_metadata['SoftwareVersions'] = p_data_ds.get("SoftwareVersions") # Can be str or list
                                if 'TransducerData' not in found_metadata or found_metadata['TransducerData'] is None:
                                    found_metadata['TransducerData'] = p_data_ds.get("TransducerData") # Can be multi-valued
                                if 'StationName' not in found_metadata or found_metadata['StationName'] is None:
                                    found_metadata['StationName'] = p_data_ds.get("StationName")

                                # Log extracted values for debugging
                                # print(f"  Extracted P-DATA: Manufacturer='{found_metadata.get('Manufacturer')}', Model='{found_metadata.get('ManufacturerModelName')}', SN='{found_metadata.get('DeviceSerialNumber')}', SW='{found_metadata.get('SoftwareVersions')}', Transducer='{found_metadata.get('TransducerData')}', Station='{found_metadata.get('StationName')}'")

                            except InvalidDicomError as e:
                                print(f"WARN: Failed to parse reassembled P-DATA fragment for Context ID {pdv_context_id} as DICOM: {e}")
                            except Exception as e:
                                print(f"ERROR processing P-DATA fragment for Context ID {pdv_context_id}: {e}\n{traceback.format_exc()}")
                            finally:
                                # Clear the buffer for this context ID after attempting parse
                                del p_data_fragments[pdv_context_id]
                        else:
                             print(f"Debug: Received last fragment for Context ID {pdv_context_id}, but no data buffered.")


                except struct.error as e:
                    print(f"ERROR unpacking PDV header: {e}. Header bytes: {pdv_header!r}")
                    break # Stop processing this PDU
                except Exception as e:
                    print(f"ERROR processing PDV item: {e}\n{traceback.format_exc()}")
                    break # Stop processing this PDU


        elif pdu_type == 0x06: # A-RELEASE-RQ
            print("Debug: Found A-RELEASE-RQ PDU.")
            pass # Can handle if needed

        elif pdu_type == 0x07: # A-RELEASE-RP
            print("Debug: Found A-RELEASE-RP PDU.")
            pass # Can handle if needed

        elif pdu_type == 0x08: # A-ABORT
            print("WARN: Found A-ABORT PDU. Association terminated abruptly.")
            # Could extract Source and Reason from A-ABORT if needed
            pass

        else:
            # print(f"Debug: Skipping unknown or unhandled PDU type {pdu_type} (Length: {pdu_length})")
            pass

    # --- End of PDU Processing Loop ---
    print(f"Debug: Finished processing stream for key {key}. Final stream position: {stream.tell()}/{initial_buffer_len}")

    # --- STEP 3 & 4 (Modified): Relax Condition & Add Indicator ---
    # Check if essential metadata (AE Titles) was found OR if we successfully parsed P-DATA
    # We might get P-DATA without seeing the full association setup in some captures.
    # --- DEBUG LOGGING START ---
    final_check_condition = (found_metadata.get('CallingAE') and found_metadata.get('CalledAE')) or parsed_p_data_success
    if is_target_stream:
        print(f"--- DEBUG DICOM: Final Check: CallingAE='{found_metadata.get('CallingAE')}', CalledAE='{found_metadata.get('CalledAE')}', ParsedPDataSuccess={parsed_p_data_success} ---")
        print(f"--- DEBUG DICOM: Final Check Condition Result: {final_check_condition} ---")
    # --- DEBUG LOGGING END ---
    if final_check_condition:
        if not (found_metadata.get('CallingAE') and found_metadata.get('CalledAE')):
             print("WARN: Proceeding based on successful P-DATA parse, but AE Titles were not found/extracted.")
        else:
             print(f"Debug: Found essential AE Titles: Calling='{found_metadata.get('CallingAE')}', Called='{found_metadata.get('CalledAE')}'")

        # Determine if negotiation was successful (at least one context accepted) - only relevant if we saw AC PDU
        any_context_accepted = False
        if assoc_rq_contexts and current_context_results: # Check if we have both RQ proposals and AC results
            for context_id, rq_context in assoc_rq_contexts.items():
                if context_id in current_context_results:
                    ac_result = current_context_results[context_id]
                    if ac_result.get('Result') == 0: # 0 = Acceptance
                        print(f"Debug: Context ID {context_id} accepted.")
                        any_context_accepted = True
                        break # Found one, no need to check further for this flag
                # else: (Optional: warning if AC didn't mention a proposed context ID)
                #    print(f"WARN: Proposed Context ID {context_id} not found in A-ASSOC-AC results.")
        else:
             print("Debug: Cannot determine negotiation success (missing RQ contexts or AC results).")

        # Log negotiation outcome
        print(f"Debug: Negotiation success flag calculated as: {any_context_accepted}")
        if not any_context_accepted and current_context_results:
            # Log if we had AC results but none were accepted
            print("WARN: No presentation contexts appear to have been accepted in the A-ASSOCIATE-AC PDU based on parsed results.")

        # --- Create Metadata Object ---
        # Proceed to create the metadata object REGARDLESS of negotiation success,
        # as long as we have the essential AE titles.
        print(f"Debug: Proceeding to create DicomExtractedMetadata object with collected data.")
        try:
           # *** IMPORTANT: Ensure DicomExtractedMetadata model includes 'negotiation_successful' ***
           # If not, remove the negotiation_successful argument below.
           return DicomExtractedMetadata(
               # Use .get() for safety, though we checked AE titles above
               CallingAE=found_metadata.get('CallingAE'),
               CalledAE=found_metadata.get('CalledAE'),
               ImplementationClassUID=found_metadata.get('ImplementationClassUID'),
               ImplementationVersionName=found_metadata.get('ImplementationVersionName'),
               # Set flag based on calculation, or None if check couldn't be performed
               negotiation_successful=any_context_accepted if current_context_results else None,
               # --- Add extracted P-DATA fields ---
               Manufacturer=found_metadata.get('Manufacturer'),
               ManufacturerModelName=found_metadata.get('ManufacturerModelName'),
               DeviceSerialNumber=found_metadata.get('DeviceSerialNumber'),
               SoftwareVersions=found_metadata.get('SoftwareVersions'),
               TransducerData=found_metadata.get('TransducerData'),
               StationName=found_metadata.get('StationName')
               # ------------------------------------
           )
        except Exception as e:
            # Catch potential errors during model instantiation (e.g., Pydantic validation)
            print(f"ERROR creating DicomExtractedMetadata object: {e}\n{traceback.format_exc()}")
            return None # Return None if model creation fails

    else:
        # Didn't find essential AE titles or successfully parsed P-DATA
        print(f"Debug: Did not find essential AE titles or parse any P-DATA datasets in the stream for key {key}. Returning None.")
        return None


from typing import Dict, List, Optional, Tuple, Any, Callable # Added Callable

# --- Main Extractor Function ---
def extract_dicom_metadata_from_pcap(
    session_id: str,
    progress_callback: Optional[Callable[[int], None]] = None,
    check_stop_requested: Optional[Callable[[], bool]] = None # Added cancellation check callback
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Main function to extract DICOM metadata from a PCAP file associated with a session.
    Reads the PCAP, identifies TCP sessions potentially containing DICOM,
    and extracts metadata using `extract_relevant_metadata`.

    Returns a dictionary where keys are string representations of (client_ip, server_ip, server_port)
    tuples and values are lists of DicomCommunicationInfo-like dictionaries.
    """
    print(f">>> [Extractor] ENTER function for session {session_id}")
    pcap_file_path = get_capture_path(session_id)
    if not os.path.exists(pcap_file_path):
        print(f"ERROR: PCAP file not found at {pcap_file_path}")
        raise FileNotFoundError(f"PCAP file not found for session {session_id}")

    print(f">>> [Extractor] Reading PCAP file: {pcap_file_path}")
    try:
        packets = rdpcap(pcap_file_path)
    except Exception as e:
        print(f"ERROR reading PCAP file {pcap_file_path} with Scapy: {e}\n{traceback.format_exc()}")
        return {} # Return empty if PCAP can't be read

    print(f">>> [Extractor] Analyzing {len(packets)} packets for TCP sessions...")
    # Group packets into TCP sessions using Scapy's sessions()
    try:
        tcp_sessions = packets.sessions()
    except Exception as e:
        print(f"ERROR grouping packets into TCP sessions: {e}\n{traceback.format_exc()}")
        return {}

    print(f">>> [Extractor] Found {len(tcp_sessions)} TCP sessions in the PCAP.")

    # Store results keyed by (client_ip, server_ip, server_port) tuple
    # Value will be a list of DicomCommunicationInfo objects (as dicts for now)
    results_by_ip: Dict[Tuple[str, str, int], List[Dict[str, Any]]] = defaultdict(list)
    # Keep track of all processed streams to avoid duplicates if sessions() returns overlapping fragments
    processed_stream_hashes = set()
    # Store AE titles found directly from packet summaries, keyed by (client_ip, server_ip, server_port)
    ae_titles_from_summary: Dict[Tuple[str, str, int], Dict[str, Optional[str]]] = defaultdict(lambda: {"CallingAE": None, "CalledAE": None})


    session_count = 0
    total_sessions = len(tcp_sessions)

    # --- First Pass: Extract AE Titles directly from Raw Payload Bytes ---
    print(">>> [Extractor] First Pass: Scanning packets for A-ASSOCIATE raw payload info...")
    packet_count = 0

    for pkt in packets:
        packet_count += 1
        if not pkt.haslayer(TCP) or not pkt.haslayer(IP) or not pkt.haslayer(Raw):
            continue

        payload = bytes(pkt[Raw].load)
        # Check for A-ASSOCIATE-RQ (0x01) or A-ASSOCIATE-AC (0x02) PDU Type
        # and minimum length to contain AE titles (1 + 1 + 4 + 2 + 2 + 16 + 16 = 42 bytes)
        if len(payload) >= 42 and (payload[0] == 0x01 or payload[0] == 0x02):
            pdu_type = payload[0]
            pkt_client_ip = pkt[IP].src
            pkt_server_ip = pkt[IP].dst
            pkt_client_port = pkt[TCP].sport
            pkt_server_port = pkt[TCP].dport

            try:
                # Extract Called AE Title (bytes 10-25) and Calling AE Title (bytes 26-41)
                called_ae_bytes = payload[10:26]
                calling_ae_bytes = payload[26:42]

                # Decode assuming ASCII (common for AE titles) and strip padding spaces
                called_ae_found = called_ae_bytes.decode('ascii', errors='ignore').strip()
                calling_ae_found = calling_ae_bytes.decode('ascii', errors='ignore').strip()

                if called_ae_found or calling_ae_found:
                    print(f"  [Raw Payload Scan] Packet {packet_count} ({'RQ' if pdu_type == 0x01 else 'AC'}): Found Calling='{calling_ae_found}', Called='{called_ae_found}'")

                    # Determine the primary key (Client -> Server)
                    # For RQ, packet direction is Client -> Server
                    # For AC, packet direction is Server -> Client
                    if pdu_type == 0x01: # RQ
                        primary_key = (pkt_client_ip, pkt_server_ip, pkt_server_port)
                    else: # AC
                        primary_key = (pkt_client_ip, pkt_server_ip, pkt_client_port) # Note: AC source port is server port

                    # Store AE titles under the primary key, overwriting if necessary (last seen wins?)
                    # Or only store if None? Let's store if found.
                    if calling_ae_found:
                         ae_titles_from_summary[primary_key]["CallingAE"] = calling_ae_found
                         print(f"    -> Stored CallingAE '{calling_ae_found}' for key {primary_key}")
                    if called_ae_found:
                         ae_titles_from_summary[primary_key]["CalledAE"] = called_ae_found
                         print(f"    -> Stored CalledAE '{called_ae_found}' for key {primary_key}")

            except Exception as e:
                print(f"  [Raw Payload Scan] Error processing payload for packet {packet_count}: {e}")

    print(f"<<< [Extractor] First Pass Complete. Found AE titles from raw payload scan: {dict(ae_titles_from_summary)}")


    # --- Second Pass: Process TCP Sessions (Existing Stream Parsing Logic - pydicom) ---
    print(">>> [Extractor] Second Pass: Processing reassembled TCP sessions...")
    session_count = 0
    total_sessions = len(tcp_sessions)
    last_reported_progress = -1 # Track last reported progress

    for session_key, session_packets in tcp_sessions.items():
        session_count += 1
        print(f"\n>>> [Extractor] Processing TCP session {session_count}/{total_sessions}: {session_key}")

        # --- Cancellation Check ---
        if check_stop_requested and check_stop_requested():
            print(f"!!! [Extractor] Stop requested. Aborting extraction for session {session_id} before processing session {session_key}.")
            raise JobCancelledException("Stop requested by user.")
        # ------------------------

        # --- Progress Reporting Logic ---
        if progress_callback and total_sessions > 0:
            current_progress = int(((session_count) / total_sessions) * 100)
            # Report only on change or every few percent to avoid spamming logs/callbacks
            if current_progress > last_reported_progress and (current_progress % 5 == 0 or current_progress == 100):
                try:
                    progress_callback(current_progress)
                    last_reported_progress = current_progress
                    print(f"  [Progress Callback] Reported: {current_progress}%") # Debug log
                except Exception as cb_err:
                    print(f"Warning: Progress callback failed during DICOM extraction: {cb_err}")
        # -----------------------------

        # Heuristic: Skip sessions with very few packets (unlikely to be DICOM association)
        if len(session_packets) < 3: # Need at least SYN, SYN/ACK, ACK
             print(f"  Skipping session with only {len(session_packets)} packets.")
             continue

        # Reassemble TCP Stream data
        stream_data = b""
        client_ip: Optional[str] = None
        server_ip: Optional[str] = None
        server_port: Optional[int] = None
        client_port: Optional[int] = None # Store client port too

        # Determine client/server based on first SYN or data packet
        # Look for SYN or first packet with payload to guess direction
        first_data_packet = None
        syn_packet = None
        for pkt in session_packets:
             if TCP in pkt and pkt[TCP].flags & 0x02: # Check for SYN flag
                 syn_packet = pkt
                 break
             if TCP in pkt and pkt[TCP].payload:
                 first_data_packet = pkt
                 break

        if syn_packet:
            client_ip = syn_packet[IP].src
            server_ip = syn_packet[IP].dst
            client_port = syn_packet[TCP].sport
            server_port = syn_packet[TCP].dport
        elif first_data_packet:
            # If no SYN (capture started mid-stream), guess based on first data
            client_ip = first_data_packet[IP].src
            server_ip = first_data_packet[IP].dst
            client_port = first_data_packet[TCP].sport
            server_port = first_data_packet[TCP].dport
        else:
             print("  Skipping session: Cannot determine client/server IPs/ports (no SYN or payload).")
             continue # Cannot determine direction

        # Filter packets for this specific flow (client -> server and server -> client)
        # This might be redundant if tcp_sessions already gives clean sessions, but adds safety
        flow_packets = [pkt for pkt in session_packets if IP in pkt and TCP in pkt and
                        ((pkt[IP].src == client_ip and pkt[IP].dst == server_ip and pkt[TCP].sport == client_port and pkt[TCP].dport == server_port) or \
                         (pkt[IP].src == server_ip and pkt[IP].dst == client_ip and pkt[TCP].sport == server_port and pkt[TCP].dport == client_port))]

        # Crude reassembly by concatenating payloads in order
        # Scapy's TCPSession reassembly is preferred if available and reliable
        # For simplicity here, just concat payloads for DICOM check
        # WARNING: This crude reassembly might fail for complex streams with retransmissions etc.
        ordered_payloads = sorted(flow_packets, key=lambda p: (p.time, p[TCP].seq))
        for pkt in ordered_payloads:
            if pkt[TCP].payload:
                 stream_data += bytes(pkt[TCP].payload)

        if not stream_data:
            print("  Skipping session: No TCP payload data found.")
            continue

        print(f"  Stream reassembled with {len(stream_data)} bytes for session between {client_ip}:{client_port} and {server_ip}:{server_port}.")

        # Avoid reprocessing identical stream data if session keys were ambiguous
        stream_hash = hash(stream_data)
        if stream_hash in processed_stream_hashes:
            print("  Skipping session: Identical stream data already processed.")
            continue
        processed_stream_hashes.add(stream_hash)

        # Attempt to extract metadata using the existing stream-based function
        stream_buffer = io.BytesIO(stream_data)
        metadata_obj = extract_relevant_metadata(stream_buffer, (client_ip, server_ip, server_port)) # This function still does the detailed PDU parsing

        # --- Integration Step: Merge AE Titles from Packet Scan ---
        comm_key = (client_ip, server_ip, server_port)
        summary_aes = ae_titles_from_summary.get(comm_key, {})
        summary_calling_ae = summary_aes.get("CallingAE")
        summary_called_ae = summary_aes.get("CalledAE")

        if metadata_obj:
            print(f">>> [Extractor] Stream metadata extracted for key: {comm_key}")
            # Override AE titles if they are missing/empty in stream result but found in packet scan
            if not metadata_obj.CallingAE and summary_calling_ae:
                print(f"  Overriding empty CallingAE with value from packet scan: '{summary_calling_ae}'")
                metadata_obj.CallingAE = summary_calling_ae
            if not metadata_obj.CalledAE and summary_called_ae:
                print(f"  Overriding empty CalledAE with value from packet scan: '{summary_called_ae}'")
                metadata_obj.CalledAE = summary_called_ae

            # Append result as a dictionary
            metadata_dict = {}
            for field, value in metadata_obj.__dict__.items():
                 if isinstance(value, bytes):
                     try:
                         metadata_dict[field] = value.decode('ascii', errors='replace').strip()
                     except UnicodeDecodeError:
                         metadata_dict[field] = repr(value) # Fallback for non-decodable bytes
                 else:
                     metadata_dict[field] = value

            comm_info = {
                "client_ip": client_ip,
                "server_ip": server_ip,
                "server_port": server_port,
                "metadata": metadata_dict
            }
            results_by_ip[comm_key].append(comm_info)
            print(f"  Stored communication info (potentially merged). Current count for key {comm_key}: {len(results_by_ip[comm_key])}")
        elif summary_calling_ae or summary_called_ae:
             # If stream parsing failed BUT packet scan found AE titles, create a minimal metadata entry
             print(f"  Stream parsing failed for key {comm_key}, but found AE titles in packet scan. Creating minimal entry.")
             minimal_metadata = {
                 "CallingAE": summary_calling_ae,
                 "CalledAE": summary_called_ae,
                 # Set other fields to None or default
                 "ImplementationClassUID": None, "ImplementationVersionName": None, "negotiation_successful": None,
                 "Manufacturer": None, "ManufacturerModelName": None, "DeviceSerialNumber": None,
                 "SoftwareVersions": None, "TransducerData": None, "StationName": None
             }
             comm_info = {
                "client_ip": client_ip,
                "server_ip": server_ip,
                "server_port": server_port,
                "metadata": minimal_metadata
             }
             results_by_ip[comm_key].append(comm_info)
             print(f"  Stored minimal communication info from packet scan. Current count for key {comm_key}: {len(results_by_ip[comm_key])}")
        else:
            # No metadata found by either method
            print(f"  No relevant DICOM metadata found or extracted for stream between {client_ip}:{client_port} and {server_ip}:{server_port} by either method.")


    # --- Post-processing: Aggregation by IP Pair ---
    print(f"\n>>> [Extractor] Finished processing all {total_sessions} TCP sessions. Aggregating results by IP pair...")

    aggregated_results: Dict[str, Dict[str, Any]] = {}

    for key_tuple, comm_list in results_by_ip.items():
        client_ip, server_ip, _ = key_tuple # Extract IPs from the tuple key
        agg_key = f"{client_ip}-{server_ip}" # Create aggregation key based on IPs only

        if agg_key not in aggregated_results:
            # Initialize the entry for this IP pair
            aggregated_results[agg_key] = {
                "client_ip": client_ip,
                "server_ip": server_ip,
                # Initialize all potential metadata fields to None or default
                "CallingAE": None,
                "CalledAE": None,
                "ImplementationClassUID": None,
                "ImplementationVersionName": None,
                "negotiation_successful": None, # Keep track of negotiation status if needed
                "Manufacturer": None,
                "ManufacturerModelName": None,
                "DeviceSerialNumber": None,
                "SoftwareVersions": None, # Use None initially, could become list later if needed
                "TransducerData": None,
                "StationName": None,
                # Add a field to store the list of server ports seen for this IP pair
                "server_ports": set() # Use a set to store unique ports
            }

        # Add the server port from this specific communication to the set
        aggregated_results[agg_key]["server_ports"].add(key_tuple[2]) # Add the port

        # Iterate through each communication instance found for this specific flow (key_tuple)
        for comm_info in comm_list:
            metadata = comm_info.get("metadata", {})
            if not metadata: continue # Skip if no metadata in this instance

            # Aggregate metadata: Update fields only if the current aggregated value is None/empty
            for field in [
                "CallingAE", "CalledAE", "ImplementationClassUID", "ImplementationVersionName",
                "Manufacturer", "ManufacturerModelName", "DeviceSerialNumber",
                "SoftwareVersions", "TransducerData", "StationName"
            ]:
                if aggregated_results[agg_key][field] is None and metadata.get(field) is not None:
                    aggregated_results[agg_key][field] = metadata[field]

            # Handle negotiation_successful: Maybe prioritize 'True' or 'False' over 'None'?
            # For simplicity, let's take the first non-None value encountered.
            if aggregated_results[agg_key]["negotiation_successful"] is None and metadata.get("negotiation_successful") is not None:
                 aggregated_results[agg_key]["negotiation_successful"] = metadata.get("negotiation_successful")


    # Convert server_ports set to a sorted list for consistent JSON output
    for key in aggregated_results:
        aggregated_results[key]["server_ports"] = sorted(list(aggregated_results[key]["server_ports"]))

    total_aggregated_entries = len(aggregated_results)
    print(f">>> [Extractor] Aggregation complete. Found {total_aggregated_entries} unique IP pairs with DICOM metadata.")
    print(f"<<< [Extractor] EXIT function for session {session_id}. Returning aggregated results.")
    # Use repr() for potentially more detail on complex objects within the dict
    # print(f"<<< [Extractor] Final aggregated results content: {repr(aggregated_results)}")

    return aggregated_results # Return the aggregated dictionary


# --- Test Execution Block ---
if __name__ == '__main__':
    # Create a dummy session dir if it doesn't exist
    if not os.path.exists(SESSION_DIR):
        os.makedirs(SESSION_DIR)
        print(f"Created session directory: {SESSION_DIR}")

    TEST_SESSION_ID = "test_dicom_session"
    print(f"\n--- Running Test Block for session: {TEST_SESSION_ID} ---")
    TEST_PCAP_PATH = get_capture_path(TEST_SESSION_ID)

    # Check if test pcap exists, if not, maybe skip test or create a dummy one
    if not os.path.exists(TEST_PCAP_PATH):
        print(f"WARN: Test PCAP file not found at {TEST_PCAP_PATH}.")
        # Optionally create a dummy PCAP here for basic testing if needed
        # print("Consider creating a dummy PCAP with DICOM traffic for testing.")
    else:
        print(f"Running extraction test on: {TEST_PCAP_PATH}")
        try:
            # Call the main extraction function
            results = extract_dicom_metadata_from_pcap(TEST_SESSION_ID)
            print("\n--- Extraction Test Results (Dict Format) ---")
            # Pretty print the resulting dictionary
            import json
            print(json.dumps(results, indent=2, default=str)) # Use default=str for safety
            print("-------------------------------------------")
        except FileNotFoundError as e:
            print(f"Test Error: {e}")
        except Exception as e:
            print(f"An unexpected error occurred during the test: {e}\n{traceback.format_exc()}")
