// File: src/App.tsx
// Added Route for DicomPage
// Session list state and fetching logic moved to SessionContext.

import React from 'react'; // Removed useState, useEffect, useCallback
import { Routes, Route } from 'react-router-dom';
// import axios from 'axios'; // No longer needed here

// --- MUI Imports ---
import { Box, Toolbar, AppBar, Typography, CssBaseline } from '@mui/material'; // Removed Alert

// --- Your Page/Component Imports ---
// --- Your Page/Component Imports ---
import Sidebar from './components/Sidebar';
import UploadPage from './pages/UploadPage';
import SubnetsPage from './pages/SubnetsPage';
import DicomPage from './pages/DicomPage';
import AsyncPage from './pages/AsyncPage';
import DicomAnonymizationV2Page from './pages/DicomAnonymizationV2Page'; // Import the new page
import MacPage from './pages/MacPage'; // Import the new MAC page
import SettingsPage from './pages/SettingsPage'; // Import the new Settings page

// --- API Imports ---
// import { listSessions, PcapSession } from './services/api'; // No longer needed here

// --- Constants ---
const NOZOMI_BLUE = '#005d80';

// --- App Component ---
const App: React.FC = () => {
  // Session list state (traces, listLoading, listError) and fetchTraces logic
  // have been moved to SessionContext.

  return (
    <Box sx={{ display: 'flex' }}>
      <CssBaseline />

      {/* --- AppBar --- */}
      <AppBar
        position="fixed"
        sx={{
          zIndex: (theme) => theme.zIndex.drawer + 1,
          backgroundColor: NOZOMI_BLUE,
        }}
      >
        <Toolbar>
          <img src="./img/logo-small.png" alt="Logo" style={{ height: '40px', marginRight: '30px' }} />
          <Typography variant="h6" noWrap component="div" sx={{ color: 'white' }}>
            Trace Editor
          </Typography>
          <Box sx={{ flexGrow: 1 }} />
          <Typography variant="body2" noWrap component="div" sx={{ color: 'white' }}>
             Powered by Adriel Regueira
          </Typography>
        </Toolbar>
      </AppBar>

      {/* --- Sidebar --- */}
      <Sidebar />

      {/* --- Main Content Area --- */}
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          p: 3,
          mt: '64px', // Adjust if AppBar height changes
        }}
      >
        {/* Global listError Alert removed, will be handled by components consuming SessionContext */}

        {/* --- Routing Definitions --- */}
        <Routes>
          {/* UploadPage will now get its data from SessionContext */}
          <Route
            path="/"
            element={
              <UploadPage />
            }
          />
          {/* SubnetsPage might need the list too, or just the selected session ID from context */}
          <Route path="/subnets" element={<SubnetsPage />} />
          {/* DicomPage might need the list too, or just the selected session ID from context */}
          <Route path="/dicom" element={<DicomPage />} />
          {/* AsyncPage will now get its data from SessionContext if needed, or use addSession from context */}
          <Route
            path="/async"
            element={<AsyncPage />}
          />
          {/* Route for DICOM Anonymization V2 */}
          <Route path="/dicom-anonymization-v2" element={<DicomAnonymizationV2Page />} />
          {/* Route for MAC Vendor Modification */}
          <Route path="/mac" element={<MacPage />} />
          {/* Route for Settings Page */}
          <Route path="/settings" element={<SettingsPage />} />
          {/* Add other routes here */}
        </Routes>
      </Box>
    </Box>
  );
};

export default App;
