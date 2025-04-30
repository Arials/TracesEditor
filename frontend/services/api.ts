import axios from 'axios';

// Define the base URL for the backend API
const API_BASE_URL = 'http://localhost:8000';

// Create an Axios instance with the base URL
const api = axios.create({
  baseURL: API_BASE_URL,
});

// --- Interfaces for better type safety ---
// (Ideally, import these from a dedicated types file, e.g., '../types')
interface SubnetInfo {
  cidr: string;
  ip_count: number;
}

interface Rule {
  source: string;
  target: string;
}

interface JobStatus {
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress?: number; // Optional progress percentage
  result?: any; // Result data if completed (e.g., file path, though often not needed if downloading directly)
  error?: string; // Error message if failed
}

// --- API Functions ---

/**
 * Fetches the list of detected subnets for a given session.
 * @param session_id - The ID of the session.
 * @returns Promise resolving to the Axios response containing SubnetInfo[].
 */
export const getSubnets = (session_id: string) => {
  // Backend Endpoint: GET /subnets/{session_id}
  return api.get<SubnetInfo[]>(`/subnets/${session_id}`);
};

/**
 * Saves the transformation rules for a given session.
 * @param session_id - The ID of the session.
 * @param rules - An array of transformation rules.
 * @returns Promise resolving to the Axios response (typically just status ok).
 */
export const saveRules = (session_id: string, rules: Rule[]) => {
  // Backend Endpoint: PUT /rules
  // The backend RuleInput model expects { session_id: string, rules: Rule[] }
  // Axios automatically sends this structure if we pass the object { session_id, rules }
  // However, the backend model RuleInput includes session_id in the body,
  // so we should send the RuleInput structure.
  const payload = { session_id, rules };
  return api.put('/rules', payload);
};


/**
 * Starts an asynchronous anonymization job.
 * @param session_id - The ID of the session.
 * @returns Promise resolving to the Axios response containing { job_id: string }.
 */
export const startJob = (session_id: string) => {
  // Backend Endpoint: POST /apply_async
  // Backend expects SessionInput model: { session_id: string }
  const payload = { session_id };
  return api.post<{ job_id: string }>('/apply_async', payload);
};

/**
 * Fetches the current status of a background job.
 * @param job_id - The ID of the job.
 * @returns Promise resolving to the Axios response containing JobStatus.
 */
export const getJobStatus = (job_id: string) => {
  // Backend Endpoint: GET /status/{job_id}
  return api.get<JobStatus>(`/status/${job_id}`);
};

/**
 * Triggers the download of the anonymized PCAP file for a completed job.
 * NOTE: This function assumes the backend provides a GET endpoint
 * (e.g., '/download/{session_id}') that returns the file directly
 * with appropriate headers (Content-Disposition).
 * @param session_id - The ID of the session whose file should be downloaded.
 */
export const applyCapture = (session_id: string) => {
  // Construct the URL to the download endpoint.
  // *** IMPORTANT: You need to implement this GET endpoint in your backend (`main.py`) ***
  // This endpoint should call `apply_anonymization_response(session_id)`
  // or similar logic to return a FastAPI FileResponse.
  const downloadUrl = `${API_BASE_URL}/download/${session_id}`; // Adjust path if needed

  // Trigger download by navigating or using a link
  // Using window.location.href is simple for GET requests triggering downloads
  console.log(`Attempting to download from: ${downloadUrl}`);
  window.location.href = downloadUrl;

  // Alternative using a hidden link (sometimes more reliable):
  /*
  const link = document.createElement('a');
  link.href = downloadUrl;
  // Optional: Suggest a filename (depends on backend Content-Disposition header)
  // link.download = `${session_id}_anon.pcap`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  */
};


/**
 * Subscribes to Server-Sent Events (SSE) for real-time job progress updates.
 * NOTE: This requires the backend to implement an SSE endpoint at `/status/{job_id}/events`.
 * Your current backend (`main.py`) does NOT have this endpoint implemented.
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

  es.onerror = (err: Event | string) => {
    console.error('SSE connection error:', err);
    if (onError) {
      onError(err);
    }
    // Important: Close the connection on error to prevent constant reconnection attempts
    // if the server endpoint isn't available or persistently fails.
    es.close();
  };

  return es;
};