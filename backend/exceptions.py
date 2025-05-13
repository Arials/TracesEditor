# backend/exceptions.py

class PcapAnonymizerException(Exception):
    """Base exception for PcapAnonymizer application specific errors."""
    pass

class JobCancelledException(PcapAnonymizerException):
    """Custom exception to signal job cancellation."""
    pass

class FileProcessingError(PcapAnonymizerException):
    """Base exception for errors related to file processing."""
    pass

class CsvProcessingError(FileProcessingError):
    """Base exception for errors related to CSV file processing."""
    pass

class OuiCsvValidationError(CsvProcessingError):
    """Exception raised for errors during OUI CSV file validation."""
    pass

class OuiCsvParseError(CsvProcessingError):
    """Exception raised for errors during OUI CSV file parsing."""
    pass

# Add other custom exceptions here if needed in the future
