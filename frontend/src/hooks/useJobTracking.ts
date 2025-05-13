import { useState, useEffect, useCallback, useRef } from 'react';
import { JobStatus, subscribeJobEvents, getJobDetails as fetchJobDetailsAPI } from '../services/api';

/**
 * Options for configuring the `useJobTracking` hook.
 */
interface UseJobTrackingOptions {
  /** Optional localStorage key to persist the job ID. If provided, the hook attempts to resume tracking this job on mount. */
  jobIdLocalStorageKey?: string;
  /** Optional callback triggered on any job status update received via SSE or initial fetch. */
  onJobUpdate?: (status: JobStatus) => void;
  /** Optional callback triggered when the job status becomes 'completed'. */
  onJobSuccess?: (status: JobStatus) => void;
  /** Optional callback triggered when the job status becomes 'failed' or 'cancelled'. */
  onJobFailure?: (status: JobStatus) => void;
  /** Optional callback for SSE connection errors. */
  onSseError?: (error: Event | string) => void;
  /** Optional callback to trigger a data refresh directly, for same-tab updates. */
  onJobSuccessTriggerRefresh?: () => void; 
}

/**
 * Return type of the `useJobTracking` hook.
 */
interface UseJobTrackingReturn {
  /** The current status of the tracked job, or null if no job is active. */
  jobStatus: JobStatus | null;
  /** Boolean indicating if the hook is currently fetching details for a resumed job. */
  isLoadingJobDetails: boolean;
  /** Boolean indicating if a job is currently being started, or if the active job is 'pending' or 'running'. */
  isProcessing: boolean;
  /** Stores error messages related to starting a job, fetching job details, or SSE connection issues. */
  error: string | null;
  /**
   * Function to start a new job.
   * @param apiCall - An asynchronous function that calls the backend API to initiate the job.
   *                  This function must return a Promise resolving to either an object with the job `id` (e.g., `{ id: number }`)
   *                  or the full initial `JobStatus` object.
   * @returns A Promise that resolves when the job start process (including initial SSE subscription if applicable) is complete.
   */
  startJob: (
    apiCall: () => Promise<{ id: number } | JobStatus>
  ) => Promise<void>;
  /** Function to clear the current job status, any errors, and the persisted job ID from localStorage (if configured). */
  resetJobState: () => void;
}

/**
 * Custom React hook for tracking the status of a long-running backend job.
 * It handles:
 * - Starting a new job via a provided API call.
 * - Persisting the job ID in localStorage to resume tracking across sessions/refreshes (optional).
 * - Subscribing to Server-Sent Events (SSE) for real-time status updates.
 * - Fetching initial job details if resuming.
 * - Providing callbacks for job lifecycle events (update, success, failure, SSE error).
 * - Managing loading, processing, and error states.
 *
 * @param options - Configuration options for the hook.
 * @returns An object containing the job status, loading/processing states, error messages, and functions to start/reset a job.
 */
export const useJobTracking = ({
  jobIdLocalStorageKey,
  onJobUpdate,
  onJobSuccess,
  onJobFailure,
  onSseError,
  onJobSuccessTriggerRefresh, // Destructure the new callback
}: UseJobTrackingOptions = {}): UseJobTrackingReturn => {
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [isLoadingJobDetails, setIsLoadingJobDetails] = useState<boolean>(false);
  const [isStartingJob, setIsStartingJob] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const eventSourceRef = useRef<EventSource | null>(null);
  const currentJobIdRef = useRef<number | null>(null); // To manage current job ID for SSE

  const isProcessing = isStartingJob || jobStatus?.status === 'pending' || jobStatus?.status === 'running';

  // --- Helper to clear persisted job ID ---
  const clearPersistedJobId = useCallback(() => {
    if (jobIdLocalStorageKey) {
      localStorage.removeItem(jobIdLocalStorageKey);
    }
  }, [jobIdLocalStorageKey]);

  // --- Helper to close SSE ---
  const closeSse = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
      // console.log(`SSE closed for job ${currentJobIdRef.current}`);
    }
  }, []);


  // --- SSE Event Handlers ---
  const handleSseUpdate = useCallback((newStatus: JobStatus) => {
    setJobStatus(newStatus);
    onJobUpdate?.(newStatus);

    if (newStatus.status === 'completed') {
      onJobSuccess?.(newStatus);
      onJobSuccessTriggerRefresh?.(); // Call same-tab refresh callback
      console.log('useJobTracking (SSE): Setting localStorage for cross-tab update.'); 
      localStorage.setItem('pcapSessionsLastUpdated', new Date().toISOString()); 
      clearPersistedJobId();
      closeSse();
    } else if (['failed', 'cancelled'].includes(newStatus.status)) {
      onJobFailure?.(newStatus);
      clearPersistedJobId();
      closeSse();
    }
  }, [onJobUpdate, onJobSuccess, onJobFailure, clearPersistedJobId, closeSse, onJobSuccessTriggerRefresh]); // Add onJobSuccessTriggerRefresh to dependencies

  const handleSseError = useCallback((err: Event | string) => {
    console.error('useJobTracking SSE Error:', err);
    setError('SSE connection error. Job status may be outdated.');
    onSseError?.(err);
    // Don't clear persisted ID here, job might still be running on backend.
    // Consider if we should attempt to fetch final status or let user handle.
    closeSse(); // Close SSE on error to prevent repeated attempts from this instance
  }, [onSseError, closeSse]);


  // --- Function to initiate SSE subscription ---
  const subscribeToJob = useCallback((jobId: number) => {
    closeSse(); // Ensure any previous connection is closed
    currentJobIdRef.current = jobId;
    // console.log(`Subscribing to SSE for job ${jobId}`);
    eventSourceRef.current = subscribeJobEvents(jobId.toString(), handleSseUpdate, handleSseError);
  }, [closeSse, handleSseUpdate, handleSseError]);


  // --- Effect to resume job from localStorage ---
  useEffect(() => {
    if (!jobIdLocalStorageKey) return;

    const storedJobIdStr = localStorage.getItem(jobIdLocalStorageKey);
    if (storedJobIdStr) {
      const jobId = parseInt(storedJobIdStr, 10);
      if (isNaN(jobId)) {
        clearPersistedJobId();
        return;
      }

      currentJobIdRef.current = jobId;
      setIsLoadingJobDetails(true);
      setError(null);

      fetchJobDetailsAPI(jobId)
        .then(details => {
          if (details) {
            setJobStatus(details);
            onJobUpdate?.(details); // Notify listener of initial status
            if (['pending', 'running'].includes(details.status)) {
              subscribeToJob(details.id);
            } else {
              // Job already in terminal state
              if (details.status === 'completed') {
                onJobSuccess?.(details);
                onJobSuccessTriggerRefresh?.(); // Call same-tab refresh callback
                console.log('useJobTracking (Resume): Setting localStorage for cross-tab update.');
                localStorage.setItem('pcapSessionsLastUpdated', new Date().toISOString()); 
              } else if (['failed', 'cancelled'].includes(details.status)) {
                onJobFailure?.(details);
              }
              clearPersistedJobId(); // Clear if already terminal
            }
          } else {
            setError(`Job (ID: ${jobId}) not found.`);
            clearPersistedJobId();
          }
        })
        .catch(err => {
          console.error('Error fetching job details on resume:', err);
          setError('Failed to fetch details of a previously tracked job.');
          // Don't clear persisted ID, allow potential manual retry or observation
        })
        .finally(() => {
          setIsLoadingJobDetails(false);
        });
    }
    // No cleanup for eventSourceRef here, as it's managed by subscribeToJob and closeSse
  }, [jobIdLocalStorageKey, clearPersistedJobId, subscribeToJob, onJobUpdate, onJobSuccess, onJobFailure, onJobSuccessTriggerRefresh]); // Add onJobSuccessTriggerRefresh


  // --- Function to start a new job ---
  const startJob = useCallback(async (apiCall: () => Promise<{ id: number } | JobStatus>) => {
    setIsStartingJob(true);
    setError(null);
    setJobStatus(null); // Clear previous job status
    closeSse(); // Close any existing SSE connection
    currentJobIdRef.current = null;

    try {
      const result = await apiCall();
      // Type guard to differentiate between {id: number} and JobStatus
      const initialJobId = 'id' in result && typeof result.id === 'number' && !('status' in result) ? result.id : (result as JobStatus).id;
      const initialStatus = 'status' in result ? result as JobStatus : null;


      if (initialStatus) {
        setJobStatus(initialStatus); // Set initial status if full object returned
        onJobUpdate?.(initialStatus);
      } else {
        // If only ID is returned, set a temporary pending status.
        setJobStatus({ id: initialJobId, status: 'pending', progress: 0 } as JobStatus); // Minimal status
        onJobUpdate?.({ id: initialJobId, status: 'pending', progress: 0 } as JobStatus);
      }
      
      currentJobIdRef.current = initialJobId;

      if (jobIdLocalStorageKey) {
        localStorage.setItem(jobIdLocalStorageKey, initialJobId.toString());
      }

      // Subscribe if job is not already in a terminal state from initial response
      if (!initialStatus || ['pending', 'running'].includes(initialStatus.status)) {
         subscribeToJob(initialJobId);
      } else {
        // If job started and immediately completed/failed (e.g., validation error returned as job status)
        if (initialStatus.status === 'completed') {
          onJobSuccess?.(initialStatus);
          onJobSuccessTriggerRefresh?.(); // Call same-tab refresh callback
          console.log('useJobTracking (StartJob): Setting localStorage for cross-tab update.'); 
          localStorage.setItem('pcapSessionsLastUpdated', new Date().toISOString()); 
        } else if (['failed', 'cancelled'].includes(initialStatus.status)) {
          onJobFailure?.(initialStatus);
        }
        clearPersistedJobId(); // Clear if terminal from start
      }

    } catch (err: any) {
      console.error('Error starting job:', err);
      const errorMessage = err?.response?.data?.detail || err.message || 'Failed to start job.';
      setError(errorMessage);
      setJobStatus(null); // Ensure jobStatus is cleared on error
      // Provide a minimal JobStatus-like object for onJobFailure
      onJobFailure?.({ id: currentJobIdRef.current ?? -1, status: 'failed', error_message: errorMessage, progress:0, job_type: 'transform', session_id: '', created_at: new Date().toISOString(), updated_at: new Date().toISOString() }); // Changed 'unknown' to 'transform'
      clearPersistedJobId(); // Clear any potentially set (but failed) job ID
    } finally {
      setIsStartingJob(false);
    }
  }, [jobIdLocalStorageKey, closeSse, subscribeToJob, clearPersistedJobId, onJobUpdate, onJobSuccess, onJobFailure, onJobSuccessTriggerRefresh]); // Add onJobSuccessTriggerRefresh

  // --- Function to reset state ---
  const resetJobState = useCallback(() => {
    closeSse();
    setJobStatus(null);
    setError(null);
    setIsLoadingJobDetails(false);
    setIsStartingJob(false);
    clearPersistedJobId();
    currentJobIdRef.current = null;
  }, [closeSse, clearPersistedJobId]);


  // --- Cleanup on unmount ---
  useEffect(() => {
    return () => {
      closeSse();
      // Do not clear localStorage on unmount, as the job might still be running
      // and should be resumable if the component remounts.
    };
  }, [closeSse]);

  return {
    jobStatus,
    isLoadingJobDetails,
    isProcessing,
    error,
    startJob,
    resetJobState,
  };
};
