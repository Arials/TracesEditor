import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom'; // Import Link
import axios from 'axios'; // Import axios for error checking
import {
  Box,
  Typography,
  Paper,
  Grid,
  Divider,
  CircularProgress,
  Alert,
  Button,
  TextField,
  IconButton,
  Snackbar, // Import Snackbar
  Tooltip, // Import Tooltip
  Dialog, // Import Dialog components
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  List, // Import List components
  ListItem,
  ListItemText,
  Select, // Import Select
  MenuItem, // Import MenuItem
  FormControl, // Import FormControl
  InputLabel, // Import InputLabel
 } from '@mui/material';
 // Import GridRowId as well
 import { DataGrid, GridColDef, GridRowSelectionModel, GridRowId } from '@mui/x-data-grid'; // Removed GridFooter import
 import DeleteIcon from '@mui/icons-material/Delete';
 import AddIcon from '@mui/icons-material/Add';
 import InfoIcon from '@mui/icons-material/Info'; // Import Info icon for details
import FileUploadIcon from '@mui/icons-material/FileUpload';
import FileDownloadIcon from '@mui/icons-material/FileDownload';
 import SyncIcon from '@mui/icons-material/Sync';
 import PlayArrowIcon from '@mui/icons-material/PlayArrow';
 import SaveIcon from '@mui/icons-material/Save'; // Import Save icon

 // Assuming SessionContext provides the selected session ID
import { useSession } from '../context/SessionContext';
import { useJobTracking } from '../hooks/useJobTracking'; // Import the hook

 // Import API functions and types
import {
  getMacSettings,
  updateMacSettings, // Import the new update function
  startMacOuiUpdateJob,
  getIpMacPairs,
  getMacRules,
  saveMacRules,
  exportMacRules,
  importMacRules,
  startMacTransformationJob,
  getMacVendors, // Import the new API function
  getOuiForVendor, // Import the OUI lookup function
  MacSettings,
  IpMacPair,
  MacRule,
  JobListResponse, // For job responses
  JobStatus, // Import JobStatus
  // subscribeJobEvents and getJobDetails are no longer directly needed here as the hook handles them
} from '../services/api';

// Define a type for the rule object used in the frontend state, including potential context
/**
 * Represents a MAC transformation rule as displayed and managed in the frontend.
 * It extends the backend `MacRule` with a temporary `id` for DataGrid compatibility
 * and an optional `selectionContext` to store information about how the rule was created
 * if derived from selected IP-MAC pairs.
 */
interface DisplayMacRule extends MacRule { // Inherit all fields from MacRule (original_mac, target_vendor, target_oui)
  id: number; // Temporary, frontend-only ID for DataGrid row identification (typically array index or a running counter).
  selectionContext?: Array<{ ip: string; mac: string; original_vendor?: string | null }>; // Stores context if created from selection.
}


const MacPage: React.FC = () => {
  // Get the full activeSession object from context
  const { activeSession, fetchSessions } = useSession(); // Get full activeSession

  // --- Component State ---

  // Data states
  const [settings, setSettings] = useState<MacSettings | null>(null); // MAC anonymization settings (e.g., OUI CSV URL)
  const [ipMacPairs, setIpMacPairs] = useState<IpMacPair[]>([]); // Detected IP-MAC pairs for the active session
  const [rules, setRules] = useState<DisplayMacRule[]>([]); // MAC transformation rules for the active session
  const [allMacVendors, setAllMacVendors] = useState<string[]>([]); // List of all known MAC vendors for selection

  // Loading states
  const [loadingSettings, setLoadingSettings] = useState<boolean>(false); // True when fetching settings
  const [loadingPairs, setLoadingPairs] = useState<boolean>(false); // True when fetching IP-MAC pairs
  const [loadingRules, setLoadingRules] = useState<boolean>(false); // True when fetching rules
  const [loadingVendors, setLoadingVendors] = useState<boolean>(false); // True when fetching all MAC vendors
  const [updatingOui, setUpdatingOui] = useState<boolean>(false); // True when OUI update job is initiated
  const [isSavingSettings, setIsSavingSettings] = useState<boolean>(false); // True when saving updated settings (CSV URL)
  const [addingRule, setAddingRule] = useState<boolean>(false); // True when adding a new rule (especially from selection)
  const [deletingRuleId, setDeletingRuleId] = useState<number | null>(null); // Stores the ID of the rule being deleted to show loading state
  const [importingRules, setImportingRules] = useState<boolean>(false); // True when importing rules from a file
  const [exportingRules, setExportingRules] = useState<boolean>(false); // True when exporting rules to a file
  // Note: `transforming` state was removed as `isMacJobProcessing` from useJobTracking hook serves this purpose.

  // UI and Error states
  const [error, setError] = useState<string | null>(null); // General page-level error messages
  const [selectedRows, setSelectedRows] = useState<GridRowId[]>([]); // IDs of rows selected in the IP-MAC pairs DataGrid
  const [snackbarOpen, setSnackbarOpen] = useState<boolean>(false); // Controls Snackbar visibility for feedback
  const [snackbarMessage, setSnackbarMessage] = useState<string>(''); // Message displayed in the Snackbar
  const [editedCsvUrl, setEditedCsvUrl] = useState<string>(''); // Temporarily holds the edited OUI CSV URL before saving

  // State for "Create Rule from Selection" Dialog
  const [isRuleFromSelectionDialogOpen, setIsRuleFromSelectionDialogOpen] = useState<boolean>(false); // Controls dialog visibility
  const [selectedSourceVendors, setSelectedSourceVendors] = useState<string[]>([]); // Holds original MAC addresses of selected pairs for the dialog
  const [ruleFromSelectionTargetVendor, setRuleFromSelectionTargetVendor] = useState<string>(''); // Target vendor selected in the dialog

  // --- Job Tracking Hook for MAC Transformation ---
  const localStorageMacJobIdKey = 'macPageTransformJobId'; // Key for storing the MAC transformation job ID in localStorage
  const {
    jobStatus: macTransformJobStatus, // Renamed to avoid conflict if other jobs were tracked
    isLoadingJobDetails: isLoadingMacJobDetails,
    isProcessing: isMacJobProcessing,
    error: macJobError,
    startJob: startMacJob, // Renamed for clarity
    resetJobState: resetMacJobState,
  } = useJobTracking({
    jobIdLocalStorageKey: localStorageMacJobIdKey,
    onJobSuccess: (completedJob) => {
      console.log('MacPage onJobSuccess - completedJob:', JSON.stringify(completedJob, null, 2)); 
      setSnackbarMessage(`MAC transformation job (ID: ${completedJob.id}) completed successfully.`);
      setSnackbarOpen(true);
      if (completedJob.result_data?.output_trace_id) {
        console.log('MacPage: output_trace_id found. Same-tab refresh handled by useJobTracking via callback. Cross-tab by localStorage in hook.');
      }
      // setError(null); // Clear general page error on job success
    },
    onJobSuccessTriggerRefresh: fetchSessions, // Pass fetchSessions for same-tab refresh
    onJobFailure: (failedJob) => {
      // The hook sets macJobError. We can use that to display.
      // setError(`MAC transformation job (ID: ${failedJob.id}) failed: ${failedJob.error_message || 'Unknown error'}`);
      setSnackbarMessage(`MAC transformation job (ID: ${failedJob.id}) failed: ${failedJob.error_message || 'Unknown error'}`);
      setSnackbarOpen(true);
    },
    onSseError: (sseErr) => {
      // setError(`SSE connection error for MAC transformation job. Status may be outdated.`);
      setSnackbarMessage('SSE connection error for MAC transformation job. Status may be outdated.');
      setSnackbarOpen(true);
    }
  });


  // State for controlled pagination models
  const [ipMacPaginationModel, setIpMacPaginationModel] = useState({
    pageSize: 25,
    page: 0,
  });
  const [rulesPaginationModel, setRulesPaginationModel] = useState({
    pageSize: 10,
    page: 0,
  });


  // --- Data Fetching Callbacks ---

  /**
   * Fetches the global MAC anonymization settings.
   */
  const fetchSettings = useCallback(async () => {
    setLoadingSettings(true);
    setError(null);
    try {
      const data = await getMacSettings();
      setSettings(data);
    } catch (err: any) {
      console.error("Failed to load MAC settings:", err);
      let displayMessage = "An unexpected error occurred while loading MAC settings.";
      if (axios.isAxiosError(err)) {
        if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
            displayMessage = `Failed to load settings: ${err.response.data.detail}`;
        } else if (err.message) {
            displayMessage = `Failed to load settings: ${err.message}`;
        }
      } else if (err instanceof Error && err.message) {
        displayMessage = `Failed to load settings: ${err.message}`;
      }
      setError(displayMessage);
      setSettings(null);
    } finally {
      setLoadingSettings(false);
    }
  }, []);

  /**
   * Fetches the IP-MAC pairs for the currently active session.
   * Requires `activeSession` to be set.
   */
  const fetchIpMacPairs = useCallback(async () => {
    // Check for activeSession ID
    if (!activeSession?.id) {
      setIpMacPairs([]); // Clear pairs if no session
      setError(null); // Clear error if just no session selected
      return;
    }
    const currentSessionId = activeSession.id;
    const pcapFilename = activeSession.actual_pcap_filename; // Get pcap_filename

    if (!pcapFilename) {
      setError("Could not determine the PCAP filename for the selected session.");
      setIpMacPairs([]);
      setLoadingPairs(false);
      return;
    }

    setLoadingPairs(true);
    setError(null);
    try {
      // Pass session ID and pcap_filename to the API call
      const data = await getIpMacPairs(currentSessionId, pcapFilename);
      // Backend now returns the list directly, so use `data` instead of `data.pairs`
      setIpMacPairs(data);
    } catch (err: any) {
      console.error("Failed to load IP-MAC pairs:", err);
      let displayMessage = "An unexpected error occurred while loading IP-MAC pairs.";
      if (axios.isAxiosError(err)) {
        if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
            displayMessage = `Failed to load IP-MAC pairs: ${err.response.data.detail}`;
        } else if (err.message) {
            displayMessage = `Failed to load IP-MAC pairs: ${err.message}`;
        }
      } else if (err instanceof Error && err.message) {
        displayMessage = `Failed to load IP-MAC pairs: ${err.message}`;
      }
      setError(displayMessage);
      setIpMacPairs([]);
    } finally {
      setLoadingPairs(false);
    }
  // Depend on activeSession object itself
  }, [activeSession]);

  /**
   * Fetches the MAC transformation rules for the currently active session.
   * Requires `activeSession` to be set (filename not needed for rules).
   * Maps backend rules to `DisplayMacRule` by adding a temporary `id`.
   */
  const fetchRules = useCallback(async () => {
    if (!activeSession?.id) {
       setRules([]); // Clear rules if no active session
       return;
    }
    const currentSessionId = activeSession.id;

    setLoadingRules(true);
    setError(null);
    try {
      const data = await getMacRules(currentSessionId); // Use currentSessionId
      // Map backend rules to DisplayMacRule, adding temporary ID
      // Ensure target_oui is handled (it should come from the backend if saved correctly)
      const displayRules = data.map((rule, index) => ({
        id: index,
        original_mac: rule.original_mac,
        target_vendor: rule.target_vendor,
        target_oui: rule.target_oui || '', // Provide default empty string if missing (shouldn't happen ideally)
        // selectionContext is not loaded from backend, only added when creating from selection
      }));
      setRules(displayRules);
    } catch (err: any) {
      console.error("Failed to load MAC rules:", err);
      let displayMessage = "An unexpected error occurred while loading MAC rules.";
      if (axios.isAxiosError(err)) {
        if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
            displayMessage = `Failed to load rules: ${err.response.data.detail}`;
        } else if (err.message) {
            displayMessage = `Failed to load rules: ${err.message}`;
        }
      } else if (err instanceof Error && err.message) {
        displayMessage = `Failed to load rules: ${err.message}`;
      }
      setError(displayMessage);
      setRules([]);
    } finally {
      setLoadingRules(false);
    }
  // Depend on activeSession object (specifically its ID for rules)
  }, [activeSession]);

  // --- Initial Data Fetch ---
  useEffect(() => {
    fetchSettings();

    /** Fetches all known MAC vendors from the backend. */
    const fetchAllKnownVendors = async () => {
      setLoadingVendors(true);
      try {
        const vendors = await getMacVendors();
        setAllMacVendors(vendors);
      } catch (err: any) {
        console.error("Failed to load MAC vendors:", err);
        let displayMessage = "An unexpected error occurred while loading MAC vendors.";
        if (axios.isAxiosError(err)) {
          if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
              displayMessage = `Failed to load MAC vendors: ${err.response.data.detail}`;
          } else if (err.message) {
              displayMessage = `Failed to load MAC vendors: ${err.message}`;
          }
        } else if (err instanceof Error && err.message) {
          displayMessage = `Failed to load MAC vendors: ${err.message}`;
        }
        setError(prev => `${prev ? prev + '\n' : ''}${displayMessage}`);
        setAllMacVendors([]); // Set empty on error
      } finally {
        setLoadingVendors(false);
      }
    };
    fetchAllKnownVendors();

    // Log the active session object when the effect runs
    console.log('[MacPage useEffect] Active Session:', activeSession);

    // Fetch session-specific data only if activeSession.id exists
    if (activeSession?.id) {
      console.log('[MacPage useEffect] Active session ID found, calling fetchIpMacPairs...');
      fetchIpMacPairs(); // This now checks for filename internally
      // fetchRules(); // Removed as per new logic: Rules are not loaded on initial MacPage load
    } else {
      // Clear session-specific data if no active session
      setIpMacPairs([]);
      setRules([]);
      setError(null); // Clear potential old errors
    }
  // Depend on fetchSettings (stable), fetchIpMacPairs (depends on activeSession), fetchRules (depends on activeSession)
  // and activeSession itself to trigger re-fetch/clear when session changes.
  }, [fetchSettings, fetchIpMacPairs, fetchRules, activeSession]);

  // Effect to update the local `editedCsvUrl` state when the `settings` are loaded or changed.
  useEffect(() => {
    if (settings) {
      setEditedCsvUrl(settings.csv_url);
    }
  }, [settings]);

  // --- Event Handlers ---

  /**
   * Initiates a backend job to update the OUI (Organizationally Unique Identifier) CSV file.
   */
  const handleUpdateOui = async () => {
    setError(null);
    setUpdatingOui(true);
    try {
      const job: JobListResponse = await startMacOuiUpdateJob();
      // console.log('OUI Update Job Started:', job);
      setSnackbarMessage(`OUI update job started (ID: ${job.id}). Check Async Jobs page for status.`);
      setSnackbarOpen(true);
      // Note: Settings (last_updated) are not automatically refreshed here.
      // User might need to manually refresh or check Async Jobs page.
    } catch (err: any) {
      console.error("Failed to start OUI update job:", err);
      let displayMessage = "An unexpected error occurred while starting the OUI update job.";
      if (axios.isAxiosError(err)) {
        if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
            displayMessage = `Failed to start OUI update job: ${err.response.data.detail}`;
        } else if (err.message) {
            displayMessage = `Failed to start OUI update job: ${err.message}`;
        }
      } else if (err instanceof Error && err.message) {
        displayMessage = `Failed to start OUI update job: ${err.message}`;
      }
      setError(displayMessage);
    } finally {
      setUpdatingOui(false);
    }
  };

  /**
   * Saves the potentially modified OUI CSV URL to the backend.
   */
  const handleSaveSettings = async () => {
    if (!settings || editedCsvUrl === settings.csv_url || isSavingSettings) return;
    setError(null);
    setIsSavingSettings(true);
    try {
      const updatedSettings = await updateMacSettings(editedCsvUrl);
      setSettings(updatedSettings); // Update local settings state with response
      setSnackbarMessage('Settings saved successfully.');
      setSnackbarOpen(true);
    } catch (err: any) {
      console.error("Failed to save MAC settings:", err);
      let displayMessage = "An unexpected error occurred while saving settings.";
      if (axios.isAxiosError(err)) {
        if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
            displayMessage = `Failed to save settings: ${err.response.data.detail}`;
        } else if (err.message) {
            displayMessage = `Failed to save settings: ${err.message}`;
        }
      } else if (err instanceof Error && err.message) {
        displayMessage = `Failed to save settings: ${err.message}`;
      }
      setError(displayMessage);
      setSnackbarMessage(displayMessage); // Show error in snackbar as well
      setSnackbarOpen(true);
    } finally {
      setIsSavingSettings(false);
    }
  };

  /**
   * Deletes a MAC transformation rule.
   * @param ruleId - The temporary frontend ID of the rule to delete.
   */
  const handleDeleteRule = async (ruleId: number) => {
    if (!activeSession?.id || deletingRuleId !== null) return; // Check activeSession.id
    const currentSessionId = activeSession.id;
    setError(null);
    setDeletingRuleId(ruleId);

    // Filter out the rule to be deleted using its temporary frontend ID
    const remainingRules = rules.filter((rule) => rule.id !== ruleId);

    try {
      // Prepare rules for backend (without frontend-specific 'id' or 'selectionContext')
      const rulesToSaveBackend = remainingRules.map(({ original_mac, target_vendor, target_oui }) => ({ original_mac, target_vendor, target_oui }));
      await saveMacRules(currentSessionId, rulesToSaveBackend); // Use currentSessionId
      setRules(remainingRules); // Update frontend state with the filtered list
      setSnackbarMessage('Rule deleted successfully.');
      setSnackbarOpen(true);
    } catch (err: any) {
      console.error("Failed to delete MAC rule:", err);
      let displayMessage = "An unexpected error occurred while deleting the rule.";
      if (axios.isAxiosError(err)) {
        if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
            displayMessage = `Failed to delete rule: ${err.response.data.detail}`;
        } else if (err.message) {
            displayMessage = `Failed to delete rule: ${err.message}`;
        }
      } else if (err instanceof Error && err.message) {
        displayMessage = `Failed to delete rule: ${err.message}`;
      }
      setError(displayMessage);
      // Note: If save fails, frontend state (rules) is already updated. Consider reverting or re-fetching.
    } finally {
      setDeletingRuleId(null);
    }
  };

  /**
   * Triggers a backend process to export the current MAC transformation rules for the active session.
   * The backend handles the file download directly.
   */
  const handleExportRules = async () => {
    if (!activeSession?.id || exportingRules) return; // Check activeSession.id
    const currentSessionId = activeSession.id;
    setError(null);
    setExportingRules(true);
    try {
      await exportMacRules(currentSessionId); // Use currentSessionId
      // Backend handles the download, maybe show snackbar on success?
      setSnackbarMessage('Rules exported successfully.');
      setSnackbarOpen(true);
    } catch (err: any) {
      console.error("Failed to export MAC rules:", err);
      let displayMessage = "An unexpected error occurred while exporting rules.";
      if (axios.isAxiosError(err)) {
        if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
            displayMessage = `Failed to export rules: ${err.response.data.detail}`;
        } else if (err.message) {
            displayMessage = `Failed to export rules: ${err.message}`;
        }
      } else if (err instanceof Error && err.message) {
        displayMessage = `Failed to export rules: ${err.message}`;
      }
      setError(displayMessage);
    } finally {
      setExportingRules(false); // End loading
    }
  };

  /**
   * Handles the import of MAC transformation rules from a user-selected JSON file.
   * @param event - The file input change event.
   */
  const handleImportRules = async (event: React.ChangeEvent<HTMLInputElement>) => {
    if (!activeSession?.id || !event.target.files || event.target.files.length === 0 || importingRules) { // Check activeSession.id
      return;
    }
    const currentSessionId = activeSession.id;
    const file = event.target.files[0];
    setError(null);
    setImportingRules(true);
    try {
      await importMacRules(currentSessionId, file); // Use currentSessionId
      // Refresh rules list after import
      fetchRules(); // This will now fetch and map to DisplayMacRule with new IDs
      setSnackbarMessage('Rules imported successfully.');
      setSnackbarOpen(true);
    } catch (err: any) {
      console.error("Failed to import MAC rules:", err);
      let displayMessage = "An unexpected error occurred while importing rules.";
      if (axios.isAxiosError(err)) {
        if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
            displayMessage = `Failed to import rules: ${err.response.data.detail}`;
        } else if (err.message) {
            displayMessage = `Failed to import rules: ${err.message}`;
        }
      } else if (err instanceof Error && err.message) {
        displayMessage = `Failed to import rules: ${err.message}`;
      }
      setError(displayMessage);
    } finally {
      // Reset file input
      event.target.value = '';
      setImportingRules(false); // End loading
    }
  };

  // --- Handlers for "Create Rule from Selection" Dialog ---

  /**
   * Opens the dialog to create new MAC transformation rules based on the currently
   * selected IP-MAC pairs in the DataGrid.
   */
  const handleOpenRuleFromSelectionDialog = () => {
    if (selectedRows.length === 0) {
      setSnackbarMessage('No IP-MAC pairs selected.');
      setSnackbarOpen(true);
      return;
    }

    // `selectedRows` contains GridRowId[], which are `${ip_address}-${mac_address}`.
    // Filter `ipMacPairs` to get the full objects for the selected rows.
    const selectedIpMacObjects = ipMacPairs.filter(pair =>
      selectedRows.includes(`${pair.ip_address}-${pair.mac_address}`)
    );

    // Store only the original MAC addresses from the selection for display in the dialog.
    // `selectedSourceVendors` state is reused for this purpose.
    setSelectedSourceVendors(selectedIpMacObjects.map(pair => pair.mac_address));

    setRuleFromSelectionTargetVendor(''); // Reset target vendor input in the dialog
    setIsRuleFromSelectionDialogOpen(true); // Open the dialog
  };

  /**
   * Closes the "Create Rule from Selection" dialog and resets related temporary states.
   */
  const handleCloseRuleFromSelectionDialog = () => {
    setIsRuleFromSelectionDialogOpen(false);
    // Optionally reset other dialog-specific states if they shouldn't persist
    // setSelectedSourceVendors([]); // Cleared if dialog is re-opened with new selection
    // setRuleFromSelectionTargetVendor('');
  };

  /**
   * Handles the saving of new MAC transformation rules created from the dialog.
   * This involves fetching the OUI for the chosen target vendor and then
   * creating a new rule for each originally selected MAC address.
   */
  const handleSaveRuleFromSelection = async () => {
    // `selectedSourceVendors` state currently holds the list of original MAC addresses from the dialog.
    if (!activeSession?.id || selectedSourceVendors.length === 0 || !ruleFromSelectionTargetVendor || addingRule) { // Check activeSession.id
      return;
    }
    const currentSessionId = activeSession.id;

    setError(null);
    setAddingRule(true);

    try {
      // Step 1: Fetch the OUI for the selected target vendor.
      // This OUI will be used for all new rules created in this batch.
      // console.log(`Fetching OUI for target vendor: ${ruleFromSelectionTargetVendor}`);
      const ouiResponse = await getOuiForVendor(ruleFromSelectionTargetVendor);
      const targetOui = ouiResponse.oui; // The actual OUI string (e.g., "00:1A:2B")
      // console.log(`Fetched OUI: ${targetOui} for vendor ${ruleFromSelectionTargetVendor}`);

      if (!targetOui) {
        // If no OUI is found, inform the user. This might happen if the vendor is not in the OUI list.
        throw new Error(`Could not find an OUI for vendor "${ruleFromSelectionTargetVendor}". Please ensure the vendor exists in the OUI database or update the OUI list via settings.`);
      }

      // Step 2: Prepare the new rules.
      // Determine the starting ID for new rules to avoid conflicts with existing frontend IDs.
      const baseId = rules.length > 0 ? Math.max(...rules.map(r => r.id)) + 1 : 0;
      const newDisplayRules: DisplayMacRule[] = [];

      // Retrieve the full IpMacPair objects corresponding to the initial selection
      // (those whose MACs are in `selectedSourceVendors`).
      // `selectedRows` (GridRowId[]) still holds the original DataGrid selection identifiers.
      const originallySelectedIpMacObjects = ipMacPairs.filter(pair =>
        selectedRows.includes(`${pair.ip_address}-${pair.mac_address}`)
      );

      // Create a new DisplayMacRule for each originally selected MAC address.
      originallySelectedIpMacObjects.forEach((selectedPairContext, index) => {
        newDisplayRules.push({
          id: baseId + index, // Assign a new temporary frontend ID
          original_mac: selectedPairContext.mac_address, // The MAC to be transformed
          target_vendor: ruleFromSelectionTargetVendor, // The chosen target vendor
          target_oui: targetOui, // The fetched OUI for the target vendor
          selectionContext: [{ // Store context about how this rule was created
            ip: selectedPairContext.ip_address,
            mac: selectedPairContext.mac_address,
            original_vendor: selectedPairContext.vendor,
          }],
        });
      });

      // Step 3: Combine new rules with existing ones and save to backend.
      const updatedRulesList = [...rules, ...newDisplayRules];

      // Map to the backend format (MacRule: original_mac, target_vendor, target_oui)
      const rulesToSaveBackend = updatedRulesList.map(({ original_mac, target_vendor, target_oui }) => ({ original_mac, target_vendor, target_oui }));
      await saveMacRules(currentSessionId, rulesToSaveBackend); // Use currentSessionId

      // Step 4: Update frontend state and provide feedback.
      setRules(updatedRulesList);
      setSnackbarMessage(`${newDisplayRules.length} rule(s) added successfully for vendor ${ruleFromSelectionTargetVendor}.`);
      setSnackbarOpen(true);
      handleCloseRuleFromSelectionDialog(); // Close the dialog on success

    } catch (err: any) {
      console.error("Failed to save rules from selection:", err);
      let displayMessage = "An unexpected error occurred while saving rules from selection.";
      if (axios.isAxiosError(err)) {
        if (err.response && err.response.data && typeof err.response.data.detail === 'string') {
            displayMessage = `Failed to save rules from selection: ${err.response.data.detail}`;
        } else if (err.message) {
            displayMessage = `Failed to save rules from selection: ${err.message}`;
        }
      } else if (err instanceof Error && err.message) {
        // This will catch the custom error thrown if OUI is not found
        displayMessage = `Failed to save rules from selection: ${err.message}`;
      }
      setError(displayMessage);
      setSnackbarMessage(displayMessage); // Show detailed error in snackbar
      setSnackbarOpen(true);
    } finally {
      setAddingRule(false); // Reset loading state
    }
  };
  // --- End Dialog Handlers ---

  /**
   * Initiates the MAC address transformation job for the active session using the configured rules.
   * Uses the `useJobTracking` hook to manage the job lifecycle.
   */
  const handleApplyTransform = async () => {
    // Check for activeSession ID before starting
    if (!activeSession?.id || isMacJobProcessing || isLoadingMacJobDetails) {
       if (!activeSession?.id) {
         setError('Cannot start transformation: No active session selected.');
      }
      // Prevent starting if no session, or if a job is already processing/loading details.
      return;
    }
    const currentSessionId = activeSession.id;
    const currentPcapFilename = activeSession.actual_pcap_filename; // Get the filename

    // Filename IS needed for this API call (passed to /mac/apply)

    if (!currentPcapFilename) { // Add a check for the filename
      setError('Cannot start transformation: PCAP filename is missing for the active session.');
      setSnackbarMessage('Cannot start transformation: PCAP filename is missing for the active session.');
      setSnackbarOpen(true);
      return;
    }

    setError(null); // Clear general page error before starting a new job.

    // Define the API call that the hook will execute to start the job.
    const apiCallToStartMacJob = async () => {
      // We already checked activeSession ID and pcapFilename at the start of handleApplyTransform
      if (!currentSessionId || !currentPcapFilename) { // Check both here
        throw new Error("Session ID or PCAP filename became unavailable unexpectedly.");
      }
      // Pass sessionId and the pcap filename to the API call
      return startMacTransformationJob(currentSessionId, currentPcapFilename);
    };

    // The `startMacJob` function from the `useJobTracking` hook handles:
    // - Calling `apiCallToStartMacJob`.
    // - Storing the job ID in localStorage.
    // - Setting up SSE for real-time updates.
    // - Managing loading states (`isMacJobProcessing`, `isLoadingMacJobDetails`).
    // - Updating `macTransformJobStatus` and `macJobError`.
    // Snackbar messages for success/failure are handled by the hook's callbacks.
    startMacJob(apiCallToStartMacJob);
  };

  // Note: The useEffect for listening to EventSource for an active MAC transformation job
  // and managing `macTransformCompletionStatus` has been removed, as this functionality
  // is now encapsulated within the `useJobTracking` hook.
  // UI rendering for job status is now based on `macTransformJobStatus` and `macJobError` from the hook.

  // --- DataGrid Column Definitions ---
  const ipMacColumns: GridColDef[] = [
    { field: 'ip_address', headerName: 'IP Address', flex: 1 },
    { field: 'mac_address', headerName: 'MAC Address', flex: 1.5 },
    // Explicitly type params for valueGetter
    { field: 'vendor', headerName: 'Vendor', flex: 2 }, // Sin valueGetter
  ];

  const ruleColumns: GridColDef<DisplayMacRule>[] = [ // Specify the row type
    { field: 'original_mac', headerName: 'Original MAC', flex: 1.5 }, // Changed from source_vendor
    { field: 'target_vendor', headerName: 'Target Vendor', flex: 1 },
    {
      field: 'details', // New column for details
      headerName: 'Details',
      sortable: false,
      filterable: false,
      width: 80,
      align: 'center',
      headerAlign: 'center',
      renderCell: (params) => {
        const context = params.row.selectionContext;
        if (!context || context.length === 0) {
          return null; // No details to show if not created from selection or context is empty
        }
        // Create tooltip content
        const tooltipContent = (
          <Box sx={{ p: 1, maxWidth: 400 }}> {/* Add maxWidth */}
            <Typography variant="body2" gutterBottom>
              Created from selection ({context.length} pairs):
            </Typography>
            <List dense disablePadding sx={{ maxHeight: 150, overflow: 'auto' }}>
              {context.map((item, idx) => (
                <ListItem key={idx} disableGutters sx={{ pl: 1 }}>
                  <ListItemText
                    primary={`${item.ip} / ${item.mac}`}
                    secondary={`Vendor: ${item.original_vendor || 'N/A'}`}
                    primaryTypographyProps={{ variant: 'caption', style: { wordBreak: 'break-all' } }} // Allow breaking
                    secondaryTypographyProps={{ variant: 'caption' }}
                  />
                </ListItem>
              ))}
            </List>
            <Typography variant="caption" sx={{ display: 'block', mt: 1 }}>
              Target Vendor: {params.row.target_vendor}
            </Typography>
          </Box>
        );
        return (
          <Tooltip title={tooltipContent} arrow placement="right">
            <IconButton size="small">
              <InfoIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        );
      },
    },
    {
      field: 'actions',
      headerName: 'Actions',
      sortable: false,
      filterable: false,
      width: 80, // Adjusted width slightly
      align: 'center',
      headerAlign: 'center',
      renderCell: (params) => (
        <IconButton
          aria-label="delete"
          size="small"
          onClick={() => handleDeleteRule(params.row.id)} // Use the rule's ID
          disabled={deletingRuleId === params.row.id}
        >
          {deletingRuleId === params.row.id ? <CircularProgress size={20} color="inherit" /> : <DeleteIcon fontSize="small" />}
        </IconButton>
      ),
    },
  ];

  // Use the rules state directly as it now contains the ID
  const rulesWithIds = rules;

  const handleSnackbarClose = (_event?: React.SyntheticEvent | Event, reason?: string) => {
    if (reason === 'clickaway') {
      return;
    }
    setSnackbarOpen(false);
  };

  return (
    <Box sx={{ p: 2 }}>
      <Typography variant="h4" gutterBottom>
        MAC Transformations
      </Typography>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {/* Removed constraining Box */}
      <Grid container spacing={3}>
        {/* --- Settings Section --- */}
        {/* @ts-ignore */}
        <Grid item xs={12} sx={{ display: 'flex', justifyContent: 'center' }}> {/* Changed Grid to Grid item */}
          <Paper sx={{ p: 2, width: '100%', maxWidth: '800px' }}>
            <Typography variant="h6" gutterBottom>Settings</Typography>
            {loadingSettings ? <CircularProgress size={20} /> : (
              settings ? (
                <Box>
                  {/* URL Editing */}
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <TextField
                      label="OUI CSV URL"
                      variant="outlined"
                      size="small"
                      fullWidth
                      value={editedCsvUrl}
                      onChange={(e) => setEditedCsvUrl(e.target.value)}
                      disabled={isSavingSettings} // Disable while saving
                    />
                    <Tooltip title="Save URL">
                      {/* Span needed for tooltip on disabled button */}
                      <span>
                        <IconButton
                          color="primary"
                          onClick={handleSaveSettings}
                          disabled={editedCsvUrl === settings.csv_url || isSavingSettings}
                          size="small"
                        >
                          {isSavingSettings ? <CircularProgress size={24} color="inherit" /> : <SaveIcon />}
                        </IconButton>
                      </span>
                    </Tooltip>
                  </Box>

                  {/* Last Updated and Update Button */}
                  <Typography variant="body2" sx={{ mb: 1 }}>
                    Last Updated: {settings.last_updated ? new Date(settings.last_updated).toLocaleString() : 'Never'}
                  </Typography>
                  <Button
                    variant="outlined"
                    size="small"
                    startIcon={updatingOui ? <CircularProgress size={20} color="inherit" /> : <SyncIcon />}
                    onClick={handleUpdateOui}
                    sx={{ mt: 1 }}
                    disabled={updatingOui} // Disable button while updating
                  >
                    {updatingOui ? 'Updating...' : 'Update OUI CSV'}
                  </Button>
                </Box>
              ) : <Typography variant="body2">Could not load settings.</Typography>
            )}
          </Paper>
        </Grid>

        {/* --- Unified Actions, Detected, and Rules Section --- */}
        {/* @ts-ignore */}
        <Grid item xs={12} sx={{ display: 'flex', justifyContent: 'center' }}>
          <Paper sx={{ p: 2, width: '100%', maxWidth: '800px', display: 'flex', flexDirection: 'column' }}>
            {/* Actions Section Content */}
            <Box component="section" sx={{ mb: 2 }}>
              <Typography variant="h6" gutterBottom>Actions</Typography>
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                <Button
                  variant="contained"
                  color="primary"
                  startIcon={isMacJobProcessing ? <CircularProgress size={20} color="inherit" /> : <PlayArrowIcon />}
                  onClick={handleApplyTransform}
                  disabled={!activeSession?.id || rules.length === 0 || isMacJobProcessing || isLoadingMacJobDetails} // Use activeSession.id
                >
                  {isMacJobProcessing || isLoadingMacJobDetails ? 'Processing...' : 'Apply Transformation'}
                </Button>
                <Button
                  variant="outlined"
                  startIcon={exportingRules ? <CircularProgress size={20} /> : <FileDownloadIcon />}
                  onClick={handleExportRules}
                  disabled={!activeSession?.id || rules.length === 0 || exportingRules} // Use activeSession.id
                >
                  {exportingRules ? 'Exporting...' : 'Export Rules'}
                </Button>
                <Button
                  variant="outlined"
                  component="label" // Makes the button act like a label for the hidden input
                  startIcon={importingRules ? <CircularProgress size={20} /> : <FileUploadIcon />}
                  disabled={!activeSession?.id || importingRules} // Use activeSession.id
                >
                  {importingRules ? 'Importing...' : 'Import Rules'}
                  <input
                    type="file"
                    hidden
                    accept=".json"
                    onChange={handleImportRules}
                  />
                </Button>
              </Box>
              {/* Display MAC Transformation Job Status/Error from Hook */}
              {macJobError && (
                <Alert severity="error" sx={{ mt: 2 }}>
                  {macJobError}
                </Alert>
              )}
              {macTransformJobStatus && !macJobError && (
                <Alert 
                  severity={
                    macTransformJobStatus.status === 'completed' ? 'success' :
                    macTransformJobStatus.status === 'failed' || macTransformJobStatus.status === 'cancelled' ? 'error' :
                    'info'
                  } 
                  sx={{ mt: 2 }}
                >
                  MAC Transformation Job (ID: {macTransformJobStatus.id}): {macTransformJobStatus.status}
                  {macTransformJobStatus.status === 'running' && ` (${macTransformJobStatus.progress}%)`}
                  {macTransformJobStatus.status === 'failed' && `: ${macTransformJobStatus.error_message || 'Unknown error'}`}
                  {macTransformJobStatus.status === 'completed' && (
                    <>
                      {' '}
                      <Link to="/upload" style={{ color: 'inherit', textDecoration: 'underline' }}>
                        View on Upload Page
                      </Link>
                    </>
                  )}
                  {(macTransformJobStatus.status === 'running' || macTransformJobStatus.status === 'pending' || isLoadingMacJobDetails) && <CircularProgress size={16} sx={{ ml: 1 }} />}
                </Alert>
              )}
            </Box>

            <Divider sx={{ my: 1 }} />

            {/* Detected IP-MAC Pairs Section Content */}
            <Box component="section" sx={{ display: 'flex', flexDirection: 'column', mb: 2 }}>
              <Typography variant="h6" gutterBottom>Detected IP-MAC Pairs</Typography>
              <Box sx={{ mb: 1 }}>
                <Button
                  variant="outlined"
                  size="small"
                  startIcon={<AddIcon />}
                  onClick={handleOpenRuleFromSelectionDialog}
                  disabled={selectedRows.length === 0} // Check Array length
                >
                  Create Rule from Selection
                </Button>
              </Box>
              {loadingPairs ? <CircularProgress sx={{ alignSelf: 'center', mt: 4 }} /> : (
                <Box sx={{ flexGrow: 1, width: '100%', overflow: 'auto', height: 400 }}> {/* Adjusted height */}
                  <DataGrid
                    rows={ipMacPairs} // Use original data
                    columns={ipMacColumns}
                    getRowId={(row) => `${row.ip_address}-${row.mac_address}`} // Use IP-MAC combination as stable ID
                    pagination
                    paginationMode="client"
                    pageSizeOptions={[5, 10, 25]}
                    paginationModel={ipMacPaginationModel}
                    onPaginationModelChange={setIpMacPaginationModel}
                    checkboxSelection
                    onRowSelectionModelChange={(model: GridRowSelectionModel) => {
                      const newSelectionArray = (Array.isArray(model) ? model : (model ? [model] : [])) as GridRowId[];
                      setSelectedRows(newSelectionArray);
                    }}
                    rowSelectionModel={selectedRows}
                    density="compact"
                  />
                </Box>
              )}
            </Box>

            <Divider sx={{ my: 1 }} />

            {/* Transformation Rules Section Content */}
            <Box component="section">
            <Typography variant="h6" gutterBottom>Transformation Rules</Typography>
            {/* Manual rule addition removed as per user feedback */}
              <Box sx={{ height: 300, width: '100%' }}>
                {loadingRules ? <CircularProgress /> : (
                  <DataGrid
                    rows={rulesWithIds} // Use the state directly
                    columns={ruleColumns}
                    pagination
                    paginationMode="client"
                    pageSizeOptions={[5, 10]}
                    paginationModel={rulesPaginationModel}
                    onPaginationModelChange={setRulesPaginationModel}
                    density="compact"
                  />
                )}
              </Box>
            </Box>
          </Paper>
        </Grid>
      </Grid> {/* Closing Grid container */}

      {/* Snackbar for feedback */}
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={6000} // Hide after 6 seconds
        onClose={handleSnackbarClose}
        message={snackbarMessage}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }} // Position bottom-right
      />

      {/* --- Create Rule from Selection Dialog --- */}
      <Dialog open={isRuleFromSelectionDialogOpen} onClose={handleCloseRuleFromSelectionDialog} maxWidth="sm" fullWidth>
        <DialogTitle>Create Rule from Selection</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ mb: 2 }}>
            Create transformation rules for the selected MAC addresses:
          </DialogContentText>
          <Paper variant="outlined" sx={{ maxHeight: 150, overflow: 'auto', mb: 2 }}>
            <List dense>
              {/* selectedSourceVendors now holds the list of MAC addresses */}
              {selectedSourceVendors.map((mac, index) => (
                <ListItem key={index}>
                  <ListItemText primary={mac} />
                </ListItem>
              ))}
              {selectedSourceVendors.length === 0 && (
                 <ListItem>
                   <ListItemText primary="No MAC addresses selected." sx={{ fontStyle: 'italic' }} />
                 </ListItem>
              )}
            </List>
          </Paper>
          {/* Replace TextField with Select */}
          <FormControl fullWidth margin="dense" size="small" disabled={addingRule || loadingVendors}>
            <InputLabel id="target-vendor-select-label">Target Vendor</InputLabel>
            <Select
              labelId="target-vendor-select-label"
              id="target-vendor-select"
              value={ruleFromSelectionTargetVendor}
              label="Target Vendor"
              onChange={(e) => setRuleFromSelectionTargetVendor(e.target.value as string)}
              MenuProps={{
                PaperProps: {
                  style: {
                    maxHeight: 200, // Limit dropdown height
                  },
                },
              }}
            >
              {loadingVendors && <MenuItem disabled><em>Loading vendors...</em></MenuItem>}
              {!loadingVendors && allMacVendors.length === 0 && <MenuItem disabled><em>No vendors available</em></MenuItem>}
              {allMacVendors.map((vendor) => (
                <MenuItem key={vendor} value={vendor}>
                  {vendor}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseRuleFromSelectionDialog} disabled={addingRule}>Cancel</Button>
          <Button
            onClick={handleSaveRuleFromSelection}
            disabled={selectedSourceVendors.length === 0 || !ruleFromSelectionTargetVendor || addingRule}
            variant="contained" // Make save button contained
          >
            {addingRule ? <CircularProgress size={24} color="inherit" /> : 'Save Rules'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default MacPage;
