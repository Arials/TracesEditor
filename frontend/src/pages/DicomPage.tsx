// File: src/pages/DicomPage.tsx
// Refactored to find/start DICOM job based on selected session context OR job_id from URL,
// display results if completed, or status/link if pending/running/newly started.

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { Link as RouterLink, useSearchParams } from 'react-router-dom'; // Import Link and useSearchParams
import { useSession } from '../context/SessionContext';
import {
    updateDicomMetadata,
    getJobDetails,
    listJobs, // Need to list jobs to find relevant one
    startDicomExtractionJob, // Need to start a job if none exists
    AggregatedDicomResponse,
    AggregatedDicomInfo,
    DicomMetadataUpdatePayload,
    JobStatusResponse,
    JobListResponse // Need the list response type
} from '../services/api';

// Material UI Imports
import {
  Box,
  Typography,
  CircularProgress,
  Alert,
  Paper,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Button,
  Tooltip,
  Chip,
  LinearProgress // Import LinearProgress
} from '@mui/material';
import { DataGrid, GridColDef, GridRenderCellParams, GridRowId } from '@mui/x-data-grid';
import EditIcon from '@mui/icons-material/Edit';
// Removed: PlayArrowIcon
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import LaunchIcon from '@mui/icons-material/Launch'; // Icon for navigation links
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline'; // Icon for Start/Retry button

// Helper function to format header names
const formatHeaderName = (key: string): string => {
  // Replace underscores with spaces, then add space before capitals (if preceded by lowercase)
  const spaced = key
    .replace(/_/g, ' ') // Replace underscores with spaces first
    .replace(/([a-z])([A-Z])/g, '$1 $2') // Add space between lowercase and uppercase
    .trim();
  // Capitalize each word
  return spaced
    .split(' ')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');
};


// GridRow now represents one aggregated entry per IP pair
interface DicomGridRow extends AggregatedDicomInfo {
  id: GridRowId; // Use the ip_pair_key ("client_ip-server_ip") as the unique ID
  // Inherits all fields from AggregatedDicomInfo:
  // client_ip, server_ip, server_ports,
  // CallingAE, CalledAE, ImplementationClassUID, ImplementationVersionName,
  // negotiation_successful, Manufacturer, ManufacturerModelName, DeviceSerialNumber,
  // SoftwareVersions, TransducerData, StationName
} // <-- Added missing closing brace

type DicomEditFormData = DicomMetadataUpdatePayload;

// Define possible states for the page
type PageStatus = 'idle' | 'loading' | 'showing_results' | 'job_running' | 'job_starting' | 'job_failed' | 'no_session' | 'error';

const DicomPage: React.FC = () => {
  // Get sessionId and sessionName from context
  const { sessionId, sessionName } = useSession();
  // Get search params from URL
  const [searchParams] = useSearchParams();
  // State for the relevant job (could be running or completed)
  const [relevantJob, setRelevantJob] = useState<JobStatusResponse | JobListResponse | null>(null);
  // State for the overall page status
  const [pageStatus, setPageStatus] = useState<PageStatus>('idle');
  // State for general errors
  const [error, setError] = useState<string | null>(null);
  // State for the newly created job ID if we start one
  const [newlyStartedJobId, setNewlyStartedJobId] = useState<number | null>(null);
  // State to track if the explicit start button is loading
  const [isStartingJobManually, setIsStartingJobManually] = useState<boolean>(false);

  // State for the edit dialog
  const [isEditDialogOpen, setIsEditDialogOpen] = useState<boolean>(false);
  const [editingIpPairKey, setEditingIpPairKey] = useState<GridRowId | null>(null);
  const [editFormData, setEditFormData] = useState<DicomEditFormData>({});
  const [editLoading, setEditLoading] = useState<boolean>(false);
  const [editError, setEditError] = useState<string | null>(null);

  // --- Function to Fetch Specific Job Details ---
  const fetchSpecificJob = useCallback(async (jobId: number) => {
    console.log(`[DicomPage] Attempting to fetch specific job ID: ${jobId}`);
    setPageStatus('loading');
    setError(null);
    setRelevantJob(null); // Reset relevant job
    setNewlyStartedJobId(null); // Reset this too
    try {
        const details = await getJobDetails(jobId);
        console.log(`[DicomPage] Fetched details for job ${jobId}:`, details);
        setRelevantJob(details); // Store the fetched job details

        if (details.status === 'completed') {
            if (details.result_data && typeof details.result_data === 'object' && Object.keys(details.result_data).length > 0) {
                setPageStatus('showing_results');
                console.log(`[DicomPage] Job ${jobId} completed, showing results.`);
            } else {
                console.error(`[DicomPage] Job ${jobId} completed but result_data is missing or empty.`);
                // Keep relevantJob with details, but show specific status/message
                setError(`DICOM extraction for job ${jobId} completed, but no metadata was found.`);
                setPageStatus('error'); // Or a dedicated 'no_data' status if preferred
            }
        } else if (details.status === 'failed') {
            setError(`DICOM extraction job ${jobId} failed: ${details.error_message || 'Unknown error'}`);
            setPageStatus('job_failed');
        } else { // Pending or Running
            setPageStatus('job_running');
        }
    } catch (err: any) {
        console.error(`[DicomPage] Error fetching job details for ID ${jobId}:`, err);
        setError(err?.response?.data?.detail || err?.message || `Failed to fetch details for job ${jobId}.`);
        setPageStatus('error');
        setRelevantJob(null); // Clear job info on fetch error
    }
  }, []); // Empty dependency array for useCallback, as it doesn't depend on component state/props

  // --- Function to Find Latest Job for Session ---
  const findLatestJobForSession = useCallback(async (currentSessionId: string) => {
    console.log(`[DicomPage] Finding latest DICOM job for session ID: ${currentSessionId}.`);
    setPageStatus('loading');
    setError(null);
    setRelevantJob(null); // Reset relevant job
    setNewlyStartedJobId(null); // Reset this too
    try {
        const allJobs = await listJobs();
        const dicomJobsForSession = allJobs
            .filter(job => job.session_id === currentSessionId && job.job_type === 'dicom_extract')
            .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

        const latestJob = dicomJobsForSession.length > 0 ? dicomJobsForSession[0] : null;
        console.log(`[DicomPage] Found ${dicomJobsForSession.length} DICOM jobs for session ${currentSessionId}. Latest ID: ${latestJob?.id}`);

        if (latestJob) {
            console.log(`[DicomPage] Found latest job ${latestJob.id}. Fetching full details...`);
            try {
                // Fetch full details immediately, regardless of status, to get trace_name etc.
                const details = await getJobDetails(latestJob.id);
                setRelevantJob(details); // Update state with full details

                // Now determine page status based on the detailed status
                if (details.status === 'completed') {
                    if (details.result_data && typeof details.result_data === 'object' && Object.keys(details.result_data).length > 0) {
                        setPageStatus('showing_results');
                        console.log(`[DicomPage] Job ${details.id} details fetched, status: completed, showing results.`);
                    } else {
                        console.error(`[DicomPage] Job ${details.id} completed but result_data is missing or empty.`);
                        setError("Latest DICOM extraction completed, but no metadata was found.");
                        setPageStatus('error'); // Or 'no_data'?
                    }
                } else if (details.status === 'failed') {
                    setError(`Latest DICOM extraction job (${details.id}) failed: ${details.error_message || 'Unknown error'}`);
                    setPageStatus('job_failed');
                    console.log(`[DicomPage] Job ${details.id} details fetched, status: failed.`);
                } else { // Pending or Running
                    setPageStatus('job_running');
                    console.log(`[DicomPage] Job ${details.id} details fetched, status: ${details.status}.`);
                }
            } catch (detailsError: any) {
                 console.error(`[DicomPage] Error fetching details for job ${latestJob.id} within findLatestJobForSession:`, detailsError);
                 // Fallback: Show error, but maybe keep basic job info if needed? Or just show error.
                 setError(detailsError?.response?.data?.detail || detailsError?.message || `Failed to fetch full details for job ${latestJob.id}.`);
                 setPageStatus('error');
                 setRelevantJob(null); // Clear job info on details fetch error
            }
        } else {
            console.log(`[DicomPage] No existing DICOM job found for session ${currentSessionId}. Waiting for manual start.`);
            setPageStatus('idle'); // Ready for manual start
            setRelevantJob(null); // Ensure no job is considered active
        }
    } catch (err: any) {
        console.error(`[DicomPage] Error finding latest DICOM job for session ${currentSessionId}:`, err);
        setError(err?.response?.data?.detail || err?.message || "An error occurred while finding the DICOM job.");
        setPageStatus('error');
        setRelevantJob(null); // Clear job info on find error
    }
  }, []); // Empty dependency array for useCallback

  // --- Main Effect to Load Data based on URL or Session ---
  useEffect(() => {
    // Reset error and newly started job ID on any change triggering the effect
    setError(null);
    setNewlyStartedJobId(null);
    // Let the fetch functions handle resetting relevantJob and setting pageStatus initially

    const jobIdFromUrl = searchParams.get('job_id');

    if (jobIdFromUrl) {
        const jobIdNum = parseInt(jobIdFromUrl, 10);
        if (!isNaN(jobIdNum)) {
            fetchSpecificJob(jobIdNum);
        } else {
            console.error(`[DicomPage] Invalid job_id in URL: ${jobIdFromUrl}`);
            setError("Invalid Job ID provided in the URL.");
            setPageStatus('error');
            setRelevantJob(null); // Clear job info
        }
    } else if (sessionId) {
        findLatestJobForSession(sessionId);
    } else {
        console.log("[DicomPage] No active session selected and no job_id in URL.");
        setPageStatus('no_session');
        setRelevantJob(null); // Ensure no job is displayed
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, searchParams, fetchSpecificJob, findLatestJobForSession]); // Add searchParams and the useCallback functions

  // --- Explicit Job Start Function (for current session) ---
  const handleStartJobClick = useCallback(async () => {
    if (!sessionId) {
      setError("No session selected to start a job for.");
      return;
    }
    console.log(`[DicomPage] User clicked Start/Retry Extraction for session ${sessionId}.`);
    setIsStartingJobManually(true); // Show loading indicator on button
    setError(null); // Clear previous errors
    setPageStatus('job_starting'); // Update page status

    try {
      const newJobInfo: JobListResponse = await startDicomExtractionJob(sessionId);
      console.log(`[DicomPage] Successfully started new DICOM job via button click: ${newJobInfo.id}`);
      setNewlyStartedJobId(newJobInfo.id);
      setRelevantJob(newJobInfo); // Update the relevant job state
      setPageStatus('job_running'); // Transition to running status
    } catch (startJobError: any) {
      console.error("[DicomPage] Error calling startDicomExtractionJob from button click:", startJobError);
      setError(startJobError?.response?.data?.detail || startJobError?.message || "Failed to start the DICOM extraction job.");
      setPageStatus('error'); // Show error state
    } finally {
      setIsStartingJobManually(false); // Hide loading indicator
    }
  }, [sessionId]); // Dependency: sessionId

  // --- Data Grid Calculation (Derived from relevantJob if completed) ---
  const flatGridData = useMemo((): DicomGridRow[] => {
    // Ensure we have a completed job with result_data
    if (pageStatus !== 'showing_results' || !relevantJob || relevantJob.status !== 'completed' || !('result_data' in relevantJob) || !relevantJob.result_data) {
      return [];
    }

    const results = relevantJob.result_data;
    console.log("[DicomPage] useMemo calculating flatGridData from relevantJob.result_data:", JSON.stringify(results));

    if (typeof results !== 'object' || Object.keys(results).length === 0) {
      console.log('[DicomPage] useMemo: No valid results data found in completed job, returning [].');
      return [];
    }

    try {
      // Assuming results has the structure Record<string, AggregatedDicomInfo>
      const flattened = Object.entries(results).map(([ipPairKey, aggInfo]) => {
        const typedAggInfo = aggInfo as AggregatedDicomInfo;
        return {
          ...typedAggInfo,
          id: ipPairKey, // Use the key as the unique row ID
        };
      });
      console.log('[DicomPage] useMemo: Calculated flattened data:', flattened);
      return flattened;
    } catch (error) {
      console.error('[DicomPage] useMemo: Error processing job result data:', error);
      setError('Error processing received DICOM job result data.'); // Inform user
      setPageStatus('error'); // Set error status
      return [];
    }
  }, [relevantJob, pageStatus]); // Depend on relevantJob and pageStatus

  // --- Edit Dialog Functions (Moved Before dynamicColumns) ---
  const handleEditOpen = useCallback((rowData: DicomGridRow) => {
    console.log("[DicomPage] Opening edit dialog for row ID (ipPairKey):", rowData.id);
    // Ensure we have the original session ID from the completed job details
    const originalSessionId = (relevantJob as JobStatusResponse)?.session_id;
    if (!originalSessionId) {
        console.error("[DicomPage] Cannot open edit dialog: Missing original session ID from job details.");
        setError("Cannot edit metadata: Missing original session ID information.");
        return;
    }
    const metadataToEdit: DicomEditFormData = {
        CallingAE: rowData.CallingAE,
        CalledAE: rowData.CalledAE,
        ImplementationClassUID: rowData.ImplementationClassUID,
        ImplementationVersionName: rowData.ImplementationVersionName,
        Manufacturer: rowData.Manufacturer,
        ManufacturerModelName: rowData.ManufacturerModelName,
        DeviceSerialNumber: rowData.DeviceSerialNumber,
        SoftwareVersions: rowData.SoftwareVersions,
        TransducerData: rowData.TransducerData,
        StationName: rowData.StationName,
    };
    setEditingIpPairKey(rowData.id); // Store the row ID (ipPairKey)
    setEditFormData(metadataToEdit);
    setIsEditDialogOpen(true);
    setEditError(null);
  }, [relevantJob]); // Depend on relevantJob to get session_id

  // Close the edit dialog
  const handleEditDialogClose = useCallback(() => {
    setIsEditDialogOpen(false);
    // Delay clearing state slightly to avoid flicker during close animation
    setTimeout(() => {
        setEditingIpPairKey(null);
        setEditFormData({});
        setEditError(null);
        setEditLoading(false);
    }, 150);
  }, []);

  // Update form state on input change
  const handleEditFormChange = useCallback((event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = event.target;
    setEditFormData(prev => ({ ...prev, [name]: value || null })); // Store null if empty
  }, []);

  // Handle saving the edited data
  const handleEditSave = useCallback(async () => {
    // Get the original session ID from the job details stored in relevantJob
    const originalSessionId = (relevantJob as JobStatusResponse)?.session_id;

    if (!editingIpPairKey || !originalSessionId) {
      console.error("[DicomPage] Cannot save edit: Missing editingIpPairKey or originalSessionId from job details.");
      setEditError("Cannot save changes: Missing required information (IP pair key or original session ID).");
      return;
    }

    setEditLoading(true);
    setEditError(null);
    console.log(`[DicomPage] Attempting to save edited data for session ${originalSessionId}, IP pair ${editingIpPairKey}:`, editFormData);

    try {
      const payload: DicomMetadataUpdatePayload = { ...editFormData };
      // Optional: Clean up payload (remove nulls if backend ignores them)
      Object.keys(payload).forEach(key => {
          if (payload[key as keyof DicomMetadataUpdatePayload] === null) {
              delete payload[key as keyof DicomMetadataUpdatePayload];
          }
      });

      console.log("Sending cleaned payload:", payload);

      await updateDicomMetadata(originalSessionId, String(editingIpPairKey), payload);

      console.log("[DicomPage] Save successful.");
      // Optionally, update the local state immediately to reflect changes without refetching
      // This requires updating the `relevantJob` state carefully.
      // For simplicity, we'll just close the dialog. User might need to refresh or re-run job later.
      handleEditDialogClose();

    } catch (err: any) {
      console.error("[DicomPage] Error saving DICOM metadata:", err);
      const errorMsg = err?.response?.data?.detail || err?.message || "An unknown error occurred while saving changes.";
      setEditError(errorMsg);
    } finally {
      setEditLoading(false);
    }
  }, [relevantJob, editingIpPairKey, editFormData, handleEditDialogClose]); // Dependencies


  // --- Dynamic Column Generation ---
  const dynamicColumns = useMemo((): GridColDef<DicomGridRow>[] => {
    if (flatGridData.length === 0) {
      // Return a default column or empty array if no data
      return [{ field: 'noData', headerName: 'No Data Available', width: 300 }];
    }

    // 1. Define the static 'Actions' column first
    const actionsColumn: GridColDef<DicomGridRow> = {
        field: 'actions',
        headerName: 'Actions',
        width: 100,
        sortable: false,
        filterable: false,
        renderCell: (params: GridRenderCellParams<DicomGridRow>) => (
            <Tooltip title="Edit Metadata Overrides">
                <IconButton onClick={() => handleEditOpen(params.row)} disabled={pageStatus === 'loading' || editLoading}>
                    <EditIcon />
                </IconButton>
            </Tooltip>
        ),
    };

    // 2. Get all unique keys from the data (excluding 'id')
    const allKeys = new Set<string>();
    flatGridData.forEach(row => {
        Object.keys(row).forEach(key => {
            if (key !== 'id') { // Exclude the manually added 'id' field
                allKeys.add(key);
            }
        });
    });

    // 3. Create GridColDef for each unique key
    const dataColumns: GridColDef<DicomGridRow>[] = Array.from(allKeys).map(key => {
        const headerName = formatHeaderName(key); // Use helper function
        // console.log(`[DicomPage] Generating column for key: "${key}", headerName: "${headerName}"`); // <-- REMOVE LOGGING

        // Determine width based on key name (simple heuristic)
        let width = 150;
        if (key.toLowerCase().includes('uid')) width = 250;
        if (key.toLowerCase().includes('ip')) width = 130;
        if (key.toLowerCase().includes('version')) width = 180;
        if (key.toLowerCase().includes('serial')) width = 160;

        return {
            field: key,
            headerName: headerName, // Use the generated headerName
            // width: width, // Remove fixed width
            flex: 1, // Add flex grow
            minWidth: 130, // Add a minimum width
            sortable: true, // Enable sorting by default
            renderCell: (params: GridRenderCellParams<DicomGridRow, any>) => {
                const value = params.value;

                // Custom rendering based on key or value type
                if (key === 'negotiation_successful') {
                    if (value === true) return <Chip icon={<CheckCircleIcon />} label="Yes" color="success" size="small" variant="outlined" />;
                    if (value === false) return <Chip icon={<CancelIcon />} label="No" color="error" size="small" variant="outlined" />;
                    return <Chip icon={<HelpOutlineIcon />} label="N/A" color="default" size="small" variant="outlined" />;
                }

                if (Array.isArray(value)) {
                    const displayString = value.join(', ');
                    return (
                        <Tooltip title={displayString}>
                            <Typography variant="body2" noWrap>{displayString}</Typography>
                        </Tooltip>
                    );
                }

                if (typeof value === 'object' && value !== null) {
                    const jsonString = JSON.stringify(value);
                     return (
                        <Tooltip title={jsonString}>
                            <Typography variant="body2" noWrap>{jsonString}</Typography>
                        </Tooltip>
                     );
                }

                // Default rendering for strings, numbers, null, undefined
                const displayValue = value ?? ''; // Handle null/undefined
                return (
                    <Tooltip title={String(displayValue)}>
                        <Typography variant="body2" noWrap>{String(displayValue)}</Typography>
                    </Tooltip>
                );
            },
            // Align boolean columns to center
            align: typeof flatGridData[0]?.[key as keyof DicomGridRow] === 'boolean' ? 'center' : 'left',
            headerAlign: typeof flatGridData[0]?.[key as keyof DicomGridRow] === 'boolean' ? 'center' : 'left',
        };
    });

    // 4. Combine actions column and data columns
    return [actionsColumn, ...dataColumns];

  }, [flatGridData, pageStatus, editLoading, handleEditOpen]); // Dependencies: data, status, edit state, edit handler


  console.log(`[DicomPage] Render state check: sessionId=${sessionId}, pageStatus=${pageStatus}, error=${!!error}, relevantJob ID=${relevantJob?.id}`);

  // --- Render Logic based on Page Status ---

  const renderContent = () => {
    // Determine context for messages (URL Job ID or Session)
    const jobIdFromUrl = searchParams.get('job_id');
    const contextMessage = jobIdFromUrl
        ? `for Job ID ${jobIdFromUrl}`
        : sessionId
        ? `for session "${sessionName || sessionId.substring(0, 8)}..."`
        : '';

    switch (pageStatus) {
      case 'idle':
        // If idle and a session IS selected, show the start button (no job found for session)
        if (sessionId) {
          return (
            <Box sx={{ textAlign: 'center', py: 4 }}>
              <Typography variant="body1" gutterBottom>
                No DICOM extraction job found for this session.
              </Typography>
              <Button
                variant="contained"
                color="primary"
                startIcon={isStartingJobManually ? <CircularProgress size={20} color="inherit" /> : <PlayCircleOutlineIcon />}
                onClick={handleStartJobClick}
                disabled={isStartingJobManually || !sessionId}
                sx={{ mt: 1 }}
              >
                {isStartingJobManually ? 'Starting...' : 'Start DICOM Extraction'}
              </Button>
            </Box>
          );
        }
        // If idle and NO session is selected (should be handled by 'no_session', but as fallback)
        return null;
      case 'no_session':
        return <Alert severity="info">Please select a PCAP session from the Upload page first.</Alert>;
      case 'loading':
      case 'job_starting':
        return (
          <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
            <CircularProgress />
            <Typography sx={{ ml: 2 }}>
              {pageStatus === 'loading' ? `Loading DICOM job information ${contextMessage}...` : `Starting DICOM extraction job ${contextMessage}...`}
            </Typography>
          </Box>
        );
      case 'error':
        // Include context in the error message
        return <Alert severity="error">{error || 'An unknown error occurred.'} {contextMessage}</Alert>;
      case 'job_failed':
         return (
             <Box>
                 <Alert severity="error" sx={{ mb: 2 }}>
                     DICOM extraction job {relevantJob?.id ? `(ID: ${relevantJob.id}) ` : ''}failed: {relevantJob?.error_message || 'Unknown error'}.
                     {sessionId && " You can try starting a new extraction job for the current session."}
                 </Alert>
                 {/* Show Start/Retry Button only if a session is selected */}
                 {sessionId && (
                    <Button
                        variant="contained"
                        color="primary"
                        startIcon={isStartingJobManually ? <CircularProgress size={20} color="inherit" /> : <PlayCircleOutlineIcon />}
                        onClick={handleStartJobClick}
                        disabled={isStartingJobManually || !sessionId}
                        sx={{ mt: 1 }}
                    >
                        {isStartingJobManually ? 'Starting...' : 'Retry Extraction'}
                    </Button>
                 )}
             </Box>
         );
      case 'job_running':
        return (
          <Alert severity="info" sx={{ display: 'flex', alignItems: 'center' }}>
            <Box sx={{ flexGrow: 1, mr: 2 }}> {/* Added margin-right */}
              <Typography variant="body1">
                DICOM extraction job {relevantJob?.id ? `(ID: ${relevantJob.id}) ` : ''}is {relevantJob?.status || 'in progress'} {contextMessage}.
              </Typography>
              {/* Show progress if available */}
              {(relevantJob?.status === 'running' || relevantJob?.status === 'pending') && typeof relevantJob?.progress === 'number' && relevantJob.progress >= 0 && ( // Ensure progress is valid
                 <LinearProgress variant="determinate" value={relevantJob.progress} sx={{ my: 1 }} />
              )}
              <Button
                component={RouterLink}
                // Always link to the specific job ID if available
                to={`/async?job_id=${relevantJob?.id || newlyStartedJobId}`}
                variant="outlined"
                size="small"
                endIcon={<LaunchIcon />}
                sx={{ mt: 1, mr: 1 }} // Added margin-right
                disabled={!relevantJob?.id && !newlyStartedJobId} // Disable if no job ID yet
              >
                Monitor Job Progress
              </Button>
            </Box>
            {/* Show Start New Extraction button only if a session is selected */}
            {sessionId && (
                <Button
                    variant="contained"
                    color="secondary"
                    startIcon={isStartingJobManually ? <CircularProgress size={20} color="inherit" /> : <PlayCircleOutlineIcon />}
                    onClick={handleStartJobClick}
                    disabled={isStartingJobManually || !sessionId}
                    size="small" // Make button smaller
                    sx={{ whiteSpace: 'nowrap' }} // Prevent wrapping
                >
                    {isStartingJobManually ? 'Starting...' : 'Start New Extraction'}
                </Button>
            )}
          </Alert>
        );
      case 'showing_results':
        if (flatGridData.length === 0) {
             // Provide context in the warning
             return <Alert severity="warning">DICOM extraction {relevantJob?.id ? `for job ${relevantJob.id} ` : ''}completed, but no metadata matching the expected format was found in the results {contextMessage}.</Alert>;
        }
        return (
          // Add width: '100%' to constrain the Paper horizontally
          <Paper sx={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', width: '100%' }}>
              <DataGrid
                rows={flatGridData}
                columns={dynamicColumns} // Use dynamic columns
                sx={{ height: '100%' }}
                initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
                pageSizeOptions={[10, 25, 50, 100]}
                autoHeight={false}
                density="compact"
                getRowId={(row) => row.id} // Ensure ID getter is present
              />
            {/* End of removed intermediate Box */}
          </Paper>
        );
      default:
        return <Alert severity="error">An unexpected state occurred.</Alert>;
    }
  };

  // --- Main Component Render ---
  // Determine title context dynamically based on state
  const jobIdFromUrl = searchParams.get('job_id');
  let titleContext = '';

  // Prioritize showing info from the loaded job if available
  if (relevantJob) {
    const traceNameDisplay = relevantJob.trace_name ? `(${relevantJob.trace_name})` : '(No Trace Name)';
    // If loaded via URL, show Job ID and Trace Name
    if (jobIdFromUrl && String(relevantJob.id) === jobIdFromUrl) {
       titleContext = `for Job ID ${relevantJob.id} ${traceNameDisplay}`;
    }
    // If loaded via Session, show Session Name, Job ID, and Trace Name
    else if (sessionId) {
       const sessionDisplay = sessionName ? `"${sessionName}"` : sessionId.substring(0, 8) + '...';
       titleContext = `for Session ${sessionDisplay} (Job: ${relevantJob.id}, Trace: ${traceNameDisplay})`;
    }
    // Fallback if context is ambiguous but job loaded
    else {
       titleContext = `for Job ID ${relevantJob.id} ${traceNameDisplay}`;
    }
  }
  // Handle states before a job is fully loaded or if no job is found
  else if (pageStatus === 'loading' || pageStatus === 'job_starting') {
    if (jobIdFromUrl) {
      titleContext = `for Job ID ${jobIdFromUrl}...`;
    } else if (sessionName) {
      titleContext = `for Session "${sessionName}"...`;
    } else if (sessionId) {
      titleContext = `for Session ${sessionId.substring(0, 8)}...`;
    } else {
      titleContext = '...'; // Generic loading
    }
  } else if (pageStatus === 'idle' && sessionId) {
    const sessionDisplay = sessionName ? `"${sessionName}"` : sessionId.substring(0, 8) + '...';
    titleContext = `for Session ${sessionDisplay} (No Job Found)`;
  } else if (pageStatus === 'no_session') {
    titleContext = '(No Session Selected)';
  }
  // Note: Error state title is handled within the error Alert message itself for more detail


  return (
    <Box sx={{ p: 3, display: 'flex', flexDirection: 'column', height: 'calc(100vh - 64px - 48px)' }}>
      <Typography variant="h5" gutterBottom>
        DICOM Metadata {titleContext}
      </Typography>

      {renderContent()}

      {/* Edit Metadata Dialog (Common to 'showing_results' state) */}
      <Dialog open={isEditDialogOpen} onClose={handleEditDialogClose} maxWidth="md" fullWidth>
        <DialogTitle>Edit DICOM Metadata Override</DialogTitle>
        <DialogContent>
          <Typography variant="body2" gutterBottom>
            Editing metadata for IP pair: {editingIpPairKey || 'N/A'}.
            Changes will be saved as overrides for this session. Empty fields will not be saved.
          </Typography>
           {/* Make fields editable */}
           <TextField margin="dense" name="CallingAE" label="Calling AE Title" type="text" fullWidth variant="standard" value={editFormData.CallingAE || ''} onChange={handleEditFormChange} disabled={editLoading} />
           <TextField margin="dense" name="CalledAE" label="Called AE Title" type="text" fullWidth variant="standard" value={editFormData.CalledAE || ''} onChange={handleEditFormChange} disabled={editLoading} />
           <TextField margin="dense" name="ImplementationClassUID" label="Implementation Class UID" type="text" fullWidth variant="standard" value={editFormData.ImplementationClassUID || ''} onChange={handleEditFormChange} disabled={editLoading} />
           <TextField margin="dense" name="ImplementationVersionName" label="Implementation Version Name" type="text" fullWidth variant="standard" value={editFormData.ImplementationVersionName || ''} onChange={handleEditFormChange} disabled={editLoading} />

           {/* Add TextFields for P-DATA fields (Make editable) */}
           <TextField margin="dense" name="Manufacturer" label="Manufacturer" type="text" fullWidth variant="standard" value={editFormData.Manufacturer || ''} onChange={handleEditFormChange} disabled={editLoading} />
           <TextField margin="dense" name="ManufacturerModelName" label="Model Name" type="text" fullWidth variant="standard" value={editFormData.ManufacturerModelName || ''} onChange={handleEditFormChange} disabled={editLoading} />
           <TextField margin="dense" name="DeviceSerialNumber" label="Serial Number" type="text" fullWidth variant="standard" value={editFormData.DeviceSerialNumber || ''} onChange={handleEditFormChange} disabled={editLoading} />
           {/* SoftwareVersions might be complex (string/list). Simple text field for now. */}
           {/* Consider a more complex input if needed, or parse the string on save */}
           <TextField margin="dense" name="SoftwareVersions" label="Software Version(s)" type="text" fullWidth variant="standard" value={Array.isArray(editFormData.SoftwareVersions) ? editFormData.SoftwareVersions.join(', ') : editFormData.SoftwareVersions || ''} onChange={handleEditFormChange} disabled={editLoading} helperText="Enter versions separated by comma if multiple" />
           {/* TransducerData is complex. Simple text field for now. */}
           {/* User needs to input valid JSON if they want to edit this */}
           <TextField margin="dense" name="TransducerData" label="Transducer Data (JSON)" type="text" fullWidth variant="standard" value={editFormData.TransducerData ? JSON.stringify(editFormData.TransducerData) : ''} onChange={handleEditFormChange} disabled={editLoading} multiline maxRows={4} helperText="Enter as JSON string if modifying" />
           <TextField margin="dense" name="StationName" label="Station Name" type="text" fullWidth variant="standard" value={editFormData.StationName || ''} onChange={handleEditFormChange} disabled={editLoading} />

            {/* Display edit error */}
            {editError && (<Alert severity="error" sx={{ mt: 2 }}>{editError}</Alert>)}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleEditDialogClose} disabled={editLoading}>Cancel</Button>
          {/* Enable save button */}
          <Button onClick={handleEditSave} variant="contained" disabled={editLoading}>
            {editLoading ? <CircularProgress size={24} color="inherit"/> : 'Save Changes'}
          </Button>
        </DialogActions>
      </Dialog>

    </Box>
  );
};

export default DicomPage;
