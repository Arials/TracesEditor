# --- Imports ---
import sys
import os

# Add the project root to sys.path
# This allows 'from backend import ...' to work when main.py is run directly
# The project root is the parent directory of the 'backend' directory where this script is located.
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import asyncio
import json
import logging  # Added for logging configuration
import os  # Required for file operations (delete)
import shutil
import tempfile  # Added missing import
import traceback  # To debug and print full tracebacks
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path  # Added for Path type hint
from typing import Any, Dict, List, Literal, Optional, Tuple  # Added Dict, Any, Literal, Tuple

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,  # Added Query
    Response,
    status,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    JSONResponse,  # Added JSONResponse
    StreamingResponse,
)
from fastapi.routing import APIRouter # Added for organizing routes
from sqlmodel import Session, SQLModel, select  # Ensure select is imported

# --- Database Imports ---
from backend.database import AsyncJob, PcapSession, create_db_and_tables, engine, get_session  # Added AsyncJob, engine

# --- Storage Import ---
from backend import storage  # Import the refactored storage module

# --- Basic Logging Configuration ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- Central Exception Import ---
from backend.exceptions import JobCancelledException

logger.info(
    "Successfully imported JobCancelledException from backend.exceptions in main.py"
)

# --- Anonymizer Imports (Existing IP/MAC functionality & New DICOM V2) ---
from backend.anonymizer import (  # Use absolute import
    apply_anonymization,
    # apply_anonymization_response, # This model seems unused, consider removing if confirmed
    generate_preview,
    get_subnets,
    save_rules,
)

logger.info("Successfully imported functions from backend.anonymizer")


# --- DICOM V2 Anonymizer Import ---
from backend.DicomAnonymizer import anonymize_dicom_v2, extract_dicom_metadata # Assuming this is in project root or PYTHONPATH

# --- DICOM PCAP Extractor Import ---
from backend.dicom_pcap_extractor import extract_dicom_metadata_from_pcap

logger.info("Successfully imported extract_dicom_metadata_from_pcap from backend.dicom_pcap_extractor")


# --- Pydantic Models ---
from pydantic import BaseModel, Field
from backend.models import (
    AggregatedDicomResponse,
    DicomMetadataUpdatePayload,
    IpMacPair, # Import IpMacPair directly
    # IpMacPairListResponse, # Temporarily commented out
    MacRule,
    MacRuleInput,
    MacSettings,
    MacSettingsUpdate,
    PcapSessionResponse,
    RuleInput,
)

# --- DICOM PCAP Generation Imports ---
from backend.protocols.dicom.models import DicomPcapRequestPayload, Scene # Added Scene
from backend.protocols.dicom.scene_processor import DicomSceneProcessor, DicomSceneProcessorError # New import
from backend.protocols.dicom.utils import (
    create_associate_rq_pdu,
    create_associate_ac_pdu,
    create_dicom_dataset,
    create_p_data_tf_pdu,
)
from backend.protocols.dicom.handler import generate_dicom_session_packet_list
from scapy.all import PacketList # Ensure PacketList is imported


# --- MAC Anonymizer Imports ---
from backend.MacAnonymizer import (
    apply_mac_transformation,
    download_oui_csv,
    extract_ip_mac_pairs,
    load_mac_settings,
    MAC_SETTINGS_PATH, # May need to be re-evaluated if settings are per-session or global
    OUI_CSV_PATH,      # May need to be re-evaluated
    parse_oui_csv,
    save_mac_settings as save_mac_settings_global, # Renamed to avoid conflict if a per-session save is needed
    validate_oui_csv,
    # parse_oui_csv, # Already imported above
    # OUI_CSV_PATH, # Already imported above
)

logger.info("Successfully imported functions from backend.MacAnonymizer")


# --- Constants ---
RESOURCES_DIR = os.path.join(os.path.dirname(__file__), "resources")
os.makedirs(RESOURCES_DIR, exist_ok=True)

# --- Helper Function to Validate Session and File Existence ---
async def validate_session_and_file(
    session_id: str,
    pcap_filename: str, # Logical filename, e.g., "capture.pcap" or "anonymized.pcap"
    db_session: Session
) -> Tuple[PcapSession, Path]:
    """
    Validates that a PcapSession exists for the given ID and that the specified
    PCAP file exists within that session's directory.

    Returns the PcapSession record and the validated Path object to the file.
    Raises HTTPException (404) if the session or file is not found.
    """
    logger.debug(f"Validating session ID: {session_id}, filename: {pcap_filename}")

    pcap_session_record = db_session.get(PcapSession, session_id)
    if not pcap_session_record:
        logger.error(f"PcapSession record not found for ID: {session_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session (trace) with ID '{session_id}' not found."
        )

    try:
        # Directly use the session_id to get the file path
        validated_pcap_path = storage.get_session_filepath(session_id, pcap_filename)
    except ValueError as e: # Catch potential errors from storage layer (e.g., invalid filename)
        logger.error(f"ValueError in storage.get_session_filepath for session_id {session_id}, filename {pcap_filename}: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e: # Catch other unexpected storage errors
        logger.error(f"Unexpected error getting filepath for session {session_id}, file {pcap_filename}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error accessing session file path.")


    if not validated_pcap_path.exists() or not validated_pcap_path.is_file():
        logger.error(f"PCAP file '{pcap_filename}' not found at expected path: {validated_pcap_path} for session ID {session_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Input PCAP file '{pcap_filename}' not found for session '{pcap_session_record.name}' (ID: {session_id}). Please ensure the file exists in the correct session directory."
        )

    logger.info(f"Validated session {session_id} and file path {validated_pcap_path}")
    # Return the PcapSession record and the validated Path object
    return pcap_session_record, validated_pcap_path


# Define allowed job types
JobType = Literal[
    "transform",            # IP/MAC anonymization
    "dicom_extract",
    "dicom_anonymize_v2",
    "dicom_metadata_review", # Placeholder, not fully implemented
    "mac_oui_update",
    "mac_transform",
]

# Response model for listing jobs
class JobListResponse(BaseModel):
    id: int
    session_id: str
    trace_name: Optional[str] = None
    job_type: JobType
    status: str
    progress: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    error_message: Optional[str] = None
    output_trace_id: Optional[str] = None

# Response model for a single job's status
class JobStatusResponse(JobListResponse):
    result_data: Optional[Dict] = None

class SessionInput(BaseModel):
    session_id: str

class PcapSessionUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None

# --- Lifespan Manager ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI application starting up...")
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logger.info("SQLAlchemy engine logging level set to WARNING.")
    create_db_and_tables()
    logger.info("Checking for stale 'running' jobs from previous runs...")
    try:
        with Session(engine) as startup_session:
            stale_jobs_statement = select(AsyncJob).where(AsyncJob.status == "running")
            stale_jobs = startup_session.exec(stale_jobs_statement).all()
            if stale_jobs:
                logger.info(f"Found {len(stale_jobs)} stale 'running' jobs. Marking as 'failed'.")
                for job in stale_jobs:
                    job.status = "failed"
                    job.error_message = "Job interrupted due to backend restart."
                    job.updated_at = datetime.utcnow()
                    startup_session.add(job)
                startup_session.commit()
                logger.info("Stale jobs marked as 'failed'.")
            else:
                logger.info("No stale 'running' jobs found.")
    except Exception as e:
        logger.error(f"ERROR: Could not check/update stale jobs during startup: {e}")
        logger.exception("Exception detail during startup job check:")
    yield
    logger.info("FastAPI application shutting down...")

# --- FastAPI Application ---
app = FastAPI(lifespan=lifespan)

# --- CORS Middleware Configuration ---
# Define the origins allowed to make requests to your backend.
# Replace "http://localhost:5173" with the actual URL of your frontend if it's different.
origins = [
    "http://localhost:5173",  # Common for Vite dev server
    "http://127.0.0.1:5173", # Also common
    # Add any other origins if your frontend might be served from them
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,       # List of allowed origins
    allow_credentials=True,      # Allow cookies to be included in requests
    allow_methods=["*"],         # Allow all methods (GET, POST, PUT, DELETE, OPTIONS, etc.)
    allow_headers=["*"],         # Allow all headers
)
# --- End CORS Middleware Configuration ---


# --- Routers ---
# General router for existing endpoints
general_router = APIRouter()
# Router for DICOM protocol specific endpoints
dicom_router = APIRouter(prefix="/protocols/dicom", tags=["dicom"])


# --- DICOM Protocol Endpoints ---
@dicom_router.post("/generate-pcap", response_class=FileResponse)
async def generate_dicom_pcap_endpoint(
    payload: DicomPcapRequestPayload,
    db_session: Session = Depends(get_session) # Keep db_session if storage needs it, though not directly used here
):
    logger.info(f"Received request to generate DICOM PCAP with payload: {payload.model_dump_json(indent=2)}")

    try:
        # 1. Create A-ASSOCIATE-RQ PDU
        assoc_rq_pdu_bytes = create_associate_rq_pdu(
            calling_ae_title=payload.association_request.calling_ae_title,
            called_ae_title=payload.association_request.called_ae_title,
            application_context_name=payload.association_request.application_context_name,
            presentation_contexts_input=[pc.model_dump() for pc in payload.association_request.presentation_contexts]
        )
        logger.info(f"A-ASSOCIATE-RQ PDU created, length: {len(assoc_rq_pdu_bytes)} bytes")

        # 2. Simulate A-ASSOCIATE-AC PDU (assuming acceptance of all proposed contexts)
        presentation_context_results = []
        for pc_rq in payload.association_request.presentation_contexts:
            # Assuming the first proposed transfer syntax is accepted
            accepted_transfer_syntax = pc_rq.transfer_syntaxes[0] if pc_rq.transfer_syntaxes else "1.2.840.10008.1.2" # Default Implicit VR LE
            presentation_context_results.append({
                "id": pc_rq.id,
                "result": 0, # Acceptance
                "transfer_syntax": accepted_transfer_syntax
            })
        
        assoc_ac_pdu_bytes = create_associate_ac_pdu(
            calling_ae_title=payload.association_request.calling_ae_title, # From original RQ
            called_ae_title=payload.association_request.called_ae_title,   # Responding as this AE
            application_context_name=payload.association_request.application_context_name,
            presentation_contexts_results_input=presentation_context_results
        )
        logger.info(f"A-ASSOCIATE-AC PDU created, length: {len(assoc_ac_pdu_bytes)} bytes")

        # 3. Create P-DATA-TF PDUs for each DICOM message
        p_data_tf_pdu_bytes_list = []
        for msg_item in payload.dicom_messages:
            # Command Set
            cmd_dataset = create_dicom_dataset(msg_item.command_set.to_pydicom_dict())
            cmd_dataset.is_little_endian = True
            cmd_dataset.is_implicit_VR = True
            # Add MessageType to command dataset if not already present (pydicom might do this, but explicit is safer)
            # For C-STORE-RQ, AffectedSOPClassUID is (0000,0002), Priority (0000,0700), MessageID (0000,0110)
            # CommandField (0000,0100) is 1 for RQ, DataSetType (0000,0800)
            # pydicom's dimse_extended_negotiation and other high-level functions handle this.
            # For manual creation, ensure all necessary command fields are set.
            # For C-STORE-RQ, CommandField is 0x0001. DataSetType is 0x0000 if no dataset, 0x0101 if dataset follows.
            # For C-ECHO-RQ, CommandField is 0x0030. DataSetType is 0x0101 (no data set).
            
            # Simplified: pydicom's create_dataset_from_elements will add some tags if they are standard
            # For now, relying on the input JSON to provide necessary command elements.
            # The `create_p_data_tf_pdu` handles `is_command` flag.

            p_data_cmd_pdu_bytes = create_p_data_tf_pdu(
                dimse_dataset=cmd_dataset,
                presentation_context_id=msg_item.presentation_context_id,
                is_command=True
            )
            p_data_tf_pdu_bytes_list.append(p_data_cmd_pdu_bytes)
            logger.info(f"P-DATA-TF (Command: {msg_item.message_type}) PDU created, length: {len(p_data_cmd_pdu_bytes)} bytes")

            if msg_item.data_set:
                data_dataset = create_dicom_dataset(msg_item.data_set.to_pydicom_dict())
                data_dataset.is_little_endian = True
                data_dataset.is_implicit_VR = True
                p_data_data_pdu_bytes = create_p_data_tf_pdu(
                    dimse_dataset=data_dataset,
                    presentation_context_id=msg_item.presentation_context_id,
                    is_command=False
                )
                p_data_tf_pdu_bytes_list.append(p_data_data_pdu_bytes)
                logger.info(f"P-DATA-TF (Data for {msg_item.message_type}) PDU created, length: {len(p_data_data_pdu_bytes)} bytes")

        # 4. Generate Scapy PacketList
        network_params_dict = payload.connection_details.model_dump()
        scapy_packet_list = generate_dicom_session_packet_list(
            network_params=network_params_dict,
            associate_rq_pdu_bytes=assoc_rq_pdu_bytes,
            associate_ac_pdu_bytes=assoc_ac_pdu_bytes,
            p_data_tf_pdu_list=p_data_tf_pdu_bytes_list
            # client_isn and server_isn will use defaults from handler
        )
        logger.info(f"Scapy PacketList generated with {len(scapy_packet_list)} packets.")

        # 5. Store PCAP using storage module
        # For this test endpoint, we generate a unique ID but don't create a PcapSession DB record.
        temp_trace_id = f"temp_dicom_gen_{uuid.uuid4().hex[:8]}"
        output_pcap_filename = f"generated_dicom_{temp_trace_id}.pcap"
        
        # Ensure the base sessions directory exists (storage.py might not do this)
        # storage.SESSIONS_BASE_DIR.mkdir(parents=True, exist_ok=True) # storage.write_pcap_to_session should handle this.

        pcap_file_path: Path = storage.write_pcap_to_session(
            session_id=temp_trace_id,
            filename=output_pcap_filename,
            packets=scapy_packet_list
        )
        logger.info(f"PCAP file successfully written to: {pcap_file_path}")

        # 6. Return FileResponse
        return FileResponse(
            path=str(pcap_file_path),
            media_type="application/vnd.tcpdump.pcap",
            filename=output_pcap_filename, # Filename for the download
            # Add headers to suggest deletion after download if it's truly temporary
            # headers={"Content-Disposition": f"attachment; filename=\"{output_pcap_filename}\""}
        )

    except HTTPException as e:
        logger.error(f"HTTPException during DICOM PCAP generation: {e.detail}", exc_info=True)
        raise e
    except Exception as e:
        logger.error(f"Unexpected error during DICOM PCAP generation: {str(e)}", exc_info=True)
        # traceback.print_exc() # For more detailed console logging during debug
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate DICOM PCAP: {str(e)}"
        )

@dicom_router.post("/v2/generate-pcap-from-scene", response_class=FileResponse)
async def generate_pcap_from_scene_endpoint(
    scene_payload: Scene,
    # db_session: Session = Depends(get_session) # Not creating persistent records for this type of generation
):
    logger.info(f"Received request for /v2/protocols/dicom/generate-pcap-from-scene for scene: {scene_payload.scene_id}")
    try:
        processor = DicomSceneProcessor(scene=scene_payload) # Uses default asset_templates_base_path
        
        scapy_packet_list: PacketList = processor.process_scene()
        
        if not scapy_packet_list:
            logger.warning(f"Scene processing for scene '{scene_payload.scene_id}' resulted in an empty packet list.")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Scene processing resulted in no packets. Please check scene definition."
            )

        logger.info(f"Scene '{scene_payload.scene_id}' processed successfully. Generated {len(scapy_packet_list)} packets.")

        temp_trace_id = f"scene_gen_{uuid.uuid4().hex[:12]}"
        # Sanitize scene_id for filename, take first 16 chars, replace non-alphanum with underscore
        safe_scene_id_part = "".join(c if c.isalnum() else "_" for c in scene_payload.scene_id[:16])
        output_pcap_filename = f"scene_{safe_scene_id_part}_{temp_trace_id[:8]}.pcap"

        pcap_file_path: Path = storage.write_pcap_to_session(
            session_id=temp_trace_id, # This creates a temporary session directory
            filename=output_pcap_filename,
            packets=scapy_packet_list
        )
        logger.info(f"Temporary PCAP file for scene '{scene_payload.scene_id}' written to: {pcap_file_path}")

        return FileResponse(
            path=str(pcap_file_path),
            media_type="application/vnd.tcpdump.pcap",
            filename=output_pcap_filename,
        )

    except DicomSceneProcessorError as e:
        logger.error(f"Error during DICOM scene processing for scene '{scene_payload.scene_id}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error processing DICOM scene: {str(e)}"
        )
    except HTTPException as e: # Re-raise known HTTPExceptions
        raise e
    except Exception as e:
        logger.error(f"Unexpected error during scene-based DICOM PCAP generation for scene '{scene_payload.scene_id}': {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate PCAP from scene: {str(e)}"
        )


# --- General API Endpoints (moved to general_router) ---

@general_router.post("/upload", response_model=PcapSession)
async def upload(
    name: str = Form(...),
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    db_session: Session = Depends(get_session),
):
    session_id = storage.create_new_session_id()
    safe_original_filename = os.path.basename(file.filename or "unknown.pcap")
    logger.info(f"Processing upload for new session: {session_id}, name: {name}")
    try:
        pcap_path_obj = storage.store_uploaded_pcap(session_id, file, "capture.pcap")
        pcap_path = str(pcap_path_obj)
        logger.info(f"SUCCESS: File successfully saved to: {pcap_path}")
    except Exception as e:
        logger.error(f"ERROR: Failed to save uploaded file for session {session_id}. Error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {e}")

    rules_path_obj = storage.get_session_filepath(session_id, "rules.json")
    rules_path = str(rules_path_obj)
    upload_time = datetime.utcnow()
    db_pcap_session = PcapSession(
        id=session_id, name=name, description=description,
        original_filename=safe_original_filename, upload_timestamp=upload_time,
        pcap_path=pcap_path, rules_path=rules_path, updated_at=upload_time,
    )
    db_session.add(db_pcap_session)
    try:
        db_session.commit()
        db_session.refresh(db_pcap_session)
        logger.info(f"SUCCESS: Session metadata saved to DB for ID: {session_id}")
    except Exception as e:
        db_session.rollback()
        try:
            if os.path.exists(pcap_path): os.remove(pcap_path)
        except OSError as rm_err:
            logger.warning(f"Warning: Failed to clean up file {pcap_path} after DB error: {rm_err}")
        logger.error(f"Database commit failed for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save session metadata: {e}")
    try:
        storage.store_rules(session_id, [])
    except Exception as e:
        logger.warning(f"Warning: Failed to create initial empty rules file for {session_id}: {e}")
    return db_pcap_session

@general_router.get("/sessions", response_model=List[PcapSessionResponse])
async def list_sessions_endpoint(db_session: Session = Depends(get_session)): # Renamed for clarity
    logger.info("Request received for GET /sessions")
    all_pcap_responses: List[PcapSessionResponse] = []
    try:
        pcap_session_statement = select(PcapSession).order_by(PcapSession.upload_timestamp.desc())
        db_pcap_sessions = db_session.exec(pcap_session_statement).all()
        logger.info(f"Found {len(db_pcap_sessions)} PcapSession records.")
        for session in db_pcap_sessions:
            file_type_for_response = "original"
            derived_from_session_id_for_response = None
            source_job_id_for_response = None
            if session.async_job_id:
                source_job_id_for_response = session.async_job_id
                derived_from_session_id_for_response = session.original_session_id
                job = db_session.get(AsyncJob, session.async_job_id)
                if job:
                    if job.job_type == "transform": file_type_for_response = "ip_mac_anonymized"
                    elif job.job_type == "mac_transform": file_type_for_response = "mac_transformed"
                    elif job.job_type == "dicom_anonymize_v2": file_type_for_response = "dicom_v2_anonymized"
                    else:
                        logger.warning(f"Unmapped job_type '{job.job_type}' for PcapSession {session.id}. Defaulting to 'derived'.")
                        file_type_for_response = "derived"
                else:
                    logger.warning(f"PcapSession {session.id} has async_job_id {session.async_job_id} but job not found. Defaulting to 'derived_job_info_missing'.")
                    file_type_for_response = "derived_job_info_missing"
            
            actual_pcap_filename = os.path.basename(session.pcap_path) if session.pcap_path else session.original_filename
            # If it's a derived trace and pcap_path is just the original session ID (old bug), try to infer filename
            if session.original_session_id and session.pcap_path == session.original_session_id:
                 # This logic might need refinement based on how derived filenames are stored/named
                if file_type_for_response == "ip_mac_anonymized": actual_pcap_filename = "anonymized_capture.pcap" # Example
                elif file_type_for_response == "mac_transformed": actual_pcap_filename = "mac_transformed.pcap" # Example
                elif file_type_for_response == "dicom_v2_anonymized": actual_pcap_filename = "dicom_anonymized_v2.pcap" # Example


            response_item = PcapSessionResponse(
                id=session.id, name=session.name, description=session.description,
                original_filename=session.original_filename, upload_timestamp=session.upload_timestamp,
                # pcap_path=session.pcap_path, rules_path=session.rules_path, # Internal paths omitted from response
                updated_at=session.updated_at, is_transformed=session.is_transformed,
                original_session_id=session.original_session_id, async_job_id=session.async_job_id,
                file_type=file_type_for_response,
                derived_from_session_id=derived_from_session_id_for_response,
                source_job_id=source_job_id_for_response,
                actual_pcap_filename=actual_pcap_filename,
            )
            all_pcap_responses.append(response_item)
        all_pcap_responses.sort(key=lambda x: x.upload_timestamp, reverse=True)
        logger.info(f"Returning {len(all_pcap_responses)} file entries.")
        return all_pcap_responses
    except Exception as e:
        logger.error(f"Error fetching sessions: {e}")
        logger.exception("Exception detail during /sessions fetch:")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve file list: {e}")

@general_router.put("/sessions/{session_id}", response_model=PcapSession)
async def update_session(
    session_id: str, session_update: PcapSessionUpdate, db_session: Session = Depends(get_session)
):
    logger.info(f"Request received for PUT /sessions/{session_id}")
    db_pcap_session = db_session.get(PcapSession, session_id)
    if not db_pcap_session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    update_data = session_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")
    logger.info(f"Updating session {session_id} with data: {update_data}")
    needs_update = False
    for key, value in update_data.items():
        if hasattr(db_pcap_session, key):
            setattr(db_pcap_session, key, value)
            needs_update = True
    if needs_update:
        db_pcap_session.updated_at = datetime.utcnow()
        db_session.add(db_pcap_session)
        try:
            db_session.commit()
            db_session.refresh(db_pcap_session)
            logger.info(f"Session {session_id} updated successfully.")
        except Exception as e:
            db_session.rollback()
            logger.error(f"Database commit failed for session {session_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to update session metadata: {e}")
    return db_pcap_session

@general_router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, db_session: Session = Depends(get_session)):
    logger.info(f"Request received for DELETE /sessions/{session_id}")
    pcap_session = db_session.get(PcapSession, session_id)
    if not pcap_session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    try:
        # Determine the physical directory to delete.
        # If it's a derived trace, its record might point to files in original_session_id's dir.
        # However, the PcapSession record being deleted is 'session_id'.
        # If 'session_id' is an original trace, its directory is 'session_id'.
        # If 'session_id' is a derived trace, it doesn't have its own physical directory.
        # Deleting a derived trace record should NOT delete the original's directory.
        # Only delete directory if pcap_session.original_session_id is None (it's an original trace)
        if pcap_session.original_session_id is None:
            session_dir_path = storage.get_session_dir(session_id)
            if session_dir_path.exists() and session_dir_path.is_dir():
                shutil.rmtree(session_dir_path)
                logger.info(f"Deleted session directory: {str(session_dir_path)} for original trace {session_id}")
            else:
                logger.warning(f"Session directory not found or not a directory for original trace {session_id}: {str(session_dir_path)}")
        else:
            logger.info(f"Session {session_id} is a derived trace. Its database record will be deleted, but no physical directory will be removed as its files reside in {pcap_session.original_session_id}'s directory.")

    except Exception as e:
        logger.warning(f"Warning during directory handling for session {session_id}. Error: {e}")
        logger.exception(f"Exception during session directory deletion for {session_id}:")

    # Delete related AsyncJob if it produced this session
    if pcap_session.async_job_id:
        job_to_delete = db_session.get(AsyncJob, pcap_session.async_job_id)
        if job_to_delete and job_to_delete.output_trace_id == session_id:
            # Potentially delete the job too, or just nullify its output_trace_id
            # For now, let's just log. Deleting jobs might be a separate concern.
            logger.info(f"Session {session_id} was an output of job {pcap_session.async_job_id}. Consider job cleanup if necessary.")

    db_session.delete(pcap_session)
    try:
        db_session.commit()
        logger.info(f"PcapSession record {session_id} deleted successfully from database.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        db_session.rollback()
        logger.error(f"Database commit failed for deleting PcapSession record {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete session from database: {e}")

# --- Background Task Definitions ---

async def run_apply_anonymization(
    job_id: int,
    input_session_id: str, # Renamed for clarity - this is the ID of the trace to read from
    input_pcap_filename: str, # Filename within that directory
):
    with Session(engine) as db_session:
        job = db_session.get(AsyncJob, job_id)
        if not job:
            logger.error(f"Job {job_id} not found for IP/MAC anonymization task.")
            return

        if job.status == "cancelling" or job.stop_requested:
            job.status = "cancelled"
            job.error_message = "Cancelled before start."
            job.updated_at = datetime.utcnow()
            db_session.add(job)
            db_session.commit()
            logger.info(f"Job {job_id} (IP/MAC Anonymization) cancelled before start.")
            return

        job.status = "running"
        job.progress = 0 # Initialize progress
        job.updated_at = datetime.utcnow()
        db_session.add(job)
        db_session.commit()
        logger.info(f"Job {job_id} (IP/MAC Anonymization) for input session {input_session_id}, file '{input_pcap_filename}' started.")

        # Define callbacks for anonymizer
        def progress_callback(progress_percentage: int):
            with Session(engine) as cb_session: # Use a new session for thread safety if anonymizer runs in a separate thread
                cb_job = cb_session.get(AsyncJob, job_id)
                if cb_job:
                    cb_job.progress = progress_percentage
                    cb_job.updated_at = datetime.utcnow()
                    cb_session.add(cb_job)
                    cb_session.commit()
                    logger.debug(f"Job {job_id} progress: {progress_percentage}%")

        def check_stop_requested() -> bool:
            with Session(engine) as cb_session:
                cb_job = cb_session.get(AsyncJob, job_id)
                if cb_job and (cb_job.stop_requested or cb_job.status == "cancelling"):
                    logger.info(f"Stop request detected for job {job_id} by check_stop_requested.")
                    return True
                return False

        new_output_trace_id = storage.create_new_session_id()
        output_pcap_filename = f"anonymized_ip_mac_{new_output_trace_id[:8]}.pcap" # Example filename

        try:
            # Call the synchronous anonymizer.apply_anonymization without await
            # It will create the output directory if it doesn't exist via storage.write_pcap_to_session
            anonymization_result = apply_anonymization(
                input_trace_id=input_session_id, # Use the input session ID for reading
                input_pcap_filename=input_pcap_filename,
                new_output_trace_id=new_output_trace_id, # Pass the new ID for the output directory/trace
                output_pcap_filename=output_pcap_filename,
                progress_callback=progress_callback,
                check_stop_requested=check_stop_requested
            )

            # Create a new PcapSession record for the anonymized output
            original_session_record = db_session.get(PcapSession, input_session_id) # Get original to copy name etc.
            original_session_name = original_session_record.name if original_session_record else "Unknown Original"

            new_pcap_session = PcapSession(
                id=new_output_trace_id, # Use the ID from anonymization_result which should match new_output_trace_id
                name=f"IP/MAC Anonymized - {original_session_name}",
                description=f"Derived from '{original_session_name}' (ID: {input_session_id}) by IP/MAC anonymization job {job_id}.",
                original_filename=output_pcap_filename, # The name of the file within its session dir
                upload_timestamp=datetime.utcnow(),
                pcap_path=str(anonymization_result["full_output_path"]), # Full path to the new pcap
                rules_path=str(storage.get_session_filepath(new_output_trace_id, "rules.json")), # Path for potential rules copy
                updated_at=datetime.utcnow(),
                is_transformed=True,
                original_session_id=input_session_id, # Link to the original session
                async_job_id=job_id
            )
            db_session.add(new_pcap_session)

            # Optionally, copy rules from original session to new session
            try:
                original_rules_path = storage.get_session_filepath(input_session_id, "rules.json")
                if original_rules_path.exists():
                    new_rules_path = storage.get_session_filepath(new_output_trace_id, "rules.json")
                    # Ensure target directory exists (storage.write_pcap_to_session should have made new_output_trace_id dir)
                    new_rules_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original_rules_path, new_rules_path)
                    logger.info(f"Copied rules from {input_session_id} to new session {new_output_trace_id}")
            except Exception as copy_err:
                logger.warning(f"Could not copy rules for job {job_id} from {input_session_id} to {new_output_trace_id}: {copy_err}")


            job.status = "completed"
            job.progress = 100
            job.output_trace_id = new_pcap_session.id
            logger.info(f"Job {job_id} (IP/MAC Anonymization) completed. Output trace ID: {new_pcap_session.id}")

        except JobCancelledException:
            job.status = "cancelled"
            job.error_message = "Job execution was cancelled by user."
            logger.info(f"Job {job_id} (IP/MAC Anonymization) was cancelled during execution.")
        except FileNotFoundError as e:
            job.status = "failed"
            job.error_message = f"File not found during IP/MAC anonymization: {e}"
            logger.error(f"Job {job_id} (IP/MAC Anonymization) failed for input {input_session_id}: {e}", exc_info=True)
        except Exception as e:
            job.status = "failed"
            job.error_message = f"An unexpected error occurred during IP/MAC anonymization: {str(e)}"
            logger.error(f"Job {job_id} (IP/MAC Anonymization) failed for input {input_session_id}: {e}", exc_info=True)
            # traceback.print_exc() # For more detailed console logging during debug
        finally:
            job.updated_at = datetime.utcnow()
            db_session.add(job)
            db_session.commit()

async def run_mac_transform(
    job_id: int,
    input_session_id: str, # Renamed for clarity
    input_pcap_filename: str, # Renamed for clarity
):
    with Session(engine) as db_session:
        job = db_session.get(AsyncJob, job_id)
        if not job: logger.error(f"Job {job_id} not found."); return
        if job.status == "cancelling":
            job.status = "cancelled"; job.error_message = "Cancelled before start."; job.updated_at = datetime.utcnow()
            db_session.add(job); db_session.commit(); logger.info(f"Job {job_id} cancelled before start."); return
        job.status = "running"; job.updated_at = datetime.utcnow(); db_session.add(job); db_session.commit()
        logger.info(f"Job {job_id} (MAC Transform) for input session {input_session_id}, file {input_pcap_filename} started.")
        try:
            # apply_mac_transformation needs to be updated to accept input_trace_id, new_output_trace_id etc.
            # For now, assuming it's called correctly internally or we adapt the call here.
            # Let's assume apply_mac_transformation is adapted or we create a wrapper.
            # Placeholder: Assume apply_mac_transformation handles creating the new trace ID and saving.
            # It should return the new PcapSession record.
            # We need to generate the new ID here to pass it.
            new_output_trace_id = storage.create_new_session_id()
            output_pcap_filename = f"mac_transformed_{new_output_trace_id[:8]}.pcap" # Example filename

            # TODO: Adapt the call to apply_mac_transformation or the function itself
            # Assuming apply_mac_transformation is adapted like apply_anonymization:
            mac_transform_result = apply_mac_transformation( # This function needs adaptation
                input_trace_id=input_session_id,
            input_pcap_filename=input_pcap_filename,
            new_output_trace_id=new_output_trace_id,
            output_pcap_filename=output_pcap_filename,
            # Pass callbacks if apply_mac_transformation supports them
            # progress_callback=progress_callback, # TODO: Implement progress/cancel in apply_mac_transformation if needed
            # check_stop_requested=check_stop_requested
        )

        # Create PcapSession record after transformation is successful
            # This part needs clarification based on apply_mac_transformation's actual signature/behavior.
            # For now, let's assume we need to create it here based on the result dict.
            original_session_record = db_session.get(PcapSession, input_session_id)
            original_session_name = original_session_record.name if original_session_record else "Unknown Original"

            new_pcap_session = PcapSession(
                id=new_output_trace_id,
                name=f"MAC Transformed - {original_session_name}",
                description=f"Derived from '{original_session_name}' (ID: {input_session_id}) by MAC transformation job {job_id}.",
                original_filename=output_pcap_filename,
                upload_timestamp=datetime.utcnow(),
                pcap_path=str(mac_transform_result["full_output_path"]),
                rules_path=str(storage.get_session_filepath(new_output_trace_id, "mac_rules.json")), # Path for potential rules copy
                updated_at=datetime.utcnow(),
                is_transformed=True,
                original_session_id=input_session_id,
                async_job_id=job_id
            )
            db_session.add(new_pcap_session)
            # Optionally copy mac_rules.json if needed

            job.status = "completed"; job.progress = 100; job.output_trace_id = new_pcap_session.id
            logger.info(f"Job {job_id} MAC transform completed. Output trace ID: {new_pcap_session.id}")
        except JobCancelledException:
            job.status = "cancelled"; job.error_message = "Job execution was cancelled."
        except FileNotFoundError as e:
            job.status = "failed"; job.error_message = f"File not found: {e}"
        except Exception as e:
            job.status = "failed"; job.error_message = f"Error during MAC transformation: {str(e)}"
            logger.error(f"Job {job_id} MAC transform failed for input {input_session_id}: {e}", exc_info=True)
        finally:
            job.updated_at = datetime.utcnow(); db_session.add(job); db_session.commit()

async def run_dicom_extract(
    job_id: int,
    input_session_id: str, # Renamed for clarity
    input_pcap_filename: str, # Renamed for clarity
):
    with Session(engine) as db_session:
        job = db_session.get(AsyncJob, job_id)
        if not job: logger.error(f"Job {job_id} not found."); return
        if job.status == "cancelling":
            job.status = "cancelled"; job.error_message = "Cancelled before start."; job.updated_at = datetime.utcnow()
            db_session.add(job); db_session.commit(); logger.info(f"Job {job_id} cancelled before start."); return
        job.status = "running"; job.updated_at = datetime.utcnow(); db_session.add(job); db_session.commit()
        logger.info(f"Job {job_id} (DICOM Extract) for input session {input_session_id}, file {input_pcap_filename} started.")
        try:
            # extract_dicom_metadata_from_pcap needs the input session ID and filename
            # It should use storage.read_pcap_from_session(input_session_id, input_pcap_filename) internally
            # Assuming extract_dicom_metadata_from_pcap is adapted or called correctly.
            # TODO: Verify/Adapt extract_dicom_metadata_from_pcap if needed.
            # It should return the result data to be stored in the job.
            extracted_data = await extract_dicom_metadata_from_pcap(
                session_id=input_session_id, # Pass the correct input session ID
                pcap_file_name=input_pcap_filename,
                job_id=job_id, # For cancellation check
                db_session=db_session # For job progress updates
            )
            job.result_data = extracted_data # Store the result directly in the job
            job.status = "completed"; job.progress = 100
            logger.info(f"Job {job_id} DICOM extraction completed.")
        except JobCancelledException:
            job.status = "cancelled"; job.error_message = "Job execution was cancelled."
        except FileNotFoundError as e:
            job.status = "failed"; job.error_message = f"File not found: {e}"
        except Exception as e:
            job.status = "failed"; job.error_message = f"Error during DICOM extraction: {str(e)}"
            logger.error(f"Job {job_id} DICOM extraction failed for input {input_session_id}: {e}", exc_info=True)
        finally:
            job.updated_at = datetime.utcnow(); db_session.add(job); db_session.commit()

async def run_dicom_anonymize_v2(
    job_id: int,
    input_session_id: str, # Renamed for clarity
    input_pcap_filename: str, # Renamed for clarity
    metadata_overrides_json_string: Optional[str], # JSON string of overrides
):
    with Session(engine) as db_session:
        job = db_session.get(AsyncJob, job_id)
        if not job: logger.error(f"Job {job_id} not found."); return
        if job.status == "cancelling":
            job.status = "cancelled"; job.error_message = "Cancelled before start."; job.updated_at = datetime.utcnow()
            db_session.add(job); db_session.commit(); logger.info(f"Job {job_id} cancelled before start."); return
        job.status = "running"; job.updated_at = datetime.utcnow(); db_session.add(job); db_session.commit()
        logger.info(f"Job {job_id} (DICOM Anonymize V2) for input session {input_session_id}, file {input_pcap_filename} started.")

        metadata_overrides: Optional[Dict[str, DicomMetadataUpdatePayload]] = None
        if metadata_overrides_json_string:
            try:
                overrides_raw = json.loads(metadata_overrides_json_string)
                metadata_overrides = {k: DicomMetadataUpdatePayload(**v) for k, v in overrides_raw.items()}
            except json.JSONDecodeError:
                job.status = "failed"; job.error_message = "Invalid JSON in metadata_overrides."
                job.updated_at = datetime.utcnow(); db_session.add(job); db_session.commit()
                logger.error(f"Job {job_id} failed due to invalid metadata_overrides JSON.")
                return
        try:
            # anonymize_dicom_v2 needs input session ID and filename.
            # It will create a new PcapSession for the output.
            # TODO: Verify/Adapt anonymize_dicom_v2 if needed.
            # Assuming it's adapted like apply_anonymization:
            new_output_trace_id = storage.create_new_session_id()
            output_pcap_filename = f"dicom_anonymized_v2_{new_output_trace_id[:8]}.pcap" # Example filename

            # Assuming anonymize_dicom_v2 is adapted to take new_output_trace_id etc.
            # and returns a result dict or the new PcapSession record.
            # Call anonymize_dicom_v2 (assuming its signature matches the pattern)
            # It returns device_data, verification_summary, not the PcapSession record
            device_data, verification_summary = await anonymize_dicom_v2(
                input_trace_id=input_session_id,
                input_pcap_filename=input_pcap_filename,
                new_output_trace_id=new_output_trace_id,
                output_pcap_filename=output_pcap_filename,
                metadata_overrides=metadata_overrides, # Pass parsed overrides
                debug_mode=False, # Add missing argument, default to False
                # Pass callbacks if supported by anonymize_dicom_v2
                # progress_callback=progress_callback, # TODO: Implement progress/cancel in anonymize_dicom_v2 if needed
                # check_stop_requested=check_stop_requested,
                # db_session=db_session, # Pass session if needed internally by anonymize_dicom_v2
                # job_id=job_id # Pass job_id if needed internally by anonymize_dicom_v2
            )

            # Create the PcapSession record for the new trace
            original_session_record = db_session.get(PcapSession, input_session_id)
            original_session_name = original_session_record.name if original_session_record else "Unknown Original"
            output_full_path = storage.get_session_filepath(new_output_trace_id, output_pcap_filename) # Get the full path

            new_pcap_session = PcapSession(
                id=new_output_trace_id,
                name=f"DICOM Anonymized V2 - {original_session_name}",
                description=f"Derived from '{original_session_name}' (ID: {input_session_id}) by DICOM Anonymization V2 job {job_id}.",
                original_filename=output_pcap_filename,
                upload_timestamp=datetime.utcnow(),
                pcap_path=str(output_full_path),
                rules_path=None, # DICOM V2 doesn't use separate rules files in the same way
                updated_at=datetime.utcnow(),
                is_transformed=True,
                original_session_id=input_session_id,
                async_job_id=job_id
            )
            db_session.add(new_pcap_session)
            # Optionally store device_data or verification_summary if needed, e.g., in job.result_data
            # job.result_data = {"devices": device_data, "verification": verification_summary}

            job.status = "completed"; job.progress = 100; job.output_trace_id = new_pcap_session.id
            logger.info(f"Job {job_id} DICOM Anonymize V2 completed. Output trace ID: {new_pcap_session.id}")
        except JobCancelledException:
            job.status = "cancelled"; job.error_message = "Job execution was cancelled."
        except FileNotFoundError as e:
            job.status = "failed"; job.error_message = f"File not found: {e}"
        except Exception as e:
            job.status = "failed"; job.error_message = f"Error during DICOM Anonymization V2: {str(e)}"
            logger.error(f"Job {job_id} DICOM Anonymization V2 failed for input {input_session_id}: {e}", exc_info=True)
        finally:
            job.updated_at = datetime.utcnow(); db_session.add(job); db_session.commit()


# --- IP/MAC Anonymization Endpoints (moved to general_router) ---
@general_router.get("/subnets/{session_id_from_frontend}")
async def get_subnets_endpoint(
    session_id_from_frontend: str,
    db_session: Session = Depends(get_session),
    pcap_filename: Optional[str] = Query("capture.pcap", description="Logical filename of the PCAP to analyze")
):
    logger.info(f"Subnet request for session_id: {session_id_from_frontend}, logical_file: {pcap_filename}")
    try:
        # Use the new helper function for validation
        pcap_session_record, _ = await validate_session_and_file(
            session_id=session_id_from_frontend,
            pcap_filename=pcap_filename,
            db_session=db_session
        )
    except HTTPException as e:
        logger.error(f"Error validating session/file for subnet extraction: {e.detail}")
        raise e # Propagate 404 or other validation errors

    logger.info(f"Extracting subnets for session {pcap_session_record.name} ({session_id_from_frontend}), file {pcap_filename}.")
    try:
        # Call get_subnets directly with the validated session_id
        subnets = get_subnets(session_id_from_frontend, pcap_filename)
        return subnets
    except FileNotFoundError: # Should be caught by validate_session_and_file, but keep as fallback
        raise HTTPException(status_code=404, detail=f"PCAP file '{pcap_filename}' not found for session '{pcap_session_record.name}'.")
    except Exception as e:
        logger.error(f"Error extracting subnets: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to extract subnets: {e}")

@general_router.put("/rules")
async def rules_endpoint(input: RuleInput, db_session: Session = Depends(get_session)):
    session_id = input.session_id # Use the ID directly
    logger.info(f"Request received for PUT /rules for session_id: {session_id}")

    # Validate the session exists
    pcap_session_record = db_session.get(PcapSession, session_id)
    if not pcap_session_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session (trace) with ID '{session_id}' not found, cannot save rules.")

    # No need to resolve physical directory ID anymore
    logger.info(f"Subnet rules for session {session_id} will be saved in its directory.")
    try:
        rules_as_dict_list = [rule.model_dump(by_alias=False) for rule in input.rules]
        # Call save_rules directly with the session_id
        result = save_rules(session_id, rules_as_dict_list) # save_rules uses storage.store_rules
        # Update timestamp of the session
        pcap_session_record.updated_at = datetime.utcnow()
        db_session.add(pcap_session_record)
        db_session.commit()
        logger.info(f"Updated 'updated_at' for PcapSession {session_id} after saving rules.")
        return result
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error saving rules for session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save subnet rules: {e}")

@general_router.get("/preview/{session_id_from_frontend}")
async def preview_endpoint(
    session_id_from_frontend: str,
    pcap_filename: Optional[str] = Query("capture.pcap", description="Logical filename of PCAP to preview"),
    db_session: Session = Depends(get_session),
):
    logger.info(f"Preview request for session_id: {session_id_from_frontend}, logical_file: {pcap_filename}")
    try:
        # Use the new helper function for validation
        pcap_session_record, validated_pcap_path = await validate_session_and_file(
            session_id=session_id_from_frontend,
            pcap_filename=pcap_filename,
            db_session=db_session
        )
    except HTTPException as e:
        logger.error(f"Error validating session/file for preview: {e.detail}")
        raise e # Propagate 404 or other validation errors

    logger.info(f"Generating preview for {pcap_session_record.name} ({session_id_from_frontend}), file {validated_pcap_path}.")
    try:
        # Call generate_preview directly with the validated session_id and filename
        preview_data = generate_preview(session_id_from_frontend, pcap_filename)
        return preview_data
    except FileNotFoundError: # Should be caught by validate_session_and_file
        raise HTTPException(status_code=404, detail=f"PCAP file '{pcap_filename}' not found for session '{pcap_session_record.name}'.")
    except Exception as e:
        logger.error(f"Error generating preview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate preview: {e}")

@general_router.post("/apply", response_model=AsyncJob)
async def apply_endpoint(
    background_tasks: BackgroundTasks, 
    session_id_from_frontend: str = Form(..., alias="session_id"),
    input_pcap_filename: str = Form(...),
    db_session: Session = Depends(get_session)
):
    logger.info(f"Apply IP/MAC anonymization request for session_id: {session_id_from_frontend}, input_pcap_filename: {input_pcap_filename}")
    try:
        # Validate input session and file exist
        pcap_session_record, _ = await validate_session_and_file(
            session_id=session_id_from_frontend,
            pcap_filename=input_pcap_filename,
            db_session=db_session
        )
    except HTTPException as e:
        raise e # Propagate 404 or other validation errors

    # Load rules directly from the input session's directory
    rules = storage.get_rules(session_id_from_frontend)
    if rules is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Anonymization rules not found for session '{pcap_session_record.name}'. Please define rules first.")

    # Create the job, associating it with the input session ID
    new_job = AsyncJob(
        session_id=session_id_from_frontend, # Job is associated with the input trace
        trace_name=pcap_session_record.name, # User-facing name of the input trace
        job_type="transform", status="pending", created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    )
    db_session.add(new_job)
    try:
        db_session.commit(); db_session.refresh(new_job)
        logger.info(f"Created AsyncJob {new_job.id} for IP/MAC anonymization of {pcap_session_record.name} ({session_id_from_frontend})/{input_pcap_filename}.")
    except Exception as e:
        db_session.rollback()
        logger.error(f"DB error creating AsyncJob for IP/MAC anonymization: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create anonymization job.")

    # Pass the input session ID directly to the background task
    background_tasks.add_task(
        run_apply_anonymization,
        job_id=new_job.id,
        input_session_id=session_id_from_frontend, # Pass the input session ID
        input_pcap_filename=input_pcap_filename
    )
    return new_job

# --- MAC Anonymization Endpoints (moved to general_router) ---

@general_router.get("/mac/vendors")
async def get_mac_vendors_endpoint():
    """
    Retrieves the MAC address vendor lookup data from the OUI CSV file.
    """
    logger.info("Request received for GET /mac/vendors")
    try:
        # OUI_CSV_PATH is imported from MacAnonymizer as a string. Convert to Path object for .exists()
        oui_csv_file_path_obj = Path(OUI_CSV_PATH)

        if not oui_csv_file_path_obj.exists():
            logger.error(f"OUI CSV file not found at expected path: {oui_csv_file_path_obj}")
            # Attempt to download it if missing? Or just return error?
            # For now, return error. OUI update is a separate job.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"OUI data file not found. Please run the OUI update process."
            )

        # parse_oui_csv expects a string path, so we pass the original OUI_CSV_PATH (string)
        vendor_data = parse_oui_csv(OUI_CSV_PATH) # Function from MacAnonymizer
        if not vendor_data:
             logger.warning(f"OUI CSV file at {oui_csv_file_path_obj} was parsed but resulted in empty data.")
             # Return empty list if parsed data is empty
             return []

        # Extract unique vendor names (values) and sort them
        unique_vendor_names = sorted(list(set(vendor_data.values())))

        logger.info(f"Successfully parsed OUI data from {OUI_CSV_PATH}. Returning {len(unique_vendor_names)} unique vendor names.")
        return unique_vendor_names # Return the sorted list of names
    except FileNotFoundError: # Should be caught by the explicit check, but good fallback
         raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"OUI data file not found. Please run the OUI update process."
            )
    except Exception as e:
        logger.error(f"Error parsing OUI data file {OUI_CSV_PATH}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load or parse MAC vendor data: {str(e)}"
        )

@general_router.get("/mac/vendors/{vendor_name}/oui", response_model=Dict[str, Optional[str]])
async def get_oui_for_vendor_endpoint(vendor_name: str):
    """
    Retrieves the OUI for a specific vendor name.
    Performs a case-insensitive search.
    """
    logger.info(f"Request received for GET /mac/vendors/{vendor_name}/oui")
    try:
        oui_csv_file_path_obj = Path(OUI_CSV_PATH)
        if not oui_csv_file_path_obj.exists():
            logger.error(f"OUI CSV file not found at {OUI_CSV_PATH} for OUI lookup.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="OUI data file not found. Please update OUI list via settings."
            )

        # oui_map is OUI_prefix -> Vendor Name
        oui_map = parse_oui_csv(OUI_CSV_PATH)
        if not oui_map:
            logger.warning(f"OUI map parsed from {OUI_CSV_PATH} is empty for OUI lookup.")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"OUI data is empty or could not be parsed.")

        normalized_input_vendor = vendor_name.strip().upper()
        
        # Iterate through the OUI map to find the vendor (case-insensitive)
        for oui_prefix, name_from_csv in oui_map.items():
            if name_from_csv.strip().upper() == normalized_input_vendor:
                logger.info(f"Found OUI '{oui_prefix}' for vendor '{vendor_name}' (normalized: '{normalized_input_vendor}')")
                return {"oui": oui_prefix}
        
        logger.warning(f"OUI not found for vendor '{vendor_name}' (normalized: '{normalized_input_vendor}') after checking {len(oui_map)} entries.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"OUI not found for vendor '{vendor_name}'.")

    except FileNotFoundError: # Should be caught by explicit check
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OUI data file not found.")
    except Exception as e:
        logger.error(f"Error during OUI lookup for vendor '{vendor_name}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to lookup OUI for vendor '{vendor_name}': {str(e)}"
        )

@general_router.get("/mac/settings", response_model=MacSettings)
async def get_mac_settings_endpoint(db_session: Session = Depends(get_session)):
    # MAC settings are currently global, not per-session.
    # This endpoint might need re-evaluation if settings become session-specific.
    settings = load_mac_settings() # From MacAnonymizer.py (global settings file)
    if not settings:
        # Provide default settings if file doesn't exist or is invalid
        logger.warning("MAC settings file not found or invalid, returning default.")
        return MacSettings(csv_url="https://standards-oui.ieee.org/oui/oui.csv", last_updated=None)
    return settings

@general_router.put("/mac/settings", response_model=MacSettings)
async def update_mac_settings_endpoint(update: MacSettingsUpdate, db_session: Session = Depends(get_session)):
    # Global settings update
    try:
        updated_settings = save_mac_settings_global({"csv_url": update.csv_url}) # save_mac_settings_global from MacAnonymizer
        return updated_settings
    except Exception as e:
        logger.error(f"Failed to update MAC settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update MAC settings: {str(e)}")

@general_router.post("/mac/update_oui_csv", response_model=AsyncJob)
async def update_oui_csv_endpoint(
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(get_session)
):
    # This job is global, not tied to a specific session_id for its operation,
    # but we need a placeholder or a way to represent global jobs if AsyncJob.session_id is mandatory.
    # For now, let's use a conceptual "global_mac_settings" as session_id for the job.
    # This might need a dedicated field in AsyncJob or a convention.
    # Rule 5: "AsyncJob.session_id field SHOULD store the actual_physical_directory_id"
    # This doesn't directly apply here as it's not a trace-specific operation.
    # Let's use a fixed dummy session_id for the job record for now.
    # A better approach might be to allow nullable session_id for certain job_types.
    global_mac_job_session_id = "global_mac_oui_update_job" # Conceptual ID

    new_job = AsyncJob(
        session_id=global_mac_job_session_id, # Placeholder
        trace_name="OUI CSV Update",
        job_type="mac_oui_update", status="pending", created_at=datetime.utcnow(), updated_at=datetime.utcnow()
    )
    db_session.add(new_job); db_session.commit(); db_session.refresh(new_job)
    logger.info(f"Created AsyncJob {new_job.id} for OUI CSV update.")
    
    async def run_update_oui_task(job_id: int): # Inner task for global operation
        with Session(engine) as task_db_session:
            job = task_db_session.get(AsyncJob, job_id)
            if not job: return
            job.status = "running"; task_db_session.commit()
            try:
                await download_oui_csv() # This function in MacAnonymizer updates the global file
                job.status = "completed"; job.progress = 100
            except Exception as e:
                job.status = "failed"; job.error_message = str(e)
                logger.error(f"OUI CSV update job {job.id} failed: {e}", exc_info=True)
            finally:
                job.updated_at = datetime.utcnow(); task_db_session.add(job); task_db_session.commit()

    background_tasks.add_task(run_update_oui_task, job_id=new_job.id)
    return new_job

# Updated response_model to List[IpMacPair] (using the direct import)
@general_router.get("/mac/ip-mac-pairs/{session_id_from_frontend}", response_model=List[IpMacPair])
async def get_ip_mac_pairs_endpoint(
    session_id_from_frontend: str,
    db_session: Session = Depends(get_session), # Restored
    pcap_filename: str = Query("capture.pcap", description="Logical filename of PCAP to analyze") # Restored
):
    logger.info(f"IP-MAC pairs request for session_id: {session_id_from_frontend}, file: {pcap_filename}") # Removed test route mention
    try:
        # Use the new helper function for validation
        pcap_session_record, _ = await validate_session_and_file(
            session_id=session_id_from_frontend,
            pcap_filename=pcap_filename,
            db_session=db_session
        )
    except HTTPException as e:
        raise e # Propagate 404 or other validation errors

    logger.info(f"Validation successful for session {session_id_from_frontend}, file {pcap_filename}. Proceeding to extract pairs.")
    try:
        # Load the OUI map first
        logger.debug(f"Attempting to load OUI map from: {OUI_CSV_PATH}")
        oui_map: Dict[str, str] = {}
        if os.path.exists(OUI_CSV_PATH):
            try:
                oui_map = parse_oui_csv(OUI_CSV_PATH) # Function from MacAnonymizer
                if not oui_map:
                    logger.warning(f"OUI map parsed from {OUI_CSV_PATH} is empty for IP-MAC pair extraction.")
                else:
                    logger.info(f"Loaded OUI map with {len(oui_map)} entries for IP-MAC pair extraction.")
            except Exception as e_oui:
                logger.warning(f"Failed to load or parse OUI map {OUI_CSV_PATH} for IP-MAC pair extraction: {e_oui}. Vendor info will be missing.")
        else:
            logger.warning(f"OUI CSV file not found at {OUI_CSV_PATH} for IP-MAC pair extraction. Vendor info will be missing.")

        # Call extract_ip_mac_pairs (synchronous) with the loaded oui_map
        logger.info(f"Calling extract_ip_mac_pairs for session {session_id_from_frontend}, file {pcap_filename}...")
        pairs = extract_ip_mac_pairs(session_id_from_frontend, pcap_filename, oui_map) # From MacAnonymizer
        logger.info(f"extract_ip_mac_pairs completed for session {session_id_from_frontend}. Found {len(pairs)} pairs.")
        # Return the list directly
        return pairs
    except FileNotFoundError: # Should be caught by validate_session_and_file or storage.read_pcap_from_session
        # Log the specific record name for better debugging if this unlikely case happens
        session_name = pcap_session_record.name if 'pcap_session_record' in locals() else session_id_from_frontend
        logger.error(f"File not found error during IP-MAC pair extraction for session '{session_name}'. This might indicate an issue after initial validation.")
        raise HTTPException(status_code=404, detail=f"PCAP file '{pcap_filename}' could not be processed for session '{session_name}'.")
    except Exception as e:
        logger.error(f"Error extracting IP-MAC pairs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to extract IP-MAC pairs: {str(e)}")

@general_router.get("/mac/rules/{session_id_from_frontend}", response_model=List[MacRule])
async def get_mac_rules_endpoint(
    session_id_from_frontend: str,
    db_session: Session = Depends(get_session)
):
    """
    Retrieves the saved MAC anonymization rules for a specific session.
    """
    logger.info(f"Request received for GET /mac/rules/{session_id_from_frontend}")

    # Validate the session exists (don't strictly need the record, but good practice)
    pcap_session_record = db_session.get(PcapSession, session_id_from_frontend)
    if not pcap_session_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session (trace) with ID '{session_id_from_frontend}' not found.")

    mac_rules_filename = "mac_rules.json"
    try:
        # Load rules directly using storage.load_json
        rules_data = storage.load_json(session_id_from_frontend, mac_rules_filename)

        if rules_data is None:
            # If file doesn't exist or is empty/invalid JSON, return empty list
            logger.info(f"MAC rules file '{mac_rules_filename}' not found or empty for session {session_id_from_frontend}. Returning empty list.")
            return []

        # Validate the loaded data against the Pydantic model (List[MacRule])
        # Pydantic will raise validation errors if the structure is wrong
        validated_rules = [MacRule(**rule) for rule in rules_data]
        logger.info(f"Successfully loaded and validated {len(validated_rules)} MAC rules for session {session_id_from_frontend}.")
        return validated_rules

    except json.JSONDecodeError as json_err:
        logger.error(f"Error decoding JSON from '{mac_rules_filename}' for session {session_id_from_frontend}: {json_err}", exc_info=True)
        # Return empty list or raise error? Let's return empty list for robustness.
        return []
    except Exception as e:
        logger.error(f"Error loading MAC rules for session {session_id_from_frontend}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load MAC rules: {str(e)}"
        )


@general_router.put("/mac/rules") # Assuming MacRuleInput contains session_id
async def mac_rules_endpoint(input: MacRuleInput, db_session: Session = Depends(get_session)):
    session_id = input.session_id # Use the ID directly
    logger.info(f"Request to save MAC rules for session_id: {session_id}")

    # Validate the session exists
    pcap_session_record = db_session.get(PcapSession, session_id)
    if not pcap_session_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session (trace) with ID '{session_id}' not found.")

    # No need to resolve physical directory ID
    mac_rules_filename = "mac_rules.json"
    logger.info(f"MAC rules for session {session_id} will be saved in its directory as {mac_rules_filename}")
    try:
        # Frontend is now responsible for providing target_oui.
        # Pydantic validation will ensure target_oui is present as it's mandatory in MacRule model.
        rules_data = [r.model_dump() for r in input.rules]
        storage.store_json(session_id, mac_rules_filename, rules_data)
        
        pcap_session_record.updated_at = datetime.utcnow()
        db_session.add(pcap_session_record)
        db_session.commit()
        return {"message": "MAC rules saved successfully.", "session_id": session_id, "file": mac_rules_filename}
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error saving MAC rules for session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save MAC rules: {str(e)}")

@general_router.post("/mac/apply", response_model=AsyncJob)
async def apply_mac_transform_endpoint(
    background_tasks: BackgroundTasks,
    session_id_from_frontend: str = Form(..., alias="session_id"),
    input_pcap_filename: str = Form(...),
    db_session: Session = Depends(get_session)
):
    logger.info(f"Apply MAC transform request for session_id: {session_id_from_frontend}, file: {input_pcap_filename}")
    try:
        # Validate input session and file exist
        pcap_session_record, _ = await validate_session_and_file(
            session_id=session_id_from_frontend,
            pcap_filename=input_pcap_filename,
            db_session=db_session
        )
    except HTTPException as e:
        raise e # Propagate 404 or other validation errors

    # Load MAC rules directly from the input session's directory
    mac_rules = storage.load_json(session_id_from_frontend, "mac_rules.json")
    if mac_rules is None: # Could be empty list [] which is valid for "no rules"
        logger.warning(f"MAC rules file not found or invalid in session {session_id_from_frontend} for MAC transform. Proceeding without specific rules (pass-through or default OUI).")
        # Allow proceeding if rules are optional

    # Create the job, associating it with the input session ID
    new_job = AsyncJob(
        session_id=session_id_from_frontend, # Job associated with the input trace
        trace_name=pcap_session_record.name,
        job_type="mac_transform", status="pending", created_at=datetime.utcnow(), updated_at=datetime.utcnow()
    )
    db_session.add(new_job); db_session.commit(); db_session.refresh(new_job)
    logger.info(f"Created AsyncJob {new_job.id} for MAC transform of {pcap_session_record.name} ({session_id_from_frontend})/{input_pcap_filename}.")

    # Pass the input session ID directly to the background task
    background_tasks.add_task(
        run_mac_transform,
        job_id=new_job.id,
        input_session_id=session_id_from_frontend, # Pass the input session ID
        input_pcap_filename=input_pcap_filename
    )
    return new_job

# --- DICOM Endpoints (moved to general_router, except the new one which is in dicom_router) ---
@general_router.post("/dicom/extract_metadata", response_model=AsyncJob)
async def extract_dicom_metadata_endpoint(
    background_tasks: BackgroundTasks,
    session_id_from_frontend: str = Form(..., alias="session_id"),
    input_pcap_filename: str = Form(...),
    db_session: Session = Depends(get_session)
):
    logger.info(f"DICOM metadata extraction request for session_id: {session_id_from_frontend}, file: {input_pcap_filename}")
    try:
        # Validate input session and file exist
        pcap_session_record, _ = await validate_session_and_file(
            session_id=session_id_from_frontend,
            pcap_filename=input_pcap_filename,
            db_session=db_session
        )
    except HTTPException as e:
        raise e # Propagate 404 or other validation errors

    # Create the job, associating it with the input session ID
    new_job = AsyncJob(
        session_id=session_id_from_frontend, # Job associated with the input trace
        trace_name=pcap_session_record.name,
        job_type="dicom_extract", status="pending", created_at=datetime.utcnow(), updated_at=datetime.utcnow()
    )
    db_session.add(new_job); db_session.commit(); db_session.refresh(new_job)
    logger.info(f"Created AsyncJob {new_job.id} for DICOM extraction from {pcap_session_record.name} ({session_id_from_frontend})/{input_pcap_filename}.")

    # Pass the input session ID directly to the background task
    background_tasks.add_task(
        run_dicom_extract,
        job_id=new_job.id,
        input_session_id=session_id_from_frontend, # Pass the input session ID
        input_pcap_filename=input_pcap_filename
    )
    return new_job

@general_router.post("/dicom/anonymize_v2", response_model=AsyncJob)
async def anonymize_dicom_v2_endpoint(
    background_tasks: BackgroundTasks,
    session_id_from_frontend: str = Form(..., alias="session_id"),
    input_pcap_filename: str = Form(...),
    metadata_overrides_json: Optional[str] = Form(None), # JSON string for overrides
    db_session: Session = Depends(get_session)
):
    logger.info(f"DICOM Anonymize V2 request for session_id: {session_id_from_frontend}, file: {input_pcap_filename}")
    try:
        # Validate input session and file exist
        pcap_session_record, _ = await validate_session_and_file(
            session_id=session_id_from_frontend,
            pcap_filename=input_pcap_filename,
            db_session=db_session
        )
    except HTTPException as e:
        raise e # Propagate 404 or other validation errors

    # Overrides JSON string is passed directly to the task runner.
    # The task runner will handle parsing it.

    # Create the job, associating it with the input session ID
    new_job = AsyncJob(
        session_id=session_id_from_frontend, # Job associated with the input trace
        trace_name=pcap_session_record.name,
        job_type="dicom_anonymize_v2", status="pending", created_at=datetime.utcnow(), updated_at=datetime.utcnow()
    )
    db_session.add(new_job); db_session.commit(); db_session.refresh(new_job)
    logger.info(f"Created AsyncJob {new_job.id} for DICOM Anonymize V2 of {pcap_session_record.name} ({session_id_from_frontend})/{input_pcap_filename}.")

    # Pass the input session ID directly to the background task
    background_tasks.add_task(
        run_dicom_anonymize_v2,
        job_id=new_job.id,
        input_session_id=session_id_from_frontend, # Pass the input session ID
        input_pcap_filename=input_pcap_filename,
        metadata_overrides_json_string=metadata_overrides_json
    )
    return new_job

DICOM_OVERRIDES_FILENAME = "dicom_metadata_overrides.json" # This can remain global if filename is standard

@general_router.get("/dicom/metadata_overrides/{session_id_from_frontend}/{ip_pair_key}")
async def get_dicom_metadata_overrides_endpoint(
    session_id_from_frontend: str,
    ip_pair_key: str, # e.g., "192.168.1.10-192.168.1.20"
    db_session: Session = Depends(get_session)
):
    logger.info(f"Get DICOM metadata overrides for session {session_id_from_frontend}, IP pair {ip_pair_key}")
    # Validate the session exists
    pcap_session_record = db_session.get(PcapSession, session_id_from_frontend)
    if not pcap_session_record:
        raise HTTPException(status_code=404, detail=f"Session {session_id_from_frontend} not found.")

    # Load overrides directly from the session's directory
    all_overrides = storage.load_json(session_id_from_frontend, DICOM_OVERRIDES_FILENAME)
    if all_overrides and ip_pair_key in all_overrides:
        return all_overrides[ip_pair_key]
    return {} # Return empty dict if no specific override for this key

@general_router.put("/dicom/metadata_overrides/{session_id_from_frontend}/{ip_pair_key}")
async def update_dicom_metadata_overrides_endpoint(
    session_id_from_frontend: str,
    ip_pair_key: str,
    payload: DicomMetadataUpdatePayload,
    db_session: Session = Depends(get_session)
):
    logger.info(f"Update DICOM metadata overrides for session {session_id_from_frontend}, IP pair {ip_pair_key}")

    # Validate the session exists
    pcap_session_record = db_session.get(PcapSession, session_id_from_frontend)
    if not pcap_session_record:
        raise HTTPException(status_code=404, detail=f"Session {session_id_from_frontend} not found.")

    # Load and store overrides directly in the session's directory
    all_overrides = storage.load_json(session_id_from_frontend, DICOM_OVERRIDES_FILENAME) or {}
    all_overrides[ip_pair_key] = payload.model_dump(exclude_none=True) # Store only provided fields
    storage.store_json(session_id_from_frontend, DICOM_OVERRIDES_FILENAME, all_overrides)

    # Update timestamp of the session
    pcap_session_record.updated_at = datetime.utcnow()
    db_session.add(pcap_session_record)
    db_session.commit()

    return {"message": "DICOM metadata overrides updated successfully.", "ip_pair_key": ip_pair_key, "overrides": payload}

# --- Job Management Endpoints (moved to general_router) ---
@general_router.get("/jobs", response_model=List[JobListResponse])
async def list_jobs(db_session: Session = Depends(get_session)):
    statement = select(AsyncJob).order_by(AsyncJob.created_at.desc())
    jobs = db_session.exec(statement).all()
    return jobs

@general_router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: int, db_session: Session = Depends(get_session)):
    job = db_session.get(AsyncJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@general_router.post("/jobs/{job_id}/cancel", response_model=JobStatusResponse)
async def cancel_job(job_id: int, db_session: Session = Depends(get_session)):
    job = db_session.get(AsyncJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ["pending", "running"]:
        raise HTTPException(status_code=400, detail=f"Job in status '{job.status}' cannot be cancelled.")
    job.status = "cancelling" # Signal to the task
    job.stop_requested = True # More explicit flag
    job.updated_at = datetime.utcnow()
    db_session.add(job); db_session.commit(); db_session.refresh(job)
    logger.info(f"Cancellation requested for job {job_id}.")
    return job

@general_router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job_record(job_id: int, db_session: Session = Depends(get_session)):
    job = db_session.get(AsyncJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # Optionally, add logic: only allow deletion of completed/failed/cancelled jobs
    if job.status in ["running", "pending", "cancelling"]:
        raise HTTPException(status_code=400, detail=f"Job in status '{job.status}' cannot be deleted. Please cancel or wait for completion.")
    
    # If the job produced an output trace, consider if that trace should also be deleted or unlinked.
    # For now, just deleting the job record.
    if job.output_trace_id:
        logger.warning(f"Job {job_id} produced output trace {job.output_trace_id}. Deleting job record only. Trace remains.")

    db_session.delete(job)
    db_session.commit()
    logger.info(f"AsyncJob record {job_id} deleted.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# --- SSE Job Status Endpoint ---
async def job_status_event_generator(job_id: int, initial_job_status: JobStatusResponse, db: Session):
    """
    Asynchronously generates Server-Sent Events for job status updates.
    Relies on polling the database for changes.
    """
    logger.info(f"SSE connection opened for job_id: {job_id}")
    last_status_json = initial_job_status.model_dump_json()
    yield f"data: {last_status_json}\n\n" # Send initial status immediately

    try:
        while True:
            await asyncio.sleep(1) # Polling interval (e.g., 1 second)
            
            # Re-fetch job in each iteration to get the latest state
            # This ensures that the db session is used in a way that's safe for long polling
            current_job_from_db = db.get(AsyncJob, job_id)
            if not current_job_from_db:
                logger.warning(f"Job {job_id} not found during SSE polling. Closing stream.")
                yield f"data: {{\"error\": \"Job not found\", \"job_id\": {job_id}}}\n\n"
                break

            # Convert SQLModel instance to a dictionary before validation
            job_dict = current_job_from_db.model_dump()
            current_job_response = JobStatusResponse.model_validate(job_dict)
            current_status_json = current_job_response.model_dump_json()

            if current_status_json != last_status_json:
                last_status_json = current_status_json
                logger.info(f"SSE: Job {job_id} status update: {last_status_json}")
                yield f"data: {last_status_json}\n\n"

            if current_job_from_db.status in ["completed", "failed", "cancelled"]:
                logger.info(f"SSE: Job {job_id} reached terminal state '{current_job_from_db.status}'. Closing stream.")
                # Send final status one last time if it changed and led to termination
                if current_status_json != last_status_json: # Ensure the very last update is sent
                     yield f"data: {current_status_json}\n\n"
                break
    except asyncio.CancelledError:
        logger.info(f"SSE connection for job_id: {job_id} closed by client.")
        # Do not reraise CancelledError if you want the generator to exit cleanly
        # FastAPI/Starlette will handle the client disconnect.
    except Exception as e:
        logger.error(f"SSE error for job_id {job_id}: {e}", exc_info=True)
        try:
            # Attempt to send an error message to the client
            error_payload = {"error": "SSE stream encountered an internal error", "job_id": job_id}
            yield f"data: {json.dumps(error_payload)}\n\n"
        except Exception as send_err:
            logger.error(f"SSE: Failed to send error to client for job {job_id}: {send_err}")
    finally:
        logger.info(f"SSE stream ended for job_id: {job_id}")


@general_router.get("/jobs/{job_id}/events", response_class=StreamingResponse)
async def job_events_sse(job_id: int, db_session: Session = Depends(get_session)):
    job_orm = db_session.get(AsyncJob, job_id) # Renamed to job_orm
    if not job_orm:
        # Return a plain JSON response for the 404, not a stream
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "Job not found"}
        )
    
    # Convert SQLModel instance to a dictionary before validation
    job_dict = job_orm.model_dump()
    initial_job_status = JobStatusResponse.model_validate(job_dict)
    
    # Pass the db_session to the generator. The generator should use this session.
    # FastAPI handles the lifecycle of db_session for the request.
    return StreamingResponse(job_status_event_generator(job_id, initial_job_status, db_session), media_type="text/event-stream")


# --- Download Endpoint (moved to general_router) ---
@general_router.get("/download/{session_id_from_frontend}/{filename}")
async def download_session_file_endpoint( # Renamed function
    session_id_from_frontend: str,
    filename: str, # This is the logical filename the user wants to download
    db_session: Session = Depends(get_session)
):
    logger.info(f"Download request for session {session_id_from_frontend}, filename {filename}")
    try:
        # Use the new helper function for validation
        _, validated_file_path = await validate_session_and_file(
            session_id=session_id_from_frontend,
            pcap_filename=filename, # The logical filename is used here
            db_session=db_session
        )
    except HTTPException as e:
        # Propagate 404 or other validation errors
        raise e

    # The helper already confirmed the file exists
    logger.info(f"Serving file: {validated_file_path} with requested filename: {filename}")

    # Determine media type based on filename extension
    media_type = "application/octet-stream" # Default
    if filename.lower().endswith(".pcap"):
        media_type = "application/vnd.tcpdump.pcap"
    elif filename.lower().endswith(".json"):
        media_type = "application/json"
    # Add more types here if needed (e.g., .txt, .csv)
    # elif filename.lower().endswith(".txt"):
    #     media_type = "text/plain"
    # elif filename.lower().endswith(".csv"):
    #     media_type = "text/csv"

    logger.info(f"Determined media type: {media_type} for filename: {filename}")

    return FileResponse(path=validated_file_path, filename=filename, media_type=media_type)

# --- Settings Management Endpoints (moved to general_router) ---
@general_router.post("/api/v1/settings/clear-all-data", status_code=status.HTTP_200_OK)
async def clear_all_data_endpoint(
    background_tasks: BackgroundTasks, # Moved before db_session
    db_session: Session = Depends(get_session)
):
    logger.info("Request received for POST /api/v1/settings/clear-all-data")

    error_messages = []

    # 1. Delete all AsyncJob records
    try:
        statement_jobs = select(AsyncJob)
        jobs_to_delete = db_session.exec(statement_jobs).all()
        num_jobs_deleted = len(jobs_to_delete)
        for job in jobs_to_delete:
            db_session.delete(job)
        db_session.commit()
        logger.info(f"Successfully deleted {num_jobs_deleted} AsyncJob records.")
    except Exception as e:
        db_session.rollback()
        msg = f"Error deleting AsyncJob records: {str(e)}"
        logger.error(msg, exc_info=True)
        error_messages.append(msg)

    # 2. Delete all PcapSession records
    try:
        statement_sessions = select(PcapSession)
        sessions_to_delete = db_session.exec(statement_sessions).all()
        num_sessions_deleted = len(sessions_to_delete)
        for session_record in sessions_to_delete:
            db_session.delete(session_record)
        db_session.commit()
        logger.info(f"Successfully deleted {num_sessions_deleted} PcapSession records.")
    except Exception as e:
        db_session.rollback()
        msg = f"Error deleting PcapSession records: {str(e)}"
        logger.error(msg, exc_info=True)
        error_messages.append(msg)

    # 3. Delete all physical session directories
    deleted_dirs_count = 0
    failed_dirs_count = 0
    try:
        sessions_base_dir = storage.SESSIONS_BASE_DIR # Corrected to use the constant
        if sessions_base_dir.exists() and sessions_base_dir.is_dir():
            for session_dir_item in sessions_base_dir.iterdir():
                if session_dir_item.is_dir(): # Ensure it's a directory
                    try:
                        shutil.rmtree(session_dir_item)
                        logger.info(f"Successfully deleted session directory: {session_dir_item}")
                        deleted_dirs_count += 1
                    except Exception as e:
                        msg = f"Failed to delete session directory {session_dir_item}: {str(e)}"
                        logger.error(msg, exc_info=True)
                        error_messages.append(msg)
                        failed_dirs_count += 1
        logger.info(f"Physical directory cleanup: {deleted_dirs_count} deleted, {failed_dirs_count} failed.")
    except Exception as e:
        msg = f"Error accessing or iterating session directories at {storage.SESSIONS_BASE_DIR}: {str(e)}" # Corrected here as well
        logger.error(msg, exc_info=True)
        error_messages.append(msg)

    if error_messages:
        # If there were any errors, return a 500 status but include details
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "message": "Completed clearing data with some errors.",
                "details": error_messages,
                "jobs_deleted": num_jobs_deleted if 'num_jobs_deleted' in locals() else 0,
                "sessions_deleted_db": num_sessions_deleted if 'num_sessions_deleted' in locals() else 0,
                "directories_deleted_fs": deleted_dirs_count,
                "directories_failed_fs": failed_dirs_count
            }
        )

    return {
        "message": "All data cleared successfully.",
        "jobs_deleted": num_jobs_deleted if 'num_jobs_deleted' in locals() else 0,
        "sessions_deleted_db": num_sessions_deleted if 'num_sessions_deleted' in locals() else 0,
        "directories_deleted_fs": deleted_dirs_count
    }

# --- Main block for direct execution (optional, for development) ---
if __name__ == "__main__":
    import uvicorn
    # This allows running the app with `python backend/main.py`
    # create_db_and_tables() # Ensure tables are created if running directly (also done in lifespan)
    uvicorn.run(app, host="0.0.0.0", port=8000)

# Include the routers in the main app
app.include_router(general_router)
app.include_router(dicom_router)
