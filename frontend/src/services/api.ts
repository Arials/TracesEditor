// Consolidated API Service
// This file combines functionality from both previous api.ts files
// Located at frontend/services/api.ts and frontend/src/services/api.ts

import axios from 'axios';

// Define the base URL for the backend API
export const API_BASE_URL = 'http://localhost:8000'; // Added export

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
  // New fields to align with backend PcapSessionResponse
  file_type?: string | null; // e.g., "original", "ip_mac_anonymized", "mac_transformed"
  derived_from_session_id?: string | null;
  source_job_id?: number | null;
  actual_pcap_filename?: string | null;
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
  job_type: 'transform' | 'dicom_extract' | 'dicom_anonymize_v2' | 'dicom_metadata_review' | 'mac_oui_update' | 'mac_transform'; // Added MAC job types
  status: 'pending' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled'; // Added cancelling/cancelled
  progress: number;
  created_at: string; // ISO datetime string
  updated_at?: string | null; // ISO datetime string
  error_message?: string | null;
  output_trace_id?: string | null; // ID of the PcapSession created by this job
}

/** Detailed job status, including potential results. */
export interface JobStatusResponse extends JobListResponse {
  result_data?: Record<string, any> | null; // For DICOM results (JSON object)
  // output_trace_id is inherited from JobListResponse
}

/** Type alias for JobStatus, aligning with JobStatusResponse for consistency. */
export type JobStatus = JobStatusResponse;


// --- DICOM Metadata Review Interfaces (New) ---

/** Structure for a single extracted metadata item for review. */
export interface ExtractedMetadataItem {
  name?: string | null;
  vr?: string | null;
  original: string;
  proposed: string;
}

/** Structure for the result_data of a 'dicom_metadata_review' job. */
export interface ExtractedMetadataReviewResponse {
  // Maps IP Pair Key (e.g., "1.2.3.4-5.6.7.8") to its metadata
  [ipPairKey: string]: {
    ae_titles: {
      // Maps AE Title Key (e.g., "calling", "called") to its details
      [aeKey: string]: ExtractedMetadataItem;
    };
    tags: {
      // Maps Tag Key (e.g., "(0x0010, 0x0010)") to its details
      [tagKey: string]: ExtractedMetadataItem;
    };
  };
}


// --- DICOM Extraction Interfaces (Existing - for dicom_extract job type) ---

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

// --- DICOM Anonymization V2 Interfaces ---

/** Structure for the device data within the V2 response. */
interface DeviceDetailsV2 {
  calling_ae?: string;
  called_ae?: string;
  manufacturer?: string;
  [key: string]: string | undefined; // Allow other string properties
}

/** Structure for the map of IP addresses to device details in the V2 response. */
interface DeviceDataV2 {
  [ip_address: string]: DeviceDetailsV2;
}

/** Expected response structure from the /anonymize_dicom_v2/ endpoint. */
export interface AnonymizeDicomV2Response {
  output_pcap_filename: string; // Corrected field name
  device_data: DeviceDataV2;
  verification_summary?: any; // Keep 'any' for now, refine if structure is known
}

// --- MAC Vendor Modification Interfaces (New) ---

/** Settings related to MAC address vendor modification. */
export interface MacSettings {
  csv_url: string;
  last_updated?: string | null; // ISO datetime string
}

/** Represents a rule for transforming MAC addresses based on vendor. */
export interface MacRule {
  original_mac: string; // Changed from source_vendor
  target_vendor: string;
  target_oui: string; // Added target OUI
}

/** Represents an extracted IP address, MAC address, and its identified vendor. */
export interface IpMacPair {
  ip_address: string;
  mac_address: string;
  vendor?: string | null;
}

/** Response model for the endpoint returning extracted IP-MAC pairs. */
export interface IpMacPairListResponse {
  pairs: IpMacPair[];
}

/** Input model for the endpoint that saves MAC transformation rules. */
export interface MacRuleInput {
  session_id: string;
  rules: MacRule[];
}


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

/** Fetches details for a single PCAP session. */
export const getSessionById = (sessionId: string): Promise<PcapSession> => {
  return api.get<PcapSession>(`/sessions/${sessionId}`).then(response => response.data);
};

/** Clears all debug data (sessions, jobs, files) from the backend. */
export const clearAllData = async (): Promise<void> => {
  try {
    const response = await api.post(`${API_BASE_URL}/api/v1/settings/clear-all-data`);
    // Check for non-2xx status codes that axios might not throw as errors by default
    // For a 204 No Content, response.data will be empty.
    if (response.status < 200 || response.status >= 300) {
      // Try to get detail from response if available, otherwise use generic message
      const detail = response.data?.detail || `Request failed with status ${response.status}`;
      throw new Error(detail);
    }
    // No specific data expected on success for a clear operation (204 No Content)
  } catch (error: any) {
    console.error("Error clearing all data:", error);
    if (axios.isAxiosError(error) && error.response) {
      // Use error.response.data.detail if available, otherwise a generic message
      const detail = error.response.data?.detail || `Failed to clear data (status ${error.response.status})`;
      throw new Error(detail);
    }
    // For non-Axios errors or errors without a response object
    throw new Error(error.message || 'An unknown error occurred while clearing data.');
  }
};

// --- Subnet Analysis API Functions ---

/**
 * Fetches the list of detected subnets for a given session and specific PCAP file.
 * @param sessionId - The ID of the session.
 * @param pcapFilename - The logical filename of the PCAP to analyze within the session.
 * @returns Promise resolving to the Axios response containing SubnetInfo[].
 */
export const getSubnets = (sessionId: string, pcapFilename: string): Promise<SubnetInfo[]> => {
  // Backend Endpoint: GET /subnets/{session_id}?pcap_filename=...
  // Axios automatically handles URI encoding for query parameters.
  return api.get<SubnetInfo[]>(`/subnets/${sessionId}`, { params: { pcap_filename: pcapFilename } })
    .then(response => response.data);
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
  console.log(`Subscribing to SSE at: ${url} for job ID: ${jobId}`);
  const es = new EventSource(url); // Use EventSource directly

  let terminalStatusProcessedByOnMessage = false;

  es.onmessage = (event: MessageEvent) => {
    try {
      // Assuming the backend sends JSON strings in the event data
      const payload: JobStatus = JSON.parse(event.data);
      onMessage(payload); // Call the component's onMessage handler first

      // Check if this message indicates a terminal state
      if (payload.status === 'completed' || payload.status === 'failed') {
        terminalStatusProcessedByOnMessage = true;
        console.log(`Terminal status (${payload.status}) processed for job ${jobId}. Flag set.`);
        // The backend will close the stream shortly after sending a terminal status.
        // The EventSource itself will also close if the server closes the connection.
        // No need to call es.close() here from the client side based on message content.
      }
    } catch (e) {
      console.error('Failed to parse SSE message data:', event.data, e);
      // Optionally call onError or ignore parse errors,
      // but be cautious as this might suppress legitimate errors if not handled carefully.
    }
  };

  es.onerror = (err: Event) => { // EventSource error event type is Event
    console.error(`SSE connection error for job ${jobId}:`, err, `readyState: ${es.readyState}`);

    // If a terminal status was processed by onMessage AND the EventSource is now CLOSED,
    // assume it's a normal closure by the server after the job finished.
    // In this case, we suppress the component's generic onError handler.
    if (terminalStatusProcessedByOnMessage && es.readyState === EventSource.CLOSED) {
      console.log(`SSE stream for job ${jobId} closed after terminal status. Suppressing component's onError.`);
    } else {
      // Otherwise, it's a genuine unexpected error or premature closure.
      if (onError) {
        onError(err); // Call the component's onError handler
      }
    }

    // Always ensure the EventSource is closed on any error to prevent retries,
    // unless it was the specific suppressed case and already closed.
    // Calling close() on an already closed EventSource is safe and idempotent.
    es.close();
  };

  return es;
};


// --- NEW Job Management Functions ---

/** Fetches the list of all asynchronous jobs. */
export const listJobs = (): Promise<JobListResponse[]> => {
  return api.get<JobListResponse[]>('/jobs').then(response => response.data);
};

/** Fetches the details and status of a specific job. Handles 404s by returning null. */
export const getJobDetails = async (jobId: number | string): Promise<JobStatus | null> => {
  try {
    const response = await api.get<JobStatusResponse>(`/jobs/${jobId}`);
    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response && error.response.status === 404) {
      console.warn(`Job with ID ${jobId} not found.`);
      return null; // Return null if job is not found (404)
    }
    console.error(`Error fetching job details for job ID ${jobId}:`, error);
    throw error; // Re-throw other errors
  }
};

/** Starts an asynchronous PCAP transformation job (IP/Subnet anonymization). */
export const startTransformationJob = (sessionId: string, inputPcapFilename: string): Promise<JobListResponse> => {
  // Backend Endpoint: POST /apply
  console.log(`[api.ts] Calling POST /apply for session ${sessionId}, input file ${inputPcapFilename}`);
  const formData = new FormData();
  formData.append('session_id', sessionId);
  formData.append('input_pcap_filename', inputPcapFilename);

  // Axios will typically set the Content-Type to multipart/form-data automatically when FormData is used.
  return api.post<JobListResponse>(`/apply`, formData)
    .then(response => response.data);
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

/** Starts an asynchronous DICOM metadata review job. */
export const startDicomMetadataReviewJob = (sessionId: string): Promise<JobListResponse> => {
  // Backend Endpoint: POST /sessions/{session_id}/dicom_metadata_review/start
  console.log(`[api.ts] Calling POST /sessions/${sessionId}/dicom_metadata_review/start`);
  // No payload needed, session_id is in URL
  return api.post<JobListResponse>(`/sessions/${sessionId}/dicom_metadata_review/start`).then(response => response.data);
};


// --- NEW Function to Start Async DICOM V2 Anonymization Job ---
/**
 * Starts an asynchronous DICOM V2 anonymization job for a given session.
 * @param sessionId - The ID of the session containing the PCAP to anonymize.
 * @param debug - Whether to enable debug/verification mode on the backend.
 * @returns Promise resolving to the created job details (JobListResponse).
 */
export const startDicomAnonymizationV2Job = (sessionId: string, debug: boolean): Promise<JobListResponse> => {
  const formData = new FormData();
  formData.append('debug', String(debug)); // Send boolean as string 'true'/'false'

  console.log(`[api.ts] Calling POST /sessions/${sessionId}/anonymize_dicom_v2/start with debug: ${debug}`);

  return api.post<JobListResponse>(
    `/sessions/${sessionId}/anonymize_dicom_v2/start`,
    formData, // Send debug flag in form data
    {
      headers: { 'Content-Type': 'multipart/form-data' }, // Necessary even if only sending form fields without files sometimes
    }
  ).then(response => {
    console.log('[api.ts] Received response from /sessions/.../anonymize_dicom_v2/start:', response.data);
    return response.data;
  }).catch(error => {
    console.error('[api.ts] Error calling /sessions/.../anonymize_dicom_v2/start:', error.response?.data || error.message);
    throw error; // Re-throw
  });
};


// --- MAC Vendor Modification API Functions (New) ---

/** Fetches a sorted list of unique MAC vendor names. */
export const getMacVendors = (): Promise<string[]> => {
  console.log(`[api.ts] Calling GET /mac/vendors`);
  return api.get<string[]>('/mac/vendors').then(response => response.data);
};

/** Fetches the current MAC modification settings. */
export const getMacSettings = (): Promise<MacSettings> => {
  console.log(`[api.ts] Calling GET /mac/settings`);
  return api.get<MacSettings>('/mac/settings').then(response => response.data);
};

/** Fetches the OUI for a specific vendor name. */
export const getOuiForVendor = (vendorName: string): Promise<{ oui: string | null }> => {
  console.log(`[api.ts] Calling GET /mac/vendors/${encodeURIComponent(vendorName)}/oui`);
  // The backend returns { oui: "XX:XX:XX" } or 404/500
  return api.get<{ oui: string | null }>(`/mac/vendors/${encodeURIComponent(vendorName)}/oui`)
    .then(response => response.data)
    .catch(error => {
      // If the backend returns 404, it means the vendor wasn't found.
      // We can return null OUI in this case, but log the error.
      if (error.response && error.response.status === 404) {
        console.warn(`[api.ts] OUI not found for vendor "${vendorName}".`);
        return { oui: null }; // Return null OUI for not found
      }
      // For other errors, re-throw them.
      console.error(`[api.ts] Error fetching OUI for vendor "${vendorName}":`, error.response?.data || error.message);
      throw error;
    });
};

/** Updates the MAC modification settings (specifically the CSV URL). */
export const updateMacSettings = (newUrl: string): Promise<MacSettings> => {
  console.log(`[api.ts] Calling PUT /mac/settings with URL: ${newUrl}`);
  const payload = { csv_url: newUrl };
  // The backend returns the updated settings object on success
  return api.put<MacSettings>('/mac/settings', payload).then(response => response.data);
};

/** Starts a background job to download and update the OUI CSV file. */
export const startMacOuiUpdateJob = (): Promise<JobListResponse> => {
  console.log(`[api.ts] Calling POST /mac/settings/update-csv`);
  // No payload needed for this POST request
  return api.post<JobListResponse>('/mac/settings/update-csv').then(response => response.data);
};

/** Fetches the list of unique IP-MAC pairs with vendor info for a given session. */
export const getIpMacPairs = (sessionId: string, pcapFilename?: string): Promise<IpMacPair[]> => {
  const params = pcapFilename ? { pcap_filename: pcapFilename } : {};
  console.log(`[api.ts] Calling GET /mac/ip-mac-pairs/${sessionId} with params:`, params);
  // Backend now returns IpMacPair[] directly
  return api.get<IpMacPair[]>(`/mac/ip-mac-pairs/${sessionId}`, { params }).then(response => response.data);
};

/** Retrieves the MAC transformation rules for a given session. */
export const getMacRules = (sessionId: string): Promise<MacRule[]> => {
  console.log(`[api.ts] Calling GET /mac/rules/${sessionId}`);
  return api.get<MacRule[]>(`/mac/rules/${sessionId}`).then(response => response.data);
};

/** Saves or updates the MAC transformation rules for a given session. */
export const saveMacRules = (sessionId: string, rules: MacRule[]): Promise<void> => {
  console.log(`[api.ts] Calling PUT /mac/rules`); // Log updated to reflect the change
  const payload: MacRuleInput = { session_id: sessionId, rules };
  return api.put<void>(`/mac/rules`, payload).then(() => undefined); // Return void on success (204 No Content)
};

/** Exports the MAC transformation rules file for download. */
export const exportMacRules = async (sessionId: string): Promise<void> => {
  console.log(`[api.ts] Calling GET /mac/rules/${sessionId}/export`);
  try {
    const response = await api.get(`/mac/rules/${sessionId}/export`, {
      responseType: 'blob', // Important: response is a file blob
    });
    // Create a URL for the blob
    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement('a');
    link.href = url;
    // Extract filename from content-disposition header if available, otherwise use default
    const contentDisposition = response.headers['content-disposition'];
    let filename = `${sessionId}_mac_rules.json`; // Default filename
    if (contentDisposition) {
      const filenameMatch = contentDisposition.match(/filename="?(.+)"?/);
      if (filenameMatch && filenameMatch.length > 1) {
        filename = filenameMatch[1];
      }
    }
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    // Clean up
    link.parentNode?.removeChild(link);
    window.URL.revokeObjectURL(url);
  } catch (error) {
    console.error(`[api.ts] Error exporting MAC rules for session ${sessionId}:`, error);
    // Handle error appropriately (e.g., show notification to user)
    throw error; // Re-throw for the caller to handle
  }
};

/** Imports MAC transformation rules from an uploaded JSON file. */
export const importMacRules = (sessionId: string, file: File): Promise<void> => {
  console.log(`[api.ts] Calling POST /mac/rules/${sessionId}/import`);
  const formData = new FormData();
  formData.append('file', file);
  return api.post<void>(`/mac/rules/${sessionId}/import`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(() => undefined); // Return void on success (204 No Content)
};

/** Starts an asynchronous MAC transformation job. */
export const startMacTransformationJob = (sessionId: string, inputPcapFilename: string): Promise<JobListResponse> => { // Add inputPcapFilename
  console.log(`[api.ts] Calling POST /mac/apply for session ${sessionId}, input file ${inputPcapFilename}`);
  
  const formData = new FormData();
  formData.append('session_id', sessionId);
  formData.append('input_pcap_filename', inputPcapFilename);

  // Axios will typically set the Content-Type to multipart/form-data automatically when FormData is used.
  return api.post<JobListResponse>(`/mac/apply`, formData) // Correct endpoint and send formData
    .then(response => response.data);
};

/** Downloads a specific file associated with a session. */
export const downloadSessionFile = async (sessionId: string, filename: string): Promise<void> => {
  console.log(`[api.ts] Calling GET /sessions/${sessionId}/files/${filename}`);
  try {
    const response = await api.get(`/sessions/${sessionId}/files/${filename}`, {
      responseType: 'blob', // Important: response is a file blob
    });
    // Create a URL for the blob
    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement('a');
    link.href = url;
    // Use the provided filename for the download attribute
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    // Clean up
    link.parentNode?.removeChild(link);
    window.URL.revokeObjectURL(url);
  } catch (error: any) { // Catch specific AxiosError if needed
    console.error(`[api.ts] Error downloading file ${filename} for session ${sessionId}:`, error.response?.data || error.message);
    // Handle error appropriately (e.g., show notification to user)
    // Check if the error response contains specific details
    let detail = `Failed to download file ${filename}.`;
    if (error.response && error.response.data instanceof Blob && error.response.data.type === "application/json") {
      // Try to read the error detail from the JSON blob
      try {
        const errJson = JSON.parse(await error.response.data.text());
        if (errJson.detail) {
          detail = errJson.detail;
        }
      } catch (parseError) {
        console.error("Failed to parse error response blob:", parseError);
      }
    } else if (error.response?.data?.detail) {
       detail = error.response.data.detail;
    }
    // You might want to show this detail to the user via a snackbar or alert
    alert(`Error: ${detail}`); // Simple alert for now
    throw new Error(detail); // Re-throw a more informative error
  }
};


// Export the Axios instance if needed elsewhere
export default api;
