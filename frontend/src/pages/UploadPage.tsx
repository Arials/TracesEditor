// File: src/pages/UploadPage.tsx
// Purpose: Allows users to upload new PCAP traces, view existing traces,
//          edit metadata, delete traces, and select a trace for analysis
//          in other pages (Subnets, DICOM).
// Changes: Renamed 'handleAnalyze' to 'handleSelectSession' and removed navigation
//          so it only sets the session ID in the context. Updated tooltip.
//          Refactored DataGrid columns to be dynamic like DicomPage. Added download button.

import React, { useState, useEffect, useCallback, useMemo } from 'react'; // Added useMemo
// import { useNavigate } from 'react-router-dom'; // No longer needed here
import axios from 'axios';
import { useSession } from '../context/SessionContext';

// Import API service functions and types
import {
    // listSessions, // No longer called directly here
    uploadCapture,
    updateSession,
    deleteSession,
    downloadSessionFile, // Import the generic download function
    PcapSession, // This interface now includes file_type etc.
    PcapSessionUpdateData
} from '../services/api';

// Material UI Imports
import {
  Box, Typography, Button, Input, CircularProgress, Alert, TextField, LinearProgress, Divider,
  Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, IconButton, Tooltip, Chip // Added Chip
} from '@mui/material';
// Removed incorrect GridValueGetterParams import
import { DataGrid, GridColDef, GridRenderCellParams } from '@mui/x-data-grid';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import DownloadIcon from '@mui/icons-material/Download'; // Added DownloadIcon

// Props are no longer needed as data will come from context
// interface UploadPageProps {
//   traces: PcapSession[];
//   listLoading: boolean;
//   fetchTraces: () => Promise<void>; // Function to refresh the list
// }

const UploadPage: React.FC = () => { // Removed props
  // --- Get session data from context ---
  const {
    sessions, // Renamed from traces
    isLoadingSessions, // Renamed from listLoading
    sessionsError, // For displaying list fetching errors
    fetchSessions, // Renamed from fetchTraces
    activeSessionId,
    setActiveSession,
    // addSession, // Potentially for optimistic UI updates
    // updateSessionInList, // Potentially for optimistic UI updates
    // removeSession // Potentially for optimistic UI updates
  } = useSession();

  // --- State for Upload Form ---
  const [file, setFile] = useState<File | null>(null);
  const [traceName, setTraceName] = useState('');
  const [traceDesc, setTraceDesc] = useState('');
  const [uploadLoading, setUploadLoading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState('');
  const [fileTypeError, setFileTypeError] = useState('');

  // --- State for Trace List & Management ---
  // listError (now sessionsError) is handled by context. Local errors for specific actions remain.
  const [deleteError, setDeleteError] = useState<string | null>(null);
  // activeSessionId and setActiveSession are already destructured from useSession() above.

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
  // --- State for Download ---
  const [downloadingFileId, setDownloadingFileId] = useState<string | null>(null); // Store ID of file being downloaded
  const [downloadError, setDownloadError] = useState<string | null>(null); // Store download errors


  // --- Hooks ---
  // const navigate = useNavigate(); // Not needed

  // --- Data Fetching ---
  // fetchTraces is now passed as a prop from App.tsx
  // The initial fetch is handled in App.tsx's useEffect

  // Note: The localStorage listener useEffect has been removed as direct context updates
  // (via fetchSessions called by useJobTracking callback) will handle same-tab refreshes.
  // Cross-tab refresh still relies on localStorage being set by useJobTracking and
  // the browser firing the 'storage' event to other tabs if UploadPage is open there.

  // Effect to listen for localStorage changes from other tabs
  useEffect(() => {
    const handleStorageChange = (event: StorageEvent) => {
      if (event.key === 'pcapSessionsLastUpdated') {
        // console.log('UploadPage: Detected pcapSessionsLastUpdated change (cross-tab), refreshing traces.');
        fetchSessions(); 
      }
    };
    window.addEventListener('storage', handleStorageChange);
    return () => {
      window.removeEventListener('storage', handleStorageChange);
    };
  }, [fetchSessions]); // fetchSessions from SessionContext

  // --- Event Handlers ---

  /**
   * Handles the selection of a file from the input field.
   * Validates the file type (.pcap or .pcapng) and updates component state.
   * If the trace name field is empty, it pre-fills it with the filename (without extension).
   * @param e - The React change event from the file input element.
   */
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

  /**
   * Handles the trace file upload process.
   * Validates the selected file and trace name, then calls the API to upload the capture.
   * Manages loading states, progress updates, and error handling for the upload.
   * On success, it refreshes the session list and clears the form.
   */
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
    const nameExists = sessions.some( // Use sessions from context
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
      await fetchSessions(); // Use fetchSessions from context
      setTraceName('');
      setTraceDesc('');
      setFile(null);
      // Reset file input visually by changing its key in the JSX below
      setUploadProgress(0); // Reset progress bar

    } catch (err: any) {
      // Handle upload errors
      let displayMessage = "An unexpected error occurred while uploading. Please try again.";
      if (axios.isAxiosError(err)) {
        if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
            displayMessage = `Upload Failed: ${err.response.data.detail}`;
        } else if (err.message) {
            displayMessage = `Upload Failed: ${err.message}`;
        } else {
            displayMessage = `Upload Failed: An unknown server error occurred (status ${err.response?.status || 'N/A'}).`;
        }
      } else if (err instanceof Error && err.message) {
        displayMessage = err.message;
      }
      setUploadError(displayMessage);
      console.error("Upload error details:", err);
      setUploadProgress(0); // Reset progress on error
    } finally {
      setUploadLoading(false); // Ensure loading indicator stops
    }
  };

  // --- Edit Handlers ---
  /**
   * Opens the edit dialog and pre-fills the form with the data of the selected trace.
   * @param trace - The PCAP session object to be edited.
   */
  const handleEditClick = useCallback((trace: PcapSession) => {
    // console.log("Edit clicked for trace:", trace);
    setEditingTrace(trace);
    setEditFormData({
        name: trace.name,
        description: trace.description || ''
    });
    setIsEditDialogOpen(true);
    setEditError(null);
  }, []);

  /**
   * Closes the edit dialog and resets its associated state (editingTrace, form data, errors, loading).
   */
  const handleEditDialogClose = useCallback(() => {
    setIsEditDialogOpen(false);
    setTimeout(() => { // Delay reset to allow dialog close animation
        setEditingTrace(null);
        setEditFormData({ name: '', description: '' });
        setEditError(null);
        setEditLoading(false);
    }, 150);
  }, []);

  /**
   * Updates the `editFormData` state as the user types in the edit dialog form fields.
   * @param event - The React change event from the input or textarea element.
   */
  const handleEditFormChange = useCallback((event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = event.target;
    setEditFormData(prev => ({ ...prev, [name]: value }));
  }, []);

  /**
   * Handles saving the edited trace data.
   * Validates the form data (name cannot be empty, checks for duplicate names),
   * then calls the API to update the session.
   * Manages loading states and error handling for the save operation.
   * On success, refreshes the session list and closes the dialog.
   */
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
    const nameExists = sessions.some( // Use sessions from context
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
      await fetchSessions(); // Use fetchSessions from context
      handleEditDialogClose(); // Close dialog
    } catch (err: any) {
      console.error("Failed to update trace:", err);
      let displayMessage = "An unexpected error occurred while saving changes. Please try again.";
      if (axios.isAxiosError(err)) {
        if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
            displayMessage = `Update Failed: ${err.response.data.detail}`;
        } else if (err.message) {
            displayMessage = `Update Failed: ${err.message}`;
        } else {
            displayMessage = `Update Failed: An unknown server error occurred (status ${err.response?.status || 'N/A'}).`;
        }
      } else if (err instanceof Error && err.message) {
        displayMessage = err.message;
      }
      setEditError(displayMessage); // Show error within the dialog
    } finally {
      setEditLoading(false); // Ensure loading indicator stops
    }
  }, [editingTrace, editFormData, sessions, fetchSessions, handleEditDialogClose]); // Use sessions and fetchSessions from context
  // --- End of Edit Handlers ---

  // --- Delete Handlers ---
  /**
   * Opens the delete confirmation dialog for the selected trace.
   * @param trace - The PCAP session object to be deleted.
   */
  const handleDeleteClick = useCallback((trace: PcapSession) => {
    // console.log("Attempting to delete trace:", trace);
    setDeletingTrace(trace);
    setIsDeleteDialogOpen(true);
    setDeleteError(null); // Clear previous delete errors
    setDownloadError(null); // Clear download errors as well, as they share some UI space
  }, []);

  /**
   * Closes the delete confirmation dialog and resets its associated state.
   */
  const handleDeleteDialogClose = useCallback(() => {
    setIsDeleteDialogOpen(false);
    setTimeout(() => { // Delay reset for dialog animation
        setDeletingTrace(null);
        setDeleteLoading(false);
    }, 150);
  }, []);

  /**
   * Handles the actual deletion of a trace after user confirmation.
   * Calls the API to delete the session and manages loading/error states.
   * On success, refreshes the session list and closes the dialog.
   */
  const handleDeleteConfirm = useCallback(async () => {
    if (!deletingTrace) return;

    // console.log("Confirming deletion for trace ID:", deletingTrace.id);
    setDeleteLoading(true);
    setDeleteError(null); // Clear local delete error

    try {
      await deleteSession(deletingTrace.id);
      // console.log("Trace deleted successfully:", deletingTrace.id);
      await fetchSessions(); // Use fetchSessions from context
      handleDeleteDialogClose(); // Close dialog

    } catch (err: any) {
      console.error("Failed to delete trace:", err);
      let displayMessage = "An unexpected error occurred while deleting the trace. Please try again.";
      if (axios.isAxiosError(err)) {
        if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
            displayMessage = `Deletion Failed: ${err.response.data.detail}`;
        } else if (err.message) {
            displayMessage = `Deletion Failed: ${err.message}`;
        } else {
            displayMessage = `Deletion Failed: An unknown server error occurred (status ${err.response?.status || 'N/A'}).`;
        }
      } else if (err instanceof Error && err.message) {
        displayMessage = err.message;
      }
      // Display the error using the local deleteError state
      setDeleteError(displayMessage);
      // Keep the dialog open on error? Or close? Closing for now.
    } finally {
       setDeleteLoading(false);
    }
  }, [deletingTrace, fetchSessions, handleDeleteDialogClose]); // Use fetchSessions from context
  // --- End of Delete Handlers ---

  // --- Download Handler ---
  /**
   * Handles the download of a trace file (original or transformed).
   * Determines the correct session ID and filename to use for the API call.
   * Manages loading and error states for the download.
   * @param trace - The PCAP session object whose file is to be downloaded.
   */
  const handleDownload = useCallback(async (trace: PcapSession) => {
    if (!trace || downloadingFileId) return; // Prevent double clicks or if already downloading

    // Determine the correct session ID and filename for the download API.
    // For original files, use trace.id and trace.original_filename.
    // For transformed files (derived traces), use trace.derived_from_session_id and trace.actual_pcap_filename.
    // For original files, use trace.id and trace.original_filename
    // For transformed files, use derived_from_session_id and actual_pcap_filename
    const sessionIdToUse = trace.derived_from_session_id || trace.id;
    const filenameToUse = trace.actual_pcap_filename || trace.original_filename || `${trace.name}.pcap`; // Fallback filename

    // console.log(`Attempting download: SessionID='${sessionIdToUse}', Filename='${filenameToUse}', TraceID='${trace.id}'`);

    setDownloadingFileId(trace.id); // Use the trace's unique ID for loading state
    setDownloadError(null); // Clear previous errors

    try {
      await downloadSessionFile(sessionIdToUse, filenameToUse);
      // Download is handled by the browser, no further action needed on success here
    } catch (err: any) {
      console.error("Download failed:", err);
      // The error message might be pre-formatted by api.ts
      setDownloadError(err.message || `Failed to download file ${filenameToUse}.`);
    } finally {
      setDownloadingFileId(null); // Clear loading state for this trace ID
    }
  }, [downloadingFileId]); // Dependency
  // --- End of Download Handler ---


  // --- MODIFIED: Function to set the active session ---
  /** Sets the clicked trace as the active session in the global context */
  const handleSelectSession = useCallback((trace: PcapSession) => {
    if (!trace || !trace.id || !trace.name) {
        console.error("handleSelectSession: Invalid trace object received", trace); // Keep error log
        return;
    }
    // console.log(`Setting active session: ID=${trace.id}, Name=${trace.name}`);
    // Call the context function with the full trace object
    setActiveSession(trace);
    // No navigation here - user will use sidebar to navigate to analysis pages
  }, [setActiveSession]); // Dependency is setActiveSession

  // Helper function to format header names (similar to DicomPage)
  const formatHeaderName = (key: string): string => {
    const spaced = key
      .replace(/_/g, ' ')
      .replace(/([a-z])([A-Z])/g, '$1 $2')
      .trim();
    return spaced
      .split(' ')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
      .join(' ');
  };


  // --- DataGrid Column Definitions (Dynamic) ---
  const columns = useMemo((): GridColDef<PcapSession>[] => {
    // Define static columns first
    const staticColumns: GridColDef<PcapSession>[] = [
      // --- ACTION COLUMN ---
      {
        field: 'actions',
        headerName: 'Actions',
        width: 180, // Increased width for download button
      sortable: false,
      filterable: false,
      disableColumnMenu: true,
        renderCell: (params: GridRenderCellParams<any, PcapSession>) => {
          const currentTrace = params.row;
          // Removed duplicate declaration: const currentTrace = params.row;
          const isActive = currentTrace.id === activeSessionId; // Check if this row is the currently active session
          // Download logic moved to onClick handler below

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
              {/* Download Button */}
              <Tooltip title="Download Trace File">
                {/* Span needed for tooltip on disabled button */}
                <span>
                  <IconButton
                    aria-label="download"
                    size="small"
                    onClick={() => handleDownload(currentTrace)}
                    disabled={downloadingFileId === currentTrace.id} // Disable while this specific file is downloading
                  >
                    {downloadingFileId === currentTrace.id ? <CircularProgress size={18} /> : <DownloadIcon fontSize="inherit" />}
                  </IconButton>
                </span>
              </Tooltip>
              <Tooltip title="Delete Trace">
                <IconButton
                  aria-label="delete"
                  size="small"
                  onClick={() => handleDeleteClick(currentTrace)} // Corrected handler and removed duplicate props
                >
                  <DeleteIcon fontSize="inherit" />
                </IconButton>
              </Tooltip>
            </Box>
          );
        },
      },
      // --- TYPE COLUMN ---
      {
        field: 'file_type', // Use the new field from the PcapSession interface
        headerName: 'Type',
        width: 180, // Increased width for longer labels
        renderCell: (params: GridRenderCellParams<any, PcapSession>) => {
          let label = "Original";
          let color: "primary" | "secondary" | "info" | "warning" | "success" | "error" | "default" = "primary"; // Default color type
          switch (params.row.file_type) {
            case "original":
              label = "Original Upload";
              color = "primary";
              break;
            case "ip_mac_anonymized":
              label = "IP/MAC Anonymized";
              color = "secondary";
              break;
            case "mac_transformed":
              label = "MAC Transformed";
              color = "info"; // Use a different color
              break;
            case "dicom_v2_anonymized": // Add case for potential future types
              label = "DICOM V2 Anonymized";
              color = "success";
              break;
            default:
              // Fallback based on is_transformed if file_type is missing/unexpected
              label = params.row.is_transformed ? "Transformed (Legacy)" : "Original";
              color = params.row.is_transformed ? "warning" : "primary";
          }
          return (
            <Chip label={label} size="small" color={color} variant="outlined" />
          );
        },
      },
    ];

    // Get all unique keys from the first trace object (assuming all traces have the same structure)
    // Exclude keys already handled by static columns or internal IDs
    const dynamicKeys = sessions.length > 0 // Use sessions from context
      ? Object.keys(sessions[0]).filter(key =>
          key !== 'id' && // Exclude internal ID
          key !== 'actions' && // Exclude manually added field
          key !== 'type' && // Exclude manually added field
          key !== 'is_transformed' && // Handled by 'type' column
          key !== 'original_session_id' // Used in 'name' tooltip
        )
      : [];

    // Create GridColDef for each dynamic key
    const dynamicColumns: GridColDef<PcapSession>[] = dynamicKeys.map(key => {
      const headerName = formatHeaderName(key);
      let minWidth = 150; // Default min width
      let flex = 1; // Default flex grow

      // Adjust sizing hints based on key
      if (key.toLowerCase().includes('name')) { minWidth = 200; flex = 1.5; }
      if (key.toLowerCase().includes('description')) { minWidth = 250; flex = 2; }
      if (key.toLowerCase().includes('filename')) { minWidth = 200; flex = 1.5; }
      if (key.toLowerCase().includes('timestamp')) { minWidth = 180; flex = 1; }

      // Base column definition
      let colDef: GridColDef<PcapSession> = {
        field: key,
        headerName: headerName,
        minWidth: minWidth,
        flex: flex,
        sortable: true,
        editable: false, // Editing is done via dialog
        // Custom rendering logic
        renderCell: (params: GridRenderCellParams<any, PcapSession>) => {
          // Explicitly access the value from the row using the current key
          const value = params.row[key as keyof PcapSession];
          const rowData = params.row; // Keep rowData for context if needed (e.g., for 'name' tooltip)

          // Specific rendering for 'name'
          if (key === 'name') {
            const name = value as string || '';
            return rowData.is_transformed ? (
              <Tooltip title={`Transformed from session ID: ${rowData.original_session_id || 'N/A'}`}>
                <Typography variant="body2" noWrap>{name}</Typography>
              </Tooltip>
            ) : (
              <Typography variant="body2" noWrap>{name}</Typography>
            );
          }

          // Specific rendering/formatting for 'upload_timestamp'
          if (key === 'upload_timestamp') {
            // Ensure value is treated as string for Date constructor
            const date = value ? new Date(value as string) : null;
            const displayValue = date ? date.toLocaleString() : '';
            return (
              <Tooltip title={displayValue}>
                <Typography variant="body2" noWrap>{displayValue}</Typography>
              </Tooltip>
            );
          }

          // Default rendering for other types (string, number, boolean, etc.)
          // Ensure value is converted to string for Tooltip title and Typography children
          const displayValue = (value === null || value === undefined) ? '' : String(value);
          let tooltipTitle = displayValue;
          if (typeof value === 'object' && value !== null) {
              try {
                  tooltipTitle = JSON.stringify(value);
              } catch {
                  tooltipTitle = '[Object]'; // Fallback if stringify fails
              }
          }

          return (
            <Tooltip title={tooltipTitle}>
              {/* Display the simple string version in the cell */}
              {/* Ensure Typography child is a string */}
              <Typography variant="body2" noWrap>{displayValue}</Typography>
            </Tooltip>
          );
        },
        // Conditionally add type and valueGetter directly in the definition
        type: key === 'upload_timestamp' ? 'dateTime' : undefined,
        valueGetter: key === 'upload_timestamp'
          ? (params: any) => (params?.row?.upload_timestamp ? new Date(params.row.upload_timestamp as string) : null)
          : undefined,
      };

      return colDef;
    });

    // Combine static and dynamic columns
    return [...staticColumns, ...dynamicColumns];

  }, [sessions, activeSessionId, handleEditClick, handleDeleteClick, handleSelectSession, fetchSessions]); // Added fetchSessions to dependencies, use sessions


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
      {/* Display delete errors */}
      {deleteError && <Alert severity="error" sx={{ mb: 2 }}>{deleteError}</Alert>}
      {/* Display download errors */}
      {downloadError && <Alert severity="error" sx={{ mb: 2 }}>{downloadError}</Alert>}
      {/* Display session fetching errors from context */}
      {sessionsError && <Alert severity="error" sx={{ mb: 2 }}>{sessionsError}</Alert>}
      <Box sx={{ height: 500, width: '100%' }}> {/* Container for DataGrid */}
         <DataGrid
            rows={sessions} // Use sessions from context
            columns={columns} // Column definitions
            loading={isLoadingSessions} // Use isLoadingSessions from context
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
