// File: src/App.tsx
// Added Route for DicomPage

import React from 'react';
import { Routes, Route } from 'react-router-dom';

// --- MUI Imports ---
import { Box, Toolbar, AppBar, Typography, CssBaseline } from '@mui/material'; // Removed IconButton as it wasn't used here

// --- Your Page/Component Imports ---
import Sidebar from './components/Sidebar'; // Assuming path is correct
import UploadPage from './pages/UploadPage'; // Assuming path is correct
import SubnetsPage from './pages/SubnetsPage'; // Assuming path is correct
import DicomPage from './pages/DicomPage';
import AsyncPage from './pages/AsyncPage'; // Import the new AsyncPage

// --- Constants ---
// Define sidebar width if you use it for AppBar positioning or main content margin
const drawerWidth = 240; // Adjust if your sidebar width is different

// --- App Component ---
const App: React.FC = () => {
  // Define the primary color for the AppBar
  const NOZOMI_BLUE = '#005d80'; // Example color, adjust as needed

  return (
    <Box sx={{ display: 'flex' }}> {/* Main container using Flexbox */}
      {/* CssBaseline helps normalize styles across browsers */}
      <CssBaseline />

      {/* --- AppBar (Top Navigation Bar) --- */}
      <AppBar
        position="fixed" // Keep AppBar fixed at the top
        sx={{
          // Ensure AppBar is drawn above the Sidebar (if using z-index)
          zIndex: (theme) => theme.zIndex.drawer + 1,
          backgroundColor: NOZOMI_BLUE, // Apply background color
        }}
      >
        <Toolbar>
          {/* Logo */}
          <img
            src="./img/logo-small.png" // Path relative to the 'public' folder
            alt="Logo"
            style={{ height: '40px', marginRight: '30px' }} // Adjust styling
          />
          {/* Application Title */}
          <Typography variant="h6" noWrap component="div" sx={{ color: 'white' }}>
            Trace Editor
          </Typography>
          {/* Spacer to push subsequent items to the right */}
          <Box sx={{ flexGrow: 1 }} />
          {/* Powered By Text */}
          <Typography variant="body2" noWrap component="div" sx={{ color: 'white' }}>
             Powered by Adriel Regueira
          </Typography>
        </Toolbar>
      </AppBar>

      {/* --- Sidebar --- */}
      {/* Render the Sidebar component */}
      <Sidebar />

      {/* --- Main Content Area --- */}
      <Box
        component="main" // Semantic main content tag
        sx={{
          flexGrow: 1, // Allow this Box to grow and fill available space
          p: 3, // Apply padding around the content (theme spacing unit * 3)
          // Add top margin equal to the AppBar's height to prevent content from hiding underneath
          mt: '64px', // Default MUI AppBar height. Use Toolbar component below for automatic height matching instead if preferred.
          // If using a permanent drawer that doesn't overlay content, adjust margin/width:
          // width: `calc(100% - ${drawerWidth}px)`,
          // ml: `${drawerWidth}px`,
        }}
      >
         {/* Optional: Instead of mt: '64px', you can place an empty Toolbar here
             which acts as a spacer matching the AppBar height automatically.
             Choose one method or the other. */}
         {/* <Toolbar /> */}

        {/* --- Routing Definitions --- */}
        <Routes>
          {/* Route for the homepage, rendering UploadPage */}
          <Route path="/" element={<UploadPage />} />
          {/* Route for the subnets analysis page */}
          <Route path="/subnets" element={<SubnetsPage />} />
          <Route path="/dicom" element={<DicomPage />} />
          {/* Add route for the new Async Jobs page */}
          <Route path="/async" element={<AsyncPage />} />
          {/* Add other routes here if needed */}
          {/* Example for a 404 page (optional) */}
          {/* <Route path="*" element={<NotFoundPage />} /> */}
        </Routes>
      </Box>
    </Box>
  );
};

export default App;
