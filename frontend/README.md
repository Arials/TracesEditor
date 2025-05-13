# TracesEditor Frontend

This directory contains the frontend application for the PCAP Trace Editor & Anonymizer (TracesEditor) project. It is a single-page application built with React, Vite, TypeScript, and Material UI.

## Overview

The frontend provides a user interface for:
*   Uploading and managing PCAP trace files.
*   Viewing details of uploaded traces.
*   Defining and managing MAC address transformation rules.
*   Initiating and monitoring asynchronous anonymization jobs.
*   Downloading processed (anonymized) trace files.

## Key Technologies

*   **React 19+:** For building the user interface.
*   **Vite:** As the build tool and development server.
*   **TypeScript:** For static typing.
*   **Material UI (MUI) & MUI X DataGrid:** For UI components and styling.
*   **Axios:** For making HTTP requests to the backend API.
*   **React Router DOM:** For client-side routing.
*   **ESLint:** For code linting.

## Prerequisites

*   **Node.js and npm:** Ensure you have Node.js (which includes npm) installed. For macOS users, refer to the "Prerequisites" section in the main project `README.md` at the root of this repository for instructions on installing Node.js and npm using Homebrew. For other operating systems, please follow the official Node.js installation guides.

## Setup and Running

1.  **Navigate to the frontend directory:**
    From the project's root directory:
    ```bash
    cd frontend
    ```

2.  **Install dependencies:**
    ```bash
    npm install
    ```
    (If you prefer Yarn and have it installed, you can use `yarn install`.)

3.  **Run the development server:**
    ```bash
    npm run dev
    ```
    This will typically start the frontend application on `http://localhost:5173`. The actual port might vary if 5173 is in use; check your terminal output.

4.  **Ensure the backend server is also running.** The frontend application communicates with the backend API (usually running on `http://localhost:8000`).

## Building for Production

To create a production build of the frontend:
```bash
npm run build
```
The production-ready static assets will be placed in the `dist` directory.

## Project Structure (Simplified)

```
frontend/
├── public/             # Static assets
├── src/
│   ├── assets/         # Images, svgs, etc.
│   ├── components/     # Reusable UI components (e.g., Sidebar)
│   ├── context/        # React Context providers (e.g., SessionContext)
│   ├── hooks/          # Custom React hooks (e.g., useJobTracking)
│   ├── pages/          # Page components (e.g., UploadPage, MacPage)
│   ├── services/       # API service definitions (e.g., api.ts)
│   ├── App.tsx         # Main application component, router setup
│   ├── main.tsx        # Entry point of the application
│   └── index.css       # Global styles
├── eslint.config.js    # ESLint configuration
├── index.html          # Main HTML page
├── package.json        # Project dependencies and scripts
├── tsconfig.json       # TypeScript configuration for the app
├── tsconfig.node.json  # TypeScript configuration for Vite/ESLint config files
└── vite.config.ts      # Vite configuration
