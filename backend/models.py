# models.py
# MODIFIED: Added 'negotiation_successful' field to DicomExtractedMetadata

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict # For Pydantic v2 configuration
from typing import List, Dict, Optional, Any, Union # Import necessary types # MOD-2: Added Union
from datetime import datetime # Import datetime for response model

# --- Models for PCAP Anonymization Rules (Existing) ---\n
class Rule(BaseModel):
    """
    Represents a CIDR transformation rule for PCAP IP anonymization.
    Accepts either new field names (`source`, `target`) or legacy
    names (`from_cidr`, `to_cidr`) for backward compatibility with
    older JSON payloads.
    """
    # Source CIDR network to be anonymized
    source: str = Field(..., alias='from_cidr', description="Source CIDR network")
    # Target CIDR network to map the source to
    target: str = Field(..., alias='to_cidr', description="Target CIDR network")

    # Pydantic v2 configuration to allow populating fields by alias
    # (e.g., allow using 'from_cidr' in input data to populate the 'source' field)
    model_config = ConfigDict(populate_by_name=True)


class RuleInput(BaseModel):
    """
    Input model for the endpoint that saves PCAP anonymization rules.
    """
    # The session ID for which the rules apply
    session_id: str = Field(..., description="The session ID these rules belong to")
    # A list of transformation rules
    rules: List[Rule] = Field(..., description="List of CIDR transformation rules")


# --- Model for PCAP Session Response ---
# Separate Pydantic model for API responses to avoid issues with SQLModel specifics
class PcapSessionResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    original_filename: Optional[str] = None
    upload_timestamp: datetime
    # pcap_path: str # Keep internal path? Or remove for security? Keeping for now. # MOD-1: Marked for removal
    # rules_path: Optional[str] = None # Keep internal path? Or remove? Keeping for now. # MOD-1: Marked for removal
    updated_at: Optional[datetime] = None
    # Add the new fields from the DB model
    is_transformed: bool
    original_session_id: Optional[str] = None
    async_job_id: Optional[int] = None
    # New fields to better describe the file for UploadPage
    file_type: Optional[str] = Field(default="original", description="Type of PCAP file (original, ip_mac_anonymized, mac_transformed, dicom_v2_anonymized)")
    derived_from_session_id: Optional[str] = Field(default=None, description="Original session ID if this is a derived/transformed file")
    source_job_id: Optional[int] = Field(default=None, description="Job ID that created this derived file")
    actual_pcap_filename: Optional[str] = Field(default=None, description="The actual filename on disk for derived files")

    # Enable ORM mode for automatic mapping from SQLModel objects
    model_config = ConfigDict(from_attributes=True)


# --- Models for DICOM PCAP Metadata Extraction Response (Aggregated) ---

class DicomExtractedMetadata(BaseModel):
    """
    Holds the specific DICOM tags extracted from an association negotiation
    (primarily A-ASSOCIATE-RQ and A-ASSOCIATE-AC PDUs) and P-DATA PDUs.
    All fields are optional as they might not be present in every PDU.
    This model is used as a nested structure within AggregatedDicomInfo.
    """
    # From A-ASSOCIATE-RQ/AC
    CallingAE: Optional[str] = Field(None, description="Calling AE Title")
    CalledAE: Optional[str] = Field(None, description="Called AE Title")
    ImplementationClassUID: Optional[str] = Field(None, description="Implementation Class UID")
    ImplementationVersionName: Optional[str] = Field(None, description="Implementation Version Name")
    negotiation_successful: Optional[bool] = Field(None, description="Indicates if negotiation was successful")

    # From P-DATA
    Manufacturer: Optional[str] = Field(None, description="Device Manufacturer")
    ManufacturerModelName: Optional[str] = Field(None, description="Device Model Name")
    DeviceSerialNumber: Optional[str] = Field(None, description="Device Serial Number")
    SoftwareVersions: Optional[Union[str, List[str]]] = Field(None, description="Device Software Versions (can be str or list of str)") # MOD-2
    TransducerData: Optional[Union[str, List[str]]] = Field(None, description="Transducer Data (can be str or list of str)") # MOD-2
    StationName: Optional[str] = Field(None, description="Station Name")

    model_config = ConfigDict(extra='allow')


class AggregatedDicomInfo(DicomExtractedMetadata):
    """
    Represents the aggregated DICOM metadata for a unique Client IP / Server IP pair.
    Inherits all metadata fields from DicomExtractedMetadata and adds IP/Port info.
    """
    client_ip: str = Field(..., description="IP address acting as the DICOM client (SCU)")
    server_ip: str = Field(..., description="IP address acting as the DICOM server (SCP)")
    # Store all unique server ports seen for this IP pair
    server_ports: List[int] = Field(..., description="List of unique server ports associated with this IP pair")

    # Inherits model_config from DicomExtractedMetadata


class AggregatedDicomResponse(BaseModel):
    """
    The overall response structure for the *aggregated* DICOM PCAP metadata extraction endpoint.
    It maps a unique key (e.g., "client_ip-server_ip") to the aggregated metadata object
    for that IP pair.
    """
    # The main result is a dictionary where keys identify the IP pair
    # and values are the aggregated metadata objects.
    results: Dict[str, AggregatedDicomInfo] = Field(
        ...,
        description="Dictionary mapping unique IP pair identifiers to aggregated DICOM metadata"
    )
    # Optional field to include the name of the session (trace)
    trace_name: Optional[str] = Field(None, description="The user-provided name for the session/trace")


# --- Model for DICOM Metadata Update Request ---

class DicomMetadataUpdatePayload(DicomExtractedMetadata):
    """
    Payload for the PUT request to update DICOM metadata overrides.
    Contains the fields that can be modified. Inherits optional fields
    from DicomExtractedMetadata. Client should only send fields they want to update.
    """
    # No additional fields needed here, just inherits the editable metadata fields.
    # The IP pair identifier will be part of the URL path or query params.
    pass # Inherits all fields from DicomExtractedMetadata


# --- Models for MAC Vendor Modification ---

class MacSettings(BaseModel):
    """Settings related to MAC address vendor modification."""
    csv_url: str = Field(..., description="URL to download the OUI CSV file from")
    last_updated: Optional[datetime] = Field(None, description="Timestamp of the last successful OUI CSV update")


class MacRule(BaseModel):
    """Represents a rule for transforming a specific MAC address to a new target vendor."""
    original_mac: str = Field(..., description="The specific original MAC address to transform")
    target_vendor: str = Field(..., description="Target vendor name to transform to")
    target_oui: str = Field(..., description="Target OUI (first 3 bytes) corresponding to the target vendor")


class MacRuleInput(BaseModel):
    """Input model for the endpoint that saves MAC transformation rules."""
    session_id: str = Field(..., description="The session ID these rules belong to")
    rules: List[MacRule] = Field(..., description="List of MAC vendor transformation rules")


class IpMacPair(BaseModel):
    """Represents an extracted IP address, MAC address, and its identified vendor."""
    ip_address: str = Field(..., description="IP address associated with the MAC")
    mac_address: str = Field(..., description="MAC address found in the PCAP")
    vendor: Optional[str] = Field(None, description="Vendor name identified from the OUI prefix (if found)")


class IpMacPairListResponse(BaseModel):
    """Response model for the endpoint returning extracted IP-MAC pairs."""
    pairs: List[IpMacPair] = Field(..., description="List of unique IP-MAC pairs found in the PCAP")


class MacSettingsUpdate(BaseModel):
    """Input model for updating the MAC settings, specifically the CSV URL."""
    csv_url: str
