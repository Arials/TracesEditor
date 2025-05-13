## Brief overview
This rule outlines the convention for managing file paths and PCAP file I/O in the backend of the PcapAnonymizer project. The primary goal is to centralize path logic and PCAP handling for consistency and maintainability.

## Backend Path Management
- **Centralized Storage Module:** All backend modules (e.g., `anonymizer.py`, `main.py`, `MacAnonymizer.py`, `DicomAnonymizer.py`) MUST use the `backend/storage.py` module for constructing paths to session-specific files and directories, and for reading/writing session-specific files.
- **Avoid Direct Path Construction:** Do not use `os.path.join` or manual path manipulation with hardcoded directory names (like `'./sessions'`) directly within individual backend scripts for session data. Instead, call the appropriate functions from `storage.py`.
- **Session-Specific Directories (Strategy 2):**
    - Each trace (whether an original upload or a derived trace from a transformation) MUST have its own unique physical directory.
    - The directory name MUST correspond directly to the `PcapSession.id` of that specific trace (e.g., `backend/sessions/<trace_id>/`).
    - The `storage.py` module is responsible for managing these directories (e.g., via `storage.get_session_dir(trace_id)`).
- **Direct ID Usage:** When performing any file operation (read, write, check existence) for a specific trace, the `session_id` corresponding to that trace's `PcapSession.id` MUST be used directly in calls to `storage.py` functions (e.g., `storage.read_pcap_from_session(trace_id, ...)`). There is no need to resolve a different "physical" directory ID.
- **Standardized Filenames:** When possible, use standardized filenames within session directories (e.g., `rules.json`, `capture.pcap`, `mac_rules.json`, `anonymized_....pcap`). The `storage.py` module may provide helper functions for common files (e.g., `storage.store_rules()`, `storage.get_rules()`).

### Generic Path Retrieval
- Functions like `storage.get_session_filepath(trace_id, filename)` return `pathlib.Path` objects for a specific file within the given trace's directory. These are suitable for general file operations.
- If these generic path functions are used directly with libraries that expect string paths (like some Scapy functions, though this is now abstracted), the calling module would be responsible for converting the `Path` object to a string (e.g., `str(my_path_object)`). However, for PCAP operations, the specific utility functions below should be preferred.

### PCAP File Handling with Scapy

To ensure consistency and abstract away Scapy's specific path requirements, the `backend/storage.py` module provides utility functions for reading and writing PCAP files within a specific trace's directory:

-   **`storage.read_pcap_from_session(trace_id: str, filename: str = "capture.pcap") -> PacketList`**:
    Use this function to read a PCAP file from the specified trace's directory. It returns a Scapy `PacketList`.

-   **`storage.write_pcap_to_session(trace_id: str, filename: str, packets: PacketList) -> Path`**:
    Use this function to write a Scapy `PacketList` to a PCAP file within the specified trace's directory. It returns the `pathlib.Path` object of the written file.

-   **`storage.store_uploaded_pcap(trace_id: str, uploaded_file: UploadFile, target_filename: str = "capture.pcap") -> Path`**:
    Use this function to save an `UploadFile` object as a PCAP file in the specified trace's directory. It returns the `pathlib.Path` of the saved file.

These functions handle the necessary `Path` to `str` conversions internally when interacting with Scapy, and manage file opening/closing.

**Preference should be given to using these higher-level utility functions for all PCAP I/O operations related to session files.**


### Handling Chained Transformations

When transformations are chained (e.g., IP/MAC anonymization followed by MAC anonymization):

1.  A transformation function (e.g., `apply_anonymization`) takes the `input_trace_id` and the `input_pcap_filename` to read from.
2.  It generates a `new_output_trace_id` for the resulting derived trace.
3.  It saves the output PCAP file using `storage.write_pcap_to_session(new_output_trace_id, output_pcap_filename, ...)`, placing the file in the *new* directory corresponding to the derived trace.
4.  The backend API endpoint receives the `input_trace_id` and `input_pcap_filename` from the frontend. It starts the background task, passing these IDs.
5.  If a subsequent transformation is requested on the *derived* trace, the frontend sends the `derived_trace_id` and its `pcap_filename` to the API. The API uses this `derived_trace_id` directly for reading the input for the next step.

### API Layer (`main.py`) Considerations

-   API endpoints receiving a `session_id` (which represents a specific `trace_id`) from the frontend should use this ID directly for all file operations via `storage.py`.
-   Helper functions like `resolve_physical_session_details` may still be useful for validating that a `PcapSession` record exists for the given `trace_id` and that the requested `pcap_filename` exists within that trace's directory, but they **SHOULD NOT** attempt to resolve or return a different directory ID (like an `original_session_id`).
-   When creating `AsyncJob` records, the `AsyncJob.session_id` field should generally refer to the *input* trace ID that the job is operating on. The `AsyncJob.output_trace_id` field will store the ID of the newly created derived trace upon successful completion.

### Example (Conceptual)

**Correct (Reading input for a transformation):**
```python
# In main.py endpoint or background task
input_trace_id = "abc-123" # ID of the trace to read from
input_filename = "capture.pcap"
# ... validate input_trace_id exists ...
packets = storage.read_pcap_from_session(input_trace_id, input_filename)
```

**Correct (Writing output of a transformation):**
```python
# In transformation logic (e.g., anonymizer.py)
new_output_trace_id = "def-456" # ID for the new derived trace
output_filename = "anonymized_abc.pcap"
new_packets = ... # Processed packets
# ...
output_path_obj = storage.write_pcap_to_session(new_output_trace_id, output_filename, new_packets)
# The file is now in backend/sessions/def-456/anonymized_abc.pcap
```

**Correct (Reading a derived trace for further processing):**
```python
# In main.py endpoint or background task
derived_trace_id = "def-456" # ID of the derived trace to read
derived_filename = "anonymized_abc.pcap"
# ... validate derived_trace_id exists ...
packets_for_next_step = storage.read_pcap_from_session(derived_trace_id, derived_filename)
