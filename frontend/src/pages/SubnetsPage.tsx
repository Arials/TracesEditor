import React, { useEffect, useState, useCallback } from 'react';
import { useSession } from '../context/SessionContext';
import { getSubnets, saveRules, startTransformationJob, JobStatus } from '../services/api'; // Removed getJobDetails, subscribeJobEvents, API_BASE_URL as hook handles them
import { useJobTracking } from '../hooks/useJobTracking'; // Import the hook
import {
  Box,
  Typography,
  Paper,
  TextField,
  Button,
  CircularProgress,
  Alert,
  Checkbox,
  FormControlLabel,
  LinearProgress,
} from '@mui/material';
import { DataGrid, GridColDef, GridRenderCellParams } from '@mui/x-data-grid';
import SaveAltIcon from '@mui/icons-material/SaveAlt';
import FolderOpenIcon from '@mui/icons-material/FolderOpen';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import { saveAs } from 'file-saver';

// import { SubnetInfo } from '../types'; // Removed incorrect import

// --- Local Type Definitions (based on api.ts or expected structure) ---
interface SubnetInfo {
  cidr: string;
  ip_count: number;
}

// REMOVED: Local JobStatus interface (conflicts with imported one)

// --- DataGrid Row Type ---
// We just need the original SubnetInfo plus an 'id' for the DataGrid
interface SubnetRow extends SubnetInfo {
  id: string;
}

// --- Helper Function for Transformation Generation ---

/**
 * Generates a default set of transformation rules for subnets.
 * It maps original subnets to a new, anonymized address space,
 * typically starting from 10.0.0.0, while trying to maintain
 * some structural similarity by mapping /8, /16, and then
 * individual subnets sequentially.
 *
 * @param validSubnets - An array of SubnetInfo objects representing the detected subnets.
 * @returns A record where keys are original CIDRs and values are their proposed transformed CIDRs.
 */
function generateDefaultSubnetTransformations(validSubnets: SubnetInfo[]): Record<string, string> {
  const t: Record<string, string> = {};

  // 1️⃣ Group subnets by their original first octet (e.g., all "192.x.x.x" subnets)
  const roots8 = new Map<string, SubnetInfo[]>();
  validSubnets.forEach((s: SubnetInfo) => {
    const [a] = s.cidr.split('.');
    roots8.set(a, [...(roots8.get(a) || []), s]);
  });

  let nextTransformedSecondOctet = 0; // Counter for the second octet of the transformed 10.x.0.0/8 space

  roots8.forEach((subnetsInFirstOctetGroup, originalFirstOctet) => {
    // Create a transformation for the entire /8 block
    const originalSuper8 = `${originalFirstOctet}.0.0.0/8`;
    const currentTransformedSecondOctet = nextTransformedSecondOctet++;
    t[originalSuper8] = `10.${currentTransformedSecondOctet}.0.0/8`;

    // 2️⃣ Group subnets within this /8 block by their original second octet
    const by16 = new Map<string, SubnetInfo[]>();
    subnetsInFirstOctetGroup.forEach((s: SubnetInfo) => {
      const [, b] = s.cidr.split('.');
      by16.set(b, [...(by16.get(b) || []), s]);
    });

    // Map to track the next available third octet for each transformed second octet's /16 groups.
    // Key: original second octet string, Value: next third octet to use for transformation.
    // This is reset for each new `currentTransformedSecondOctet` implicitly by its scope.
    let nextTransformedThirdOctetMap: Record<string, number> = {};

    by16.forEach((subnetsInSecondOctetGroup, originalSecondOctetStr) => {
      // Create a transformation for the /16 block
      const originalSuper16 = `${originalFirstOctet}.${originalSecondOctetStr}.0.0/16`;
      
      // Determine the next third octet for the transformation.
      // It's based on the currentTransformedSecondOctet and increments for each new originalSecondOctetStr.
      const currentTransformedThirdOctet = nextTransformedThirdOctetMap[originalSecondOctetStr] ?? 0;
      nextTransformedThirdOctetMap[originalSecondOctetStr] = currentTransformedThirdOctet + 1;
      
      t[originalSuper16] = `10.${currentTransformedSecondOctet}.${currentTransformedThirdOctet}.0/16`;

      // 3️⃣ Process leaf subnets within this /16 block
      let nextTransformedFourthOctet = 0; // Counter for the fourth octet within the current transformed 10.second.third.X/prefix
      subnetsInSecondOctetGroup.forEach((s: SubnetInfo) => {
        const [, maskStr] = s.cidr.split('/');
        const prefix = Number(maskStr);
        // Construct the transformed CIDR for the leaf subnet
        // The .replace handles cases like /16 or /8 where the fourth octet might be .0.0 but should be .0
        const transformedCidr = `10.${currentTransformedSecondOctet}.${currentTransformedThirdOctet}.${nextTransformedFourthOctet}.0/${prefix}`.replace('.0.0/', '.0/');
        t[s.cidr] = transformedCidr;
        nextTransformedFourthOctet++;
      });
    });
  });

  return t;
}


/* ----------------------------------------------------------
   MAIN PAGE
---------------------------------------------------------- */
// Removed buildHierarchy, flatten, TreeNode, FlatRow

const SubnetsPage: React.FC = () => {
  // Removed searchParams as it's no longer used for session ID fallback
  // const [searchParams] = useSearchParams();
  // Get the full activeSession object, sessionName (though not used here), and setActiveSession from context
  const { activeSession, fetchSessions } = useSession(); // Get full activeSession

  const [subnets, setSubnets] = useState<SubnetInfo[]>([]);
  const [transforms, setTransforms] = useState<Record<string, string>>({});
  const [loadingSubnets, setLoadingSubnets] = useState(false); // Renamed from 'loading' for clarity
  const [pageError, setPageError] = useState<string | null>(null); // Renamed from 'error' for clarity to distinguish from hook's error
  const [savingRules, setSavingRules] = useState(false); // Renamed from 'saving' for clarity

  const localStorageJobIdKey = 'subnetPageTransformJobId';

  // --- Job Tracking Hook ---
  const {
    jobStatus,
    isLoadingJobDetails: isLoadingHookJobDetails,
    isProcessing: isHookProcessing,
    error: jobHookError,
    startJob,
    resetJobState,
  } = useJobTracking({
    jobIdLocalStorageKey: localStorageJobIdKey, 
    onJobSuccess: (completedJob) => {
      // This onJobSuccess is for SubnetsPage specific UI updates (e.g., snackbar)
      // The actual data refresh (fetchSessions) and localStorage update for cross-tab
      // will be handled by useJobTracking via the onJobSuccessTriggerRefresh callback.
      console.log('SubnetsPage: Job completed successfully via hook.', completedJob);
      if (completedJob.result_data?.output_trace_id) {
        console.log('SubnetsPage: output_trace_id found. Refresh handled by useJobTracking.');
      }
      // Optionally, clear page-specific errors on job success
      // setPageError(null);
    },
    onJobSuccessTriggerRefresh: fetchSessions, // Pass fetchSessions for same-tab and cross-tab (via hook's localStorage)
    onJobFailure: (failedJob) => {
      // The hook itself will set its 'error' state.
      // We can use jobHookError to display this.
      // If additional page-specific error handling for job failure is needed, it can go here.
      console.error('SubnetsPage: Job failed via hook:', failedJob); // Keep error log
    },
    onSseError: (sseError) => {
      console.error('SubnetsPage: SSE connection error via hook:', sseError); // Keep error log
      // The hook sets its 'error' state.
      // setPageError('Connection error during job processing. Please check job status.'); // Example of setting page-level error
    }
  });

  // REMOVED: Fallback logic for setting sessionId from query string

  /* fetch subnets */
  useEffect(() => {
    // Check for both activeSession and its actual_pcap_filename
    if (!activeSession?.id || !activeSession?.actual_pcap_filename) {
      setSubnets([]); // Clear subnets if no active session or filename
      resetJobState(); // Reset job state if session is lost or changes
      if (activeSession?.id && !activeSession?.actual_pcap_filename) {
        setPageError("Active session is missing the required PCAP filename.");
      } else {
        setPageError(null); // Clear error if just no session selected
      }
      return;
    }

    const currentSessionId = activeSession.id;
    const currentPcapFilename = activeSession.actual_pcap_filename;

    setLoadingSubnets(true);
    setPageError(null); // Clear previous page errors
    getSubnets(currentSessionId, currentPcapFilename) // Pass both ID and filename
      .then((data: SubnetInfo[]) => {
        const validSubnets = Array.isArray(data) ? data : [];
        setSubnets(validSubnets);
        
        // Generate transformations using the helper function
        const newTransforms = generateDefaultSubnetTransformations(validSubnets);
        setTransforms(newTransforms);
      })
      .catch((err: any) => {
        console.error("Error loading subnets:", err); // Keep console log
        let displayMessage = "An unexpected error occurred while loading subnets. Please try again or select a different session.";
        if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
          displayMessage = `Error loading subnets: ${err.response.data.detail}`;
        } else if (err.message) {
          displayMessage = `Error loading subnets: ${err.message}`;
        }
        setPageError(displayMessage);
      })
      .finally(() => setLoadingSubnets(false));
  // Depend on activeSession object itself, so it re-runs if the session or its filename changes
  }, [activeSession, resetJobState]);

  // Old job handling (useEffect for resuming job, handleJobUpdate, handleJobError)
  // is removed as useJobTracking now manages this.
  // The useJobTracking hook will internally handle resuming from localStorageJobIdKey.

  // Directly map subnets to rows needed by DataGrid
  const rows = React.useMemo<SubnetRow[]>(() =>
    subnets.map(subnet => ({
      ...subnet,
      id: subnet.cidr, // Use cidr as the unique ID for the row
    })),
    [subnets]
  );

  const handleChange = (c: string, v: string) =>
    setTransforms(prev => ({ ...prev, [c]: v }));

  // Update GridColDef to use SubnetRow
  const columns: GridColDef<SubnetRow>[] = [
    {
      field: 'cidr',
      headerName: 'Subnet',
      width: 240,
      minWidth: 240,
      maxWidth: 240,
      flex: 0,
      resizable: false,
      sortable: true,
      // Removed renderCell with depth padding
    },
    {
      field: 'ip_count',
      headerName: 'IPs',
      width: 120,
      minWidth: 120,
      maxWidth: 120,
      flex: 0,
      resizable: false,
      type: 'number',
      sortable: true,
    },
    {
      field: 'transform',
      headerName: 'Transformation',
      width: 220,
      minWidth: 220,
      maxWidth: 220,
      flex: 0,
      resizable: false,
      sortable: false,
      // Update renderCell to use SubnetRow
      renderCell: (p: GridRenderCellParams<any, SubnetRow>) => (
        <TextField
          size="small"
          value={transforms[p.row.cidr.trim()] || ''}
          onChange={e => handleChange(p.row.cidr.trim(), e.target.value)}
          sx={{ minWidth: 180 }}
        />
      ),
    },
  ];

  const handleExport = () => {
    const blob = new Blob([JSON.stringify(transforms, null, 2)], { type: 'application/json' });
    saveAs(blob, 'subnet_transforms.json');
  };

  const handleImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const r = new FileReader();
    r.onload = () => {
      try {
        setTransforms(JSON.parse(r.result as string));
      } catch {
        setPageError('Invalid JSON'); // Corrected: Use setPageError
      }
    };
    r.readAsText(f);
    e.target.value = '';
  };

  const ruleArray = () =>
    Object.entries(transforms)
      .filter(([, t]) => t.trim())
      .map(([source, target]) => ({ source, target }));

  const handleApply = async () => {
    // Check for activeSession and its filename before proceeding
    if (!activeSession?.id || !activeSession?.actual_pcap_filename) {
      setPageError('Cannot apply changes: No active session or PCAP filename is available.');
      return;
    }
    const currentSessionId = activeSession.id;
    const currentPcapFilename = activeSession.actual_pcap_filename;

    const payload = ruleArray();
    if (!payload.length) {
      setPageError('You must define at least one valid rule');
      return;
    }
    setSavingRules(true);
    setPageError(null); // Clear previous page errors
    // jobHookError is managed by the hook, so no need to clear it here unless specifically intended

    try {
      // Use currentSessionId for saving rules
      await saveRules(currentSessionId, payload);
    } catch (err: any) {
      console.error("Failed to save rules:", err); // Keep error log
      let displayMessage = "An unexpected error occurred while saving rules. Please try again.";
        if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
          displayMessage = `Failed to save rules: ${err.response.data.detail}`;
        } else if (err.message) {
          displayMessage = `Failed to save rules: ${err.message}`;
        } else if (err.response?.status) {
          displayMessage = `Failed to save rules: An unknown server error occurred (status ${err.response.status}).`;
        }
      setPageError(displayMessage);
      setSavingRules(false);
      return;
    }
    setSavingRules(false);

    // Now start the job using the hook
    const apiCallToStartJob = async () => {
        // We already checked activeSession and filename at the start of handleApply
        if (!currentSessionId || !currentPcapFilename) {
          throw new Error("Session ID or PCAP filename became unavailable unexpectedly.");
        }
        // Pass both ID and filename to the API call
        return startTransformationJob(currentSessionId, currentPcapFilename);
    };

    // The hook will set its own loading/processing states (isHookProcessing, isLoadingHookJobDetails)
    // and manage jobStatus and jobHookError.
    startJob(apiCallToStartJob);
  };

  /* ---------------------------------------------------------- */

  // Check activeSession existence for page rendering
  if (!activeSession?.id) return <Alert severity="info">Select a PCAP trace from the Upload page first.</Alert>;

  // Determine UI status message based on job state from hook
  const getJobStatusMessageFromHook = (): { text: string; severity: 'info' | 'success' | 'warning' | 'error' } | null => {
    if (isLoadingHookJobDetails) return { text: 'Loading job details...', severity: 'info' };
    if (!jobStatus) return null; // No active job from hook to display status for

    switch (jobStatus.status) {
      case 'pending':
        return { text: `Job (ID: ${jobStatus.id}) is pending...`, severity: 'info' };
      case 'running':
        return { text: `Job (ID: ${jobStatus.id}) is running... Progress: ${jobStatus.progress}%`, severity: 'info' };
      case 'completed':
        return { text: `Job (ID: ${jobStatus.id}) completed successfully! Check Upload page.`, severity: 'success' };
      case 'failed':
        return { text: `Job (ID: ${jobStatus.id}) failed: ${jobStatus.error_message || 'Unknown error'}`, severity: 'error' };
      case 'cancelled':
        return { text: `Job (ID: ${jobStatus.id}) was cancelled.`, severity: 'warning' };
      case 'cancelling':
        return { text: `Job (ID: ${jobStatus.id}) is cancelling...`, severity: 'info' };
      default:
        // Should not happen if JobStatus type is strict
        return { text: `Job (ID: ${jobStatus.id}) status: ${jobStatus.status}`, severity: 'info' };
    }
  };

  const currentJobStatusMessage = getJobStatusMessageFromHook();

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h5">Detected subnets</Typography>
        <Box>
          <Button variant="contained" startIcon={<SaveAltIcon />} onClick={handleExport} sx={{ mr: 1 }} disabled={isHookProcessing || savingRules || isLoadingHookJobDetails}>
            Export
          </Button>
          <Button component="label" variant="contained" startIcon={<FolderOpenIcon />} sx={{ mr: 1 }} disabled={isHookProcessing || savingRules || isLoadingHookJobDetails}>
            Import
            <input hidden type="file" accept="application/json" onChange={handleImport} />
          </Button>
          <Button
            variant="contained"
            startIcon={<PlayArrowIcon />}
            disabled={savingRules || isHookProcessing || isLoadingHookJobDetails}
            onClick={handleApply}
          >
            {isHookProcessing || isLoadingHookJobDetails ? 'Processing…' : 'Apply Changes'}
          </Button>
        </Box>
      </Box>
      {/* Removed "Group by subnet" checkbox and maskMac FormControlLabel */}

      {/* Display page-specific errors (e.g., subnet loading, rule saving) */}
      {pageError && <Alert severity="error" sx={{ mb: 2 }}>{pageError}</Alert>}
      
      {/* Display job-specific errors from the hook */}
      {jobHookError && <Alert severity="error" sx={{ mb: 2 }}>{jobHookError}</Alert>}

      {/* Display job status message from hook */}
      {currentJobStatusMessage && !jobHookError && ( // Avoid showing job status if there's a specific job error from hook
        <Alert severity={currentJobStatusMessage.severity} sx={{ mb: 2 }}>
          {currentJobStatusMessage.text}
        </Alert>
      )}

      {/* Show progress bar for running jobs from hook */}
      {jobStatus && jobStatus.status === 'running' && typeof jobStatus.progress === 'number' && jobStatus.progress >= 0 && jobStatus.progress <= 100 && (
        <Box sx={{ width: '100%', mb: 2 }}>
          <LinearProgress variant="determinate" value={jobStatus.progress} />
        </Box>
      )}
      
      {/* Show loading spinner for initial subnet load or job detail loading from hook */}
      {(loadingSubnets || isLoadingHookJobDetails) && <CircularProgress sx={{ mb: 2 }}/>}

      {!loadingSubnets && ( // Keep DataGrid visible even if there's an error, but not if subnets are loading
        <Paper sx={{ flex: 1, minHeight: 0, width: 650 }}>
          <DataGrid
            rows={rows}
            columns={columns}
            style={{ height: '100%' }}
            disableRowSelectionOnClick // Renamed prop
            // Removed invalid prop: disableExtendRowFullWidth
            pageSizeOptions={[25, 50, 100]}
            initialState={{
              pagination: { paginationModel: { pageSize: 25, page: 0 } },
            }}
          />
        </Paper>
      )}
    </Box>
  );
};

export default SubnetsPage;
