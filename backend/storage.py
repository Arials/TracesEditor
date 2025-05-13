import json
import uuid
from pathlib import Path
import shutil # Added for store_uploaded_pcap
import logging

# Scapy imports
from scapy.all import rdpcap, wrpcap, PacketList

# FastAPI specific imports (needed for UploadFile type hint)
from fastapi import UploadFile

# Configure logger
logger = logging.getLogger(__name__)

# Define the base directory for all sessions, relative to this file's location
SESSIONS_BASE_DIR = Path(__file__).parent / 'sessions'
# Ensure the base sessions directory exists
SESSIONS_BASE_DIR.mkdir(parents=True, exist_ok=True)

def create_new_session_id() -> str:
    """Creates and returns a new unique session ID."""
    return str(uuid.uuid4())

def get_session_dir(session_id: str) -> Path:
    """
    Returns the absolute path to a specific session's directory.
    Creates the directory if it doesn't exist.
    """
    if not session_id:
        raise ValueError("session_id cannot be empty or None.")
    session_path = SESSIONS_BASE_DIR / session_id
    session_path.mkdir(parents=True, exist_ok=True)
    return session_path.resolve()

def get_session_filepath(session_id: str, filename: str) -> Path:
    """
    Returns the absolute path to a specific file within a session's directory.
    Ensures the session directory exists.
    """
    if not filename:
        raise ValueError("filename cannot be empty or None.")
    session_dir = get_session_dir(session_id)
    return (session_dir / filename).resolve()

def store_json(session_id: str, filename: str, data: dict):
    """
    Stores data (dictionary) as a JSON file in the session's directory.
    The filename should include the .json extension if desired.
    """
    filepath = get_session_filepath(session_id, filename)
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    return filepath

def load_json(session_id: str, filename: str) -> dict | None:
    """
    Loads data from a JSON file in the session's directory.
    Returns None if the file doesn't exist.
    The filename should include the .json extension if desired.
    """
    filepath = get_session_filepath(session_id, filename)
    if filepath.exists():
        with open(filepath, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                # Handle cases where the file might be empty or corrupted
                return None
    return None

def get_rules(session_id: str) -> dict | None:
    """Helper function to load 'rules.json' for a session."""
    return load_json(session_id, 'rules.json')

def store_rules(session_id: str, rules_data: dict):
    """
    Helper function to store 'rules.json' for a session.

    Args:
        session_id: The ID of the session.
        rules_data: The rules data to store (e.g., a dictionary or list).

    Returns:
        pathlib.Path: The path to the stored rules file.
    """
    return store_json(session_id, 'rules.json', rules_data)

def get_capture_path(session_id: str) -> Path:
    """
    Returns the path for the capture file (e.g., 'capture.pcap') for a session.
    Note: This function only returns the path; actual file writing/reading
    needs to be handled by the caller.
    """
    return get_session_filepath(session_id, "capture.pcap")

# --- PCAP specific helpers ---

def store_uploaded_pcap(session_id: str, uploaded_file: UploadFile, target_filename: str = "capture.pcap") -> Path:
    """
    Saves an uploaded PCAP file (FastAPI UploadFile) to the session directory.
    Closes the uploaded file's stream.
    """
    pcap_path = get_session_filepath(session_id, target_filename)
    try:
        with open(pcap_path, 'wb') as buffer:
            shutil.copyfileobj(uploaded_file.file, buffer)
        return pcap_path
    except Exception as e:
        logger.exception(f"Error storing uploaded PCAP file to {pcap_path}")
        raise RuntimeError(f"Failed to store uploaded PCAP file to {pcap_path}: {e}") from e
    finally:
        if hasattr(uploaded_file, 'file') and uploaded_file.file and not uploaded_file.file.closed:
            uploaded_file.file.close()

def read_pcap_from_session(session_id: str, filename: str = "capture.pcap") -> PacketList:
    """
    Reads a PCAP file from the session directory and returns Scapy PacketList.
    Handles Path to string conversion for Scapy.
    """
    pcap_path = get_session_filepath(session_id, filename)
    if not pcap_path.exists():
        logger.error(f"PCAP file not found in session {session_id}: {filename} at {pcap_path}")
        raise FileNotFoundError(f"PCAP file not found in session {session_id}: {filename} at {pcap_path}")
    try:
        packets = rdpcap(str(pcap_path))
        return packets
    except Exception as e:
        logger.exception(f"Failed to read PCAP file {pcap_path}")
        raise RuntimeError(f"Failed to read PCAP file {pcap_path}: {e}") from e

def write_pcap_to_session(session_id: str, filename: str, packets: PacketList) -> Path:
    """
    Writes Scapy PacketList to a PCAP file in the session directory.
    Handles Path to string conversion for Scapy. Returns the Path object of the written file.
    """
    pcap_path = get_session_filepath(session_id, filename)
    try:
        wrpcap(str(pcap_path), packets)
        return pcap_path
    except Exception as e:
        logger.exception(f"Failed to write PCAP file {pcap_path}")
        raise RuntimeError(f"Failed to write PCAP file {pcap_path}: {e}") from e

# --- Job status helpers ---
def store_job_status(session_id: str, job_id: str, status: dict):
    """
    Persist a background job's status to disk within the session directory.
    """
    if not job_id:
        raise ValueError("job_id cannot be empty or None.")
    store_json(session_id, f"job_{job_id}_status.json", status)

def load_job_status(session_id: str, job_id: str) -> dict | None:
    """
    Load a previously stored job status from the session directory.
    """
    if not job_id:
        raise ValueError("job_id cannot be empty or None.")
    return load_json(session_id, f"job_{job_id}_status.json")

def list_job_ids(session_id: str) -> list[str]:
    """
    List all job IDs for the given session, based on stored status files
    within the session directory.
    """
    session_dir_path = get_session_dir(session_id)
    job_ids = []
    prefix = "job_"
    suffix = "_status.json"
    for item in session_dir_path.iterdir():
        if item.is_file() and item.name.startswith(prefix) and item.name.endswith(suffix):
            # Extract job_id from "job_{job_id}_status.json"
            job_id = item.name[len(prefix):-len(suffix)]
            if job_id: # Ensure job_id is not empty
                job_ids.append(job_id)
    return job_ids
