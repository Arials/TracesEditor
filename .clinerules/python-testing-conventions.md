# Python Testing Conventions

## 1. Running Pytest and Resolving ImportErrors

When working with Python projects that have a nested directory structure (e.g., a `backend` source directory and a `tests` directory), you might encounter `ImportError: ModuleNotFoundError` when trying to run `pytest` directly from the project root. This typically happens because Python's import resolution mechanism doesn't automatically add the project root to `sys.path` in a way that allows test files to find source modules.

**Symptom:**
```
ERROR collecting path/to/your/tests/test_your_module.py
ImportError while importing test module '.../test_your_module.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
...
ModuleNotFoundError: No module named 'your_source_module'
```

**Solution:**

To ensure correct module path resolution, run `pytest` as a Python module from the project's root directory:

```bash
python -m pytest [path/to/your/tests or specific_test_file.py]
```

**Example:**
If your tests are in `backend/tests/` and your project root is `PcapAnonymizer`, you would run:
```bash
python -m pytest backend/tests/
```
Or for a specific file:
```bash
python -m pytest backend/tests/test_dicom_pcap_generation.py
```

This approach helps Python correctly set up its import paths relative to the project root, allowing your test files to import modules from your source directories (like `backend.protocols.dicom.handler`) without issues.

## 2. General Backend Test Planning (To be expanded)

(Placeholder for future content on how to plan backend tests)
