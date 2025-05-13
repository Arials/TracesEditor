import React, { useState, useEffect, useCallback, useContext } from 'react'; // Added useContext
import { useNavigate, Link as RouterLink } from 'react-router-dom';
import axios from 'axios'; // Import axios for error checking
import {
  listJobs,
  subscribeJobEvents,
  JobListResponse,
  JobStatus,
  stopJob,
  deleteJob,
  downloadSessionFile,
  getSessionById, // Import getSessionById
  PcapSession,    // Import PcapSession
} from '../services/api';
import { SessionContext, useSession } from '../context/SessionContext'; // Import useSession

// Material UI Imports
import {
  Box,
  Typography,
  CircularProgress,
  Alert,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  LinearProgress,
  Chip,
  Button,
  Tooltip,
  IconButton,
  Snackbar, // For notifications
} from '@mui/material';
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline'; // Icon for DICOM result/review link
import DownloadIcon from '@mui/icons-material/Download'; // Icon for potential future download links
import StopCircleIcon from '@mui/icons-material/StopCircle';
import DeleteIcon from '@mui/icons-material/Delete';
import RefreshIcon from '@mui/icons-material/Refresh';

// Define the shape of a row in our jobs table
interface JobRow extends JobListResponse {
  // No extra fields needed
}

// --- Define Props Interface ---
interface AsyncPageProps {
  // refreshSessionList is no longer needed as SessionContext handles updates
}

const AsyncPage: React.FC<AsyncPageProps> = () => { // Removed refreshSessionList from props
  const navigate = useNavigate();
  const { addSession } = useSession(); // Get addSession from context
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null); // For general page errors
  const [notification, setNotification] = useState<{ message: string; severity: 'success' | 'error' | 'warning' | 'info' } | null>(null);
  const [liveJobStatuses, setLiveJobStatuses] = useState<Record<number, JobStatus>>({});
  const [stoppingJobs, setStoppingJobs] = useState<Record<number, boolean>>({});
  const [deletingJobs, setDeletingJobs] = useState<Record<number, boolean>>({});
  const [downloadingFiles, setDownloadingFiles] = useState<Record<string, boolean>>({}); // Tracks download state for individual files

  // --- Data Fetching Callbacks ---

  /**
   * Fetches the list of all background jobs from the backend.
   * Updates component state with the fetched jobs, loading status, and any errors.
   */
  const fetchJobs = useCallback(async () => {
    // console.log('[AsyncPage] Fetching initial job list...');
    setLoading(true);
    setError(null); // Clear previous errors
    try {
      const jobList = await listJobs();
      // console.log('[AsyncPage] Received job list:', jobList);
      setJobs(jobList); // Assuming listJobs returns data compatible with JobRow
      if (jobList.length === 0) {
        setError('No background jobs found.'); // Use info/warning severity later
      }
    } catch (err: any) {
      console.error('[AsyncPage] Error fetching job list:', err);
      let displayMessage = "An unexpected error occurred while fetching the job list.";
      if (axios.isAxiosError(err)) {
        if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
            displayMessage = `Failed to fetch job list: ${err.response.data.detail}`;
        } else if (err.message) {
            displayMessage = `Failed to fetch job list: ${err.message}`;
        }
      } else if (err instanceof Error && err.message) {
        displayMessage = `Failed to fetch job list: ${err.message}`;
      }
      setError(displayMessage);
      setJobs([]); // Clear jobs on error
    } finally {
      setLoading(false);
    }
  }, []);

  // Effect to fetch the initial list of jobs when the component mounts.
  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]); // fetchJobs is memoized, so this runs once on mount.

  // Effect to listen for storage events to refresh jobs (e.g., after clearAllData)
  useEffect(() => {
    const handleStorageChange = (event: StorageEvent) => {
      if (event.key === 'jobDataLastClearedTimestamp') {
        // console.log('[AsyncPage] Detected jobDataLastClearedTimestamp change, refreshing jobs.');
        fetchJobs();
      }
    };

    window.addEventListener('storage', handleStorageChange);

    return () => {
      window.removeEventListener('storage', handleStorageChange);
    };
  }, [fetchJobs]); // Depends on fetchJobs to call the correct instance

  // --- Action Handlers ---

  /**
   * Sends a request to the backend to stop a running or pending job.
   * Manages loading state for the specific job being stopped.
   * @param jobId - The ID of the job to stop.
   */
  const handleStopJob = async (jobId: number) => {
    setStoppingJobs(prev => ({ ...prev, [jobId]: true }));
    try {
      // console.log(`[AsyncPage] Requesting stop for job ${jobId}`);
      await stopJob(jobId);
      // Optionally show a success message, or rely on SSE to update status to 'cancelling'/'cancelled'
      // console.log(`[AsyncPage] Stop request sent for job ${jobId}`);
        // Force a refresh of live status to potentially show 'cancelling' sooner
        setLiveJobStatuses(prev => ({
          ...prev,
          [jobId]: { ...prev[jobId], status: 'cancelling' } as JobStatus, // Optimistic update
        }));
    } catch (err: any) {
      console.error(`[AsyncPage] Error stopping job ${jobId}:`, err);
      let displayMessage = `An unexpected error occurred while trying to stop job ${jobId}.`;
      if (axios.isAxiosError(err)) {
        if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
            displayMessage = `Failed to stop job ${jobId}: ${err.response.data.detail}`;
        } else if (err.message) {
            displayMessage = `Failed to stop job ${jobId}: ${err.message}`;
        }
      } else if (err instanceof Error && err.message) {
        displayMessage = `Failed to stop job ${jobId}: ${err.message}`;
      }
      setError(displayMessage);
    } finally {
      setStoppingJobs(prev => ({ ...prev, [jobId]: false }));
    }
  };

  /**
   * Deletes the record of a job from the backend after user confirmation.
   * Manages loading state for the specific job being deleted.
   * Updates local state to remove the job from the list on success.
   * @param jobId - The ID of the job to delete.
   */
  const handleDeleteJob = async (jobId: number) => {
    if (!window.confirm(`Are you sure you want to delete the record for job ${jobId}? This does not stop a running job.`)) {
      return;
    }
    setDeletingJobs(prev => ({ ...prev, [jobId]: true }));
    try {
      // console.log(`[AsyncPage] Deleting job ${jobId}`);
      await deleteJob(jobId);
      // console.log(`[AsyncPage] Job ${jobId} deleted successfully`);
      // Remove the job from the local state
      setJobs(prev => prev.filter(j => j.id !== jobId));
      // Also remove from live statuses if present
      setLiveJobStatuses(prev => {
        const newState = { ...prev };
        delete newState[jobId];
        return newState;
      });
    } catch (err: any) {
      console.error(`[AsyncPage] Error deleting job ${jobId}:`, err);
      let displayMessage = `An unexpected error occurred while trying to delete job ${jobId}.`;
      if (axios.isAxiosError(err)) {
        if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
            displayMessage = `Failed to delete job ${jobId}: ${err.response.data.detail}`;
        } else if (err.message) {
            displayMessage = `Failed to delete job ${jobId}: ${err.message}`;
        }
      } else if (err instanceof Error && err.message) {
        displayMessage = `Failed to delete job ${jobId}: ${err.message}`;
      }
      setError(displayMessage);
    } finally {
      setDeletingJobs(prev => ({ ...prev, [jobId]: false }));
    }
  };

  /**
   * Initiates the download of a file associated with a job's session.
   * Manages loading state for the specific file download.
   * @param sessionId - The ID of the session containing the file.
   * @param filename - The name of the file to download.
   * @param jobId - The ID of the job (used for managing download loading state key).
   */
  const handleDownloadFile = async (sessionId: string, filename: string, jobId: number) => {
    const downloadKey = `${jobId}-${filename}`; // Unique key for tracking download state
    setDownloadingFiles(prev => ({ ...prev, [downloadKey]: true }));
    setError(null); // Clear previous page-level errors
    try {
      // console.log(`[AsyncPage] Attempting download for session ${sessionId}, file ${filename}`);
      await downloadSessionFile(sessionId, filename);
      // No explicit success message needed as the browser handles the download prompt
    } catch (err: any) {
      console.error(`[AsyncPage] Error downloading file ${filename}:`, err);
      // The downloadSessionFile in api.ts might already format a good message.
      // If not, or for more specific context:
      let displayMessage = `An unexpected error occurred while downloading ${filename}.`;
      if (err instanceof Error && err.message) { // err.message from downloadSessionFile is usually good
        displayMessage = err.message;
      } else if (axios.isAxiosError(err)) {
        if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
            displayMessage = `Failed to download ${filename}: ${err.response.data.detail}`;
        } else if (err.message) {
            displayMessage = `Failed to download ${filename}: ${err.message}`;
        }
      }
      setError(displayMessage);
    } finally {
      setDownloadingFiles(prev => ({ ...prev, [downloadKey]: false }));
    }
  };

  // --- SSE Handling for Live Job Status Updates ---
  useEffect(() => {
    const eventSources: Record<number, EventSource> = {}; // Stores active EventSource connections, keyed by job ID.

    /**
     * Callback function to handle incoming Server-Sent Events (SSE) messages
     * with live updates for a job's status.
     * @param data - The JobStatus object received from the SSE stream.
     */
    const handleJobUpdate = (data: JobStatus) => {
      // console.log(`[AsyncPage] SSE Update for Job ${data.id}:`, data);
      setLiveJobStatuses(prevLiveStatuses => ({
        ...prevLiveStatuses,
        [data.id]: data,
      }));

      // --- Handle new trace creation on job completion ---
      const transformationJobTypes: JobStatus['job_type'][] = ['transform', 'mac_transform', 'dicom_anonymize_v2'];
      if (data.status === 'completed' && transformationJobTypes.includes(data.job_type)) {
        if (data.output_trace_id) {
          // console.log(`[AsyncPage] Transformation job ${data.id} completed. Output trace ID: ${data.output_trace_id}. Fetching details...`);
          getSessionById(data.output_trace_id)
            .then((newlyFetchedSession: PcapSession) => {
              addSession(newlyFetchedSession);
              setNotification({ message: `New trace '${newlyFetchedSession.name}' created successfully.`, severity: 'success' });
              // Navigate to a page where the new trace is visible, e.g., the main list or the new trace's detail page
              // For now, navigating to /uploads which typically shows the Sidebar with the session list.
              navigate('/uploads'); 
            })
            .catch(fetchErr => {
              console.error(`[AsyncPage] Error fetching new trace details for ${data.output_trace_id}:`, fetchErr);
              let displayMessage = `Job ${data.id} completed, but an unexpected error occurred while fetching new trace details.`;
              if (axios.isAxiosError(fetchErr)) {
                if (fetchErr.response && fetchErr.response.data && typeof fetchErr.response.data.detail === 'string') {
                    displayMessage = `Job ${data.id} completed, but failed to fetch new trace details: ${fetchErr.response.data.detail}`;
                } else if (fetchErr.message) {
                    displayMessage = `Job ${data.id} completed, but failed to fetch new trace details: ${fetchErr.message}`;
                }
              } else if (fetchErr instanceof Error && fetchErr.message) {
                displayMessage = `Job ${data.id} completed, but failed to fetch new trace details: ${fetchErr.message}`;
              }
              setNotification({ message: displayMessage, severity: 'error' });
            });
        } else {
          console.warn(`[AsyncPage] Transformation job ${data.id} completed but no output_trace_id was provided.`);
          setNotification({ message: `Job ${data.id} completed, but no output trace ID was found.`, severity: 'warning' });
        }
      }

      // The backend is expected to close the SSE stream when a job reaches a terminal state (completed, failed, cancelled).
    };

    /**
     * Higher-order function to create an error handler for a specific job's SSE connection.
     * @param jobId - The ID of the job whose SSE connection encountered an error.
     * @returns An error handling function for the EventSource.
     */
    const handleSseError = (jobId: number) => (errorEvent: Event | string) => {
      console.error(`[AsyncPage] SSE Connection Error for Job ${jobId}:`, errorEvent);
      // Update the job's live status to indicate an SSE error.
      // This helps the user understand why updates might have stopped.
      setLiveJobStatuses(prevLiveStatuses => ({
        ...prevLiveStatuses,
        [jobId]: { 
          ...(prevLiveStatuses[jobId] || { id: jobId, status: 'unknown' }), // Ensure base object if not present
          status: 'failed', // Or a custom 'sse_error' status if preferred
          error_message: 'SSE connection lost. Status may be outdated.' 
        } as JobStatus, // Type assertion
      }));
      // Clean up the problematic EventSource.
      if (eventSources[jobId]) {
        eventSources[jobId].close();
        delete eventSources[jobId];
      }
    };

    // Iterate over the initially fetched jobs to establish SSE connections for active ones.
    jobs.forEach(job => {
      const currentLiveStatus = liveJobStatuses[job.id]?.status;
      const initialJobStatus = job.status;

      // Determine if an SSE connection should be active for this job.
      // Conditions:
      // 1. No live status yet, and initial status is 'pending' or 'running'.
      // 2. Existing live status is 'pending' or 'running'.
      const shouldBeActive = 
        (!currentLiveStatus && (initialJobStatus === 'pending' || initialJobStatus === 'running')) ||
        (currentLiveStatus === 'pending' || currentLiveStatus === 'running');

      if (shouldBeActive) {
        if (!eventSources[job.id]) { // Avoid creating duplicate EventSource objects.
          // console.log(`[AsyncPage] Subscribing to SSE for active job ${job.id} (Status: ${currentLiveStatus || initialJobStatus})`);
          eventSources[job.id] = subscribeJobEvents(
            job.id.toString(),
            handleJobUpdate,      // Handler for successful messages
            handleSseError(job.id) // Handler for SSE connection errors
          );
        }
      } else {
        // If the job is in a terminal state (completed, failed, etc.) and an EventSource exists, close it.
        if (eventSources[job.id]) {
          // console.log(`[AsyncPage] Closing SSE for job ${job.id} (Status: ${currentLiveStatus || initialJobStatus}) as it's in a terminal state.`);
          eventSources[job.id].close();
          delete eventSources[job.id];
        }
      }
    });

    // Cleanup function: Close all active SSE connections when the component unmounts or when the `jobs` dependency changes.
    // This is crucial to prevent memory leaks and unnecessary network activity.
    return () => {
      // console.log('[AsyncPage] Cleaning up all active SSE connections...');
      Object.values(eventSources).forEach(eventSourceInstance => eventSourceInstance.close());
    };
  }, [jobs, addSession, navigate, liveJobStatuses]); // Added liveJobStatuses to re-evaluate SSE connections if a job is stopped manually.

  /**
   * Helper function to render a Material UI Chip based on the job status.
   * @param status - The status string of the job.
   * @returns A Chip component styled according to the job status.
   */
  const getStatusChip = (status: JobStatus['status']): React.ReactElement => {
    switch (status) {
      case 'completed':
        return <Chip label="Completed" color="success" size="small" variant="outlined" />;
      case 'running':
        return <Chip label="Running" color="info" size="small" variant="outlined" />;
      case 'pending':
        return <Chip label="Pending" color="warning" size="small" variant="outlined" />;
      case 'failed':
        return <Chip label="Failed" color="error" size="small" variant="outlined" />;
      case 'cancelled':
        return <Chip label="Cancelled" color="default" size="small" variant="outlined" />;
      case 'cancelling':
        return <Chip label="Cancelling" color="info" size="small" variant="outlined" />;
      default:
        return <Chip label={status || 'Unknown'} size="small" variant="outlined" />;
    }
  };

  // --- Render ---
  // --- Render ---
  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
        <Typography variant="h5" gutterBottom sx={{ flexGrow: 1, mb: 0 }}>
          Background Job Status
        </Typography>
        <Tooltip title="Refresh Job List">
          <IconButton onClick={fetchJobs} disabled={loading}>
            <RefreshIcon />
          </IconButton>
        </Tooltip>
      </Box>

      {loading && <CircularProgress />}

      {error && !loading && (
        <Alert severity={error.startsWith("No background jobs") ? "info" : "error"} sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {/* Notification Snackbar */}
      {notification && (
        <Snackbar
          open
          autoHideDuration={6000}
          onClose={() => setNotification(null)}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
        >
          <Alert onClose={() => setNotification(null)} severity={notification.severity} sx={{ width: '100%' }}>
            {notification.message}
          </Alert>
        </Snackbar>
      )}

      {!loading && jobs.length > 0 && (
        <TableContainer component={Paper}>
          <Table sx={{ minWidth: 650 }} aria-label="background jobs table">
            <TableHead><TableRow><TableCell>Job ID</TableCell><TableCell>Type</TableCell>
                <TableCell>Trace Name</TableCell> {/* Changed Header */}
                <TableCell>Status</TableCell>
                <TableCell>Progress</TableCell>
                <TableCell>Created</TableCell>
                <TableCell>Last Updated</TableCell><TableCell>Result / Error</TableCell><TableCell>Actions</TableCell>{/* Added Actions Header */}
              </TableRow></TableHead>
            <TableBody>
              {jobs.map((job) => {
                // Use live status if available, otherwise use initial job status
                const displayStatus = liveJobStatuses[job.id] || job;
                const isRunning = displayStatus.status === 'running';
                const isPending = displayStatus.status === 'pending';
                const isCancelling = displayStatus.status === 'cancelling'; // Added cancelling state
                const isFailed = displayStatus.status === 'failed';
                const isCompleted = displayStatus.status === 'completed';
                const isCancelled = displayStatus.status === 'cancelled'; // Added cancelled state

                const canStop = isPending || isRunning;
                const canDelete = isCompleted || isFailed || isCancelled; // Allow deleting cancelled jobs

                return (
                  <TableRow
                    key={job.id}
                    sx={{ '&:last-child td, &:last-child th': { border: 0 } }}
                  ><TableCell component="th" scope="row">
                      {job.id}
                    </TableCell>
                    <TableCell>{displayStatus.job_type}</TableCell>
                    <TableCell>
                      {/* Display trace_name if available, otherwise fallback to session ID */}
                      {displayStatus.trace_name || `Session: ${job.session_id.substring(0, 8)}...`}
                    </TableCell>
                    <TableCell>{getStatusChip(displayStatus.status)}</TableCell>
                    <TableCell>
                      {isRunning ? (
                        <Box sx={{ width: '100%', display: 'flex', alignItems: 'center' }}>
                           <Box sx={{ width: '100%', mr: 1 }}>
                               <LinearProgress variant="determinate" value={displayStatus.progress} />
                           </Box>
                           <Box sx={{ minWidth: 35 }}>
                               <Typography variant="body2" color="text.secondary">{`${Math.round(displayStatus.progress)}%`}</Typography>
                           </Box>
                        </Box>
                      ) : (
                        // Show 100% for completed, 0% otherwise (or keep last known progress for failed?)
                        `${isCompleted ? 100 : displayStatus.progress}%`
                      )}
                    </TableCell>
                    <TableCell>{new Date(job.created_at).toLocaleString()}</TableCell>
                    <TableCell>{displayStatus.updated_at ? new Date(displayStatus.updated_at).toLocaleString() : 'N/A'}</TableCell>
                    <TableCell>
                      {isFailed && (
                        <Tooltip title={displayStatus.error_message || 'Unknown error'}>
                          <Typography color="error" variant="caption" sx={{ fontStyle: 'italic' }}>
                            Error (hover)
                          </Typography>
                        </Tooltip>
                      )}
                      {/* Button for completed 'dicom_extract' jobs */}
                      {isCompleted && displayStatus.job_type === 'dicom_extract' && (
                         <Button
                            size="small"
                            variant="outlined"
                            startIcon={<PlayCircleOutlineIcon />}
                            onClick={() => navigate(`/dicom?job_id=${job.id}`)} // Navigate to DicomPage
                         >
                            View DICOM
                         </Button>
                      )}
                      {/* Button for completed 'dicom_metadata_review' jobs */}
                      {isCompleted && displayStatus.job_type === 'dicom_metadata_review' && (
                         <Button
                            size="small"
                            variant="outlined"
                            startIcon={<PlayCircleOutlineIcon />} // Reuse icon or choose another like RateReviewIcon
                            // Link to the DicomAnonymizationV2Page, passing the job ID
                            component={RouterLink}
                            to={`/dicom-anonymization-v2?job_id=${job.id}`}
                         >
                            Review Metadata
                         </Button>
                      )}
                       {isCompleted && (displayStatus.job_type === 'transform' || displayStatus.job_type === 'mac_transform' || displayStatus.job_type === 'dicom_anonymize_v2') && displayStatus.output_trace_id && (
                        <Button
                          size="small"
                          variant="text" // Changed to text to imply navigation/view
                          color="primary"
                          onClick={() => navigate(`/uploads`)} // Or a specific trace view page
                        >
                          View New Trace
                        </Button>
                       )}
                       {/* Download Rules for MAC Transform */}
                       {isCompleted && displayStatus.job_type === 'mac_transform' && displayStatus.output_trace_id && (
                        <Button
                          size="small"
                          variant="outlined"
                          startIcon={downloadingFiles[`${job.id}-mac_rules.json`] ? <CircularProgress size={16} /> : <DownloadIcon />}
                          onClick={() => handleDownloadFile(displayStatus.output_trace_id!, 'mac_rules.json', job.id)}
                          disabled={downloadingFiles[`${job.id}-mac_rules.json`]}
                          sx={{ ml: 1 }} // Add some margin if next to another button
                        >
                          Download Rules
                        </Button>
                       )}
                    </TableCell>
                    {/* --- Actions Cell --- */}
                    <TableCell>
                      <Box sx={{ display: 'flex', gap: 0.5 }}>
                        {/* Stop Button */}
                        <Tooltip title="Stop Job">
                          {/* Span needed for tooltip when button is disabled */}
                          <span>
                            <IconButton
                              size="small"
                              color="warning"
                              onClick={() => handleStopJob(job.id)}
                              disabled={!canStop || stoppingJobs[job.id] || isCancelling}
                            >
                              {stoppingJobs[job.id] ? <CircularProgress size={20} color="inherit" /> : <StopCircleIcon fontSize="inherit" />}
                            </IconButton>
                          </span>
                        </Tooltip>

                        {/* Delete Button */}
                        <Tooltip title="Delete Job Record">
                           {/* Span needed for tooltip when button is disabled */}
                          <span>
                            <IconButton
                              size="small"
                              color="error"
                              onClick={() => handleDeleteJob(job.id)}
                              disabled={!canDelete || deletingJobs[job.id]}
                            >
                               {deletingJobs[job.id] ? <CircularProgress size={20} color="inherit" /> : <DeleteIcon fontSize="inherit" />}
                            </IconButton>
                          </span>
                        </Tooltip>
                      </Box>
                    </TableCell></TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Box>
  );
};

export default AsyncPage;
