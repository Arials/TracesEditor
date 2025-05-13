# PCAP Trace Editor & Anonymizer (TracesEditor)

This web application allows users to upload PCAP network trace files, manage them, define IP and MAC address anonymization rules based on CIDR notation, apply these rules asynchronously, and download the resulting anonymized PCAP file.

## Overview

The project provides a user-friendly interface to handle potentially sensitive network capture data by enabling selective anonymization based on configurable rules. This is useful for sharing network traces for analysis without exposing private IP addresses or specific device MAC addresses.

The application uses a React frontend (built with Vite and TypeScript, styled with Material UI) and a Python backend (using the FastAPI framework with SQLModel for database interaction and Scapy for packet manipulation).

## Features

* **Trace Upload:** Upload PCAP or PCAPng files.
* **Trace Management:**
    * Assign a custom name and description to each uploaded trace.
    * List all uploaded traces in a table.
    * Edit the name and description of existing traces.
    * Delete traces and their associated files.
    * Prevents uploading traces with duplicate names.
* **Subnet Detection:** Automatically identifies /24 subnets present in the uploaded trace. (TODO: Needs DB integration)
* **Anonymization Rules:** Define rules to map source CIDR blocks to target CIDR blocks.
* **Rule Persistence:** Saves defined rules associated with each trace session (currently file-based, TODO: migrate to DB).
* **Asynchronous Anonymization:** Anonymization runs as a background task.
* **Real-time Progress:** Uses Server-Sent Events (SSE) to provide real-time status updates ('pending', 'running', 'completed', 'failed') and progress percentage for the anonymization job.
* **Download Result:** Download the anonymized PCAP file once processing is complete.
* **Database Storage:** Uses SQLite via SQLModel to store metadata about uploaded traces (ID, name, description, paths, timestamps).

## Tech Stack

* **Backend:**
    * Python 3.12+
    * FastAPI
    * Uvicorn (ASGI Server)
    * SQLModel (ORM based on Pydantic & SQLAlchemy)
    * SQLite (Database)
    * Scapy (Packet Manipulation)
* **Frontend:**
    * React 19+ (with Vite)
    * TypeScript
    * Material UI (MUI) & MUI X DataGrid
    * Axios (HTTP Client)
    * React Router DOM
* **Development:**
    * Git / GitHub
    * Virtual Environments (`venv`)
    * Node.js / npm (or yarn)

## Setup and Installation

### 0. Prerequisites (macOS using Homebrew)

These steps are for macOS users to install the necessary tools using [Homebrew](https://brew.sh/). If you are on a different OS, please refer to the official installation guides for Node.js, npm, and Python.

*   **Install Homebrew (if you don't have it):**
    Open your terminal and paste the command from the [Homebrew website](https://brew.sh/). It usually looks like this:
    ```bash
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    ```
    Follow the on-screen instructions.

*   **Install Node.js and npm:**
    Node.js comes with npm (Node Package Manager).
    ```bash
    brew install node
    ```
    Verify the installation:
    ```bash
    node -v
    npm -v
    ```

*   **Install Python 3:**
    macOS comes with a system Python, but it's recommended to install and use a Homebrew-managed version.
    ```bash
    brew install python
    ```
    This will typically install the latest Python 3. Verify the installation (it might be available as `python3`):
    ```bash
    python3 --version
    ```

### 1. Clone the repository:
    ```bash
    git clone [https://github.com/Arials/TracesEditor.git](https://github.com/Arials/TracesEditor.git)
    cd TracesEditor
    ```

### 2. Backend Setup:
    * Navigate to the backend directory: `cd backend`
    * Create and activate a Python virtual environment (using the Homebrew-installed Python 3):
        ```bash
        python3 -m venv venv
        source venv/bin/activate  # On Windows use `venv\Scripts\activate`
        ```
    * Install dependencies:
        ```bash
        pip3 install -r requirements.txt # Use pip3 if python3 was used for venv
        ```
    * Run the backend server:
        ```bash
        uvicorn main:app --reload --host 0.0.0.0 --port 8000
        ```
        *(The database `pcap_anonymizer.db` and necessary tables will be created automatically on first run in the `backend` directory).*

### 3. Frontend Setup:
    * Open a *new* terminal window/tab.
    * Navigate to the frontend directory:
        ```bash
        # From the project root directory:
        cd frontend 
        # (Assuming you are in the project root after cloning)
        ```
    * Install dependencies (using the Homebrew-installed npm):
        ```bash
        npm install
        # or: yarn install 
        # (if you prefer yarn and have it installed: brew install yarn)
        ```
    * Run the frontend development server:
        ```bash
        npm run dev
        # or: yarn dev
        ```

## Usage

1.  Ensure both the backend and frontend servers are running.
2.  Open your web browser and navigate to the frontend URL (usually `http://localhost:5173`).
3.  Use the "Upload New PCAP Trace" section to:
    * Provide a unique "Trace Name".
    * Optionally add a "Description".
    * Select a `.pcap` or `.pcapng` file.
    * Click "Upload Trace".
4.  The "Saved Traces" table below will list your uploaded traces.
5.  Click the "Analyze" icon (play button) on a trace row to load its data for analysis (this will navigate you to the `/subnets` page, which currently might still need DB integration).
6.  Click the "Edit" icon (pencil) to modify the name and description of a trace.
7.  Click the "Delete" icon (trash can) to permanently remove a trace and its files.
8.  On the `/subnets` page (once functional):
    * View detected subnets.
    * Define CIDR transformation rules.
    * Click "Apply changes" (or similar button) to start the anonymization job.
    * Monitor the job progress via the status messages/progress bar updated by SSE.
    * Once complete, use the "Download" button or link to get the anonymized PCAP.

## TODO / Future Work

* **Complete DB Integration:** Refactor remaining backend endpoints (`/subnets`, `/rules`, `/preview`, `/download`) and the `run_apply` background task to fetch paths and rules from the SQLite database instead of relying on file-based lookups or assuming paths.
* **Store Rules in DB:** Consider storing the transformation rules directly in the database (perhaps as JSON in the `PcapSession` table or in a separate `Rules` table) instead of separate `.json` files.
* **Job Status Persistence:** Store background job status in the database so it survives backend restarts.
* **Enhanced Error Handling:** Provide more specific and user-friendly error messages on both frontend and backend.
* **Input Validation:** Add stricter validation for CIDR rule formats on the backend.
* **UI Refinements:** Improve layout, add pagination/sorting/filtering to the traces table if needed.
* **Scalability:** Investigate stream-based PCAP processing for very large files.
* **Configuration:** Move hardcoded values like `SESSION_DIR` and CORS origins to environment variables or a config file.

## License
