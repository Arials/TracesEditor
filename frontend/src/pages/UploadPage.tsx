// File: src/pages/UploadPage.tsx
// Purpose: Allows users to upload new PCAP traces, view existing traces,
//          edit metadata, delete traces, and select a trace for analysis
//          in other pages (Subnets, DICOM).
// Changes: Renamed 'handleAnalyze' to 'handleSelectSession' and removed navigation
//          so it only sets the session ID in the context. Updated tooltip.

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom'; // Keep for potential future use, but not used in select handler now
import axios from 'axios'; // Used for error checking
import { useSession } from '../context/SessionContext'; // Import context hook

// Import API service functions and types
import {
    listSessions,
    uploadCapture,
    updateSession,
    deleteSession,
    PcapSession, // This interface should now include is_transformed, original_session_id, async_job_id from api.ts
    PcapSessionUpdateData
} from '../services/api';

// Material UI Imports
import {
  Box, Typography, Button, Input, CircularProgress, Alert, TextField, LinearProgress, Divider,
  Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, IconButton, Tooltip, Chip // Added Chip
} from '@mui/material';
import { DataGrid, GridColDef, GridRenderCellParams } from '@mui/x-data-grid';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'; // Changed icon for selecting session

const UploadPage: React.FC = () => {
  // --- State for Upload Form ---
  const [file, setFile] = useState<File | null>(null);
  const [traceName, setTraceName] = useState('');
  const [traceDesc, setTraceDesc] = useState('');
  const [uploadLoading, setUploadLoading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState('');
  const [fileTypeError, setFileTypeError] = useState('');

  // --- State for Trace List & Management ---
  const [traces, setTraces] = useState<PcapSession[]>([]);
  const [listLoading, setListLoading] = useState<boolean>(true);
  const [listError, setListError] = useState<string | null>(null);
  // Get current sessionId and the new setActiveSession function from context
  const { sessionId, setActiveSession } = useSession();

  // --- State for Edit Dialog ---
  const [isEditDialogOpen, setIsEditDialogOpen] = useState<boolean>(false);
  const [editingTrace, setEditingTrace] = useState<PcapSession | null>(null);
  const [editFormData, setEditFormData] = useState<PcapSessionUpdateData>({ name: '', description: '' });
  const [editLoading, setEditLoading] = useState<boolean>(false);
  const [editError, setEditError] = useState<string | null>(null);

  // --- State for Delete Dialog ---
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState<boolean>(false);
  const [deletingTrace, setDeletingTrace] = useState<PcapSession | null>(null);
  const [deleteLoading, setDeleteLoading] = useState<boolean>(false);

  // --- Hooks ---
  // const navigate = useNavigate(); // Keep if needed elsewhere, but not for session selection

  // --- Data Fetching ---
  // --- Data Fetching ---
  const fetchTraces = useCallback(async () => {
    setListLoading(true);
    setListError(null);
    try {
      const sessionsData = await listSessions(); // Get the data array directly

      // --- FIX: Check if sessionsData is an array before mapping ---
      if (Array.isArray(sessionsData)) {
        // Map response ensuring 'id' is present and a string for DataGrid compatibility
        setTraces(sessionsData.map((trace: PcapSession) => ({ ...trace, id: String(trace.id) })));
        console.log("Fetched Traces Data:", sessionsData);
      } else {
        // Handle unexpected non-array response from API
        console.error("Failed to fetch traces: API returned unexpected data format.", sessionsData);
        setListError("Received invalid data format from the server. Expected an array.");
        setTraces([]); // Reset to empty array
      }
    } catch (err: any) {
      console.error("Failed to fetch traces:", err);
      // --- FIX: Improved error message handling ---
      let errorMessage = "Failed to load trace list. Please check backend connection.";
      if (axios.isAxiosError(err)) {
          // Try to get specific detail from backend response, fallback to status/message
          errorMessage = `API Error (${err.response?.status || 'Network Error'}): ${err.response?.data?.detail || err.message || 'Unknown API error'}`;
      } else if (err instanceof Error) {
          errorMessage = `Error: ${err.message}`;
      }
      setListError(errorMessage);
      setTraces([]); // Reset to empty array on error
    } finally {
      setListLoading(false);
    }
  }, []); // Empty dependency array means this function is stable

  // Initial fetch on component mount
  useEffect(() => {
    fetchTraces();
  }, [fetchTraces]); // Include fetchTraces in dependency array

  // --- Event Handlers ---

  /** Handles file selection from input and validates type */
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0] || null;
    setUploadError('');
    setFileTypeError('');

    if (selectedFile) {
        const validExtensions = ['.pcap', '.pcapng'];
        const fileExtension = selectedFile.name.substring(selectedFile.name.lastIndexOf('.')).toLowerCase();
        if (!validExtensions.includes(fileExtension)) {
            setFileTypeError(`Invalid file type (${fileExtension}). Please select a .pcap or .pcapng file.`);
            setFile(null);
            return; // Stop processing
        }
        // File type is valid
        setFile(selectedFile);
        // Auto-fill name only if the name field is currently empty
        if (!traceName.trim()) {
            setTraceName(selectedFile.name.replace(/\.(pcapng|pcap)$/i, '')); // Remove extension
        }
    } else {
        setFile(null); // Clear file if selection is cancelled
    }
  };

  /** Handles the trace file upload process */
  const handleUpload = async () => {
    setUploadError('');
    setFileTypeError('');

    // --- Validation ---
    if (!file) {
      setUploadError('Please select a PCAP file first.');
      return;
    }
    // Basic type check (safeguard)
    const validExtensions = ['.pcap', '.pcapng'];
    const fileExtension = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
     if (!validExtensions.includes(fileExtension)) {
        setUploadError(`Invalid file type selected (${fileExtension}). Please choose a .pcap or .pcapng file.`);
        return;
     }
    const trimmedName = traceName.trim();
    if (!trimmedName) {
      setUploadError('Please provide a name for the trace.');
      return;
    }
    // Check for duplicate trace name (case-insensitive)
    const nameExists = traces.some(
        trace => trace.name.trim().toLowerCase() === trimmedName.toLowerCase()
    );
    if (nameExists) {
        setUploadError(`A trace with the name "${trimmedName}" already exists. Please choose a different name.`);
        return; // Stop upload
    }

    // --- Proceed with Upload ---
    setUploadLoading(true);
    setUploadProgress(0);

    try {
      // Call the API function to upload
      await uploadCapture(
        file,
        trimmedName,
        traceDesc.trim() || null, // Send null if description is empty/whitespace
        (percentCompleted) => setUploadProgress(percentCompleted) // Progress callback
      );
      // Success: Refresh list and clear form
      await fetchTraces();
      setTraceName('');
      setTraceDesc('');
      setFile(null);
      // Reset file input visually by changing its key in the JSX below
      setUploadProgress(0); // Reset progress bar

    } catch (err: any) {
      // Handle upload errors
      let message = 'Error uploading file.';
      if (axios.isAxiosError(err) && err.response) {
        message = `Upload Failed: ${err.response.data?.detail || err.message}`;
      } else if (err instanceof Error) {
        message = err.message;
      }
      setUploadError(message);
      console.error("Upload error details:", err);
      setUploadProgress(0); // Reset progress on error
    } finally {
      setUploadLoading(false); // Ensure loading indicator stops
    }
  };

  // --- Edit Handlers ---
  /** Opens the edit dialog and pre-fills the form with the selected trace data */
  const handleEditClick = useCallback((trace: PcapSession) => {
    console.log("Edit clicked for trace:", trace);
    setEditingTrace(trace);
    setEditFormData({
        name: trace.name,
        description: trace.description || ''
    });
    setIsEditDialogOpen(true);
    setEditError(null);
  }, []);

  /** Closes the edit dialog and resets related state */
  const handleEditDialogClose = useCallback(() => {
    setIsEditDialogOpen(false);
    setTimeout(() => {
        setEditingTrace(null);
        setEditFormData({ name: '', description: '' });
        setEditError(null);
        setEditLoading(false);
    }, 150);
  }, []);

  /** Updates the state bound to the edit form fields */
  const handleEditFormChange = useCallback((event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = event.target;
    setEditFormData(prev => ({ ...prev, [name]: value }));
  }, []);

  /** Handles saving the edited trace data via API call */
  const handleEditSave = useCallback(async () => {
    if (!editingTrace) return;

    setEditLoading(true);
    setEditError(null);
    // Safely trim, providing empty string as fallback if undefined/null (though state initializes with '')
    const trimmedName = (editFormData.name ?? '').trim();
    const trimmedDesc = (editFormData.description ?? '').trim();

    // Basic Validation
    if (!trimmedName) {
      setEditError("Trace name cannot be empty.");
      setEditLoading(false);
      return;
    }
    // Duplicate Name Check (excluding the item being edited)
    const nameExists = traces.some(
      trace => trace.id !== editingTrace.id && trace.name.trim().toLowerCase() === trimmedName.toLowerCase()
    );
    if (nameExists) {
      setEditError(`Another trace with the name "${trimmedName}" already exists.`);
      setEditLoading(false);
      return;
    }

    // Construct update payload, sending description only if it's not empty after trimming
    const updateData: PcapSessionUpdateData = {
      name: trimmedName,
      // Assign undefined if trimmedDesc is empty, otherwise assign the trimmed string
      description: trimmedDesc ? trimmedDesc : undefined
    };

    try {
      await updateSession(editingTrace.id, updateData);
      await fetchTraces(); // Refresh list
      handleEditDialogClose(); // Close dialog
    } catch (err: any) {
      console.error("Failed to update trace:", err);
      let message = 'Error updating trace.';
      if (axios.isAxiosError(err) && err.response) {
        message = `Update Failed: ${err.response.data?.detail || err.message}`;
      } else if (err instanceof Error) { message = err.message; }
      setEditError(message); // Show error within the dialog
    } finally {
      setEditLoading(false); // Ensure loading indicator stops
    }
  }, [editingTrace, editFormData, traces, fetchTraces, handleEditDialogClose]);
  // --- End of Edit Handlers ---

  // --- Delete Handlers ---
  /** Opens the delete confirmation dialog */
  const handleDeleteClick = useCallback((trace: PcapSession) => {
    console.log("Attempting to delete trace:", trace);
    setDeletingTrace(trace);
    setIsDeleteDialogOpen(true);
    setListError(null);
  }, []);

  /** Closes the delete confirmation dialog */
  const handleDeleteDialogClose = useCallback(() => {
    setIsDeleteDialogOpen(false);
    setTimeout(() => {
        setDeletingTrace(null);
        setDeleteLoading(false);
    }, 150);
  }, []);

  /** Handles the actual deletion process after confirmation */
  const handleDeleteConfirm = useCallback(async () => {
    if (!deletingTrace) return;

    console.log("Confirming deletion for trace ID:", deletingTrace.id);
    setDeleteLoading(true);
    setListError(null);

    try {
      await deleteSession(deletingTrace.id);
      console.log("Trace deleted successfully:", deletingTrace.id);
      await fetchTraces(); // Refresh list
      handleDeleteDialogClose(); // Close dialog

    } catch (err: any) {
      console.error("Failed to delete trace:", err);
      let message = 'Error deleting trace.';
       if (axios.isAxiosError(err) && err.response) {
           message = `Deletion Failed: ${err.response.data?.detail || err.message}`;
       } else if (err instanceof Error) {
           message = err.message;
       }
      // Display the error (using listError state for now)
      setListError(message);
      // Keep the dialog open on error? Or close? Closing for now.
    } finally {
       setDeleteLoading(false);
    }
  }, [deletingTrace, fetchTraces, handleDeleteDialogClose]);
  // --- End of Delete Handlers ---

  // --- MODIFIED: Function to set the active session ---
  /** Sets the clicked trace as the active session in the global context */
  const handleSelectSession = useCallback((trace: PcapSession) => {
    if (!trace || !trace.id || !trace.name) {
        console.error("handleSelectSession: Invalid trace object received", trace);
        return;
    }
    console.log(`Setting active session: ID=${trace.id}, Name=${trace.name}`);
    // Call the new context function with both id and name
    setActiveSession({ id: trace.id, name: trace.name });
    // No navigation here - user will use sidebar to navigate to analysis pages
  }, [setActiveSession, traces]); // Dependency is setActiveSession and traces (to find the trace)

  // --- DataGrid Column Definitions ---
  // Moved 'actions' column to the beginning for better UX
  const columns: GridColDef<PcapSession>[] = [
    // --- ACTION COLUMN ---
    {
      field: 'actions',
      headerName: 'Actions',
      width: 150,
      sortable: false,
      filterable: false,
      disableColumnMenu: true,
      renderCell: (params: GridRenderCellParams<any, PcapSession>) => {
        const currentTrace = params.row;
        const isActive = currentTrace.id === sessionId; // Check if this row is the currently active session
        return (
          <Box sx={{ display: 'flex', justifyContent: 'space-evenly', width: '100%' }}>
            <Tooltip title={isActive ? "This is the active session" : "Set as Active Session"}>
              {/* Disable button if it's already the active session */}
              <span> {/* Span needed for tooltip on disabled button */}
                <IconButton
                  aria-label="select session"
                  size="small"
                  // Pass the whole trace object to the handler
                  onClick={() => handleSelectSession(currentTrace)}
                  disabled={isActive} // Disable if already selected
                  color={isActive ? "success" : "default"} // Use success color if active
                >
                  {/* Use CheckCircle if active, PlayArrow otherwise */}
                  <CheckCircleOutlineIcon fontSize="inherit" />
                </IconButton>
              </span>
            </Tooltip>
            <Tooltip title="Edit Metadata">
              <IconButton
                aria-label="edit"
                size="small"
                onClick={() => handleEditClick(currentTrace)}
              >
                <EditIcon fontSize="inherit" />
              </IconButton>
            </Tooltip>
            <Tooltip title="Delete Trace">
              <IconButton
                aria-label="delete"
                size="small"
                onClick={() => handleDeleteClick(currentTrace)}
              >
                <DeleteIcon fontSize="inherit" />
              </IconButton>
            </Tooltip>
          </Box>
        );
      },
    },
    // --- OTHER DATA COLUMNS ---
     {
      field: 'type', // New column for type
      headerName: 'Type',
      width: 120,
      renderCell: (params: GridRenderCellParams<any, PcapSession>) => (
        <Chip
          label={params.row.is_transformed ? "Transformed" : "Original"}
          size="small"
          color={params.row.is_transformed ? "secondary" : "primary"}
          variant="outlined"
        />
      ),
    },
    {
      field: 'name',
      headerName: 'Trace Name',
      width: 220,
      editable: false, // Metadata editing is done via dialog
       renderCell: (params: GridRenderCellParams<PcapSession>) => { // Use correct row model type
          // Access value and row properties correctly
          const name = params.value as string || ''; // Value should be the name string
          const rowData = params.row; // Row data is PcapSession
          return rowData.is_transformed ? (
             <Tooltip title={`Transformed from session ID: ${rowData.original_session_id || 'N/A'}`}>
                 <span>{name}</span>
             </Tooltip>
          ) : (
             <span>{name}</span>
         ); // Add semicolon if preferred style
      }, // Add the missing closing parenthesis and comma here
    },
    {
      field: 'description',
      headerName: 'Description',
      width: 280,
      sortable: false,
      editable: false,
    },
    {
      field: 'original_filename',
      headerName: 'Original File',
      width: 220,
      sortable: false,
    },
    {
      field: 'upload_timestamp',
      headerName: 'Uploaded At',
      width: 180,
      type: 'dateTime',
      // Ensure Date object is used for sorting/filtering/rendering
      valueGetter: (value: string | null | undefined) => value ? new Date(value) : null,
      // Use default locale string formatting
      valueFormatter: (value: Date | null) => value ? value.toLocaleString() : '',
    },
  ];

  // --- Rendered JSX ---
  return (
    <Box sx={{ maxWidth: 1100, margin: 'auto', p: 3 }}> {/* Container for the page */}

      {/* === Upload Section === */}
      <Typography variant="h5" gutterBottom component="h1">Upload New PCAP Trace</Typography>
      <Box component="form" noValidate autoComplete="off" sx={{ mb: 4, p: 2, border: '1px solid #ccc', borderRadius: 1 }}>
         {/* Trace Name Input */}
         <TextField
            label="Trace Name"
            value={traceName}
            onChange={(e) => setTraceName(e.target.value)}
            fullWidth
            margin="normal"
            required
            error={(!traceName.trim() && uploadError.includes("Name is required")) || uploadError.includes("already exists")}
            helperText={uploadError.includes("already exists") ? uploadError : ((!traceName.trim() && uploadError.includes("Name is required")) ? "Name is required" : "")}
            disabled={uploadLoading}
         />
         {/* Trace Description Input */}
         <TextField
            label="Description (Optional)"
            value={traceDesc}
            onChange={(e) => setTraceDesc(e.target.value)}
            fullWidth
            margin="normal"
            multiline
            rows={2}
            disabled={uploadLoading}
         />

        {/* File Input */}
        <Typography variant="body1" sx={{ mt:1, mb: 1 }}>Select PCAP File (.pcap, .pcapng):</Typography>
        <Input
          type="file"
          // The key prop was removed here to fix the file selection display issue
          inputProps={{ accept: '.pcap,.pcapng' }}
          onChange={handleFileChange}
          sx={{ display: 'block', mb: 2 }}
          disabled={uploadLoading}
          error={!!fileTypeError}
        />
        {/* Display file type error message */}
        {fileTypeError && <Alert severity="warning" sx={{ mb: 2 }}>{fileTypeError}</Alert>}

        {/* Upload Button */}
        <Button
          variant="contained"
          color="primary"
          disabled={!file || !traceName.trim() || uploadLoading || !!fileTypeError}
          onClick={handleUpload}
          startIcon={uploadLoading ? <CircularProgress size={20} color="inherit"/> : null}
        >
          {uploadLoading ? `Uploading (${uploadProgress}%)` : 'Upload Trace'}
        </Button>
        {/* Progress Bar */}
        {uploadLoading && (
          <Box sx={{ width: '100%', mt: 1 }}><LinearProgress variant="determinate" value={uploadProgress} /></Box>
        )}
        {/* Display general upload errors */}
        {uploadError && !uploadError.includes("already exists") && !uploadError.includes("Name is required") && (
          <Alert severity="error" sx={{ mt: 2 }}>{uploadError}</Alert>
        )}
      </Box>

      <Divider sx={{ my: 4 }} />

      {/* === Saved Traces List Section === */}
      <Typography variant="h5" gutterBottom component="h2">Saved Traces</Typography>
      {/* Display list fetch or delete errors */}
      {listError && !listLoading && <Alert severity="error" sx={{ mb: 2 }}>{listError}</Alert>}
      <Box sx={{ height: 500, width: '100%' }}> {/* Container for DataGrid */}
         <DataGrid
            rows={traces} // Data rows
            columns={columns} // Column definitions
            loading={listLoading} // Show loading overlay
            pageSizeOptions={[5, 10, 25, 50]} // Rows per page options
            initialState={{
              pagination: { paginationModel: { pageSize: 10 } }, // Default page size
              sorting: { sortModel: [{ field: 'upload_timestamp', sort: 'desc' }] }, // Default sort
            }}
            getRowId={(row) => row.id} // Specify the ID field
            disableRowSelectionOnClick // Prevent selection on cell click
            density="compact" // Use compact spacing
            localeText={{ noRowsLabel: 'No saved traces found.' }} // Custom empty text
          />
      </Box>

      {/* === Edit Dialog === */}
      <Dialog open={isEditDialogOpen} onClose={handleEditDialogClose} maxWidth="sm" fullWidth>
        <DialogTitle>Edit Trace Metadata</DialogTitle>
        <DialogContent>
           {/* Name Field */}
           <TextField
              autoFocus
              margin="dense"
              id="edit-trace-name"
              name="name"
              label="Trace Name"
              type="text"
              fullWidth
              variant="standard"
              value={editFormData.name}
              onChange={handleEditFormChange}
              required
              error={!!editError && editError.toLowerCase().includes("name")}
              helperText={editError && editError.toLowerCase().includes("name") ? editError : ""}
              disabled={editLoading}
            />
            {/* Description Field */}
            <TextField
              margin="dense"
              id="edit-trace-description"
              name="description"
              label="Description (Optional)"
              type="text"
              fullWidth
              variant="standard"
              multiline
              rows={3}
              value={editFormData.description}
              onChange={handleEditFormChange}
              disabled={editLoading}
            />
            {/* Display general edit errors */}
            {editError && !editError.toLowerCase().includes("name") && (
              <Alert severity="error" sx={{ mt: 2 }}>{editError}</Alert>
            )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleEditDialogClose} disabled={editLoading}>Cancel</Button>
          <Button onClick={handleEditSave} variant="contained" disabled={editLoading}>
            {editLoading ? <CircularProgress size={24}/> : 'Save Changes'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* === Delete Confirmation Dialog === */}
      <Dialog
        open={isDeleteDialogOpen}
        onClose={handleDeleteDialogClose}
        aria-labelledby="delete-dialog-title"
        aria-describedby="delete-dialog-description"
      >
        <DialogTitle id="delete-dialog-title">Confirm Deletion</DialogTitle>
        <DialogContent>
          <DialogContentText id="delete-dialog-description">
            Are you sure you want to delete the trace named "{deletingTrace?.name || 'this trace'}"?
            <br />
            This action cannot be undone.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleDeleteDialogClose} disabled={deleteLoading}>Cancel</Button>
          <Button
            onClick={handleDeleteConfirm}
            color="error"
            variant="contained"
            disabled={deleteLoading}
            autoFocus
          >
             {deleteLoading ? <CircularProgress size={24}/> : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>

    </Box> // End of main page container
  );
};

export default UploadPage;
