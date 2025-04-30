import React from 'react';
import { Routes, Route } from 'react-router-dom';
import { Box, Toolbar } from '@mui/material';

import Sidebar from './components/Sidebar';
import UploadPage from './pages/UploadPage';
import SubnetsPage from './pages/SubnetsPage';

const drawerWidth = 240;

const App: React.FC = () => {
  return (
    <Box sx={{ display: 'flex' }}>
      {/* Sidebar fijo */}
      <Sidebar />

      {/* Reserva el espacio del drawer para que no tape el contenido */}
      <Box sx={{ width: drawerWidth }} />

      {/* Contenido principal, ya alineado a la derecha */}
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          p: 3,
          width: `calc(100% - ${drawerWidth}px)`,
        }}
      >
        {/* Si añades un AppBar, esto empuja el contenido hacia abajo */}
        <Toolbar />

        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/subnets" element={<SubnetsPage />} />
        </Routes>
      </Box>
    </Box>
  );
};

export default App;