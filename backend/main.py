# --- Imports ---
import asyncio
import json
import logging      # Added for logging configuration
import os           # Required for file operations (delete)
import shutil
import traceback    # To debug and print full tracebacks
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any # Added Dict, Any
from contextlib import asynccontextmanager
from fastapi import (
    FastAPI, UploadFile, File, BackgroundTasks, HTTPException, Depends, Form, Response, status
)
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse # Added JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, SQLModel, select

# --- Database Imports ---
from database import create_db_and_tables, get_session, PcapSession, AsyncJob, engine # Added AsyncJob

# --- Anonymizer Imports (Existing PCAP functionality) ---
try:
    from anonymizer import (
        save_rules,
        generate_preview,
        apply_anonymization,
        get_subnets,
        apply_anonymization_response,
        JobCancelledException as AnonymizerJobCancelledException # Import with alias
    )
except ImportError as e:
     print(f"WARNING: Could not import 'anonymizer' or 'JobCancelledException'. Anonymization/cancellation functionality may not be available. Error: {e}")
     # Define dummy functions/exceptions if needed
     AnonymizerJobCancelledException = type('AnonymizerJobCancelledException', (Exception,), {})
     def apply_anonymization(session_id: str, progress_callback=None, check_stop_requested=None):
         raise ImportError("The module 'anonymizer' is not available or failed to import.")
     # Define other dummies if necessary

# --- DICOM PCAP Extractor Import ---
try:
    # Attempt to import the main function and the custom exception
    from dicom_pcap_extractor import extract_dicom_metadata_from_pcap, JobCancelledException
except ImportError as e:
    print(f"WARNING: Could not import 'dicom_pcap_extractor' or 'JobCancelledException'. DICOM PCAP extraction/cancellation functionality may not be available. Error: {e}")
    # Define dummy functions/exceptions to prevent FastAPI startup errors
    JobCancelledException = type('JobCancelledException', (Exception,), {}) # Dummy exception
    # This dummy function will raise an error if the endpoint is actually called.
    def extract_dicom_metadata_from_pcap(session_id: str):
        raise ImportError("The module 'dicom_pcap_extractor' is not available or failed to import.")

# --- Pydantic Models ---
# It's recommended to move these new DICOM-related models to models.py
from pydantic import BaseModel, Field # Ensure BaseModel/Field are imported
# Assuming these are moved to models.py:
# Import the new aggregated models and the update payload model
from models import RuleInput, AggregatedDicomResponse, DicomMetadataUpdatePayload
# Import the new PcapSessionResponse model
from models import RuleInput, AggregatedDicomResponse, DicomMetadataUpdatePayload, PcapSessionResponse
# If you prefer to keep them here, uncomment the definitions below and remove the import from models
"""
class AggregatedDicomInfo(BaseModel): # Example if kept here
    client_ip: str
    server_ip: str
    server_ports: List[int]
    # ... include all fields from DicomExtractedMetadata ...
    CallingAE: Optional[str] = None
    # ... etc ...

class AggregatedDicomResponse(BaseModel):
    results: Dict[str, AggregatedDicomInfo]

class DicomMetadataUpdatePayload(BaseModel):
    # ... include all fields from DicomExtractedMetadata ...
    CallingAE: Optional[str] = None
    # ... etc ...
    Manufacturer: Optional[str] = None
    ManufacturerModelName: Optional[str] = Field(None, alias="ManufacturerModelName")
    DeviceSerialNumber: Optional[str] = None
    SoftwareVersions: Optional[List[str]] = None
    TransducerType: Optional[str] = None

class DicomCommunicationInfo(BaseModel):
    source_ip: str
    source_port: int
    dest_ip: str
    dest_port: int
    metadata: DicomExtractedMetadata

class DicomExtractionResponse(BaseModel):
    results: Dict[str, List[DicomCommunicationInfo]]
"""

# --- Constants ---
SESSION_DIR = './sessions'
os.makedirs(SESSION_DIR, exist_ok=True)

# --- Global State (for async jobs) ---
# REMOVED: Global 'jobs' dictionary. State is now in the AsyncJob table.
# jobs: Dict[str, Dict[str, Any]] = {}

# --- Pydantic/SQLModel Models (Existing & New) ---

# Response model for listing jobs
class JobListResponse(BaseModel):
    id: int
    session_id: str
    trace_name: Optional[str] = None # Added trace name from PcapSession
    job_type: str
    status: str
    progress: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    error_message: Optional[str] = None

# Response model for a single job's status (similar to JobListResponse but includes result_data)
class JobStatusResponse(JobListResponse):
     result_data: Optional[Dict] = None # Include potential DICOM result


class SessionInput(BaseModel):
    session_id: str

# Model for updating session name/description via PUT request
class PcapSessionUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None


# --- Lifespan Manager ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles application startup and shutdown events."""
    print("FastAPI application starting up...")

    # Configure SQLAlchemy logger to be less verbose
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    print("SQLAlchemy engine logging level set to WARNING.")

    create_db_and_tables() # Create database tables if they don't exist

    # --- Handle stale jobs on startup ---
    print("Checking for stale 'running' jobs from previous runs...")
    try:
        with Session(engine) as startup_session:
            stale_jobs_statement = select(AsyncJob).where(AsyncJob.status == 'running')
            stale_jobs = startup_session.exec(stale_jobs_statement).all()
            if stale_jobs:
                print(f"Found {len(stale_jobs)} stale 'running' jobs. Marking as 'failed'.")
                for job in stale_jobs:
                    job.status = 'failed'
                    job.error_message = 'Job interrupted due to backend restart.'
                    job.updated_at = datetime.utcnow()
                    startup_session.add(job)
                startup_session.commit()
                print("Stale jobs marked as 'failed'.")
            else:
                print("No stale 'running' jobs found.")
    except Exception as e:
        print(f"ERROR: Could not check/update stale jobs during startup: {e}")
        traceback.print_exc()
    # --- End stale job handling ---

    yield # Application runs here
    print("FastAPI application shutting down...")

# --- FastAPI Application ---
app = FastAPI(lifespan=lifespan)

# --- CORS Middleware ---
# Allows requests from your frontend (adjust origin if needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], # Or specific frontend origin
    allow_credentials=True,
    allow_methods=["*"], # Allows all methods (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"], # Allows all headers
)

# --- API Endpoints ---

# --- /upload Endpoint (Existing - Modified for DB) ---
@app.post("/upload", response_model=PcapSession)
async def upload(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db_session: Session = Depends(get_session)
):
    """Handles PCAP file upload, saves file, creates DB record, returns session info."""
    session_id = str(uuid.uuid4())
    # Store filenames consistently, maybe using session_id
    # Ensure filenames are safe (e.g., avoid path traversal if original_filename is used directly)
    safe_original_filename = os.path.basename(file.filename or "unknown.pcap")
    pcap_filename = f"{session_id}.pcap" # Use session_id for the stored pcap name
    pcap_path = os.path.join(SESSION_DIR, pcap_filename)
    rules_filename = f"{session_id}_rules.json" # Corresponding rules file name
    rules_path = os.path.join(SESSION_DIR, rules_filename) # Path for rules file

    print(f"Processing upload for new session: {session_id}, name: {name}")
    print(f"Attempting to save uploaded file to: {os.path.abspath(pcap_path)}")

    # 1. Save uploaded PCAP file
    try:
        with open(pcap_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        print(f"SUCCESS: File successfully saved to: {pcap_path}")
    except Exception as e:
        print(f"ERROR: Failed to save file to {pcap_path}. Error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {e}")
    finally:
        await file.close() # Ensure the file handle is closed

    # 2. Create PcapSession database object
    upload_time = datetime.utcnow() # Use UTC time
    db_pcap_session = PcapSession(
        id=session_id,
        name=name,
        description=description,
        original_filename=safe_original_filename, # Store the original filename safely
        upload_timestamp=upload_time,
        pcap_path=pcap_path, # Store path to the saved pcap
        rules_path=rules_path, # Store path where rules *will* be saved
        updated_at=upload_time # Initial updated_at timestamp
    )

    # 3. Save the session metadata to the database
    db_session.add(db_pcap_session)
    try:
        db_session.commit() # Commit the transaction
        db_session.refresh(db_pcap_session) # Refresh to get any DB-generated values
        print(f"SUCCESS: Session metadata saved to DB for ID: {session_id}")
    except Exception as e:
        db_session.rollback() # Rollback transaction on error
        # Attempt to clean up the saved file if DB commit fails
        try:
            if os.path.exists(pcap_path): os.remove(pcap_path)
        except OSError as rm_err:
            print(f"Warning: Failed to clean up file {pcap_path} after DB error: {rm_err}")
        print(f"Database commit failed for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save session metadata: {e}")

    # 4. Optional: Initialize empty rules using the old storage mechanism (for backward compatibility?)
    # Consider if this is still needed if rules are fully managed via the API/DB later.
    try:
        from storage import store # Assuming storage.py still exists
        store(session_id, 'rules', []) # Store empty list as initial rules
    except Exception as e:
        # Log warning, but don't fail the upload if this part errors
        print(f"Warning: Failed to create initial empty rules file for {session_id} using storage.py: {e}")

    # 5. Return the created session data (as validated by the PcapSession model)
    return db_pcap_session


# --- GET /sessions Endpoint (Updated) ---
# Use the new PcapSessionResponse model for the response
@app.get("/sessions", response_model=List[PcapSessionResponse])
async def list_sessions(
    db_session: Session = Depends(get_session)
):
    """Retrieve a list of all saved PCAP sessions from the database."""
    print("Request received for GET /sessions")
    try:
        # Select all PcapSession records, order by upload time descending
        statement = select(PcapSession).order_by(PcapSession.upload_timestamp.desc())
        sessions = db_session.exec(statement).all()
        print(f"Found {len(sessions)} sessions in the database.")
        return sessions
    except Exception as e:
        print(f"Error fetching sessions from database: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve sessions: {e}")

# --- PUT /sessions/{session_id} Endpoint (Existing) ---
@app.put("/sessions/{session_id}", response_model=PcapSession)
async def update_session(
    session_id: str,
    session_update: PcapSessionUpdate, # Use the specific update model
    db_session: Session = Depends(get_session)
):
    """Updates the name and/or description of a specific PCAP session."""
    print(f"Request received for PUT /sessions/{session_id}")
    # 1. Fetch the existing session record from the DB
    db_pcap_session = db_session.get(PcapSession, session_id)
    if not db_pcap_session:
        # Session not found, return 404
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    # 2. Get updated data from request body, excluding fields not explicitly set by client
    update_data = session_update.model_dump(exclude_unset=True)
    if not update_data:
        # No data provided for update, return 400 Bad Request
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")

    print(f"Updating session {session_id} with data: {update_data}")
    # 3. Update the fields on the fetched session object
    needs_update = False
    for key, value in update_data.items():
        if hasattr(db_pcap_session, key): # Check if the attribute exists on the model
            setattr(db_pcap_session, key, value)
            needs_update = True # Mark that at least one field was updated

    # 4. Update the 'updated_at' timestamp if any changes were made
    if needs_update:
        db_pcap_session.updated_at = datetime.utcnow() # Update timestamp

        # 5. Add the updated object to the session, commit, and refresh
        db_session.add(db_pcap_session) # Add modifies the existing object in the session
        try:
            db_session.commit() # Commit the transaction
            db_session.refresh(db_pcap_session) # Refresh object state from DB
            print(f"Session {session_id} updated successfully.")
        except Exception as e:
            db_session.rollback() # Rollback on commit error
            print(f"Database commit failed during update for session {session_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to update session metadata: {e}")

    # 6. Return the (potentially updated) session object
    return db_pcap_session


# --- DELETE /sessions/{session_id} Endpoint (Existing) ---
@app.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT) # Use 204 status code
async def delete_session(
    session_id: str,
    db_session: Session = Depends(get_session)
):
    """Deletes a PCAP session record and its associated files."""
    print(f"Request received for DELETE /sessions/{session_id}")
    # 1. Fetch the session record to get file paths
    pcap_session = db_session.get(PcapSession, session_id)
    if not pcap_session:
        # Session not found, return 404
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    # 2. Define paths for files associated with the session
    # Use paths stored in the database record for accuracy
    files_to_delete = [
        pcap_session.pcap_path, # Original PCAP file
        pcap_session.rules_path, # Rules JSON file
        # Construct path for potentially generated anonymized file
        os.path.join(SESSION_DIR, f"{session_id}_anon.pcap")
    ]
    # Attempt to delete each associated file
    for file_path in files_to_delete:
        if file_path and os.path.exists(file_path): # Check if path is valid and file exists
            try:
                os.remove(file_path)
                print(f"Deleted file: {file_path}")
            except OSError as e:
                # Log error but continue to delete DB record even if file deletion fails
                print(f"Warning: Failed to delete file {file_path}. Error: {e}")

    # 3. Delete the database record
    db_session.delete(pcap_session)
    try:
        db_session.commit() # Commit the deletion
        print(f"Session {session_id} deleted successfully from database.")
        # For 204 No Content, return None or Response(status_code=204)
        return None
    except Exception as e:
        # This might happen if there are constraints or other DB issues
        db_session.rollback() # Rollback on error
        print(f"Database error during session deletion commit for {session_id}: {e}")
        # Use 500 Internal Server Error if commit fails
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error deleting session from database: {e}")


# --- Endpoints related to PCAP Anonymization (Existing - Needs Review/Update) ---
# TODO: Review if these endpoints should be updated to primarily use DB storage
#       instead of relying solely on storage.py and session_id file conventions.

@app.put("/rules")
async def rules_endpoint(input: RuleInput, db_session: Session = Depends(get_session)):
    """Saves the transformation rules for a given session (currently uses storage.py)."""
    # Fetch session to verify ID and potentially use DB paths in the future
    pcap_session = db_session.get(PcapSession, input.session_id)
    if not pcap_session:
        raise HTTPException(status_code=404, detail="Session not found")
    print(f"Saving rules for session {input.session_id} (using storage.py logic).")
    # Current implementation delegates to the old save_rules function
    try:
        return save_rules(input)
    except Exception as e:
        print(f"Error calling save_rules for session {input.session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save rules: {e}")

@app.get("/preview/{session_id}")
async def preview_endpoint(session_id: str, db_session: Session = Depends(get_session)):
    """Generates a preview of the anonymization based on current rules (uses storage.py)."""
    pcap_session = db_session.get(PcapSession, session_id)
    if not pcap_session:
        raise HTTPException(status_code=404, detail="Session not found")
    print(f"Generating preview for session {session_id} (using storage.py logic).")
    # Current implementation delegates to generate_preview
    try:
        # Ensure generate_preview uses pcap_session.pcap_path and rules from storage/DB
        return generate_preview(session_id) # Assumes generate_preview finds files based on session_id
    except FileNotFoundError:
         raise HTTPException(status_code=404, detail="Session data or PCAP file not found for preview.")
    except Exception as e:
        print(f"Error during preview generation for {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate preview: {e}")


@app.get("/subnets/{session_id}")
async def subnets_endpoint(session_id: str, db_session: Session = Depends(get_session)):
    """Gets the list of detected subnets from the original PCAP (uses storage.py)."""
    pcap_session = db_session.get(PcapSession, session_id)
    if not pcap_session:
        raise HTTPException(status_code=404, detail="Session not found")
    print(f"Getting subnets for session {session_id} (using storage.py logic).")
    # Current implementation delegates to get_subnets
    try:
         # Ensure get_subnets uses pcap_session.pcap_path
        return get_subnets(session_id) # Assumes get_subnets finds the file
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Original PCAP file not found for subnet analysis.")
    except Exception as e:
        print(f"Error getting subnets for {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to analyze subnets: {e}")


@app.get("/download/{session_id}")
async def download_anonymized_pcap(session_id: str, db_session: Session = Depends(get_session)):
    """Applies anonymization and provides the anonymized PCAP file for download."""
    pcap_session = db_session.get(PcapSession, session_id)
    if not pcap_session:
        raise HTTPException(status_code=404, detail="Session not found")
    print(f"Request to download anonymized PCAP for session {session_id}.")
    # Uses apply_anonymization_response which internally calls apply_anonymization
    try:
        # apply_anonymization_response should handle file path logic based on session_id
        return apply_anonymization_response(session_id)
    except FileNotFoundError:
        # This could mean original PCAP or rules are missing, or anon file wasn't created
        print(f"Download failed: Original or anonymized file not found for session {session_id}")
        raise HTTPException(status_code=404, detail="Original or anonymized file not found.")
    except Exception as e:
        print(f"Download failed for session {session_id}: {e}")
        traceback.print_exc() # Log detailed error
        raise HTTPException(status_code=500, detail=f"Error preparing file for download: {e}")

# REMOVED: Synchronous /download endpoint. Transformation is now async via /sessions/{id}/transform/start


#--- NEW Endpoints for Listing Async Jobs ---

@app.get("/jobs", response_model=List[JobListResponse], tags=["Jobs"])
async def list_all_jobs(
    db_session: Session = Depends(get_session)
):
    """Retrieves a list of all asynchronous jobs from the database, including the trace name."""
    print("Request received for GET /jobs")
    try:
        # Join AsyncJob with PcapSession to fetch the session name (trace_name)
        statement = select(AsyncJob, PcapSession.name).join(
            PcapSession, AsyncJob.session_id == PcapSession.id
        ).order_by(AsyncJob.created_at.desc())

        results = db_session.exec(statement).all()
        print(f"Found {len(results)} jobs with trace names in the database.")

        # Construct the response list, adding trace_name to each job object
        response_list = []
        for job, trace_name in results:
            # Convert the SQLModel job object to a dictionary
            job_dict = job.model_dump()
            # Add the fetched trace name to the dictionary
            job_dict['trace_name'] = trace_name
            # Create and validate the response object using the Pydantic model
            response_list.append(JobListResponse(**job_dict))

        return response_list
    except Exception as e:
        print(f"Error fetching jobs with trace names from database: {e}")
        traceback.print_exc() # Log the full traceback for debugging
        raise HTTPException(status_code=500, detail=f"Failed to retrieve jobs: {e}")


@app.get("/jobs/{job_id}", response_model=JobStatusResponse, tags=["Jobs"])
async def get_job_details(
    job_id: int,
    db_session: Session = Depends(get_session)
):
    """Retrieves the details and status of a specific asynchronous job."""
    print(f"Request received for GET /jobs/{job_id}")
    db_job = db_session.get(AsyncJob, job_id)
    if not db_job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job with ID {job_id} not found.")
    print(f"Found job {job_id}: Status={db_job.status}, Progress={db_job.progress}")
    # Assuming AsyncJob model fields align with JobStatusResponse
    return db_job


# --- NEW Endpoint to Request Job Stop ---
@app.post("/jobs/{job_id}/stop", status_code=status.HTTP_202_ACCEPTED, tags=["Jobs"])
async def request_job_stop(
    job_id: int,
    db_session: Session = Depends(get_session)
):
    """Requests a running or pending job to stop gracefully."""
    print(f"Request received for POST /jobs/{job_id}/stop")
    job = db_session.get(AsyncJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job with ID {job_id} not found.")

    # Only allow stopping jobs that are pending or running
    if job.status not in ['pending', 'running']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job {job_id} cannot be stopped because its status is '{job.status}'. Only 'pending' or 'running' jobs can be stopped."
        )

    if job.stop_requested:
        print(f"Stop already requested for job {job_id}.")
        # Return 202 Accepted even if already requested, the request is acknowledged.
        return {"message": "Stop request already acknowledged."}

    # Set the flag and potentially update status
    job.stop_requested = True
    # Optionally change status to 'cancelling' immediately, or let the task handle it
    # Let's change it here for immediate feedback via SSE
    job.status = 'cancelling'
    job.updated_at = datetime.utcnow()
    db_session.add(job)
    try:
        db_session.commit()
        print(f"Stop requested successfully for job {job_id}. Status set to 'cancelling'.")
        return {"message": "Job stop requested successfully."}
    except Exception as e:
        db_session.rollback()
        print(f"Database error while requesting stop for job {job_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to request job stop.")


# --- NEW Endpoint to Delete a Job Record ---
@app.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Jobs"])
async def delete_job_record(
    job_id: int,
    db_session: Session = Depends(get_session)
):
    """Deletes a specific asynchronous job record from the database."""
    print(f"Request received for DELETE /jobs/{job_id}")
    job = db_session.get(AsyncJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job with ID {job_id} not found.")

    # Define allowed statuses for deletion
    allowed_delete_statuses = ['completed', 'failed', 'cancelled'] # Add 'cancelled'
    if job.status not in allowed_delete_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job {job_id} cannot be deleted because its status is '{job.status}'. Only jobs with status {allowed_delete_statuses} can be deleted."
        )

    # Delete the job record
    db_session.delete(job)
    try:
        db_session.commit()
        print(f"Job {job_id} deleted successfully from database.")
        # Return 204 No Content implicitly by returning None or Response(status_code=204)
        return None
    except Exception as e:
        db_session.rollback()
        print(f"Database error during job deletion commit for {job_id}: {e}")
        # Check for specific constraint errors if necessary, otherwise return 500
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error deleting job from database: {e}")


#--- REMOVED: Synchronous DICOM Metadata Extraction Endpoint ---
# The functionality is replaced by the async job endpoints below.
# @app.get("/dicom/pcap/{session_id}/extract", ...)


# --- Background Task Function for DICOM Extraction ---
def run_dicom_extract(job_id: int, session_id: str): # job_id is now int
    """Background task function to perform DICOM metadata extraction and update DB, with cancellation support."""
    print(f"--- TASK START: DICOM Extraction Job {job_id} for Session {session_id} ---")

    # Progress callback function to update the database
    def update_progress_db(progress_percentage: int):
        with Session(engine) as progress_session:
            try:
                job = progress_session.get(AsyncJob, job_id)
                if job and job.status == 'running': # Only update if still running
                    job.progress = max(0, min(100, progress_percentage))
                    job.updated_at = datetime.utcnow()
                    progress_session.add(job)
                    progress_session.commit()
                    # print(f"DICOM Job {job_id} progress: {progress_percentage}% (DB updated)") # Optional debug log
                elif job:
                    print(f"DICOM Job {job_id} no longer running (status: {job.status}), skipping progress update.")
                else:
                     print(f"DICOM Job {job_id} not found during progress update.")
            except Exception as e:
                progress_session.rollback()
                print(f"Error updating progress in DB for job {job_id}: {e}")
            finally:
                progress_session.close() # Ensure session is closed

    # --- Cancellation Check Function ---
    # This function will be passed to the extractor to periodically check the DB flag
    def check_stop_requested_db() -> bool:
        with Session(engine) as check_session:
            try:
                job = check_session.get(AsyncJob, job_id)
                if job and job.stop_requested:
                    print(f"--- TASK CHECK: Stop requested flag is TRUE for job {job_id} in DB ---")
                    return True
                # print(f"--- TASK CHECK: Stop requested flag is FALSE for job {job_id} in DB ---") # Debug log
                return False
            except Exception as e:
                print(f"Error checking stop_requested flag in DB for job {job_id}: {e}")
                return False # Default to false if DB check fails, to avoid accidental cancellation
            finally:
                check_session.close()
    # ---------------------------------

    extracted_data = None
    error_msg = None
    final_status = "failed" # Default to failed unless successful

    # --- Database access within the background task ---
    with Session(engine) as db_session_for_task:
        try:
            # 1. Fetch and update job status to 'running'
            job = db_session_for_task.get(AsyncJob, job_id)
            if not job:
                raise Exception(f"Job {job_id} not found in DB at start of task.")
            if job.status != 'pending': # Avoid re-running completed/failed jobs
                 print(f"Job {job_id} already started (status: {job.status}). Exiting task.")
                 return

            job.status = 'running'
            job.progress = 0
            job.updated_at = datetime.utcnow()
            db_session_for_task.add(job)
            db_session_for_task.commit()
            db_session_for_task.refresh(job) # Refresh to ensure we have the latest state

            # 2. Fetch associated PCAP session
            pcap_session = db_session_for_task.get(PcapSession, session_id)
            if not pcap_session:
                raise Exception(f"PcapSession {session_id} not found in DB for job {job_id}")

            print(f"Running extract_dicom_metadata_from_pcap for job {job_id}, session {session_id}")
            # 3. Call the extraction function with DB progress and cancellation check callbacks
            extracted_data = extract_dicom_metadata_from_pcap(
                session_id=session_id,
                progress_callback=update_progress_db,
                check_stop_requested=check_stop_requested_db # Pass the DB check function
            )

            # 4. Update job status upon successful completion (if not cancelled)
            # Check if stop was requested *after* the function returned but before setting status
            if check_stop_requested_db():
                 final_status = 'cancelled'
                 error_msg = "Job cancelled by user after completion."
                 print(f"DICOM extraction job {job_id} cancelled after completion.")
            else:
                 final_status = 'completed'
                 print(f"DICOM extraction job {job_id} completed successfully.")

        except JobCancelledException:
            final_status = 'cancelled'
            error_msg = "Job cancelled by user during execution."
            print(f"DICOM extraction job {job_id} cancelled during execution.")
        except FileNotFoundError as e:
            error_msg = f"PCAP file not found: {str(e)}"
            final_status = 'failed' # Ensure status is failed
            print(f"DICOM extraction job {job_id} failed: {error_msg}")
        except ImportError as e:
            error_msg = f"Import error, DICOM extractor unavailable: {str(e)}"
            final_status = 'failed' # Ensure status is failed
            print(f"DICOM extraction job {job_id} failed: {error_msg}")
        except Exception as e:
            error_msg = str(e)
            final_status = 'failed' # Ensure status is failed
            print(f"DICOM extraction job {job_id} failed: {error_msg}")
            traceback.print_exc() # Log the full traceback
        finally:
            print(f"--- TASK FINALLY BLOCK: DICOM Job {job_id}. Attempting final DB update. Status='{final_status}', Error='{error_msg}' ---")
            # 5. Final DB update for status, result/error, and potentially reset stop_requested
            try:
                # Re-fetch job in case session expired or other issues
                final_job_update = db_session_for_task.get(AsyncJob, job_id)
                if final_job_update:
                    print(f"    Found job {job_id} in DB for final update.")
                    final_job_update.status = final_status
                    final_job_update.error_message = error_msg
                    # Store result only if completed successfully
                    final_job_update.result_data = extracted_data if final_status == 'completed' else None
                    # Set progress to 100 if completed, otherwise keep current progress
                    final_job_update.progress = 100 if final_status == 'completed' else final_job_update.progress
                    final_job_update.updated_at = datetime.utcnow()
                    # Optionally reset stop_requested flag once job is finished (cancelled/failed/completed)
                    # final_job_update.stop_requested = False
                    db_session_for_task.add(final_job_update)
                    db_session_for_task.commit()
                    print(f"    SUCCESS: Final status for job {job_id} ({final_status}) saved to DB.") # Log success
                else:
                    print(f"    ERROR: Could not find job {job_id} for final status update.") # Log not found
            except Exception as db_e:
                 db_session_for_task.rollback()
                 print(f"    CRITICAL ERROR: Failed to update final status for job {job_id} in DB: {db_e}") # Log DB error
                 traceback.print_exc() # Log traceback for DB error

    print(f"--- TASK END: DICOM Extraction Job {job_id} ---") # Added explicit end log


# --- NEW Endpoint to Start DICOM Extraction Job ---
@app.post("/sessions/{session_id}/dicom/extract/start", response_model=JobListResponse, tags=["DICOM", "Jobs"]) # Return job details
async def start_dicom_extraction_job(
    session_id: str,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(get_session)
):
    """Starts the DICOM metadata extraction process as a background task."""
    # Verify session exists before starting the job
    pcap_session = db_session.get(PcapSession, session_id)
    if not pcap_session:
        raise HTTPException(status_code=404, detail=f"Session with ID {session_id} not found.")

    # Create AsyncJob record in DB, including the trace_name from the session
    new_job = AsyncJob(
        session_id=session_id,
        job_type='dicom_extract',
        status='pending',
        progress=0,
        # Copy the user-provided session name as the trace_name for the job
        trace_name=pcap_session.name,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db_session.add(new_job)
    try:
        db_session.commit()
        db_session.refresh(new_job) # Get the auto-generated job ID
        job_id = new_job.id
        print(f"Created AsyncJob record {job_id} for DICOM extraction on session {session_id}")
    except Exception as e:
        db_session.rollback()
        print(f"Failed to create AsyncJob record for DICOM extraction: {e}")
        raise HTTPException(status_code=500, detail="Failed to initiate DICOM extraction job.")

    if job_id is None: # Should not happen if commit succeeded, but check anyway
         raise HTTPException(status_code=500, detail="Failed to get job ID after creation.")

    # --- Add logging before and after adding the task ---
    print(f"Endpoint /dicom/extract/start: Attempting to add background task for job {job_id}...")
    try:
        # Add the DICOM extraction task to run in the background
        background_tasks.add_task(run_dicom_extract, job_id, session_id)
        print(f"Endpoint /dicom/extract/start: Successfully added background task for job {job_id}.")
    except Exception as task_add_err:
        # Log if adding the task itself fails
        print(f"Endpoint /dicom/extract/start: CRITICAL ERROR adding background task for job {job_id}: {task_add_err}")
        # Optionally update the job status to failed here if adding fails?
        # For now, just log the error. The job will remain 'pending'.
        # Consider raising an HTTPException if adding the task is critical failure
        # raise HTTPException(status_code=500, detail=f"Failed to schedule background task: {task_add_err}")

    # Return the created job details immediately
    return new_job


# --- Background Task Function for DICOM Extraction ---
# Note: The duplicate definition of this function using the global 'jobs' dictionary has been removed.
# The correct version using the database (AsyncJob) is defined earlier in the file.


# --- NEW Endpoint to Start DICOM Extraction Job ---
# Note: The duplicate definition of this endpoint using the global 'jobs' dictionary has been removed.
# The correct version using the database (AsyncJob) is defined earlier in the file.


# --- NEW Endpoint for Updating DICOM Metadata Overrides ---
# This endpoint allows saving/updating DICOM metadata overrides.
@app.put("/dicom/pcap/{session_id}/metadata/{ip_pair_key}", status_code=status.HTTP_204_NO_CONTENT, tags=["DICOM"])
async def update_dicom_metadata_override(
    session_id: str,
    ip_pair_key: str, # e.g., "192.168.1.10-192.168.1.20"
    payload: DicomMetadataUpdatePayload, # The metadata fields to update
    db_session: Session = Depends(get_session) # Inject DB session
):
    """
    Saves or updates DICOM metadata overrides for a specific IP pair within a session.
    Stores the overrides in a JSON file named {session_id}_dicom_overrides.json.
    """
    print(f"Request received to update DICOM metadata override for session: {session_id}, IP pair: {ip_pair_key}")

    # 1. Verify the session exists
    pcap_session = db_session.get(PcapSession, session_id)
    if not pcap_session:
        print(f"Error: Session {session_id} not found in the database.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID {session_id} not found."
        )

    # 2. Define the path for the overrides file
    overrides_filename = f"{session_id}_dicom_overrides.json"
    overrides_path = os.path.join(SESSION_DIR, overrides_filename)
    print(f"Override file path: {overrides_path}")

    # 3. Load existing overrides (if any)
    overrides: Dict[str, Dict[str, Any]] = {}
    if os.path.exists(overrides_path):
        try:
            with open(overrides_path, 'r') as f:
                overrides = json.load(f)
            print(f"Loaded existing overrides from {overrides_path}")
        except json.JSONDecodeError:
            print(f"Warning: Could not decode existing overrides file {overrides_path}. Starting fresh.")
        except Exception as e:
            print(f"Error reading overrides file {overrides_path}: {e}. Raising error.")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not read existing DICOM overrides file: {str(e)}"
            )

    # 4. Prepare the update data
    # Use exclude_unset=True to only include fields explicitly sent by the client
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
         print("No update data provided in the payload.")
         # Return 204 No Content even if nothing changed, as the request was valid
         return Response(status_code=status.HTTP_204_NO_CONTENT)

    print(f"Updating overrides for key '{ip_pair_key}' with data: {update_data}")

    # 5. Update the overrides dictionary
    # If the key doesn't exist, create it. If it exists, update it.
    if ip_pair_key not in overrides:
        overrides[ip_pair_key] = {}

    # Merge the new data into the existing entry for the IP pair key
    # This overwrites existing values for the fields provided in the payload
    overrides[ip_pair_key].update(update_data)

    # 6. Save the updated overrides back to the JSON file
    try:
        with open(overrides_path, 'w') as f:
            json.dump(overrides, f, indent=2) # Use indent for readability
        print(f"Successfully saved updated overrides to {overrides_path}")
    except Exception as e:
        print(f"Error writing overrides file {overrides_path}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not save DICOM overrides file: {str(e)}"
        )

    # 7. Return 204 No Content on success
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Background Task Function for PCAP Transformation ---
def run_apply(job_id: int, session_id: str): # job_id is now int
    """Background task function to perform PCAP anonymization/transformation and update DB, with cancellation support."""
    print(f"Background task started for PCAP transformation job {job_id}, session {session_id}")

    # Progress callback function to update the database
    def update_progress_db(progress_percentage: int):
        with Session(engine) as progress_session:
            try:
                job = progress_session.get(AsyncJob, job_id)
                if job and job.status == 'running':
                    job.progress = max(0, min(100, progress_percentage))
                    job.updated_at = datetime.utcnow()
                    progress_session.add(job)
                    progress_session.commit()
                    # print(f"Transform Job {job_id} progress: {progress_percentage}% (DB updated)")
                elif job:
                     print(f"Transform Job {job_id} no longer running (status: {job.status}), skipping progress update.")
                else:
                     print(f"Transform Job {job_id} not found during progress update.")
            except Exception as e:
                progress_session.rollback()
                print(f"Error updating progress in DB for job {job_id}: {e}")
            finally:
                progress_session.close()

    # --- Cancellation Check Function ---
    def check_stop_requested_db() -> bool:
        with Session(engine) as check_session:
            try:
                job = check_session.get(AsyncJob, job_id)
                if job and job.stop_requested:
                    print(f"--- TASK CHECK (Transform): Stop requested flag is TRUE for job {job_id} in DB ---")
                    return True
                return False
            except Exception as e:
                print(f"Error checking stop_requested flag in DB for transform job {job_id}: {e}")
                return False
            finally:
                check_session.close()
    # ---------------------------------

    output_path = None
    error_msg = None
    final_status = "failed"

    with Session(engine) as db_session_for_task:
        try:
            # 1. Fetch and update job status to 'running'
            job = db_session_for_task.get(AsyncJob, job_id)
            if not job:
                raise Exception(f"Job {job_id} not found in DB at start of task.")
            if job.status != 'pending':
                 print(f"Job {job_id} already started (status: {job.status}). Exiting task.")
                 return

            job.status = 'running'
            job.progress = 0
            job.updated_at = datetime.utcnow()
            db_session_for_task.add(job)
            db_session_for_task.commit()
            db_session_for_task.refresh(job)

            # 2. Fetch associated PCAP session
            original_pcap_session = db_session_for_task.get(PcapSession, session_id)
            if not original_pcap_session:
                raise Exception(f"Original PcapSession {session_id} not found in DB for job {job_id}")

            # 3. Call the transformation function with progress and cancellation callbacks
            print(f"Running apply_anonymization for job {job_id}, session {session_id}")
            output_path = apply_anonymization(
                session_id=session_id,
                progress_callback=update_progress_db,
                check_stop_requested=check_stop_requested_db # Pass the DB check function
            )

            if not output_path or not os.path.exists(output_path):
                 raise Exception(f"Anonymization completed but output file path '{output_path}' is invalid or missing.")

            # 4. Create a new PcapSession record for the transformed file
            new_session_id = str(uuid.uuid4()) # Generate a new UUID for the transformed session
            transformed_session = PcapSession(
                id=new_session_id,
                name=f"{original_pcap_session.name} (Transformed)", # Append suffix to name
                description=f"Transformed from session {session_id} by job {job_id}",
                original_filename=os.path.basename(output_path), # Use the new filename
                upload_timestamp=datetime.utcnow(), # Timestamp of transformation completion
                pcap_path=output_path, # Path to the *transformed* PCAP
                rules_path=original_pcap_session.rules_path, # Copy rules path reference? Or null? Let's copy.
                updated_at=datetime.utcnow(),
                is_transformed=True,
                original_session_id=session_id,
                async_job_id=job_id
            )
            db_session_for_task.add(transformed_session)
            print(f"Created new PcapSession {new_session_id} for transformed output of job {job_id}")

            # 5. Mark job as completed (if not cancelled)
            if check_stop_requested_db():
                 final_status = 'cancelled'
                 error_msg = "Job cancelled by user after completion."
                 print(f"PCAP transformation job {job_id} cancelled after completion.")
                 # Clean up potentially created anon file if cancelled after creation
                 if output_path and os.path.exists(output_path):
                     try:
                         os.remove(output_path)
                         print(f"Cleaned up partially created anon file: {output_path}")
                     except OSError as rm_err:
                         print(f"Warning: Failed to clean up anon file {output_path} after cancellation: {rm_err}")
            else:
                 final_status = 'completed'
                 print(f"PCAP transformation job {job_id} completed. Output: {output_path}")

        except AnonymizerJobCancelledException: # Catch the specific exception from anonymizer
            final_status = 'cancelled'
            error_msg = "Job cancelled by user during execution."
            print(f"PCAP transformation job {job_id} cancelled during execution.")
        except Exception as e:
            error_msg = str(e)
            final_status = 'failed' # Ensure status is failed
            print(f"PCAP transformation job {job_id} failed: {error_msg}")
            traceback.print_exc()
        finally:
            # 6. Final DB update for job status and error
            try:
                final_job_update = db_session_for_task.get(AsyncJob, job_id)
                if final_job_update:
                    final_job_update.status = final_status
                    final_job_update.error_message = error_msg
                    # No result_data for transform jobs
                    final_job_update.progress = 100 if final_status == 'completed' else final_job_update.progress
                    final_job_update.updated_at = datetime.utcnow()
                    # Optionally reset stop_requested flag
                    # final_job_update.stop_requested = False
                    db_session_for_task.add(final_job_update)
                    db_session_for_task.commit()
                    print(f"Final status for job {job_id} ({final_status}) saved to DB.")
                else:
                     print(f"Could not find job {job_id} for final status update.")
            except Exception as db_e:
                 db_session_for_task.rollback()
                 print(f"CRITICAL: Failed to update final status for job {job_id} in DB: {db_e}")


# --- NEW Endpoint to Start PCAP Transformation Job ---
@app.post("/sessions/{session_id}/transform/start", response_model=JobListResponse, tags=["PCAP Anonymization", "Jobs"])
async def start_transformation_job(
    session_id: str,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(get_session)
):
    """Starts the PCAP transformation process as a background task."""
    # Verify session exists before starting the job
    pcap_session = db_session.get(PcapSession, session_id)
    if not pcap_session:
        raise HTTPException(status_code=404, detail=f"Session with ID {session_id} not found.")
    if pcap_session.is_transformed:
         raise HTTPException(status_code=400, detail="Cannot transform an already transformed session.")

    # Create AsyncJob record in DB
    new_job = AsyncJob(
        session_id=session_id,
        job_type='transform',
        status='pending',
        progress=0,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db_session.add(new_job)
    try:
        db_session.commit()
        db_session.refresh(new_job)
        job_id = new_job.id
        print(f"Created AsyncJob record {job_id} for transformation on session {session_id}")
    except Exception as e:
        db_session.rollback()
        print(f"Failed to create AsyncJob record for transformation: {e}")
        raise HTTPException(status_code=500, detail="Failed to initiate transformation job.")

    if job_id is None:
         raise HTTPException(status_code=500, detail="Failed to get job ID after creation.")

    print(f"Starting background task run_apply for job {job_id}")
    background_tasks.add_task(run_apply, job_id, session_id)

    # Return the created job details
    return new_job


# --- REMOVED Old /apply_async endpoint ---
# Use /sessions/{session_id}/transform/start instead


# --- REMOVED Old /status/{job_id} endpoint ---
# Replaced by /jobs/{job_id}


# --- Server-Sent Events (SSE) Endpoint for Job Status (Updated for DB) ---

async def job_event_generator(job_id: int): # job_id is now int
    """Asynchronous generator sending job status updates via SSE by polling the DB."""
    # REMOVED: Global jobs dictionary access
    last_status = None
    last_progress = -1
    last_error = None
    last_result_data_summary = None # Track summary of result_data if needed
    last_trace_name = None # Track trace name

    print(f"SSE connection opened for job {job_id}")
    try:
        while True:
            job_info: Optional[AsyncJob] = None
            # Poll the database for the job status and session name
            with Session(engine) as db_session:
                job_info: Optional[AsyncJob] = None
                trace_name: Optional[str] = None
                try:
                    # Fetch job info first
                    job_info = db_session.get(AsyncJob, job_id)
                    # If job exists, try fetching the associated session name
                    if job_info:
                        session = db_session.get(PcapSession, job_info.session_id)
                        if session:
                            trace_name = session.name
                        else:
                            print(f"SSE: Warning - PcapSession {job_info.session_id} not found for job {job_id}")
                except Exception as e:
                     print(f"SSE: Error fetching job/session info for job {job_id} from DB: {e}")
                     # Send an error event to the client
                     error_payload = json.dumps({"status": "error", "error": f"Database error fetching job: {e}", "job_id": job_id})
                     yield f"data: {error_payload}\n\n"
                     await asyncio.sleep(5) # Wait longer after DB error
                     continue # Try fetching again

            # If job disappears from DB (e.g., deleted manually)
            if not job_info:
                error_payload = json.dumps({"status": "error", "error": "Job not found or deleted", "job_id": job_id})
                yield f"data: {error_payload}\n\n" # Send error event
                print(f"SSE closing for missing job {job_id}")
                break # Stop generation

            # Prepare payload based on JobStatusResponse model structure
            current_status = job_info.status
            current_progress = job_info.progress
            current_error = job_info.error_message
            # Summarize result_data if needed to avoid sending large JSON repeatedly
            current_result_data_summary = str(job_info.result_data) if job_info.result_data else None
            current_trace_name = trace_name # Use the fetched trace_name

            # Check if anything relevant changed (including trace_name)
            if (current_status != last_status or
                current_progress != last_progress or
                current_error != last_error or
                current_result_data_summary != last_result_data_summary or
                current_trace_name != last_trace_name): # Check if trace name changed

                payload_dict = {
                    "id": job_info.id,
                    "session_id": job_info.session_id,
                    "trace_name": current_trace_name, # Include trace name in payload
                    "job_type": job_info.job_type,
                    "status": current_status,
                    "progress": current_progress,
                    "created_at": job_info.created_at.isoformat(), # Use ISO format for JSON
                    "updated_at": job_info.updated_at.isoformat() if job_info.updated_at else None,
                    "error_message": current_error,
                    "result_data": job_info.result_data # Send full result data for now
                }
                current_payload = json.dumps(payload_dict)

                yield f"data: {current_payload}\n\n" # SSE data format
                print(f"SSE sent for job {job_id}: status={current_status}, progress={current_progress}%")

                # Update last sent state
                last_status = current_status
                last_progress = current_progress
                last_error = current_error
                last_result_data_summary = current_result_data_summary
                last_trace_name = current_trace_name # Update last trace name

            # Stop sending events if job is finished (completed or failed)
            if current_status in ['completed', 'failed']:
                print(f"SSE stream closing for finished job {job_id} (status: {current_status})")
                break # Stop generation

            # Wait before checking status again
            await asyncio.sleep(1) # Check every 1 second

    except asyncio.CancelledError:
         print(f"SSE connection for job {job_id} closed by client.")
    except Exception as e:
         print(f"SSE generator error for job {job_id}: {e}")
         traceback.print_exc()
         # Attempt to send a final error message
         try:
             error_payload = json.dumps({"status": "error", "error": f"SSE generator error: {e}", "job_id": job_id})
             yield f"data: {error_payload}\n\n"
         except Exception:
             pass # Ignore errors during final error reporting
    finally:
         print(f"SSE event generation stopped for job {job_id}.")


@app.get("/jobs/{job_id}/events", tags=["Jobs"]) # Updated path
async def stream_job_status(job_id: int): # job_id is now int
    """Endpoint for clients (frontend) to subscribe to job status updates via SSE for any job type."""
    # Check if job exists when client first connects (optional, generator handles it too)
    with Session(engine) as db_session:
        job_exists = db_session.get(AsyncJob, job_id) is not None
    if not job_exists:
         raise HTTPException(status_code=404, detail=f"Job ID {job_id} not found at time of connection")

    # Return a StreamingResponse using the event generator
    return StreamingResponse(job_event_generator(job_id), media_type="text/event-stream")

# --- Main Execution (for development) ---
if __name__ == "__main__":
    import uvicorn
    print("Starting Uvicorn server for development...")
    # Run the FastAPI app using Uvicorn server
    # reload=True automatically restarts server on code changes
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
