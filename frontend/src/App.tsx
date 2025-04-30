import React from 'react';
import { Routes, Route } from 'react-router-dom';
// --- MUI Imports ---
import { Box, Toolbar, AppBar, Typography, CssBaseline, IconButton } from '@mui/material'; // Added AppBar, Typography, CssBaseline, IconButton
// --- Your Page/Component Imports ---
import Sidebar from './components/Sidebar.tsx'; // Assuming you have Sidebar
import UploadPage from './pages/UploadPage.tsx';
import SubnetsPage from './pages/SubnetsPage.tsx';


// --- Constants ---
// Define sidebar width if you use it for AppBar positioning
const drawerWidth = 240; // Adjust if your sidebar width is different

// --- App Component ---
const App: React.FC = () => {
  // Replace with the actual Hex color code from the screenshot if known
  const NOZOMI_BLUE = '#005d80 '; // Example dark blue - REPLACE THIS

  return (
    <Box sx={{ display: 'flex' }}>
      {/* CssBaseline helps normalize styles */}
      <CssBaseline />

      {/* --- AppBar (Top Navigation Bar) --- */}
      <AppBar
        position="fixed" // Keeps the AppBar fixed at the top
        sx={{
          // Ensure AppBar is above the sidebar if sidebar is also fixed/absolute
          zIndex: (theme) => theme.zIndex.drawer + 1,
          // Apply the desired background color
          backgroundColor: NOZOMI_BLUE, // Use the defined color
        }}
      >
        <Toolbar>
          {/* Logo Placeholder */}
          {/* Place your logo (e.g., nozomi-logo.svg) in the /public folder */}
          <img
            src="./img/logo-small.png" // Path relative to the public folder
            alt="Logo"
            style={{ height: '40px', marginRight: '30px' }} // Adjust height and margin
          />

          {/* Application Title */}
          <Typography variant="h6" noWrap component="div" sx={{ color: 'white' }}>
            Trace Editor {/* Or your preferred application name */}
          </Typography>

          {/* Spacer to push items to the right */}
          <Box sx={{ flexGrow: 1 }} />

          {/* Powered By Text */}
          <Typography variant="body2" noWrap component="div" sx={{ color: 'white' }}>
            Powered by Adriel Regueira
          </Typography>

        </Toolbar>
      </AppBar>

      {/* --- Sidebar (Assuming it's permanent/fixed) --- */}
      {/* Your existing Sidebar component */}
      {/* If your sidebar is under the AppBar, it doesn't need changes here */}
      {/* If it's fixed to the left, the main content needs left margin */}
      <Sidebar /> {/* You might need to adjust Sidebar styling based on AppBar */}

      {/* --- Main Content Area --- */}
      <Box
        component="main"
        sx={{
          flexGrow: 1, // Takes remaining space
          p: 3, // Padding
          // Ensure content starts below the fixed AppBar
          // The empty Toolbar creates space exactly the height of the AppBar
          mt: '64px', // Default AppBar height (adjust if needed, or use Toolbar)
          // If using a fixed sidebar like in App.tsx V1:
          // width: `calc(100% - ${drawerWidth}px)`, // Adjust width if sidebar is permanent
          // ml: `${drawerWidth}px`, // Add left margin if sidebar is permanent
        }}
      >
         {/* Removed the extra <Toolbar /> spacer here as mt: '64px' handles it */}
         {/* Alternatively, keep <Toolbar /> and remove mt: '64px' */}

        {/* --- Routing --- */}
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/subnets" element={<SubnetsPage />} />
          {/* Add other routes as needed */}
        </Routes>
      </Box>
    </Box>
  );
};

export default App;