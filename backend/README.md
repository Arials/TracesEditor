# TracesEditor Backend

This directory contains the backend application for the PCAP Trace Editor & Anonymizer (TracesEditor) project. It is a Python-based API built with FastAPI, serving data and processing logic for the frontend.

## Overview

The backend is responsible for:
*   Handling PCAP file uploads and storage.
*   Managing metadata for traces (sessions) in an SQLite database.
*   Extracting information from PCAP files (e.g., IP-MAC pairs, subnets - though subnet detection might still be WIP for DB integration).
*   Storing and retrieving anonymization rules (both for IP/subnet and MAC transformations).
*   Performing asynchronous anonymization/transformation of PCAP files using Scapy.
*   Providing real-time job status updates via Server-Sent Events (SSE).
*   Serving processed (anonymized) files for download.

## Key Technologies

*   **Python 3.12+:** The primary programming language.
*   **FastAPI:** A modern, fast (high-performance) web framework for building APIs.
*   **Uvicorn:** An ASGI server to run the FastAPI application.
*   **SQLModel:** For database interaction, acting as an ORM (based on Pydantic and SQLAlchemy).
*   **SQLite:** The database used for storing trace metadata and job information.
*   **Scapy:** A powerful Python library for packet manipulation, used for reading, modifying, and writing PCAP files.
*   **Pydantic:** Used extensively by FastAPI and SQLModel for data validation and settings management.

## Prerequisites

*   **Python 3:** Ensure you have Python 3 (preferably 3.12 or newer) and `pip` installed. For macOS users, refer to the "Prerequisites" section in the main project `README.md` at the root of this repository for instructions on installing Python using Homebrew. For other operating systems, please follow the official Python installation guides.
*   **Virtual Environment Tool:** Familiarity with Python virtual environments (e.g., `venv`) is recommended.

## Setup and Running

1.  **Navigate to the backend directory:**
    From the project's root directory:
    ```bash
    cd backend
    ```

2.  **Create and activate a Python virtual environment:**
    It's highly recommended to use a virtual environment to manage dependencies.
    ```bash
    # Using python3 if that's how your Homebrew/custom Python is aliased
    python3 -m venv venv 
    ```
    Activate the virtual environment:
    *   On macOS/Linux:
        ```bash
        source venv/bin/activate
        ```
    *   On Windows:
        ```bash
        venv\Scripts\activate
        ```
    Your terminal prompt should change to indicate that the virtual environment is active (e.g., `(venv)`).

3.  **Install dependencies:**
    With the virtual environment activated:
    ```bash
    # Use pip3 if your virtual environment's pip is named pip3
    pip install -r requirements.txt
    ```

4.  **Run the backend server:**
    ```bash
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
    ```
    *   `main:app` refers to the `app` instance of `FastAPI` in the `main.py` file.
    *   `--reload` enables auto-reloading when code changes, useful for development.
    *   The server will typically be available at `http://localhost:8000`.

5.  **Database Setup:**
    The SQLite database file (e.g., `pcap_anonymizer.db`) and necessary tables are created automatically by SQLModel (`create_db_and_tables()` in `database.py`, called during application startup) if they don't already exist in the `backend` directory.

## Project Structure (Simplified)

```
backend/
├── protocols/          # Protocol-specific handlers (e.g., DICOM, BACnet)
├── resources/          # Static resources like OUI CSV, default settings
├── sessions/           # Default directory for storing uploaded PCAP files and session-specific data
├── __init__.py
├── anonymizer.py       # Core IP/Subnet anonymization logic
├── database.py         # Database engine, session management, table creation
├── DicomAnonymizer.py  # DICOM specific anonymization logic
├── exceptions.py       # Custom exception classes
├── MacAnonymizer.py    # MAC address transformation logic
├── main.py             # FastAPI application, API endpoints
├── models.py           # Pydantic/SQLModel data models
├── requirements.txt    # Python dependencies
├── storage.py          # Module for managing file storage and paths for sessions
└── pcap_anonymizer.db  # SQLite database file (created on run)
