import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSession } from '../context/SessionContext';
import { getSubnets, saveRules, applyCapture, startJob, subscribeJobEvents } from '../services/api.ts';
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
import { SubnetInfo } from '../types';

/* ----------------------------------------------------------
   UTILS
---------------------------------------------------------- */


/** Node of the grouping tree */
export interface TreeNode {
  cidr: string;
  ip_count: number;
  children?: (TreeNode | SubnetInfo)[];
}

/* ----------------------------------------------------------
   AGRUPACIÓN JERÁRQUICA
---------------------------------------------------------- */

/**
 * Convert the flat SubnetInfo list into a tree:
 * - Drop prefixes that start with 0.*
 * - Group from /32 upwards to /8; collapse a node
 *   if it only contains 1 child.
 * - A /8 is kept only if it aggregates at least 2 different children.
 */
const buildHierarchy = (list: SubnetInfo[]): TreeNode[] => {
  const valid = list.filter(s => !s.cidr.startsWith('0.'));
  const parentOf = (cidr: string): string | null => {
    const [ip, mStr] = cidr.split('/');
    const m = Number(mStr);
    if (m <= 8) return null;
    const ipNum = ip.split('.').reduce((a, b) => (a << 8) + Number(b), 0);
    const parentMask = m - 1;
    const parentBase = (ipNum >>> (32 - parentMask)) << (32 - parentMask);
    const bytes = [24, 16, 8, 0].map(shift => (parentBase >>> shift) & 0xff);
    return `${bytes.join('.')}/${parentMask}`;
  };

  /* auxiliary maps */
  const kids = new Map<string, (TreeNode | SubnetInfo)[]>();
  const counts = new Map<string, number>();

  valid.forEach(s => {
    kids.set(s.cidr, []);
    counts.set(s.cidr, s.ip_count);
  });

  /* climb the hierarchy */
  const ascend = (cidr: string) => {
    const p = parentOf(cidr);
    if (!p) return;
    if (!kids.has(p)) kids.set(p, []);
    if (!kids.get(p)!.includes(cidr as any)) kids.get(p)!.push(cidr as any);
    counts.set(p, (counts.get(p) || 0) + (counts.get(cidr) || 0));
    ascend(p);
  };
  valid.forEach(s => ascend(s.cidr));

  /* build node; collapse if only 1 child */
  const make = (cidr: string): TreeNode | SubnetInfo => {
    const ch = kids.get(cidr) || [];
    const built = ch.map(c => make(c as string));
    if (built.length <= 1) return built[0] || valid.find(v => v.cidr === cidr)!;
    return { cidr, ip_count: counts.get(cidr)!, children: built };
  };

  /* remove /8 with a single child */
  kids.forEach((v, k) => {
    if (k.endsWith('/8') && v.length === 1) {
      const only = v[0] as any as string;
      kids.set(only, kids.get(only) || []);
      counts.set(only, counts.get(only)!);
      kids.delete(k);
      counts.delete(k);
    }
  });

  const roots: string[] = [];
  kids.forEach((_v, k) => {
    if (k.endsWith('/8')) {
      if ((kids.get(k) || []).length >= 2) roots.push(k);
    } else {
      const p = parentOf(k);
      if (!p || !kids.has(p)) roots.push(k);
    }
  });

  return roots.map(r => make(r) as TreeNode);
};

/* ----------------------------------------------------------
   HELPERS FOR DATAGRID
---------------------------------------------------------- */

interface FlatRow {
  id: string;          // required by DataGrid
  cidr: string;
  ip_count: number;
  depth: number;
}

/** Flatten TreeNode / SubnetInfo into rows, keeping `depth` for visual indent */
const flatten = (nodes: (TreeNode | SubnetInfo)[], depth = 0): FlatRow[] =>
  nodes.flatMap(n => {
    const base: FlatRow = {
      id: (n as any).cidr,
      cidr: (n as any).cidr, // no indent, just the CIDR string
      ip_count: (n as any).ip_count,
      depth,
    };
    const ch = (n as TreeNode).children;
    return ch ? [base, ...flatten(ch, depth + 1)] : [base];
  });

/* ----------------------------------------------------------
   MAIN PAGE
---------------------------------------------------------- */

const SubnetsPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const { sessionId, setSessionId } = useSession();

  const [subnets, setSubnets] = useState<SubnetInfo[]>([]);
  const [transforms, setTransforms] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; msg: string; dl?: () => void } | null>(null);
  const [progress, setProgress] = useState<number>(0);

  const [groupSubnets, setGroupSubnets] = useState<boolean>(false);
  const [maskMac, setMaskMac] = useState<boolean>(false); // placeholder for future use

  // fallback sessionId from query string
  useEffect(() => {
    const p = searchParams.get('session_id');
    if (!sessionId && p) setSessionId(p);
  }, [searchParams, sessionId]);

  /* fetch subnets */
  useEffect(() => {
    if (!sessionId) return;
    setLoading(true);
    getSubnets(sessionId)
      .then(res => {
        setSubnets(res.data);
        /* Prepare sequential transformations 10.0.0.0/8 → 10.1.0.0/8 … */
        const t: Record<string, string> = {};

        // 1️⃣ group by /8
        const roots8 = new Map<string, SubnetInfo[]>();
        res.data.forEach(s => {
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
          list8.forEach(s => {
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
            list16.forEach(s => {
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

  // Resume job on page reload
  useEffect(() => {
    const jobId = localStorage.getItem('pcapJobId');
    if (jobId && sessionId) {
      const es = subscribeJobEvents(
        jobId,
        (data: any) => {
          if (data.status === 'pending' || data.status === 'running') {
            setProgress(data.progress ?? 0);
            setStatus({ ok: false, msg: `Progress: ${data.progress ?? 0}%` });
            setApplying(true);
          } else if (data.status === 'completed') {
            setStatus({
              ok: true,
              msg: 'PCAP ready! Click to download.',
              dl: () => applyCapture(sessionId),
            });
            setApplying(false);
            es.close();
          } else if (data.status === 'failed') {
            setStatus({ ok: false, msg: `Job failed: ${data.error}` });
            setApplying(false);
            es.close();
          }
        },
        (err) => {
          console.error('SSE error', err);
          es.close();
        }
      );
      return () => es.close();
    }
  }, [sessionId]);

  const displayData = React.useMemo(
    () => (groupSubnets ? buildHierarchy(subnets) : (subnets as (TreeNode | SubnetInfo)[])),
    [subnets, groupSubnets]
  );

  const rows = React.useMemo<FlatRow[]>(() => flatten(displayData), [displayData]);

  const handleChange = (c: string, v: string) =>
    setTransforms(prev => ({ ...prev, [c]: v }));

  const columns: GridColDef[] = [
    {
      field: 'cidr',
      headerName: 'Subnet',
      width: 240,
      minWidth: 240,
      maxWidth: 240,
      flex: 0,
      resizable: false,
      sortable: true,
      renderCell: (p: GridRenderCellParams<unknown, FlatRow>) => (
        <Box pl={p.row.depth * 2}>
          {p.row.cidr}
        </Box>
      ),
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
      renderCell: (p: GridRenderCellParams<unknown, FlatRow>) => (
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

    // Start async job
    setStatus({ ok: false, msg: 'Job queued, waiting for progress…' });
    let jobId: string;
    try {
      const res = await startJob(sessionId);
      jobId = res.data.job_id;
      localStorage.setItem('pcapJobId', jobId);
    } catch {
      setStatus({ ok: false, msg: 'Failed to start job' });
      return;
    }

    // Subscribe to SSE for progress
    const es = subscribeJobEvents(
      jobId,
      (data: any) => {
        if (data.status === 'pending' || data.status === 'running') {
          setProgress(data.progress ?? 0);
          setStatus({ ok: false, msg: `Progress: ${data.progress ?? 0}%` });
        } else if (data.status === 'completed') {
          setStatus({
            ok: true,
            msg: 'PCAP ready! Click to download.',
            dl: () => applyCapture(sessionId),
          });
          es.close();
        } else if (data.status === 'failed') {
          setStatus({ ok: false, msg: `Job failed: ${data.error}` });
          es.close();
        }
      },
      (err) => {
        console.error('SSE error', err);
        es.close();
      }
    );

    setApplying(true);
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
        <FormControlLabel
          control={
            <Checkbox
              checked={groupSubnets}
              onChange={(e) => setGroupSubnets(e.target.checked)}
            />
          }
          label="Group by subnet"
        />
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
          {status.dl && (
            <Button size="small" sx={{ ml: 2 }} onClick={status.dl}>
              Download
            </Button>
          )}
        </Alert>
      )}
      {progress > 0 && progress < 100 && (
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
            disableSelectionOnClick
            disableExtendRowFullWidth        // new: avoid auto‑stretch filler column
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