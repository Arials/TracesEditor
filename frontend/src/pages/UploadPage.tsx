// File: UploadPage.tsx
// Moved Actions column to the left in the DataGrid.
// Added/updated English comments.

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios'; // For improved error handling
import { useSession } from '../context/SessionContext'; // Verify path is correct
import {
    listSessions,
    uploadCapture,
    updateSession, // Needed for edit functionality (currently placeholder)
    deleteSession, // Needed for delete functionality
    PcapSession, // Import main type
    PcapSessionUpdateData // Import type for update payload
} from '../services/api'; // Verify path is correct

// Material UI Imports
import {
  Box, Typography, Button, Input, CircularProgress, Alert, TextField, LinearProgress, Divider,
  Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, IconButton
} from '@mui/material';
// --- Ensure DataGrid and Action Icons are imported ---
import { DataGrid, GridColDef, GridRenderCellParams } from '@mui/x-data-grid'; // Removed unused GridActionsCellItem, GridRowId
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
  const [listError, setListError] = useState<string | null>(null); // Can be used for list fetch errors or delete errors

  // --- State for Edit Dialog ---
  const [isEditDialogOpen, setIsEditDialogOpen] = useState<boolean>(false);
  const [editingTrace, setEditingTrace] = useState<PcapSession | null>(null);
  const [editFormData, setEditFormData] = useState<PcapSessionUpdateData>({ name: '', description: '' });
  const [editLoading, setEditLoading] = useState<boolean>(false); // State for loading indicator during edit save
  const [editError, setEditError] = useState<string | null>(null); // State for errors within the edit dialog


  // --- State for Delete Dialog ---
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState<boolean>(false);
  const [deletingTrace, setDeletingTrace] = useState<PcapSession | null>(null);
  const [deleteLoading, setDeleteLoading] = useState<boolean>(false); // State for loading indicator during delete confirm
  // Note: deleteError uses listError currently, could add a dedicated state if needed


  // --- Hooks ---
  const navigate = useNavigate();
  const { setSessionId } = useSession();

  // --- Data Fetching ---
  const fetchTraces = useCallback(async () => {
    setListLoading(true);
    setListError(null); // Clear previous errors when refetching
    try {
      const response = await listSessions();
      // Ensure IDs are strings if needed by DataGrid
      setTraces(response.data.map((trace: PcapSession) => ({ ...trace, id: String(trace.id) })));
      console.log("Fetched Traces Data:", response.data);
    } catch (err: any) {
      console.error("Failed to fetch traces:", err);
      setListError(err.response?.data?.detail || err.message || "Failed to load trace list. Please check backend connection.");
    } finally {
      setListLoading(false);
    }
  }, []); // Dependency array is empty as it doesn't depend on component state/props

  // Initial fetch on component mount
  useEffect(() => {
    fetchTraces();
  }, [fetchTraces]); // fetchTraces is stable due to useCallback

  // --- Event Handlers ---

  /** Handles file selection from input and validates type */
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0] || null;
    setUploadError(''); // Clear previous upload errors
    setFileTypeError(''); // Clear previous file type errors

    if (selectedFile) {
        const validExtensions = ['.pcap', '.pcapng'];
        const fileExtension = selectedFile.name.substring(selectedFile.name.lastIndexOf('.')).toLowerCase();
        if (!validExtensions.includes(fileExtension)) {
            setFileTypeError(`Invalid file type (${fileExtension}). Please select a .pcap or .pcapng file.`);
            setFile(null); // Clear invalid file selection
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
    // Clear previous errors
    setUploadError('');
    setFileTypeError('');

    // --- Validation ---
    if (!file) {
      setUploadError('Please select a PCAP file first.');
      return;
    }
    // Redundant type check (good safeguard)
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
    console.log('Checking for duplicate name:', `"${trimmedName.toLowerCase()}"`);
    const nameExists = traces.some(
        trace => trace.name.trim().toLowerCase() === trimmedName.toLowerCase()
    );
    if (nameExists) {
        console.log('Duplicate name found!');
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
      // Reset file input visually by changing its key in the JSX
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
  // --- IMPLEMENT LOGIC HERE ---

  /** Opens the edit dialog and pre-fills the form with the selected trace data */
  const handleEditClick = useCallback((trace: PcapSession) => {
    console.log("Edit clicked for trace:", trace);
    setEditingTrace(trace); // Store the trace being edited
    setEditFormData({ // Pre-fill form data
        name: trace.name,
        description: trace.description || '' // Use empty string if description is null
    });
    setIsEditDialogOpen(true); // Open the dialog
    setEditError(null); // Clear any previous edit errors
  }, []); // Depends only on set* functions, so it's stable

  /** Closes the edit dialog and resets related state */
  const handleEditDialogClose = useCallback(() => {
    setIsEditDialogOpen(false);
    // Delay resetting state slightly to avoid seeing cleared fields during closing animation
    setTimeout(() => {
        setEditingTrace(null);
        setEditFormData({ name: '', description: '' });
        setEditError(null);
        setEditLoading(false); // Ensure loading state is reset
    }, 150); // Adjust timing as needed
  }, []);

  /** Updates the state bound to the edit form fields */
  const handleEditFormChange = useCallback((event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = event.target;
    setEditFormData(prev => ({ ...prev, [name]: value }));
  }, []);

  /** Handles saving the edited trace data via API call */
  const handleEditSave = useCallback(async () => {
    if (!editingTrace) return; // Should not happen if dialog is open correctly

    setEditLoading(true);
    setEditError(null);
    const trimmedName = editFormData.name.trim();
    const trimmedDesc = editFormData.description.trim();

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

    // Prepare data payload for API
    const updateData: PcapSessionUpdateData = {
      name: trimmedName,
      description: trimmedDesc || null // Send null if description is empty
    };

    try {
      // Call API to update the session
      await updateSession(editingTrace.id, updateData);
      await fetchTraces(); // Refresh the list to show updated data
      handleEditDialogClose(); // Close dialog on success
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
  }, [editingTrace, editFormData, traces, fetchTraces, handleEditDialogClose]); // Dependencies for the save handler

  // --- End of Edit Handlers ---


  // --- Delete Handlers (Previously Implemented) ---

  /** Opens the delete confirmation dialog */
  const handleDeleteClick = useCallback((trace: PcapSession) => {
    console.log("Attempting to delete trace:", trace);
    setDeletingTrace(trace); // Store the trace to be deleted
    setIsDeleteDialogOpen(true); // Open the confirmation dialog
    setListError(null); // Clear list errors when opening dialog
  }, []);

  /** Closes the delete confirmation dialog */
  const handleDeleteDialogClose = useCallback(() => {
    setIsDeleteDialogOpen(false);
    // Delay reset for animation
    setTimeout(() => {
        setDeletingTrace(null);
        setDeleteLoading(false); // Reset loading state
    }, 150);
  }, []);

  /** Handles the actual deletion process after confirmation */
  const handleDeleteConfirm = useCallback(async () => {
    if (!deletingTrace) return;

    console.log("Confirming deletion for trace ID:", deletingTrace.id);
    setDeleteLoading(true); // Start loading indicator
    setListError(null); // Clear previous errors

    try {
      await deleteSession(deletingTrace.id); // Call the API service function
      console.log("Trace deleted successfully:", deletingTrace.id);
      await fetchTraces(); // Refresh the list to reflect the deletion
      handleDeleteDialogClose(); // Close the dialog AFTER successful deletion and refresh

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
      // Optionally: setDeleteLoading(false); // Stop loading only if dialog stays open
    } finally {
       setDeleteLoading(false); // Ensure loading stops if error occurred but dialog closes
       // If the dialog might stay open on error, move setDeleteLoading(false) inside catch *only*
    }
  }, [deletingTrace, fetchTraces, handleDeleteDialogClose]); // Dependencies for delete confirm

  // --- End of Delete Handlers ---

  /** Navigates to the analysis page (/subnets) for the selected trace */
  const handleAnalyze = useCallback((id: string) => {
    console.log("Setting active session ID for analysis:", id);
    setSessionId(id); // Set session ID in context
    navigate('/subnets'); // Navigate to the subnets page route
  }, [navigate, setSessionId]); // Dependencies


  // --- DataGrid Column Definitions ---
  // --- MODIFIED: Moved 'actions' column to the beginning ---
  const columns: GridColDef<PcapSession>[] = [
    // --- ACTION COLUMN (Now first) ---
    {
      field: 'actions',
      headerName: 'Actions',
      width: 150, // Adjusted width
      sortable: false,
      filterable: false,
      disableColumnMenu: true,
      renderCell: (params: GridRenderCellParams<any, PcapSession>) => { // Ensure correct row type
        const currentTrace = params.row;
        return (
          <Box sx={{ display: 'flex', justifyContent: 'space-evenly', width: '100%' }}>
            <IconButton
              aria-label="analyze"
              size="small"
              onClick={() => handleAnalyze(currentTrace.id)}
              title="Analyze Trace"
            >
              <PlayArrowIcon fontSize="inherit" />
            </IconButton>
            <IconButton
              aria-label="edit"
              size="small"
              onClick={() => handleEditClick(currentTrace)}
              title="Edit Metadata"
            >
              <EditIcon fontSize="inherit" />
            </IconButton>
            <IconButton
              aria-label="delete"
              size="small"
              onClick={() => handleDeleteClick(currentTrace)}
              title="Delete Trace"
            >
              <DeleteIcon fontSize="inherit" />
            </IconButton>
          </Box>
        );
      },
    },
    // --- OTHER DATA COLUMNS ---
    {
      field: 'name',
      headerName: 'Trace Name',
      width: 220, // Slightly wider?
      editable: false, // Metadata editing is done via dialog
    },
    {
      field: 'description',
      headerName: 'Description',
      width: 280, // Slightly wider?
      sortable: false,
      editable: false,
    },
    {
      field: 'original_filename',
      headerName: 'Original File',
      width: 220,
      sortable: false, // Usually not needed to sort by filename
    },
    {
      field: 'upload_timestamp',
      headerName: 'Uploaded At',
      width: 180,
      type: 'dateTime',
      // Use valueGetter to ensure Date object is passed to the renderer
      valueGetter: (value: string | null | undefined) => value ? new Date(value) : null,
      // Optional: Define rendering format if needed (default is usually locale-specific)
      // valueFormatter: (value: Date | null) => value ? value.toLocaleString() : '',
    },
    // --- OLD ACTION COLUMN POSITION (Removed from here) ---
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
            // Show error if upload failed *because* name was empty, or if upload error is generic duplicate name
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
          // Use a key that changes when the file is cleared to force re-render and reset internal state
          key={file ? `file-${file.name}-${file.lastModified}` : 'file-input-cleared'}
          inputProps={{ accept: '.pcap,.pcapng' }}
          onChange={handleFileChange}
          sx={{ display: 'block', mb: 2 }}
          disabled={uploadLoading}
          error={!!fileTypeError} // Indicate error state on the input itself
        />
        {/* Display file type error message */}
        {fileTypeError && <Alert severity="warning" sx={{ mb: 2 }}>{fileTypeError}</Alert>}

        {/* Upload Button */}
        <Button
          variant="contained"
          color="primary"
          // Disable upload if: no file selected, name is empty, upload/job is in progress, or file type error exists
          disabled={!file || !traceName.trim() || uploadLoading || !!fileTypeError}
          onClick={handleUpload}
          startIcon={uploadLoading ? <CircularProgress size={20} color="inherit"/> : null} // Show spinner inside button
        >
          {uploadLoading ? `Uploading (${uploadProgress}%)` : 'Upload Trace'}
        </Button>
        {/* Progress Bar */}
        {uploadLoading && (
          <Box sx={{ width: '100%', mt: 1 }}><LinearProgress variant="determinate" value={uploadProgress} /></Box>
        )}
        {/* Display general upload errors (API failure, non-name related validation) */}
        {uploadError && !uploadError.includes("already exists") && !uploadError.includes("Name is required") && (
             <Alert severity="error" sx={{ mt: 2 }}>{uploadError}</Alert>
        )}
      </Box>

      <Divider sx={{ my: 4 }} />

      {/* === Saved Traces List Section === */}
      <Typography variant="h5" gutterBottom component="h2">Saved Traces</Typography>
      {/* Display list fetch or delete errors here */}
      {listError && !listLoading && <Alert severity="error" sx={{ mb: 2 }}>{listError}</Alert>}
      <Box sx={{ height: 500, width: '100%' }}> {/* Container for DataGrid */}
         <DataGrid
            rows={traces} // Data rows
            columns={columns} // Column definitions (with Actions now on the left)
            loading={listLoading} // Show loading overlay when fetching
            pageSizeOptions={[5, 10, 25, 50]} // Rows per page options
            initialState={{
              pagination: { paginationModel: { pageSize: 10 } }, // Default page size
              sorting: { sortModel: [{ field: 'upload_timestamp', sort: 'desc' }] }, // Default sort
            }}
            getRowId={(row) => row.id} // Explicitly tell DataGrid how to get the row ID
            // autoHeight={false} // Use fixed height (set on parent Box) for better performance
            disableRowSelectionOnClick // Prevent selection when clicking cells
            density="compact" // Reduce row padding
            localeText={{ noRowsLabel: 'No saved traces found.' }} // Custom text for empty grid
          />
      </Box>

      {/* === Edit Dialog === */}
      <Dialog open={isEditDialogOpen} onClose={handleEditDialogClose} maxWidth="sm" fullWidth>
        <DialogTitle>Edit Trace Metadata</DialogTitle>
        <DialogContent>
          {/* Optional: Explain what can be edited */}
          {/* <DialogContentText sx={{ mb: 2 }}>
            Modify the name and description for the trace: {editingTrace?.original_filename ?? ''}
          </DialogContentText> */}
           {/* Name Field */}
           <TextField
              autoFocus // Focus this field when dialog opens
              margin="dense"
              id="edit-trace-name" // Add id for label association
              name="name" // Must match key in editFormData state
              label="Trace Name"
              type="text"
              fullWidth
              variant="standard"
              value={editFormData.name}
              onChange={handleEditFormChange}
              required // Indicate field is required
              error={!!editError && editError.toLowerCase().includes("name")} // Show error if related to name
              helperText={editError && editError.toLowerCase().includes("name") ? editError : ""}
              disabled={editLoading} // Disable while save is in progress
            />
            {/* Description Field */}
            <TextField
              margin="dense"
              id="edit-trace-description"
              name="description" // Must match key in editFormData state
              label="Description (Optional)"
              type="text"
              fullWidth
              variant="standard"
              multiline
              rows={3}
              value={editFormData.description}
              onChange={handleEditFormChange}
              disabled={editLoading} // Disable while save is in progress
            />
            {/* Display general edit errors */}
            {editError && !editError.toLowerCase().includes("name") && (
                <Alert severity="error" sx={{ mt: 2 }}>{editError}</Alert>
            )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleEditDialogClose} disabled={editLoading}>Cancel</Button>
          <Button onClick={handleEditSave} variant="contained" disabled={editLoading}>
            {/* Show loading indicator */}
            {editLoading ? <CircularProgress size={24}/> : 'Save Changes'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* === Delete Confirmation Dialog === */}
      <Dialog
        open={isDeleteDialogOpen}
        onClose={handleDeleteDialogClose} // Close when clicking outside or pressing Esc
        aria-labelledby="delete-dialog-title"
        aria-describedby="delete-dialog-description"
      >
        <DialogTitle id="delete-dialog-title">Confirm Deletion</DialogTitle>
        <DialogContent>
          <DialogContentText id="delete-dialog-description">
            Are you sure you want to delete the trace named "{deletingTrace?.name || 'this trace'}"?
            <br /> {/* Add line break for better readability */}
            This action cannot be undone.
          </DialogContentText>
          {/* Optional: Show specific delete error *inside* the dialog */}
          {/* {deleteError && <Alert severity="error" sx={{ mt: 2 }}>{deleteError}</Alert>} */}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleDeleteDialogClose} disabled={deleteLoading}>Cancel</Button>
          <Button
            onClick={handleDeleteConfirm}
            color="error" // Use error color for destructive action
            variant="contained"
            disabled={deleteLoading} // Disable while delete is in progress
            autoFocus // Focus this button by default
          >
             {deleteLoading ? <CircularProgress size={24}/> : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>

    </Box> // End of main page container
  );
};

export default UploadPage;