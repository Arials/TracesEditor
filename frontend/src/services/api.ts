import axios from 'axios';

// Define the base URL for the backend API
const API_BASE_URL = 'http://localhost:8000';

// Create an Axios instance with the base URL
const api = axios.create({
  baseURL: API_BASE_URL,
});

// --- TypeScript Interfaces ---
// Based on the Python SQLModel/Pydantic models

export interface PcapSession {
  id: string;
  name: string;
  description?: string | null;
  original_filename?: string | null;
  upload_timestamp: string; // Assuming FastAPI serializes datetime to ISO string
  pcap_path: string;
  rules_path?: string | null;
  updated_at?: string | null; // Assuming FastAPI serializes datetime to ISO string
}

// For the PUT request body when updating name/description
export interface PcapSessionUpdateData {
    name?: string;
    description?: string;
}

// For subnet information
export interface SubnetInfo {
  cidr: string;
  ip_count: number;
}

// For transformation rules (if still used in this format)
export interface Rule {
  source: string;
  target: string;
}

// For background job status
export interface JobStatus {
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress?: number; // Optional progress percentage
  result?: any; // Result data if completed (e.g., file path)
  error?: string; // Error message if failed
  session_id?: string; // Included in the jobs dict
}

// --- API Functions ---

/**
 * Uploads a PCAP file with name and description to start a new session.
 * Corresponds to: POST /upload
 * @param file - The PCAP file to upload.
 * @param name - The user-defined name for the session.
 * @param description - Optional user-defined description.
 * @param onProgress - Optional callback for upload progress percentage (0-100).
 * @returns Promise resolving to the Axios response containing the created PcapSession object.
 */
export const uploadCapture = (
    file: File,
    name: string,
    description: string | null,
    onProgress?: (percent: number) => void
) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('name', name);
  if (description) {
    formData.append('description', description);
  }

  return api.post<PcapSession>( // Expect PcapSession in response data
      '/upload',
      formData,
      { // Axios config
        onUploadProgress: (progressEvent) => {
          if (onProgress && progressEvent.total && progressEvent.total > 0) {
            const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            onProgress(percentCompleted);
          }
        }
      }
  );
};

/**
 * Fetches the list of all saved PCAP sessions.
 * Corresponds to: GET /sessions
 * @returns Promise resolving to the Axios response containing PcapSession[].
 */
export const listSessions = () => {
  return api.get<PcapSession[]>('/sessions');
};

/**
 * Updates the name and/or description for a specific session.
 * Corresponds to: PUT /sessions/{sessionId}
 * @param sessionId - The ID of the session to update.
 * @param data - An object containing the fields to update (PcapSessionUpdateData).
 * @returns Promise resolving to the Axios response containing the updated PcapSession.
 */
export const updateSession = (sessionId: string, data: PcapSessionUpdateData) => {
  return api.put<PcapSession>(`/sessions/${sessionId}`, data);
};

/**
 * Deletes a specific PCAP session and its associated files.
 * Corresponds to: DELETE /sessions/{sessionId}
 * @param sessionId - The ID of the session to delete.
 * @returns Promise resolving to the Axios response (expected status 204 No Content).
 */
export const deleteSession = (sessionId: string) => {
  return api.delete<void>(`/sessions/${sessionId}`); // Expects no response body on success
};


/**
 * Fetches the list of detected subnets for a given session.
 * Corresponds to: GET /subnets/{session_id}
 * NOTE: Backend endpoint needs modification to use the DB to find the correct pcap_path.
 * @param session_id - The ID of the session.
 * @returns Promise resolving to the Axios response containing SubnetInfo[].
 */
export const getSubnets = (session_id: string) => {
  console.warn("API Call: getSubnets - Backend endpoint may still need DB integration.");
  return api.get<SubnetInfo[]>(`/subnets/${session_id}`);
};

/**
 * Saves the transformation rules for a given session.
 * Corresponds to: PUT /rules
 * NOTE: Backend endpoint needs modification to potentially use the DB for rules.
 * @param session_id - The ID of the session.
 * @param rules - An array of transformation rules.
 * @returns Promise resolving to the Axios response (typically just status ok).
 */
export const saveRules = (session_id: string, rules: Rule[]) => {
  console.warn("API Call: saveRules - Backend endpoint may still need DB integration.");
  const payload = { session_id, rules };
  return api.put('/rules', payload);
};

/**
 * Starts an asynchronous anonymization job.
 * Corresponds to: POST /apply_async
 * NOTE: Backend background task (run_apply) needs modification to use the DB.
 * @param session_id - The ID of the session.
 * @returns Promise resolving to the Axios response containing { job_id: string }.
 */
export const startJob = (session_id: string) => {
  console.warn("API Call: startJob - Backend task may still need DB integration.");
  const payload = { session_id };
  return api.post<{ job_id: string }>('/apply_async', payload);
};

/**
 * Fetches the current status of a background job (from backend memory).
 * Corresponds to: GET /status/{job_id}
 * @param job_id - The ID of the job.
 * @returns Promise resolving to the Axios response containing JobStatus.
 */
export const getJobStatus = (job_id: string) => {
  return api.get<JobStatus>(`/status/${job_id}`);
};

/**
 * Triggers the download of the anonymized PCAP file for a completed job.
 * Corresponds to: GET /download/{session_id}
 * NOTE: Backend endpoint needs modification to use the DB.
 * @param session_id - The ID of the session whose file should be downloaded.
 */
export const applyCapture = (session_id: string) => {
  console.warn("API Call: applyCapture - Backend endpoint may still need DB integration.");
  const downloadUrl = `${API_BASE_URL}/download/${session_id}`;
  console.log(`Attempting to download from: ${downloadUrl}`);
  // Trigger download by navigating the browser to the URL
  window.location.href = downloadUrl;
};

/**
 * Subscribes to Server-Sent Events (SSE) for real-time job progress updates.
 * Corresponds to: GET /status/{job_id}/events
 * NOTE: Assumes backend has implemented the SSE endpoint correctly.
 * @param job_id - The ID of the job to monitor.
 * @param onMessage - Callback function triggered when a message (event data) is received.
 * @param onError - Optional callback function triggered on SSE connection error.
 * @returns The EventSource instance, allowing manual closure (`es.close()`).
 */
export const subscribeJobEvents = (
  job_id: string,
  onMessage: (data: JobStatus) => void, // Expecting parsed JobStatus data
  onError?: (err: Event | string) => void
): EventSource => {
  const url = `${API_BASE_URL}/status/${job_id}/events`;
  console.log(`Subscribing to SSE at: ${url}`);
  const es = new EventSource(url);

  es.onmessage = (event: MessageEvent) => {
    try {
      const payload: JobStatus = JSON.parse(event.data);
      onMessage(payload);
    } catch (e) {
      console.error('Failed to parse SSE message data:', event.data, e);
    }
  };

  es.onerror = (err: Event | string) => {
    console.error('SSE connection error:', err);
    if (onError) {
      onError(err);
    }
    es.close(); // Close connection on error
  };

  return es;
};

// No default export is needed if only using named exports for API functions.