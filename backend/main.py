# --- Imports ---
import asyncio
import json
import os           # Required for file operations (delete)
import shutil
import uuid
from datetime import datetime
from typing import Optional, List, Callable, Dict # Added Dict
from contextlib import asynccontextmanager
from fastapi import (
    FastAPI, UploadFile, File, BackgroundTasks, HTTPException, Depends, Form, Response, status # Added Response, status
)
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, SQLModel, select # Added SQLModel for Update model

# --- Database Imports ---
from database import create_db_and_tables, get_session, PcapSession, engine

# --- Anonymizer Imports ---
from anonymizer import (
    save_rules,
    generate_preview,
    apply_anonymization,
    get_subnets,
    apply_anonymization_response
)
# --- Old Pydantic Models ---
from models import RuleInput
from pydantic import BaseModel


# --- Constants ---
SESSION_DIR = './sessions'
os.makedirs(SESSION_DIR, exist_ok=True)

# --- Global State ---
jobs = {}

# --- Pydantic/SQLModel Models ---
class SessionInput(BaseModel):
    session_id: str

# Model for updating session name/description via PUT request
class PcapSessionUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None


# --- Lifespan Manager ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("FastAPI application starting up...")
    create_db_and_tables()
    yield
    print("FastAPI application shutting down...")

# --- FastAPI Application ---
app = FastAPI(lifespan=lifespan)

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API Endpoints ---

# --- /upload Endpoint (Modified for DB) ---
@app.post("/upload", response_model=PcapSession)
async def upload(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db_session: Session = Depends(get_session)
):
    """Handles PCAP file upload, saves file, creates DB record, returns session info."""
    session_id = str(uuid.uuid4())
    pcap_filename = f"{session_id}.pcap"
    pcap_path = os.path.join(SESSION_DIR, pcap_filename)
    rules_filename = f"{session_id}_rules.json"
    rules_path = os.path.join(SESSION_DIR, rules_filename)

    print(f"Processing upload for new session: {session_id}, name: {name}")
    print(f"Attempting to save uploaded file to: {os.path.abspath(pcap_path)}")

    # 1. Save file
    try:
        with open(pcap_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        print(f"SUCCESS: File successfully saved to: {pcap_path}")
    except Exception as e:
        print(f"ERROR: Failed to save file to {pcap_path}. Error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {e}")
    finally:
        await file.close()

    # 2. Create DB object
    upload_time = datetime.utcnow()
    db_pcap_session = PcapSession(
        id=session_id, name=name, description=description,
        original_filename=file.filename, upload_timestamp=upload_time,
        pcap_path=pcap_path, rules_path=rules_path, updated_at=upload_time
    )

    # 3. Save to DB
    db_session.add(db_pcap_session)
    try:
        db_session.commit()
        db_session.refresh(db_pcap_session)
        print(f"SUCCESS: Session metadata saved to DB for ID: {session_id}")
    except Exception as e:
        db_session.rollback()
        try: # Cleanup file if DB fails
            if os.path.exists(pcap_path): os.remove(pcap_path)
        except OSError: pass
        print(f"Database commit failed for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save session metadata: {e}")

    # 4. Optional: Create empty rules file (temporary backward compatibility)
    try:
        from storage import store
        store(session_id, 'rules', [])
    except Exception as e:
        print(f"Warning: Failed to create initial empty rules file for {session_id}: {e}")

    # 5. Return created session data
    return db_pcap_session


# --- GET /sessions Endpoint ---
@app.get("/sessions", response_model=List[PcapSession])
async def list_sessions(
    db_session: Session = Depends(get_session)
):
    """Retrieve a list of all saved PCAP sessions from the database."""
    print("Request received for GET /sessions")
    try:
        statement = select(PcapSession).order_by(PcapSession.upload_timestamp.desc())
        sessions = db_session.exec(statement).all()
        print(f"Found {len(sessions)} sessions in the database.")
        return sessions
    except Exception as e:
        print(f"Error fetching sessions from database: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve sessions: {e}")

# --- NEW PUT /sessions/{session_id} Endpoint ---
@app.put("/sessions/{session_id}", response_model=PcapSession)
async def update_session(
    session_id: str,
    session_update: PcapSessionUpdate, # Use the new model for request body
    db_session: Session = Depends(get_session)
):
    """Updates the name and/or description of a specific PCAP session."""
    print(f"Request received for PUT /sessions/{session_id}")
    # 1. Fetch the existing session record
    db_pcap_session = db_session.get(PcapSession, session_id)
    if not db_pcap_session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 2. Get updated data from request, excluding fields not set by client
    update_data = session_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No update data provided")

    print(f"Updating session {session_id} with data: {update_data}")
    # 3. Update the fields on the fetched object
    needs_update = False
    for key, value in update_data.items():
        if hasattr(db_pcap_session, key):
            setattr(db_pcap_session, key, value)
            needs_update = True

    # 4. Update the 'updated_at' timestamp if changes were made
    if needs_update:
        db_pcap_session.updated_at = datetime.utcnow()

        # 5. Add, commit, and refresh
        db_session.add(db_pcap_session)
        try:
            db_session.commit()
            db_session.refresh(db_pcap_session)
            print(f"Session {session_id} updated successfully.")
        except Exception as e:
            db_session.rollback()
            print(f"Database commit failed during update for session {session_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to update session metadata: {e}")

    # 6. Return the updated session object
    return db_pcap_session


# --- NEW DELETE /sessions/{session_id} Endpoint ---
@app.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT) # Use 204 status code
async def delete_session(
    session_id: str,
    db_session: Session = Depends(get_session)
):
    """Deletes a PCAP session record and its associated files."""
    print(f"Request received for DELETE /sessions/{session_id}")
    # 1. Fetch the session record
    pcap_session = db_session.get(PcapSession, session_id)
    if not pcap_session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 2. Delete associated files (pcap, rules, anonymized pcap) - use paths from DB record
    files_to_delete = [
        pcap_session.pcap_path,
        pcap_session.rules_path,
        os.path.join(SESSION_DIR, f"{session_id}_anon.pcap") # Construct potential anon file path
    ]
    for file_path in files_to_delete:
        if file_path and os.path.exists(file_path): # Check if path exists
            try:
                os.remove(file_path)
                print(f"Deleted file: {file_path}")
            except OSError as e:
                # Log error but continue to delete DB record if file deletion fails
                print(f"Warning: Failed to delete file {file_path}. Error: {e}")

    # 3. Delete the database record
    db_session.delete(pcap_session)
    try:
        db_session.commit()
        print(f"Session {session_id} deleted successfully from database.")
        # For 204 No Content, we don't return a body
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        db_session.rollback()
        print(f"Database commit failed during delete for session {session_id}: {e}")
        # If DB delete fails, the files might have already been deleted. Consider implications.
        raise HTTPException(status_code=500, detail=f"Failed to delete session record: {e}")


# --- TODO: Modify other endpoints to use the database ---
# Signatures now include db_session dependency, but logic needs update

@app.put("/rules")
async def rules(input: RuleInput, db_session: Session = Depends(get_session)):
    """Saves the transformation rules for a given session."""
    # TODO: Modify to save rules associated with the PcapSession in the DB.
    #       Fetch PcapSession first to verify ID and get rules_path if still used.
    print(f"TODO: Save rules for session {input.session_id} potentially using DB.")
    pcap_session = db_session.get(PcapSession, input.session_id)
    if not pcap_session:
        raise HTTPException(status_code=404, detail="Session not found")
    # Old implementation (uses file path stored during upload):
    return save_rules(input)

@app.get("/preview/{session_id}")
async def preview(session_id: str, db_session: Session = Depends(get_session)):
    """Generates a preview of the anonymization based on current rules."""
    # TODO: Modify generate_preview to accept pcap_path and rules_path/data fetched from DB.
    pcap_session = db_session.get(PcapSession, session_id)
    if not pcap_session:
        raise HTTPException(status_code=404, detail="Session not found")
    print(f"TODO: Fetch paths/rules from DB record for preview of session {session_id}.")
    # Old implementation (uses file path stored during upload):
    return generate_preview(session_id)

@app.post("/apply")
async def apply(input: SessionInput, db_session: Session = Depends(get_session)):
    """Synchronously applies anonymization and returns the file path."""
    # TODO: Modify to fetch paths/rules from DB for session input.session_id
    pcap_session = db_session.get(PcapSession, input.session_id)
    if not pcap_session:
        raise HTTPException(status_code=404, detail="Session not found")
    print(f"TODO: Fetch paths/rules from DB for apply on session {input.session_id}.")
    # Old implementation (uses file path stored during upload):
    return apply_anonymization(input.session_id)

@app.get("/subnets/{session_id}")
async def subnets(session_id: str, db_session: Session = Depends(get_session)):
    """Gets the list of detected subnets from the original PCAP."""
    # TODO: Modify get_subnets to accept pcap_path fetched from DB.
    pcap_session = db_session.get(PcapSession, session_id)
    if not pcap_session:
        raise HTTPException(status_code=404, detail="Session not found")
    print(f"TODO: Fetch pcap_path from DB record for subnets of session {session_id}.")
    # Old implementation (uses file path stored during upload):
    return get_subnets(session_id) # Pass pcap_session.pcap_path instead

@app.get("/download/{session_id}")
async def download_anonymized_pcap(session_id: str, db_session: Session = Depends(get_session)):
    """Provides the anonymized PCAP file for download."""
    # TODO: Modify apply_anonymization_response to accept pcap_session object or paths from DB.
    pcap_session = db_session.get(PcapSession, session_id)
    if not pcap_session:
        raise HTTPException(status_code=404, detail="Session not found")
    print(f"TODO: Fetch data from DB record for download of session {session_id}.")
    try:
        print(f"Download request for session {session_id} (using old logic)")
        return apply_anonymization_response(session_id) # Pass pcap_session object/paths
    except FileNotFoundError:
        print(f"Download failed: Anonymized file not found for session {session_id} (old logic)")
        raise HTTPException(status_code=404, detail="Anonymized file not found.")
    except Exception as e:
        print(f"Download failed for session {session_id} (old logic): {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error preparing file: {str(e)}")

# --- Asynchronous Task Logic ---

def run_apply(job_id: str, session_id: str):
    """Background task function to perform anonymization. Needs DB access."""
    global jobs
    print(f"Background task started for job {job_id}")

    def update_progress(progress_percentage: int):
        if jobs.get(job_id):
            progress_percentage = max(0, min(100, progress_percentage))
            jobs[job_id]['progress'] = progress_percentage

    if jobs.get(job_id):
         jobs[job_id]['status'] = 'running'
         jobs[job_id]['progress'] = 0
    else:
        print(f"Error: Job {job_id} not found in 'jobs' dictionary at start of run_apply.")
        return

    output_path = None # Define output_path before try block
    try:
        # --- Fetch data from DB within the task ---
        # Note: BackgroundTasks run in the same event loop but might need
        # their own DB session depending on context and potential thread usage.
        # Using the global engine directly might be okay for simple sync tasks,
        # but creating a new session is safer.
        with Session(engine) as db_session_for_task: # Create a new session for this task
             pcap_session = db_session_for_task.get(PcapSession, session_id)
             if not pcap_session:
                 raise Exception(f"PcapSession {session_id} not found in DB for job {job_id}")

             # TODO: Modify apply_anonymization to accept paths/rules directly
             #       instead of just session_id to avoid it doing DB/file lookups.
             #       For now, we still call it the old way, assuming it can find files.
             print(f"Running apply_anonymization for job {job_id}, session {session_id}")
             output_path = apply_anonymization(session_id, progress_callback=update_progress)

        # Update status to completed upon successful return
        if jobs.get(job_id):
            jobs[job_id]['status'] = 'completed'
            jobs[job_id]['result'] = output_path # Store path just in case
            jobs[job_id]['progress'] = 100
        print(f"Job {job_id} completed. Output: {output_path}")
        # TODO (Optional): Persist final job status

    except Exception as e:
        print(f"Job {job_id} failed: {str(e)}")
        if jobs.get(job_id):
            jobs[job_id]['status'] = 'failed'
            jobs[job_id]['error'] = str(e)
        # TODO (Optional): Persist final job status


# --- Other Endpoints (Job Status, SSE) ---

@app.post("/apply_async")
async def apply_async(input: SessionInput, background_tasks: BackgroundTasks, db_session: Session = Depends(get_session)):
    """Starts the anonymization process as a background task."""
    # Verify session_id exists in DB before starting
    pcap_session = db_session.get(PcapSession, input.session_id)
    if not pcap_session:
        raise HTTPException(status_code=404, detail=f"Session with ID {input.session_id} not found.")

    global jobs
    job_id = str(uuid.uuid4())
    jobs[job_id] = {'status': 'pending', 'session_id': input.session_id, 'progress': 0}
    print(f"Starting job {job_id} for session {input.session_id} (Name: {pcap_session.name})")
    background_tasks.add_task(run_apply, job_id, input.session_id)
    return {"job_id": job_id}

@app.get("/status/{job_id}")
async def status(job_id: str):
    """Gets the current status and progress of a background job (from memory)."""
    global jobs
    job = jobs.get(job_id)
    if not job:
       raise HTTPException(status_code=404, detail="Unknown or expired job_id")
    return job

# --- SERVER-SENT EVENTS (SSE) ENDPOINT IMPLEMENTATION ---

async def job_event_generator(job_id: str):
    """Asynchronous generator to send job status events based on in-memory 'jobs' dict."""
    global jobs
    last_payload_sent = None
    print(f"SSE connection opened for job {job_id}")
    while True:
        job_info = jobs.get(job_id)
        if not job_info:
            error_payload = json.dumps({"status": "error", "error": "Job not found or expired", "job_id": job_id})
            yield f"data: {error_payload}\n\n"
            print(f"SSE closing for missing job {job_id}")
            break
        current_payload = json.dumps(job_info)
        if current_payload != last_payload_sent:
            yield f"data: {current_payload}\n\n"
            print(f"SSE sent for job {job_id}: {current_payload}")
            last_payload_sent = current_payload
        if job_info.get('status') in ['completed', 'failed']:
            print(f"SSE stream closing for job {job_id} (status: {job_info.get('status')})")
            break
        await asyncio.sleep(1)

@app.get("/status/{job_id}/events")
async def stream_job_status(job_id: str):
    """Endpoint for the frontend to subscribe to job status events."""
    global jobs
    if job_id not in jobs:
         raise HTTPException(status_code=404, detail="Job ID not found at time of connection")
    return StreamingResponse(job_event_generator(job_id), media_type="text/event-stream")

# --- Execution (for development) ---
if __name__ == "__main__":
    import uvicorn
    print("Starting Uvicorn server...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)