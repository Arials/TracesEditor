import React from 'react';
// Import necessary MUI components
import {
  Drawer,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon, // Added for icons
  ListItemText,
  Toolbar
} from '@mui/material';
// Import routing components
import { Link, useLocation } from 'react-router-dom';
// Import Icons
import UploadFileIcon from '@mui/icons-material/UploadFile';
import HubIcon from '@mui/icons-material/Hub';
import DescriptionIcon from '@mui/icons-material/Description';
import ListAltIcon from '@mui/icons-material/ListAlt'; // Icon for Async Jobs
import EnhancedEncryptionIcon from '@mui/icons-material/EnhancedEncryption'; // Icon for DICOM V2
import SettingsEthernetIcon from '@mui/icons-material/SettingsEthernet'; // Icon for MAC Vendor
import SettingsIcon from '@mui/icons-material/Settings'; // Icon for Settings

// Define the width of the sidebar
const drawerWidth = 240;

const Sidebar: React.FC = () => {
  // Hook to get the current URL location object
  const location = useLocation();

  // Define the menu items in an array for easier management and rendering
  const menuItems = [
    {
      text: 'Traces', // Text displayed for the item
      path: '/',      // Route it links to
      icon: <UploadFileIcon /> // Icon component
    },
    {
      text: 'Subnet Transformations',
      path: '/subnets',
      icon: <HubIcon />
    },
    {
      text: 'MAC Transformations',
      path: '/mac',
      icon: <SettingsEthernetIcon />
    },
    // {
    //   text: 'DICOM Metadata',
    //   path: '/dicom',
    //   icon: <DescriptionIcon />
    // },
    // {
    //   text: 'DICOM Anonymization V2',
    //   path: '/dicom-anonymization-v2',
    //   icon: <EnhancedEncryptionIcon />
    // },
    {
      text: 'Async Jobs', // Moved to the bottom
      path: '/async',
      icon: <ListAltIcon />
    },
    {
      text: 'Settings',
      path: '/settings',
      icon: <SettingsIcon />
    },
  ];

  return (
    <Drawer
      variant="permanent" // Sidebar is always visible and part of the layout
      anchor="left"       // Positioned on the left side
      sx={{
        width: drawerWidth, // Set the width
        flexShrink: 0,      // Prevent the drawer from shrinking when space is limited
        '& .MuiDrawer-paper': { // Apply styles to the Paper component inside the Drawer
          width: drawerWidth,      // Ensure paper container has the same width
          boxSizing: 'border-box', // Include padding and border in the element's total width/height
        },
      }}
    >
      {/* An empty Toolbar adds space at the top, aligning content below the main AppBar */}
      <Toolbar />
      <List>
        {/* Map over the menuItems array to render each navigation link */}
        {menuItems.map((item) => (
          // Use item text as key (assuming texts are unique)
          <ListItem key={item.text} disablePadding>
            <ListItemButton
              component={Link} // Use React Router's Link component for SPA navigation
              to={item.path}   // Set the destination path for the link
              selected={location.pathname === item.path} // Highlight the item if its path matches the current URL path
            >
              <ListItemIcon> {/* Container for the icon */}
                {item.icon}
              </ListItemIcon>
              <ListItemText primary={item.text} /> {/* The text label for the menu item */}
            </ListItemButton>
          </ListItem>
        ))}
      </List>
    </Drawer>
  );
};

export default Sidebar;
