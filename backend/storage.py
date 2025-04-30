import os
import json

SESSION_DIR = './sessions'
os.makedirs(SESSION_DIR, exist_ok=True)

def _path(session_id: str, key: str):
    return os.path.join(SESSION_DIR, f"{session_id}_{key}.json")

def store(session_id: str, key: str, obj):
    with open(_path(session_id, key), 'w') as f:
        json.dump(obj, f)

def load(session_id: str, key: str):
    with open(_path(session_id, key), 'r') as f:
        return json.load(f)

def get_rules(session_id: str):
    return load(session_id, 'rules')

def get_capture_path(session_id: str):
    return os.path.join(SESSION_DIR, f"{session_id}.pcap")


# --- Job status helpers ---
def store_job_status(session_id: str, job_id: str, status: dict):
    """
    Persist a background job's status to disk.
    """
    store(session_id, f"job_{job_id}_status", status)

def load_job_status(session_id: str, job_id: str):
    """
    Load a previously stored job status.
    """
    return load(session_id, f"job_{job_id}_status")

def list_job_ids(session_id: str):
    """
    List all job IDs for the given session, based on stored status files.
    """
    files = os.listdir(SESSION_DIR)
    prefix = f"{session_id}_job_"
    suffix = "_status.json"
    return [
        fname[len(prefix):-len(suffix)]
        for fname in files
        if fname.startswith(prefix) and fname.endswith(suffix)
    ]