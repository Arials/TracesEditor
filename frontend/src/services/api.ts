// Consolidated API Service
// This file combines functionality from both previous api.ts files
// Located at frontend/services/api.ts and frontend/src/services/api.ts

import axios, { AxiosResponse } from 'axios';

// Define the base URL for the backend API
const API_BASE_URL = 'http://localhost:8000';

// Create an Axios instance with the base URL
const api = axios.create({
  baseURL: API_BASE_URL,
});

// --- TypeScript Interfaces ---
// Based on the Python SQLModel/Pydantic models

/** Represents a PCAP session stored in the backend database. */
export interface PcapSession {
  id: string;
  name: string;
  description?: string | null;
  original_filename?: string | null;
  upload_timestamp: string; // FastAPI typically serializes datetime to ISO string
  pcap_path: string;
  rules_path?: string | null;
  updated_at?: string | null; // FastAPI typically serializes datetime to ISO string
  // Fields added for transformed PCAPs
  is_transformed: boolean;
  original_session_id?: string | null;
  async_job_id?: number | null;
}

/** Data structure for updating PCAP session metadata (PUT request body). */
export interface PcapSessionUpdateData {
  name?: string; // Optional: only include fields being updated
  description?: string; // Optional
}

/** Information about a detected subnet in a PCAP file. */
export interface SubnetInfo {
  cidr: string; // CIDR notation (e.g., "192.168.1.0/24")
  ip_count: number; // Number of unique IPs found within this subnet
}

/** A single IP address transformation rule. */
export interface Rule {
  source: string; // Source CIDR
  target: string; // Target CIDR
}

// --- Job Interfaces (Based on Backend Models) ---

/** Base structure for job listing. */
export interface JobListResponse {
  id: number; // Job ID is now an integer
  session_id: string;
  trace_name?: string | null; // Added trace name from backend
  job_type: 'transform' | 'dicom_extract'; // Use specific types
  status: 'pending' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled'; // Added cancelling/cancelled
  progress: number;
  created_at: string; // ISO datetime string
  updated_at?: string | null; // ISO datetime string
  error_message?: string | null;
}

/** Detailed job status, including potential results. */
export interface JobStatusResponse extends JobListResponse {
  result_data?: Record<string, any> | null; // For DICOM results (JSON object)
}

/** Type alias for JobStatus, aligning with JobStatusResponse for consistency. */
export type JobStatus = JobStatusResponse;


// --- DICOM Extraction Interfaces ---

/** Holds the specific DICOM tags extracted (used for both aggregation and update payload). */
export interface DicomExtractedMetadata {
  // From A-ASSOCIATE-RQ/AC
  CallingAE?: string | null;
  CalledAE?: string | null;
  ImplementationClassUID?: string | null;
  ImplementationVersionName?: string | null;
  negotiation_successful?: boolean | null;

  // From P-DATA
  Manufacturer?: string | null;
  ManufacturerModelName?: string | null;
  DeviceSerialNumber?: string | null;
  SoftwareVersions?: any | null; // Keep as 'any' for flexibility
  TransducerData?: any | null; // Keep as 'any'
  StationName?: string | null;
}

/** Represents the aggregated DICOM metadata for a unique Client IP / Server IP pair. */
export interface AggregatedDicomInfo extends DicomExtractedMetadata {
  client_ip: string;
  server_ip: string;
  server_ports: number[]; // List of unique server ports seen
}

/** The overall response structure for the *aggregated* DICOM extraction endpoint. */
export interface AggregatedDicomResponse {
  results: Record<string, AggregatedDicomInfo>; // Maps "client_ip-server_ip" key to aggregated info
  trace_name?: string | null; // Optional: The user-provided name for the session/trace
}

/** Payload for the PUT request to update DICOM metadata overrides. */
export type DicomMetadataUpdatePayload = Partial<DicomExtractedMetadata>; // Use Partial as client sends only changed fields

// --- Session Management API Functions ---

/** Fetches the list of all available PCAP sessions. */
export const listSessions = (): Promise<PcapSession[]> => {
  return api.get<PcapSession[]>('/sessions').then(response => response.data);
};

/** Uploads a new PCAP file with optional metadata. */
export const uploadCapture = (
  file: File,
  name: string,
  description: string | null | undefined,
  onUploadProgress?: (progressEvent: any) => void // Optional progress callback
): Promise<PcapSession> => {
  // Create form data to send the file and metadata
  // Create form data to send the file and metadata
  const formData = new FormData();
  formData.append('file', file);
  // Append other metadata fields expected by the backend endpoint
  formData.append('name', name); // Add name to form data
  // Ensure description is sent as a string, even if null/undefined
  formData.append('description', description || ''); // Add description (or empty string) to form data

  console.log("Uploading file:", file.name, "Name:", name, "Desc:", description);

  // Make POST request with name/desc in the FormData body
  return api.post<PcapSession>(
    '/upload',
    formData, // Request body now contains file, name, and description
    {
      // REMOVED: params: { name, description }, // Do not send as query parameters
      headers: { 'Content-Type': 'multipart/form-data' }, // Header for file uploads
      onUploadProgress: onUploadProgress // Pass progress callback to Axios
    }
  ).then(response => response.data); // Return the PcapSession object of the created session
};

/** Updates metadata (name, description) for an existing session. */
export const updateSession = (sessionId: string, data: PcapSessionUpdateData): Promise<PcapSession> => {
  return api.put<PcapSession>(`/sessions/${sessionId}`, data).then(response => response.data);
};

/** Deletes a specific PCAP session from the backend. */
export const deleteSession = (sessionId: string): Promise<void> => {
  return api.delete<void>(`/sessions/${sessionId}`).then(() => undefined); // Return void/undefined on success
};

// --- Subnet Analysis API Functions ---

/**
 * Fetches the list of detected subnets for a given session.
 * @param sessionId - The ID of the session.
 * @returns Promise resolving to the Axios response containing SubnetInfo[].
 */
export const getSubnets = (sessionId: string): Promise<SubnetInfo[]> => {
  // Backend Endpoint: GET /subnets/{session_id}
  return api.get<SubnetInfo[]>(`/subnets/${sessionId}`).then(response => response.data);
};

/**
 * Saves the transformation rules for a given session.
 * @param sessionId - The ID of the session.
 * @param rules - An array of transformation rules.
 * @returns Promise resolving to the Axios response (typically just status ok).
 */
export const saveRules = (sessionId: string, rules: Rule[]): Promise<any> => {
  // Backend Endpoint: PUT /rules
  // The backend RuleInput model expects { session_id: string, rules: Rule[] }
  const payload = { session_id: sessionId, rules };
  return api.put('/rules', payload).then(response => response.data);
};

/** Generates a preview of the anonymization rules. */
export const previewRules = (sessionId: string, rules: Rule[], limit: number = 5): Promise<string[]> => {
  // Assuming the rules are sent in the request body
  return api.post<string[]>(`/rules/${sessionId}/preview?limit=${limit}`, rules)
    .then(response => response.data);
};

// --- DICOM Metadata API Functions ---

/**
 * Fetches the aggregated DICOM metadata for a given session.
 * @param sessionId - The ID of the session.
 * @returns Promise resolving to AggregatedDicomResponse.
 */
export const getDicomPcapMetadata = (sessionId: string): Promise<AggregatedDicomResponse> => {
  console.log(`[api.ts] Calling GET /dicom/pcap/${sessionId}/extract`);
  return api.get<AggregatedDicomResponse>(`/dicom/pcap/${sessionId}/extract`).then(response => {
    console.log(`[api.ts] Received response for GET /dicom/pcap/${sessionId}/extract:`, response.data);
    // Ensure the response structure matches expectations, especially the 'results' field
    if (response.data && typeof response.data.results === 'object') {
      return response.data;
    } else {
      console.warn('[api.ts] Unexpected response structure for DICOM metadata. Returning empty results.');
      return { results: {} }; // Return default structure on unexpected response
    }
  }).catch(error => {
    console.error(`[api.ts] Error fetching DICOM metadata for session ${sessionId}:`, error);
    // Re-throw the error or return a default error structure
    throw error; // Let the caller handle the error
  });
};

/**
 * Updates DICOM metadata overrides for a specific IP pair in a session.
 * @param sessionId - The ID of the session.
 * @param ipPairKey - The key identifying the IP pair (e.g., "client_ip-server_ip").
 * @param payload - The metadata fields to update.
 * @returns Promise resolving to the Axios response (typically empty on success 204).
 */
export const updateDicomMetadata = (
  sessionId: string,
  ipPairKey: string,
  payload: DicomMetadataUpdatePayload
): Promise<void> => {
  console.log(`[api.ts] Calling PUT /dicom/pcap/${sessionId}/metadata/${ipPairKey}`);
  console.log(`Payload:`, JSON.stringify(payload));
  return api.put<void>(`/dicom/pcap/${sessionId}/metadata/${ipPairKey}`, payload)
    .then(() => {
      console.log(`[api.ts] updateDicomMetadata - Update successful for ${ipPairKey}`);
      return undefined; // Return void/undefined on success (204 No Content)
    })
    .catch(error => {
      console.error(`Error updating DICOM metadata for session ${sessionId}, IP pair ${ipPairKey}:`, error.response?.data || error.message);
      throw error; // Re-throw the error to be caught by the calling component
    });
};

// --- Job Management API Functions ---

/**
 * Starts an asynchronous anonymization job.
 * @param sessionId - The ID of the session.
 * @returns Promise resolving to the Axios response containing { job_id: string }.
 */
// REMOVED: startJob function (used old /apply_async endpoint)

/**
 * Starts an asynchronous DICOM metadata extraction job.
 * @param sessionId - The ID of the session.
 * @returns Promise resolving to the created job details (JobListResponse).
 */
export const startDicomExtractionJob = (sessionId: string): Promise<JobListResponse> => {
  // Backend Endpoint: POST /sessions/{session_id}/dicom/extract/start
  console.log(`[api.ts] Calling POST /sessions/${sessionId}/dicom/extract/start`);
  // No payload needed for this POST request as session_id is in the URL
  // Update the expected response type in the api.post call as well
  return api.post<JobListResponse>(`/sessions/${sessionId}/dicom/extract/start`).then(response => response.data);
};

/**
 * Fetches the current status of a background job.
// REMOVED: getJobStatus function (replaced by getJobDetails)

// REMOVED: applyCapture function (replaced by startTransformationJob)

/**
 * Subscribes to Server-Sent Events (SSE) for real-time job progress updates.
 * @param jobId - The ID of the job to monitor (now a number).
 * @param onMessage - Callback function triggered when a message (event data) is received.
 * @param onError - Optional callback function triggered on SSE connection error.
 * @returns The EventSource instance, allowing manual closure (`es.close()`).
 */
export const subscribeJobEvents = (
  jobId: string,
  onMessage: (data: JobStatus) => void, // Expecting parsed JobStatus data
  onError?: (err: Event | string) => void // Optional onError parameter
): EventSource => {
  // Use the new endpoint and integer job ID
  const url = `${API_BASE_URL}/jobs/${jobId}/events`;
  console.log(`Subscribing to SSE at: ${url}`);
  const es = new EventSource(url); // Use EventSource directly

  es.onmessage = (event: MessageEvent) => {
    try {
      // Assuming the backend sends JSON strings in the event data
      const payload: JobStatus = JSON.parse(event.data);
      onMessage(payload);
    } catch (e) {
      console.error('Failed to parse SSE message data:', event.data, e);
      // Optionally call onError or ignore parse errors
    }
  };

  es.onerror = (err: Event) => { // EventSource error event type is Event
    console.error('SSE connection error:', err);
    if (onError) { // Call optional onError handler
      onError(err); // Pass the Event object
    }
    // Important: Close the connection on error to prevent constant reconnection attempts
    // if the server endpoint isn't available or persistently fails.
    es.close();
  };

  return es;
};


// --- NEW Job Management Functions ---

/** Fetches the list of all asynchronous jobs. */
export const listJobs = (): Promise<JobListResponse[]> => {
  return api.get<JobListResponse[]>('/jobs').then(response => response.data);
};

/** Fetches the details and status of a specific job. */
export const getJobDetails = (jobId: number): Promise<JobStatusResponse> => {
  return api.get<JobStatusResponse>(`/jobs/${jobId}`).then(response => response.data);
};

/** Starts an asynchronous PCAP transformation job. */
export const startTransformationJob = (sessionId: string): Promise<JobListResponse> => {
  // Backend Endpoint: POST /sessions/{session_id}/transform/start
  console.log(`[api.ts] Calling POST /sessions/${sessionId}/transform/start`);
  // No payload needed, session_id is in URL
  return api.post<JobListResponse>(`/sessions/${sessionId}/transform/start`).then(response => response.data);
};

/** Requests a specific job to stop. */
export const stopJob = (jobId: number): Promise<{ message: string }> => {
  // Backend Endpoint: POST /jobs/{job_id}/stop
  console.log(`[api.ts] Calling POST /jobs/${jobId}/stop`);
  return api.post<{ message: string }>(`/jobs/${jobId}/stop`).then(response => response.data);
};

/** Deletes a specific (finished) job record. */
export const deleteJob = (jobId: number): Promise<void> => {
  // Backend Endpoint: DELETE /jobs/{job_id}
  console.log(`[api.ts] Calling DELETE /jobs/${jobId}`);
  return api.delete<void>(`/jobs/${jobId}`).then(() => undefined); // Return void/undefined on success (204 No Content)
};


// Export the Axios instance if needed elsewhere
export default api;
