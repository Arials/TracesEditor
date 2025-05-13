# Project: Refactoring: Independent Session per Trace

**Project ID:** PJ-IST-001
**Creation Date:** 2025-05-08
**Owner(s):** Cline
**Overall Project Status:** IN PROGRESS
**Priority:** HIGH
**Estimated Deadline:** 

## 1. General Description and Objectives
The primary objective is to refactor the PcapAnonymizer application to treat every trace (original upload or derived from a transformation) as a distinct, independent session. Each such trace will have its own dedicated physical directory for its PCAP file and associated metadata (like rules files), and its own `PcapSession` record in the database.

This "Independent Session per Trace" strategy aims to:
- Simplify backend logic by removing the need for complex physical path resolution (`resolve_physical_session_details`).
- Provide clear isolation for each trace's data and rules.
- Make the system more intuitive, robust, and maintainable.
- Align with best practices for data management and separation of concerns.

## 2. Scope
### 2.1. In Scope
- Refactor backend to treat every trace as an independent session.
- Each trace to have its own physical directory for its PCAP file and associated metadata.
- Each trace to have its own `PcapSession` record in the database.
- Simplify backend logic by removing the `resolve_physical_session_details` helper function.
- Ensure changes align with and reinforce `.clinerules/backend-storage-path-conventions.md`.
- Update frontend to correctly handle and display independent traces, including lineage.
### 2.2. Out of Scope
- Major changes to the core anonymization algorithms themselves (focus is on data structure and flow).
- Introduction of new transformation types not already planned.

## 3. Key Milestones
- **MILESTONE-01:** Database Schema Update - [STATUS: COMPLETED] - (Target Date: )
- **MILESTONE-02:** Backend API and Task Orchestration Refactoring - [STATUS: IN PROGRESS] - (Target Date: )
- **MILESTONE-03:** Transformation Logic Adaptation - [STATUS: COMPLETED] - (Target Date: )
- **MILESTONE-04:** Frontend Adaptation and Integration - [STATUS: IN PROGRESS] - (Target Date: )
- **MILESTONE-05:** Comprehensive Testing and Validation - [STATUS: PENDING] - (Target Date: )

## 4. Detailed Phases and Tasks

### Phase 1: Database Changes (`backend/database.py`)
  **Phase Objective:** Update database models to support independent trace sessions and link job outputs.
  **Phase Status:** COMPLETED

  1.  **Task 1.1:** `AsyncJob` Model: Add `output_trace_id` field. [STATUS: COMPLETED]
      *   **Details:** This field will store the ID of the new `PcapSession` (trace) created as the output of a successful transformation job. It's `nullable=True` and has a foreign key to `PcapSession.id`.
      *   **Assignee:** Cline
      *   **Notes:** As per original plan section 3.
  2.  **Task 1.2:** `AsyncJob` Model: Clarify `session_id` field usage. [STATUS: COMPLETED]
      *   **Details:** The existing `session_id: str` field in `AsyncJob` will consistently store the ID of the *input trace* for the transformation.
      *   **Assignee:** Cline
      *   **Notes:** Comments updated in code as per original plan.
  3.  **Task 1.3:** `AsyncJob` Model: Clarify `trace_name` field usage. [STATUS: COMPLETED]
      *   **Details:** The `trace_name: Optional[str]` field will continue to store the user-friendly name of the input trace.
      *   **Assignee:** Cline
      *   **Notes:** Comments updated in code as per original plan.
  4.  **Task 1.4:** `PcapSession` Model: Confirm no structural changes required. [STATUS: COMPLETED]
      *   **Details:** The `original_session_id` field will be used purely for lineage tracking. Background tasks will be responsible for creating new `PcapSession` instances for each output trace.
      *   **Assignee:** Cline

### Phase 2: Backend API and Task Orchestration Changes (`backend/main.py`)
  **Phase Objective:** Refactor backend API endpoints and background task orchestration to use direct trace IDs and create new trace sessions for outputs.
  **Phase Status:** IN PROGRESS

  1.  **Task 2.1:** Remove `resolve_physical_session_details` function. [STATUS: COMPLETED]
      *   **Details:** This function and its usage throughout `main.py` will be completely removed. Verified not present in current code.
      *   **Assignee:** Cline
  2.  **Task 2.2:** Update Transformation-Triggering API Endpoints. [STATUS: COMPLETED]
      *   **Details:** Endpoints like `/sessions/{id}/transform/start`, `/sessions/{id}/mac_transform/start`, `/sessions/{id}/anonymize_dicom_v2/start` will no longer resolve physical IDs. The `id` path parameter directly identifies the input trace.
      *   **Assignee:** Cline
      *   **Notes:** Confirmed for IP/MAC and MAC transforms; DICOM V2 endpoint updated to align.
  3.  **Task 2.3:** Modify Background Tasks (`run_apply`, `run_mac_transform`, `run_dicom_anonymize_v2`). [STATUS: COMPLETED]
      *   **Details:** Each task function will receive `input_trace_id`, generate `new_output_trace_id`, ensure output directory, determine I/O filenames, call updated core transformation, copy rules, create new `PcapSession` record, and update `AsyncJob`.
      *   **Assignee:** Cline
      *   **Sub-Tasks:**
          *   Task 2.3.1: Receive `input_trace_id`. [STATUS: COMPLETED]
          *   Task 2.3.2: Generate `new_output_trace_id` (e.g., `uuid.uuid4()`). [STATUS: COMPLETED]
          *   Task 2.3.3: Ensure Output Directory Exists (e.g., `storage.get_session_dir(new_output_trace_id)`). [STATUS: COMPLETED]
          *   Task 2.3.4: Determine Input/Output PCAP Filenames (input from job, output standardized to "capture.pcap"). [STATUS: COMPLETED]
          *   Task 2.3.5: Call Updated Core Transformation Function with new signature. [STATUS: COMPLETED]
          *   Task 2.3.6: Copy Relevant Rule Files from input trace to new output trace directory. [STATUS: COMPLETED]
          *   Task 2.3.7: Create New `PcapSession` Record for the output trace. [STATUS: COMPLETED]
          *   Task 2.3.8: Update `AsyncJob` Record (status to "completed", populate `output_trace_id`). [STATUS: COMPLETED]
  4.  **Task 2.4:** Update `GET /sessions` Endpoint. [STATUS: COMPLETED]
      *   **Details:** Simplify the endpoint to return all traces directly from the `PcapSession` table. Logic updated to fetch all `PcapSession` and determine `file_type` based on `AsyncJob`.
      *   **Assignee:** Cline
  5.  **Task 2.5:** Update Other Endpoints (rules, preview, IP-MAC pairs, DICOM metadata, etc.). [STATUS: COMPLETED]
      *   **Details:** Ensure all endpoints operating on a specific trace use the route `id` directly as `trace_id` for `storage.py` and database interactions. No physical ID resolution.
      *   **Assignee:** Cline
      *   **Notes:** Reviewed for `main.py`; largely compliant.

### Phase 3: Transformation Logic Changes (Core Anonymizers)
  **Phase Objective:** Adapt core transformation functions in `anonymizer.py`, `MacAnonymizer.py`, and `DicomAnonymizer.py` to accept input/output trace IDs and filenames.
  **Phase Status:** COMPLETED

  1.  **Task 3.1:** `backend/anonymizer.py` (`apply_anonymization`). [STATUS: COMPLETED]
      *   **Details:** Update function signature to `(input_trace_id, input_pcap_filename, new_output_trace_id, output_pcap_filename, ...)`. Read inputs using `storage.py` with `input_trace_id`. Write outputs using `storage.py` to `new_output_trace_id`.
      *   **Assignee:** Cline
      *   **Notes:** `apply_anonymization_response` helper marked for potential deprecation.
  2.  **Task 3.2:** `backend/MacAnonymizer.py` (`apply_mac_transformation`). [STATUS: COMPLETED]
      *   **Details:** Similar signature and logic updates as Task 3.1 for MAC transformation.
      *   **Assignee:** Cline
  3.  **Task 3.3:** `backend/DicomAnonymizer.py` (`anonymize_dicom_v2`). [STATUS: COMPLETED]
      *   **Details:** Similar signature and logic updates as Task 3.1 for DICOM V2 anonymization.
      *   **Assignee:** Cline

### Phase 4: Frontend Impact
  **Phase Objective:** Adapt frontend components and state management to handle each trace as an independent entity, including fetching, displaying, and interacting with new traces created from transformations.
  **Phase Status:** IN PROGRESS

  1.  **Task 4.1:** Job Polling and `output_trace_id` Handling. [STATUS: COMPLETED]
      *   **Details:** Modify job completion logic (`AsyncPage.tsx`) to extract `output_trace_id` from `AsyncJob` response. Ensure frontend `AsyncJob` type includes `output_trace_id`.
      *   **Assignee:** Cline
  2.  **Task 4.2:** New Trace Integration into Frontend State. [STATUS: COMPLETED]
      *   **Details:** Upon obtaining `output_trace_id`, fetch full `PcapSession` details for the new trace and integrate into global state (`SessionContext.tsx`).
      *   **Assignee:** Cline
  3.  **Task 4.3:** User Interface (UI) Updates for New Traces. [STATUS: COMPLETED]
      *   **Details:** Ensure session lists refresh automatically. Provide user notifications (Snackbar). Implement navigation to the new trace upon creation.
      *   **Assignee:** Cline
  4.  **Task 4.4:** Display and Management of Traces. [STATUS: COMPLETED]
      *   **Details:** Unified trace list. Implement lineage indication (e.g., in name, tooltip). Ensure consistent actions operate on the specific `trace.id`.
      *   **Assignee:** Cline
  5.  **Task 4.5:** Impact on Specific Frontend Components/Pages. [STATUS: COMPLETED]
      *   **Details:** Update `AsyncPage.tsx`, `SessionContext.tsx`, `Sidebar.tsx`, transformation trigger pages, and `UploadPage.tsx` to reflect the new model.
      *   **Assignee:** Cline
  6.  **Task 4.6:** Error Handling and Edge Cases (Frontend). [STATUS: COMPLETED]
      *   **Details:** Handle job completion without `output_trace_id`, failed new trace fetches, and prevent stale data.
      *   **Assignee:** Cline
  7.  **Task 4.7:** Testing Strategy for Frontend Changes. [STATUS: PENDING]
      *   **Details:** Define and execute end-to-end tests, UI/UX validation, and error state testing.
      *   **Assignee:** User/QA

### Phase 5: Final Testing and Validation
  **Phase Objective:** Ensure all backend and frontend changes are working correctly and robustly through comprehensive testing.
  **Phase Status:** PENDING

  1.  **Task 5.1:** Update and Execute Backend Tests for `GET /sessions`. [STATUS: PENDING]
      *   **Details:** Corresponds to pending tests from original plan's section 4 (Task 2.4.5 in this plan).
      *   **Assignee:** User/QA
  2.  **Task 5.2:** Update and Execute Backend Tests for Other Endpoints. [STATUS: PENDING]
      *   **Details:** Corresponds to pending tests from original plan's section 4 (Task 2.5.7 in this plan).
      *   **Assignee:** User/QA
  3.  **Task 5.3:** Execute Frontend Testing Strategy (as defined in Task 4.7). [STATUS: PENDING]
      *   **Assignee:** User/QA
