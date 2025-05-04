import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSession } from '../context/SessionContext';
// Updated imports: Removed applyCapture, startJob. Added startTransformationJob, JobListResponse.
import { getSubnets, saveRules, startTransformationJob, subscribeJobEvents, JobStatus, JobListResponse } from '../services/api';
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
import { AxiosResponse } from 'axios'; // Import AxiosResponse here

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


/* ----------------------------------------------------------
   MAIN PAGE
---------------------------------------------------------- */
// Removed buildHierarchy, flatten, TreeNode, FlatRow

const SubnetsPage: React.FC = () => {
  // Removed searchParams as it's no longer used for session ID fallback
  // const [searchParams] = useSearchParams();
  // Get sessionId, sessionName (though not used here), and setActiveSession from context
  const { sessionId, setActiveSession } = useSession();

  const [subnets, setSubnets] = useState<SubnetInfo[]>([]);
  const [transforms, setTransforms] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  // Update status state to potentially hold job details for SSE resume
  const [status, setStatus] = useState<{ ok: boolean; msg: string; jobId?: number; dl?: () => void } | null>(null);
  const [progress, setProgress] = useState<number>(0);
  const [currentJobId, setCurrentJobId] = useState<number | null>(null); // Store current job ID

  // Removed groupSubnets state
  const [maskMac, setMaskMac] = useState<boolean>(true); // Default to true

  // REMOVED: Fallback logic for setting sessionId from query string
  // useEffect(() => {
  //   const p = searchParams.get('session_id');
  //   // This logic is removed because we need both ID and Name for setActiveSession,
  //   // and the query parameter only provides the ID. The intended workflow
  //   // is to select the session via the UploadPage.
  //   // if (!sessionId && p) setActiveSession({ id: p, name: 'Unknown - From URL' }); // Example if we kept it
  // }, [searchParams, sessionId, setActiveSession]);

  /* fetch subnets */
  useEffect(() => {
    if (!sessionId) return;
    setLoading(true);
    getSubnets(sessionId)
      // Correct type: getSubnets likely returns Promise<SubnetInfo[]> directly
      .then((data: SubnetInfo[]) => {
        // Ensure data is an array before setting state
        const validSubnets = Array.isArray(data) ? data : [];
        setSubnets(validSubnets);
        /* Prepare sequential transformations 10.0.0.0/8 → 10.1.0.0/8 … */
        const t: Record<string, string> = {};

        // 1️⃣ group by /8
        const roots8 = new Map<string, SubnetInfo[]>();
        // Add explicit type for s
        validSubnets.forEach((s: SubnetInfo) => {
          const [a] = s.cidr.split('.');
          roots8.set(a, [...(roots8.get(a) || []), s]);
        });

        let nextSecond = 0; // global /8 counter (10.0, 10.1, ...)
        roots8.forEach((list8, firstOctet) => {
          const super8 = `${firstOctet}.0.0.0/8`;
          const secondOctet = nextSecond++;
          t[super8] = `10.${secondOctet}.0.0/8`;

          // 2️⃣ group by /16 inside the root
          const by16 = new Map<string, SubnetInfo[]>();
          // Use list8 here, which is derived from validSubnets
          list8.forEach((s: SubnetInfo) => { // Type annotation already added, ensure correct variable 'list8' is used
            const [a, b] = s.cidr.split('.');
            by16.set(b, [...(by16.get(b) || []), s]);
          });

          let nextThirdMap: Record<number, number> = {}; // third octet per /16 group

          by16.forEach((list16, secondStr) => {
            const super16 = `${firstOctet}.${secondStr}.0.0/16`;
            const thirdOctet = nextThirdMap[secondOctet] ?? 0;
            nextThirdMap[secondOctet] = thirdOctet + 1;
            t[super16] = `10.${secondOctet}.${thirdOctet}.0/16`;

            // 3️⃣ leaves
            let nextFourth = 0;
            list16.forEach((s: SubnetInfo) => { // Add explicit type for s
              const [, maskStr] = s.cidr.split('/');
              const prefix = Number(maskStr);
              const cidr = `10.${secondOctet}.${thirdOctet}.${nextFourth}.0/${prefix}`.replace('.0.0/', '.0/');
              t[s.cidr] = cidr;
              nextFourth++;
            });
          });
        });

        setTransforms(t);
      })
      .catch(() => setError('Error loading subnets'))
      .finally(() => setLoading(false));
  }, [sessionId]);

  // --- Callback Handlers for SSE ---
  // Explicitly type the callbacks to match the expected signature
  const handleJobUpdate: (data: JobStatus) => void = (data) => {
    if (data.status === 'pending' || data.status === 'running') {
      setProgress(data.progress); // Use progress directly
      setStatus({ ok: false, msg: `Progress: ${data.progress}%`, jobId: data.id });
      setApplying(true); // Keep applying true while running/pending
    } else if (data.status === 'completed') {
      // Transformation job completion is handled by the new session appearing in UploadPage.
      // We just need to update the status message and stop the 'applying' state.
      setStatus({
        ok: true,
        msg: 'Transformation complete! Check Upload page for the new PCAP.',
        jobId: data.id
        // No direct download link here anymore
      });
      setApplying(false);
      localStorage.removeItem('transformJobId'); // Clear stored job ID on completion
      setCurrentJobId(null);
    } else if (data.status === 'failed') {
      // Use error_message from the JobStatus interface
      setStatus({ ok: false, msg: `Job failed: ${data.error_message || 'Unknown error'}`, jobId: data.id });
      setApplying(false);
      // Consider closing EventSource here
    }
  };

  // Explicitly type the callbacks to match the expected signature
  const handleJobError: (err: Event | string) => void = (err) => {
    console.error('SSE error', err);
    // Optionally update status or show an error message
    // setStatus({ ok: false, msg: 'Connection error during processing.' });
    setApplying(false); // Ensure applying is set to false on error
    // EventSource is closed automatically in api.ts on error now
  };


  // Resume job on page reload - Updated for integer job ID and new status handling
  useEffect(() => {
    const storedJobId = localStorage.getItem('transformJobId'); // Use a specific key
    const jobId = storedJobId ? parseInt(storedJobId, 10) : null;

    if (jobId && !isNaN(jobId) && sessionId) {
      setCurrentJobId(jobId); // Set the current job ID state
      setApplying(true); // Assume it's applying if we have a job ID
      setStatus({ ok: false, msg: 'Resuming previous job status...', jobId });

      // Define the onMessage handler specifically for resuming with explicit type
      const resumeOnMessage: (data: JobStatus) => void = (data) => {
          if (data.status === 'pending' || data.status === 'running') {
            setProgress(data.progress);
            setStatus({ ok: false, msg: `Progress: ${data.progress}%`, jobId: data.id });
            setApplying(true); // Keep applying true
          } else if (data.status === 'completed') {
             setStatus({
               ok: true,
               msg: 'Transformation complete! Check Upload page.',
               jobId: data.id
             });
             setApplying(false);
             localStorage.removeItem('transformJobId'); // Clear stored job ID
             setCurrentJobId(null);
             // Don't close es here, let return cleanup handle it
          } else if (data.status === 'failed') {
            setStatus({ ok: false, msg: `Job failed: ${data.error_message || 'Unknown error'}`, jobId: data.id });
            setApplying(false);
             // Don't close es here
          }
      };

      // Define the onError handler specifically for resuming with explicit type
      const resumeOnError: (err: Event | string) => void = (err) => {
          console.error('SSE error on resume', err);
          // Don't close es here, let return cleanup handle it
      };

      // Pass job ID as string to subscribeJobEvents
      const es = subscribeJobEvents(jobId.toString(), resumeOnMessage, resumeOnError);
      // Return cleanup function to close EventSource when component unmounts or dependencies change
      return () => {
          console.log("Closing EventSource from useEffect cleanup");
          es.close();
      };
    }
  }, [sessionId]); // Removed groupSubnets from dependency array

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
        setError('Invalid JSON');
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
    if (!sessionId) return;
    const payload = ruleArray();
    if (!payload.length) {
      setError('You must define at least one valid rule');
      return;
    }
    setSaving(true);
    setStatus({ ok: false, msg: 'Saving rules…' });
    try {
      await saveRules(sessionId, payload);
    } catch {
      setStatus({ ok: false, msg: 'Failed to save rules' });
      setSaving(false);
      return;
    }
    setSaving(false);

    // Start async transformation job
    setStatus({ ok: false, msg: 'Starting transformation job…' });
    let jobDetails: JobListResponse; // Use the new response type
    try {
      // Call the new API function
      jobDetails = await startTransformationJob(sessionId);
      const newJobId = jobDetails.id; // Get the integer job ID
      setCurrentJobId(newJobId); // Store the new job ID
      localStorage.setItem('transformJobId', newJobId.toString()); // Store job ID for resume
      setStatus({ ok: false, msg: 'Job queued, waiting for progress…', jobId: newJobId });
    } catch (err: any) {
      console.error("Failed to start transformation job:", err);
      setStatus({ ok: false, msg: `Failed to start job: ${err?.response?.data?.detail || err.message}` });
      setSaving(false); // Ensure saving is reset on error
      return;
    }

    // Subscribe to events using the new integer job ID (converted to string)
    const es = subscribeJobEvents(jobDetails.id.toString(), handleJobUpdate, handleJobError);

    // Cleanup function for this specific EventSource instance if handleApply is interrupted
    // Note: This cleanup might be tricky if the component unmounts before the job finishes.
    // The useEffect cleanup is generally more reliable for long-running subscriptions.
    // For simplicity, we rely on the useEffect cleanup for now.

    setApplying(true); // Set applying to true immediately after starting job
  };

  /* ---------------------------------------------------------- */

  if (!sessionId) return <Alert severity="info">Upload a PCAP first.</Alert>;

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h5">Detected subnets</Typography>
        <Box>
          <Button variant="contained" startIcon={<SaveAltIcon />} onClick={handleExport} sx={{ mr: 1 }} disabled={applying}>
            Export
          </Button>
          <Button component="label" variant="contained" startIcon={<FolderOpenIcon />} sx={{ mr: 1 }} disabled={applying}>
            Import
            <input hidden type="file" accept="application/json" onChange={handleImport} />
          </Button>
          <Button
            variant="contained"
            startIcon={<PlayArrowIcon />}
            disabled={saving || applying}
            onClick={handleApply}
          >
            {applying ? 'Processing…' : 'Apply changes'}
          </Button>
        </Box>
      </Box>
      <Box display="flex" gap={4} mb={2}>
        {/* Removed "Group by subnet" checkbox */}
        <FormControlLabel
          control={
            <Checkbox
              checked={maskMac}
              onChange={(e) => setMaskMac(e.target.checked)}
            />
          }
          label="Mask MAC addresses (keep vendor OUI)"
        />
      </Box>

      {status && (
        <Alert severity={status.ok ? 'success' : 'info'} sx={{ mb: 2 }}>
          {status.msg}
          {/* Removed status.dl block entirely */}
        </Alert>
      )}
      {/* Show progress only when applying and progress is positive */}
      {applying && progress > 0 && progress < 100 && (
        <Box sx={{ width: '100%', mb: 2 }}>
          <LinearProgress variant="determinate" value={progress} />
        </Box>
      )}

      {loading && <CircularProgress />}
      {error && <Alert severity="error">{error}</Alert>}

      {!loading && !error && (
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
