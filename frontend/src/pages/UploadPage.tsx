import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios'; // For improved error handling
import { useSession } from '../context/SessionContext'; // Verify path is correct
import {
    listSessions,
    uploadCapture,
    updateSession,
    deleteSession,
    PcapSession, // Import main type
    PcapSessionUpdateData // Import type for update payload
} from '../services/api'; // Verify path is correct

// Material UI Imports
import {
  Box, Typography, Button, Input, CircularProgress, Alert, TextField, LinearProgress, Divider,
  Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, IconButton
} from '@mui/material';
// --- Ensure DataGrid and Action Icons are imported ---
import { DataGrid, GridColDef, GridActionsCellItem, GridRowId } from '@mui/x-data-grid';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';

// Make sure you have installed DataGrid: npm install @mui/x-data-grid

const UploadPage: React.FC = () => {
  // --- State for Upload Form ---
  const [file, setFile] = useState<File | null>(null);
  const [traceName, setTraceName] = useState('');
  const [traceDesc, setTraceDesc] = useState('');
  const [uploadLoading, setUploadLoading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState(''); // For errors during/after upload attempt
  const [fileTypeError, setFileTypeError] = useState(''); // Specific error for wrong file type

  // --- State for Trace List & Management ---
  const [traces, setTraces] = useState<PcapSession[]>([]);
  const [listLoading, setListLoading] = useState<boolean>(true);
  const [listError, setListError] = useState<string | null>(null);

  // --- State for Edit Dialog ---
  const [isEditDialogOpen, setIsEditDialogOpen] = useState<boolean>(false);
  const [editingTrace, setEditingTrace] = useState<PcapSession | null>(null);
  const [editFormData, setEditFormData] = useState<PcapSessionUpdateData>({ name: '', description: '' });

  // --- State for Delete Dialog ---
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState<boolean>(false);
  const [deletingTrace, setDeletingTrace] = useState<PcapSession | null>(null);

  // --- Hooks ---
  const navigate = useNavigate();
  const { setSessionId } = useSession();

  // --- Data Fetching ---
  const fetchTraces = useCallback(async () => {
    setListLoading(true);
    setListError(null);
    try {
      const response = await listSessions();
      setTraces(response.data);
      console.log("Fetched Traces Data:", response.data); // Debug: Check trace data structure
    } catch (err) {
      console.error("Failed to fetch traces:", err);
      setListError("Failed to load trace list. Please check backend connection.");
    } finally {
      setListLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTraces();
  }, [fetchTraces]);

  // --- Event Handlers ---

  /** Handles file selection and validates type */
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0] || null;
    setUploadError(''); // Clear previous upload errors
    setFileTypeError(''); // Clear previous file type errors

    if (selectedFile) {
        // --- File Type Validation ---
        const validExtensions = ['.pcap', '.pcapng'];
        const fileExtension = selectedFile.name.substring(selectedFile.name.lastIndexOf('.')).toLowerCase();
        if (!validExtensions.includes(fileExtension)) {
            setFileTypeError(`Invalid file type. Please select a .pcap or .pcapng file.`);
            setFile(null); // Clear the invalid file
            return; // Stop processing
        }
        // --- File Type OK ---
        setFile(selectedFile);
        // Suggest name only if name field is empty
        if (!traceName) {
            setTraceName(selectedFile.name.replace(/\.(pcapng|pcap)$/i, ''));
        }
    } else {
        setFile(null); // Clear file if selection is cleared
    }
  };

  /** Handles the file upload */
  const handleUpload = async () => {
    setUploadError(''); // Clear previous errors before attempting upload
    setFileTypeError(''); // Clear file type error

    // --- Validation ---
    if (!file) {
      setUploadError('Please select a PCAP file first.');
      return;
    }
    // --- File Type Validation (redundant check, good safeguard) ---
    const validExtensions = ['.pcap', '.pcapng'];
    const fileExtension = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
     if (!validExtensions.includes(fileExtension)) {
        // Use fileTypeError state for consistency, but setUploadError works too
        setUploadError(`Invalid file type selected (${fileExtension}). Please choose a .pcap or .pcapng file.`);
        return;
     }
    // --- Name Validation ---
    const trimmedName = traceName.trim();
    if (!trimmedName) {
      setUploadError('Please provide a name for the trace.');
      return;
    }
    // --- Duplicate Name Check ---
    console.log('Checking for duplicate name:', // Keep this for debugging
        `"${trimmedName.toLowerCase()}"`,
        'against existing:',
        traces.map(t => t.name.trim().toLowerCase())
    );
    const nameExists = traces.some(
        trace => trace.name.trim().toLowerCase() === trimmedName.toLowerCase()
    );
    if (nameExists) {
        console.log('Duplicate name found! Setting error.');
        setUploadError(`A trace with this name already exists. Please choose a different name.`);
        return; // Stop upload
    }

    // --- Proceed with Upload ---
    setUploadLoading(true);
    setUploadProgress(0);

    try {
      const res = await uploadCapture(
        file, trimmedName, traceDesc.trim() || null,
        (percent) => setUploadProgress(percent)
      );
      await fetchTraces(); // Refresh list
      // Clear form on success
      setTraceName('');
      setTraceDesc('');
      setFile(null);
      setUploadProgress(0); // Reset progress bar
      // Note: No automatic navigation or context setting here anymore

    } catch (err) {
      let message = 'Error uploading file.';
      if (axios.isAxiosError(err) && err.response) {
        message = `Upload Failed: ${err.response.data?.detail || err.message}`;
      } else if (err instanceof Error) { message = err.message; }
      setUploadError(message);
      console.error("Upload error details:", err);
      setUploadProgress(0);
    } finally {
      setUploadLoading(false);
    }
  };

  // --- Edit Handlers (Unchanged from previous correct version) ---
  const handleEditClick = (trace: PcapSession) => { /* ... */ };
  const handleEditDialogClose = () => { /* ... */ };
  const handleEditFormChange = (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => { /* ... */ };
  const handleEditSave = async () => { /* ... includes duplicate check */ };

  // --- Delete Handlers (Unchanged from previous correct version) ---
  const handleDeleteClick = (trace: PcapSession) => { /* ... */ };
  const handleDeleteDialogClose = () => { /* ... */ };
  const handleDeleteConfirm = async () => { /* ... */ };

  // --- Analyze Handler (Unchanged) ---
  const handleAnalyze = (id: string) => {
    console.log("Setting active session ID:", id);
    setSessionId(id);
    navigate('/subnets');
  };


  // --- DataGrid Column Definitions ---
  // Ensure this definition is correct and used by the DataGrid component
  const columns: GridColDef<PcapSession>[] = [
    { field: 'name', headerName: 'Trace Name', width: 200 },
    { field: 'description', headerName: 'Description', width: 250, sortable: false }, // Slightly wider?
    { field: 'original_filename', headerName: 'Original File', width: 200 },
    {
      field: 'upload_timestamp', headerName: 'Uploaded At', width: 180,
      type: 'dateTime', valueGetter: (value) => value ? new Date(value) : null,
    },
    {
      field: 'actions',
      headerName: 'Actions',
      sortable: false,
      filterable: false,
      disableColumnMenu: true,
      width: 200,
      renderCell: (params) => { 
        const currentTrace = params.row;
        return (
          <Box sx={{ display: 'flex', justifyContent: 'space-evenly', width: '100%' }}>
            <IconButton aria-label="analyze" size="small" onClick={() => handleAnalyze(currentTrace.id)} title="Analyze" >
              <PlayArrowIcon fontSize="inherit" />
            </IconButton>
            <IconButton aria-label="edit" size="small" onClick={() => handleEditClick(currentTrace)} title="Edit Metadata" >
              <EditIcon fontSize="inherit" />
            </IconButton>
            <IconButton aria-label="delete" size="small" onClick={() => handleDeleteClick(currentTrace)} title="Delete Trace" >
              <DeleteIcon fontSize="inherit" />
            </IconButton>
          </Box>
        );
      },
    
    },
  ];

  // --- Rendered JSX ---
  return (
    <Box sx={{ maxWidth: 1100, margin: 'auto', p: 3 }}>

      {/* === Upload Section === */}
      <Typography variant="h5" gutterBottom>Upload New PCAP Trace</Typography>
      <Box component="form" noValidate autoComplete="off" sx={{ mb: 4, p: 2, border: '1px solid #ccc', borderRadius: 1 }}>
        {/* ... (TextFields for Name and Description - unchanged) ... */}
         <TextField label="Trace Name" /* ... */ error={(!traceName.trim() && !!uploadError) || !!listError } helperText={!traceName.trim() && !!uploadError ? "Name is required" : listError ?? ""}/>
         <TextField label="Description (Optional)" /* ... */ />

        <Typography variant="body1" sx={{ mb: 1 }}>Select PCAP File (.pcap, .pcapng):</Typography>
        <Input type="file"
          key={file ? `${file.name}-${file.lastModified}` : 'file-input'}
          inputProps={{ accept: '.pcap,.pcapng' }}
          onChange={handleFileChange}
          sx={{ display: 'block', mb: 2 }} disabled={uploadLoading}
          error={!!fileTypeError} // Indicate error on file input if type is wrong
        />
        {/* Display file type error near the input */}
        {fileTypeError && <Alert severity="warning" sx={{ mb: 2 }}>{fileTypeError}</Alert>}

        <Button variant="contained" color="primary"
          // Disable upload if file type error exists
          disabled={!file || !traceName.trim() || uploadLoading || !!fileTypeError}
          onClick={handleUpload}
        >
          {uploadLoading ? `Uploading (${uploadProgress}%)` : 'Upload Trace'}
        </Button>
        {uploadLoading && (
          <Box sx={{ width: '100%', mt: 1 }}><LinearProgress variant="determinate" value={uploadProgress} /></Box>
        )}
        {/* Alert for general upload errors (duplicate name, API failure) */}
        {uploadError && <Alert severity="error" sx={{ mt: 2 }}>{uploadError}</Alert>}
      </Box>

      <Divider sx={{ my: 4 }} />

      {/* === Saved Traces List Section === */}
      <Typography variant="h5" gutterBottom>Saved Traces</Typography>
      {/* Display list error here */}
      {listError && !listLoading && <Alert severity="error" sx={{ mb: 2 }}>{listError}</Alert>}
      <Box sx={{ height: 500, width: '100%' }}>
         <DataGrid
            rows={traces}
            columns={columns} // Ensure this uses the 'columns' defined above
            loading={listLoading}
            pageSizeOptions={[5, 10, 25, 50]}
            initialState={{
              pagination: { paginationModel: { pageSize: 10 } },
              sorting: { sortModel: [{ field: 'upload_timestamp', sort: 'desc' }] },
            }}
            autoHeight={false}
          />
      </Box>

      {/* === Edit Dialog === */}
      {/* (JSX Unchanged - ensure handlers connect correctly) */}
      <Dialog open={isEditDialogOpen} onClose={handleEditDialogClose} /* ... */ >
        {/* ... Dialog Content ... */}
      </Dialog>

      {/* === Delete Confirmation Dialog === */}
      {/* (JSX Unchanged - ensure handlers connect correctly) */}
      <Dialog open={isDeleteDialogOpen} onClose={handleDeleteDialogClose} /* ... */ >
       {/* ... Dialog Content ... */}
      </Dialog>

    </Box>
  );
};

export default UploadPage;