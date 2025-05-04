import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  listJobs,
  subscribeJobEvents,
  JobListResponse,
  JobStatus, // Use the JobStatus type alias from api.ts
  stopJob,   // Import stopJob
  deleteJob, // Import deleteJob
} from '../services/api';

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
  IconButton, // Import IconButton
} from '@mui/material';
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline'; // Icon for DICOM result link
import DownloadIcon from '@mui/icons-material/Download'; // Icon for potential future download links
import StopCircleIcon from '@mui/icons-material/StopCircle'; // Icon for Stop button
import DeleteIcon from '@mui/icons-material/Delete'; // Icon for Delete button
import RefreshIcon from '@mui/icons-material/Refresh'; // Icon for Refresh button

// Define the shape of a row in our jobs table
interface JobRow extends JobListResponse {
  // No extra fields needed currently, inherits all from JobListResponse
}

const AsyncPage: React.FC = () => {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [liveJobStatuses, setLiveJobStatuses] = useState<Record<number, JobStatus>>({}); // Store live updates by job ID
  const [stoppingJobs, setStoppingJobs] = useState<Record<number, boolean>>({}); // Track stopping state by job ID
  const [deletingJobs, setDeletingJobs] = useState<Record<number, boolean>>({}); // Track deleting state by job ID

  // --- Fetch Initial Job List ---
  const fetchJobs = useCallback(async () => {
    console.log('[AsyncPage] Fetching initial job list...');
    setLoading(true);
    setError(null);
    try {
      const jobList = await listJobs();
      console.log('[AsyncPage] Received job list:', jobList);
      setJobs(jobList); // Assuming listJobs returns data compatible with JobRow
      if (jobList.length === 0) {
        setError('No background jobs found.'); // Use info/warning severity later
      }
    } catch (err: any) {
      console.error('[AsyncPage] Error fetching job list:', err);
      setError(err?.response?.data?.detail || err?.message || 'Failed to fetch job list.');
      setJobs([]); // Clear jobs on error
    } finally {
      setLoading(false);
    }
  }, []);

  // --- Effect for Initial Fetch ---
  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  // --- Action Handlers ---
  const handleStopJob = async (jobId: number) => {
    setStoppingJobs(prev => ({ ...prev, [jobId]: true }));
    try {
      console.log(`[AsyncPage] Requesting stop for job ${jobId}`);
      await stopJob(jobId);
      // Optionally show a success message, or rely on SSE to update status to 'cancelling'/'cancelled'
      console.log(`[AsyncPage] Stop request sent for job ${jobId}`);
      // Force a refresh of live status to potentially show 'cancelling' sooner
      setLiveJobStatuses(prev => ({
        ...prev,
        [jobId]: { ...prev[jobId], status: 'cancelling' } as JobStatus, // Optimistic update
      }));
    } catch (err: any) {
      console.error(`[AsyncPage] Error stopping job ${jobId}:`, err);
      setError(`Failed to stop job ${jobId}: ${err?.response?.data?.detail || err?.message || 'Unknown error'}`);
    } finally {
      setStoppingJobs(prev => ({ ...prev, [jobId]: false }));
    }
  };

  const handleDeleteJob = async (jobId: number) => {
    if (!window.confirm(`Are you sure you want to delete the record for job ${jobId}?`)) {
      return;
    }
    setDeletingJobs(prev => ({ ...prev, [jobId]: true }));
    try {
      console.log(`[AsyncPage] Deleting job ${jobId}`);
      await deleteJob(jobId);
      console.log(`[AsyncPage] Job ${jobId} deleted successfully`);
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
      setError(`Failed to delete job ${jobId}: ${err?.response?.data?.detail || err?.message || 'Unknown error'}`);
    } finally {
      setDeletingJobs(prev => ({ ...prev, [jobId]: false }));
    }
  };

  // --- SSE Handling for Live Updates ---
  useEffect(() => {
    const eventSources: Record<number, EventSource> = {};

    // Function to handle incoming SSE messages
    const handleJobUpdate = (data: JobStatus) => {
      console.log(`[AsyncPage] SSE Update for Job ${data.id}:`, data);
      setLiveJobStatuses(prev => ({
        ...prev,
        [data.id]: data, // Update the status for the specific job ID
      }));

      // If job completes or fails, stop listening for this specific job?
      // Or let the SSE generator on the backend handle closing the stream.
      // Current backend implementation closes stream on completion/failure.
    };

    // Function to handle SSE errors
    const handleJobError = (jobId: number) => (err: Event | string) => {
      console.error(`[AsyncPage] SSE Error for Job ${jobId}:`, err);
      // Maybe update the status to show a connection error?
      setLiveJobStatuses(prev => ({
        ...prev,
        [jobId]: { ...prev[jobId], status: 'failed', error_message: 'SSE Connection Error' } as JobStatus,
      }));
      // Clean up this specific EventSource
      if (eventSources[jobId]) {
        eventSources[jobId].close();
        delete eventSources[jobId];
      }
    };

    // Subscribe to events for jobs that are still pending or running
    jobs.forEach(job => {
      const liveStatus = liveJobStatuses[job.id]?.status;
      const initialStatus = job.status;
      // Subscribe if we don't have a live status yet and the initial status is pending/running,
      // OR if the live status we have is still pending/running.
      if ((!liveStatus && (initialStatus === 'pending' || initialStatus === 'running')) ||
          (liveStatus === 'pending' || liveStatus === 'running'))
      {
        if (!eventSources[job.id]) { // Avoid duplicate subscriptions
          console.log(`[AsyncPage] Subscribing to SSE for active job ${job.id}`);
          eventSources[job.id] = subscribeJobEvents(
            job.id.toString(), // Pass job ID as string
            handleJobUpdate,
            handleJobError(job.id) // Pass job ID to error handler
          );
        }
      } else {
         // If job is completed/failed and we have an active SSE connection, close it
         if (eventSources[job.id]) {
             console.log(`[AsyncPage] Closing SSE for completed/failed job ${job.id}`);
             eventSources[job.id].close();
             delete eventSources[job.id];
         }
      }
    });

    // Cleanup function: Close all active SSE connections when component unmounts or jobs list changes
    return () => {
      console.log('[AsyncPage] Cleaning up SSE connections...');
      Object.values(eventSources).forEach(es => es.close());
    };
  // DEPENDENCY ARRAY CHANGED: Only depends on the initial job list now.
  }, [jobs]); // Re-run ONLY when the initial jobs list changes.

  // --- Helper to Get Status Chip ---
  const getStatusChip = (status: JobStatus['status']) => {
    switch (status) {
      case 'completed':
        return <Chip label="Completed" color="success" size="small" />;
      case 'running':
        return <Chip label="Running" color="info" size="small" />;
      case 'pending':
        return <Chip label="Pending" color="warning" size="small" />;
      case 'failed':
        return <Chip label="Failed" color="error" size="small" />;
      default:
        return <Chip label={status || 'Unknown'} size="small" />;
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

      {!loading && jobs.length > 0 && (
        <TableContainer component={Paper}>
          <Table sx={{ minWidth: 650 }} aria-label="background jobs table">
            <TableHead>
              <TableRow>
                <TableCell>Job ID</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Trace Name</TableCell> {/* Changed Header */}
                <TableCell>Status</TableCell>
                <TableCell>Progress</TableCell>
                <TableCell>Created</TableCell>
                <TableCell>Last Updated</TableCell>
                <TableCell>Result / Error</TableCell>
                <TableCell>Actions</TableCell> {/* Added Actions Header */}
              </TableRow>
            </TableHead>
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
                  >
                    <TableCell component="th" scope="row">
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
                      {isCompleted && displayStatus.job_type === 'dicom_extract' && (
                         <Button
                            size="small"
                            variant="outlined"
                            startIcon={<PlayCircleOutlineIcon />}
                            onClick={() => navigate(`/dicom?job_id=${job.id}`)} // Navigate using job ID
                         >
                            View DICOM
                         </Button>
                      )}
                       {isCompleted && displayStatus.job_type === 'transform' && (
                         <Typography variant="caption" color="text.secondary">
                            (See Upload Page)
                         </Typography>
                       )}
                      {/* Add download button for transformed PCAPs if needed later */}
                      {/* {isCompleted && displayStatus.job_type === 'transform' && (
                         <Button size="small" startIcon={<DownloadIcon />}>Download PCAP</Button>
                      )} */}
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
                    </TableCell>
                  </TableRow>
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
