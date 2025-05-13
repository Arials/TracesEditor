# Cline Rules - Frontend Job Handling Convention

This document outlines the standard procedure for frontend components that manage and resume long-running asynchronous jobs initiated via the backend. This applies to pages like `SubnetsPage.tsx`, `AsyncPage.tsx`, `MacPage.tsx`, `DicomPage.tsx`, etc.

## Core Principles

1.  **Job State Persistence**: Job IDs that need to be monitored across page loads or browser sessions MAY be stored in `localStorage`.
2.  **Robust Resumption Logic**: Components attempting to resume monitoring a job MUST verify its current status with the backend before establishing an SSE connection or assuming a previous state.
3.  **Centralized API Access**: Backend interactions for job management (status checks, SSE subscriptions) SHOULD utilize helper functions defined in `frontend/src/services/api.ts`.
4.  **Clear User Feedback**: The UI MUST provide clear feedback to the user regarding the job's status (e.g., loading, in progress, completed, failed, not found).
5.  **State Cleanup**: Invalid or completed job IDs MUST be cleared from `localStorage` to prevent erroneous resumption attempts.

## Implementation Steps in Components

When a component mounts or a relevant `jobId` is retrieved (e.g., from `localStorage` or component props):

1.  **Retrieve `jobId`**:
    *   Get the `jobId` from its source (e.g., `localStorage.getItem('lastSubnetJobId')`).

2.  **Verify Job Status (if `jobId` exists)**:
    *   Call a dedicated API function (e.g., `api.getJobDetails(jobId: string): Promise<JobStatus | null>`) from `frontend/src/services/api.ts`. This function should handle potential 404 errors gracefully, returning `null` or a specific status if the job is not found.
    *   The `JobStatus` type should reflect the possible states from the backend (e.g., `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`).

3.  **Conditional Logic Based on Status**:
    *   **If `JobStatus` is `PENDING` or `RUNNING`**:
        *   Proceed to establish the Server-Sent Events (SSE) connection to `/jobs/{jobId}/events`.
        *   Update UI to reflect that the job is active.
    *   **If `JobStatus` is `COMPLETED`, `FAILED`, or `CANCELLED`**:
        *   Do NOT establish an SSE connection.
        *   Update UI to display the final job status and any relevant results or error messages.
        *   Clear the `jobId` from `localStorage` (e.g., `localStorage.removeItem('lastSubnetJobId')`).
    *   **If `getJobDetails` returns `null` (or indicates 'Not Found')**:
        *   Do NOT establish an SSE connection.
        *   Update UI to inform the user that the previously tracked job was not found or is no longer valid.
        *   Clear the `jobId` from `localStorage`.
    *   **During the `getJobDetails` call**:
        *   Display a loading indicator in the UI.

4.  **SSE Event Handling**:
    *   When an SSE connection is active, handle `message` events to update job progress and status.
    *   Handle `error` events from the `EventSource`.
    *   If an event indicates the job has reached a terminal state (`COMPLETED`, `FAILED`, `CANCELLED`):
        *   Close the `EventSource` connection.
        *   Clear the `jobId` from `localStorage`.
        *   Update UI accordingly.

5.  **Component Unmount**:
    *   Ensure any active `EventSource` connections are closed when the component unmounts to prevent memory leaks and unnecessary network activity.

## API Service (`api.ts`)

*   Ensure `frontend/src/services/api.ts` includes:
    *   `getJobDetails(jobId: string): Promise<JobStatus | null>`: Fetches job details. Handles 404s by returning `null` or a specific "not found" status.
    *   A clear type/interface for `JobStatus` (e.g., `interface JobStatus { id: string; status: string; progress?: number; result?: any; error?: string; created_at: string; updated_at: string; }`). The actual fields should match `models.AsyncJob` from the backend.

## Example `useEffect` Structure (Conceptual)

```typescript
useEffect(() => {
  const storedJobId = localStorage.getItem('activeJobId'); // Replace 'activeJobId' with the specific key for the page
  let eventSource: EventSource | null = null;

  if (storedJobId) {
    setLoadingJob(true); // For UI feedback, manage this state variable

    api.getJobDetails(storedJobId)
      .then(jobDetails => {
        if (jobDetails) {
          setJob(jobDetails); // Update local state with full job details, manage this state variable

          if (jobDetails.status === 'PENDING' || jobDetails.status === 'RUNNING') {
            // Subscribe to SSE
            // Ensure API_BASE_URL is correctly sourced, e.g., from a config file
            eventSource = new EventSource(`${import.meta.env.VITE_API_BASE_URL}/jobs/${storedJobId}/events`);
            
            eventSource.onmessage = (event) => {
              const newJobStatus = JSON.parse(event.data);
              setJob(newJobStatus); // Update job status and progress
              if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(newJobStatus.status)) {
                localStorage.removeItem('activeJobId'); // Replace 'activeJobId'
                eventSource?.close();
              }
            };
            
            eventSource.onerror = () => {
              // Handle SSE error, maybe clear job, show error message
              setError('Failed to connect to job updates.'); // Manage this state variable
              localStorage.removeItem('activeJobId'); // Replace 'activeJobId'
              eventSource?.close();
            };
          } else {
            // Job is completed, failed, or cancelled
            localStorage.removeItem('activeJobId'); // Replace 'activeJobId'
          }
        } else {
          // Job not found
          setError('Previously tracked job not found.'); // Manage this state variable
          localStorage.removeItem('activeJobId'); // Replace 'activeJobId'
          setJob(null); // Manage this state variable
        }
      })
      .catch(error => {
        console.error('Error fetching job details:', error);
        setError('Error fetching job details.'); // Manage this state variable
        localStorage.removeItem('activeJobId'); // Replace 'activeJobId'
        setJob(null); // Manage this state variable
      })
      .finally(() => {
        setLoadingJob(false); // Manage this state variable
      });
  }

  return () => {
    eventSource?.close();
  };
}, []); // Or dependency array if job ID can change through other means, e.g. [sessionId]
```

This convention aims to make job handling more predictable and resilient across the application.

## Inter-Page Notification for New PCAP Sessions

When a background job (e.g., IP anonymization, MAC transformation, DICOM V2 anonymization) successfully completes and generates a new PCAP session, other pages that display lists of PCAP sessions (like `UploadPage.tsx`) need to be notified to refresh their data. This is achieved using `localStorage` and the `storage` event.

**1. Job-Initiating Pages (e.g., `SubnetsPage.tsx`, `MacPage.tsx`, `DicomAnonymizationV2Page.tsx`):**

*   **On Job Completion with New Session**:
    *   In the SSE event handler (`onmessage`), when a job's status is `COMPLETED` and the event data (e.g., `newJobStatus.result_data`) contains information about the newly created PCAP session (specifically, fields like `new_pcap_session_id` and `new_pcap_session_name`):
        *   Write a timestamp to a designated `localStorage` key:
            ```typescript
            localStorage.setItem('pcapSessionsLastUpdated', Date.now().toString());
            ```
    *   This action signals that the list of PCAP sessions might have changed.

**2. Session-Listing Pages (e.g., `UploadPage.tsx`, potentially `AsyncPage.tsx`):**

*   **Listen for `localStorage` Changes**:
    *   Implement a `useEffect` hook to add an event listener for the `storage` event on the `window` object.
    *   The event handler should check if `event.key === 'pcapSessionsLastUpdated'`.
    *   If the key matches, it indicates that a new PCAP session may have been created by a background job. The component should then trigger a refresh of its session list (e.g., by re-fetching the data from the backend).
    *   **Important**: Ensure the event listener is cleaned up in the `useEffect`'s return function to prevent memory leaks.

*   **Example `useEffect` for Listening (`UploadPage.tsx`)**:
    ```typescript
    useEffect(() => {
      const handleStorageChange = (event: StorageEvent) => {
        if (event.key === 'pcapSessionsLastUpdated') {
          console.log('UploadPage: Detected pcapSessionsLastUpdated change, refreshing sessions...');
          // Call the function that fetches/refreshes the list of PCAP sessions
          // e.g., fetchPcapSessions(); 
        }
      };

      window.addEventListener('storage', handleStorageChange);

      return () => {
        window.removeEventListener('storage', handleStorageChange);
      };
    }, []); // Empty dependency array ensures this runs once on mount and cleans up on unmount
    ```

This `localStorage`-based mechanism provides a simple way to achieve inter-page communication for refreshing session lists without requiring complex global state management or additional WebSocket/SSE streams solely for this purpose.
