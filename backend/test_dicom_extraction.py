import json
import os
import sys
import traceback
import csv # Import csv module
import contextlib # For redirecting stdout

# Add the project root to the Python path
script_dir = os.path.dirname(os.path.abspath(__file__)) # PcapAnonymizer/backend
project_root = os.path.dirname(script_dir) # PcapAnonymizer/
sys.path.insert(0, project_root) # Add PcapAnonymizer/ to sys.path

try:
    # Import the main extraction function
    from backend.dicom_pcap_extractor import extract_dicom_metadata_from_pcap
    from backend.exceptions import JobCancelledException
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Ensure the script is run from the project root or the backend directory is in PYTHONPATH.")
    sys.exit(1)

# --- Configuration ---
# Get the directory where the script itself is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Construct paths relative to the script's directory
NEW_SESSION_ID = "16e52ea9-3798-45c4-a7c9-04b3b05da29d"
PCAP_FILE_PATH = os.path.join(script_dir, "sessions", NEW_SESSION_ID, "capture.pcap")
CSV_VALIDATION_FILE = os.path.join(script_dir, "a_associated Request_Healthcare_nodup.csv")

# Session ID for the extractor function context
TEST_SESSION_ID = NEW_SESSION_ID
# Output file for full debug log
DEBUG_OUTPUT_FILE = os.path.join(script_dir, "debug_test_output.txt")

# --- Main Execution ---
if __name__ == "__main__":
    # Redirect stdout to the debug file
    with open(DEBUG_OUTPUT_FILE, 'w', encoding='utf-8') as f, contextlib.redirect_stdout(f):
        print(f"--- Running DICOM Extraction Test ---")
        print(f"--- Output redirected to {DEBUG_OUTPUT_FILE} ---")
        print(f"PCAP File: {PCAP_FILE_PATH}")
        print(f"Validation CSV: {CSV_VALIDATION_FILE}")

    # Check if PCAP file exists
    if not os.path.exists(PCAP_FILE_PATH):
        print(f"ERROR: PCAP file not found at {PCAP_FILE_PATH}")
        sys.exit(1)

    # Check if CSV file exists
    if not os.path.exists(CSV_VALIDATION_FILE):
        print(f"ERROR: Validation CSV file not found at {CSV_VALIDATION_FILE}")
        sys.exit(1)

    # --- Read Validation Data from CSV ---
    expected_ae_titles = {} # Dictionary to store expected values: {(client_ip, server_ip): {'CallingAE': '...', 'CalledAE': '...'}}
    try:
        with open(CSV_VALIDATION_FILE, mode='r', newline='', encoding='utf-8') as csvfile:
            # Detect delimiter - assuming comma for now, adjust if needed
            # Sniffer can be used for more robust detection if delimiters vary
            # dialect = csv.Sniffer().sniff(csvfile.read(1024))
            # csvfile.seek(0)
            # reader = csv.DictReader(csvfile, dialect=dialect)
            reader = csv.DictReader(csvfile) # Assumes comma delimiter and header row
            print("\n--- Reading Expected AE Titles from CSV ---")
            import re # Import regex module

            # Identify relevant columns based on the actual CSV header
            ip_src_col = 'Source'
            ip_dst_col = 'Destination'
            info_col = 'Info'

            # Check if required columns exist in the header
            if not all(col in reader.fieldnames for col in [ip_src_col, ip_dst_col, info_col]):
                 print(f"ERROR: CSV file '{CSV_VALIDATION_FILE}' is missing one or more required columns: '{ip_src_col}', '{ip_dst_col}', '{info_col}'.")
                 print(f"Available columns: {reader.fieldnames}")
                 sys.exit(1)

            # Regex to extract AE titles from the Info column
            # Format: "A-ASSOCIATE request [CallingAE] --> [CalledAE]"
            # Handles optional leading text like "[TCP Spurious Retransmission] "
            ae_title_regex = re.compile(r"A-ASSOCIATE request\s+(.*?)\s+-->\s+(.*)")

            for row in reader:
                client_ip = row.get(ip_src_col, '').strip()
                server_ip = row.get(ip_dst_col, '').strip()
                info_text = row.get(info_col, '').strip()

                calling_ae = None
                called_ae = None

                # Attempt to parse AE titles from the Info column
                match = ae_title_regex.search(info_text)
                if match:
                    calling_ae = match.group(1).strip()
                    called_ae = match.group(2).strip()
                else:
                    # Optional: Log if the Info column didn't match the expected format
                    # print(f"  WARN: Could not parse AE titles from Info column for row: {row}")
                    pass # Skip rows where AE titles aren't found in the expected format

                if client_ip and server_ip and (calling_ae or called_ae):
                    key = (client_ip, server_ip)
                    # Store the first non-empty AE titles found for this IP pair
                    if key not in expected_ae_titles:
                         expected_ae_titles[key] = {'CallingAE': None, 'CalledAE': None}
                    if expected_ae_titles[key]['CallingAE'] is None and calling_ae:
                         expected_ae_titles[key]['CallingAE'] = calling_ae
                    if expected_ae_titles[key]['CalledAE'] is None and called_ae:
                         expected_ae_titles[key]['CalledAE'] = called_ae
                    print(f"  Read Expected: {client_ip} -> {server_ip} | Calling: '{calling_ae}', Called: '{called_ae}'")

        print(f"Successfully read {len(expected_ae_titles)} unique IP pairs with expected AE titles from CSV.")
        # print(f"Expected Data Structure: {expected_ae_titles}") # Optional: print the full structure

    except FileNotFoundError:
        print(f"ERROR: Validation CSV file not found at {CSV_VALIDATION_FILE}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR reading or parsing CSV file {CSV_VALIDATION_FILE}: {e}")
        traceback.print_exc()
        sys.exit(1)

    # --- Run Extraction ---
    print("\n--- Running PCAP Extraction ---")
    results = {}
    try:
        # Call the extraction function directly with the file path
        results = extract_dicom_metadata_from_pcap(
            pcap_file_path=PCAP_FILE_PATH,
            session_id=TEST_SESSION_ID
            # progress_callback and check_stop_requested can be added if needed
        )
        print("\n--- Extraction Complete ---")
        # print("\nRaw Extraction Results:")
        # print(json.dumps(results, indent=2, default=str)) # Print raw results if needed

    except JobCancelledException:
        print("Extraction cancelled.")
        sys.exit(0)
    except FileNotFoundError as e:
        print(f"ERROR during extraction: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred during extraction: {e}")
        traceback.print_exc()
        sys.exit(1)

    # --- Compare Results ---
    print("\n--- Comparing Extracted AE Titles with Expected CSV Values ---")
    match_count = 0
    mismatch_count = 0
    extracted_not_in_csv = 0
    csv_not_extracted = 0

    # Check extracted results against CSV
    for agg_key, extracted_data in results.items():
        client_ip = extracted_data.get("client_ip")
        server_ip = extracted_data.get("server_ip")
        extracted_calling = extracted_data.get("CallingAE", "").strip() if extracted_data.get("CallingAE") else ""
        extracted_called = extracted_data.get("CalledAE", "").strip() if extracted_data.get("CalledAE") else ""

        key = (client_ip, server_ip)

        if key in expected_ae_titles:
            expected_calling = expected_ae_titles[key].get('CallingAE', "")
            expected_called = expected_ae_titles[key].get('CalledAE', "")

            calling_match = (extracted_calling == expected_calling)
            called_match = (extracted_called == expected_called)

            if calling_match and called_match:
                print(f"[ MATCH ] {client_ip} -> {server_ip}")
                print(f"          Extracted: Calling='{extracted_calling}', Called='{extracted_called}'")
                print(f"          Expected:  Calling='{expected_calling}', Called='{expected_called}'")
                match_count += 1
            else:
                print(f"[MISMATCH] {client_ip} -> {server_ip}")
                print(f"          Extracted: Calling='{extracted_calling}', Called='{extracted_called}'")
                print(f"          Expected:  Calling='{expected_calling}', Called='{expected_called}'")
                if not calling_match: print(f"          -> Calling AE mismatch")
                if not called_match:  print(f"          -> Called AE mismatch")
                mismatch_count += 1
            # Mark this key as processed
            expected_ae_titles[key]['processed'] = True
        else:
            print(f"[EXTRA]   {client_ip} -> {server_ip} (Found in PCAP extraction, but not in CSV)")
            print(f"          Extracted: Calling='{extracted_calling}', Called='{extracted_called}'")
            extracted_not_in_csv += 1

    # Check for expected entries not found in extraction
    for key, expected_data in expected_ae_titles.items():
        if not expected_data.get('processed', False):
            client_ip, server_ip = key
            expected_calling = expected_data.get('CallingAE', "")
            expected_called = expected_data.get('CalledAE', "")
            print(f"[MISSING] {client_ip} -> {server_ip} (Found in CSV, but not in PCAP extraction results)")
            print(f"          Expected:  Calling='{expected_calling}', Called='{expected_called}'")
            csv_not_extracted += 1

    # --- Summary ---
    print("\n--- Comparison Summary ---")
    print(f"Total IP pairs in Extraction: {len(results)}")
    print(f"Total IP pairs in CSV:        {len(expected_ae_titles)}")
    print(f"Matches:                      {match_count}")
    print(f"Mismatches:                   {mismatch_count}")
    print(f"Extracted but not in CSV:     {extracted_not_in_csv}")
    print(f"In CSV but not Extracted:     {csv_not_extracted}")
    print("--------------------------")

    # Exit with code 0 if no mismatches/missing/extra, 1 otherwise
    if mismatch_count == 0 and extracted_not_in_csv == 0 and csv_not_extracted == 0:
        print("SUCCESS: All extracted AE Titles match the expected values in the CSV.")
        sys.exit(0)
    else:
        print("WARNING: Discrepancies found between extracted AE Titles and CSV.")
        sys.exit(1)
