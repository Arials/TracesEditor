from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class ConnectionDetails(BaseModel):
    source_mac: str = Field(..., example="00:00:00:AA:BB:CC")
    destination_mac: str = Field(..., example="00:00:00:DD:EE:FF")
    source_ip: str = Field(..., example="192.168.1.100")
    destination_ip: str = Field(..., example="192.168.1.200")
    source_port: int = Field(..., example=56789)
    destination_port: int = Field(..., example=104)

class PresentationContextItem(BaseModel):
    id: int = Field(..., example=1)
    abstract_syntax: str = Field(..., example="1.2.840.10008.5.1.4.1.1.2") # CT Image Storage
    transfer_syntaxes: List[str] = Field(..., example=["1.2.840.10008.1.2.1", "1.2.840.10008.1.2"])

class AssociationRequestDetails(BaseModel):
    calling_ae_title: str = Field(..., max_length=16, example="SCU_AET")
    called_ae_title: str = Field(..., max_length=16, example="SCP_AET")
    application_context_name: str = Field(..., example="1.2.840.10008.3.1.1.1") # DICOM Application Context Name
    presentation_contexts: List[PresentationContextItem]

class CommandSetItem(BaseModel):
    MessageID: int = Field(..., example=1)
    Priority: Optional[int] = Field(None, example=1)
    AffectedSOPClassUID: Optional[str] = Field(None, example="1.2.840.10008.5.1.4.1.1.2")
    AffectedSOPInstanceUID: Optional[str] = Field(None, example="1.2.826.0.1.3680043.9.1234.1.1")
    # Add other common command set fields as needed, or allow arbitrary key-values
    # For now, we'll allow any additional fields that pydicom can handle.
    # Using Dict[str, Any] for flexibility, specific fields above for validation and OpenAPI docs.
    extra_fields: Dict[str, Any] = Field(default_factory=dict)

    def to_pydicom_dict(self) -> Dict[str, Any]:
        """Converts to a dictionary suitable for pydicom, merging specific and extra fields."""
        data = self.extra_fields.copy()
        if self.MessageID is not None:
            data['MessageID'] = self.MessageID
        if self.Priority is not None:
            data['Priority'] = self.Priority
        if self.AffectedSOPClassUID is not None:
            data['AffectedSOPClassUID'] = self.AffectedSOPClassUID
        if self.AffectedSOPInstanceUID is not None:
            data['AffectedSOPInstanceUID'] = self.AffectedSOPInstanceUID
        return data

class DataSetItem(BaseModel):
    # Using Dict[str, Any] for flexibility, as dataset contents are highly variable.
    # pydicom will handle keyword-to-tag mapping and VR assignment.
    elements: Dict[str, Any] = Field(..., example={
        "SOPClassUID": "1.2.840.10008.5.1.4.1.1.2",
        "SOPInstanceUID": "1.2.826.0.1.3680043.9.1234.1.1",
        "PatientName": "Doe^Jane",
        "PatientID": "PID001",
        "StudyInstanceUID": "1.2.826.0.1.3680043.9.1234",
        "SeriesInstanceUID": "1.2.826.0.1.3680043.9.1234.1",
        "Modality": "CT",
        "InstanceNumber": "1"
    })

    def to_pydicom_dict(self) -> Dict[str, Any]:
        """Returns the elements dictionary."""
        return self.elements

class DicomMessageItem(BaseModel):
    presentation_context_id: int = Field(..., example=1)
    message_type: str = Field(..., example="C-STORE-RQ") # e.g., C-STORE-RQ, C-ECHO-RQ
    command_set: CommandSetItem
    data_set: Optional[DataSetItem] = None # Can be null for messages like C-ECHO-RQ

class DicomPcapRequestPayload(BaseModel):
    connection_details: ConnectionDetails
    association_request: AssociationRequestDetails
    dicom_messages: List[DicomMessageItem]

    class Config:
        json_schema_extra = {
            "example": {
                "connection_details": {
                    "source_mac": "00:00:00:AA:BB:CC",
                    "destination_mac": "00:00:00:DD:EE:FF",
                    "source_ip": "192.168.1.100",
                    "destination_ip": "192.168.1.200",
                    "source_port": 56789,
                    "destination_port": 104
                },
                "association_request": {
                    "calling_ae_title": "SCU_AET",
                    "called_ae_title": "SCP_AET",
                    "application_context_name": "1.2.840.10008.3.1.1.1",
                    "presentation_contexts": [
                        {
                            "id": 1,
                            "abstract_syntax": "1.2.840.10008.5.1.4.1.1.2",
                            "transfer_syntaxes": [
                                "1.2.840.10008.1.2.1",
                                "1.2.840.10008.1.2"
                            ]
                        }
                    ]
                },
                "dicom_messages": [
                    {
                        "presentation_context_id": 1,
                        "message_type": "C-STORE-RQ",
                        "command_set": {
                            "MessageID": 1,
                            "Priority": 1,
                            "AffectedSOPClassUID": "1.2.840.10008.5.1.4.1.1.2",
                            "AffectedSOPInstanceUID": "1.2.826.0.1.3680043.9.1234.1.1"
                        },
                        "data_set": {
                            "elements": {
                                "SOPClassUID": "1.2.840.10008.5.1.4.1.1.2",
                                "SOPInstanceUID": "1.2.826.0.1.3680043.9.1234.1.1",
                                "PatientName": "Doe^Jane",
                                "PatientID": "PID001",
                                "StudyInstanceUID": "1.2.826.0.1.3680043.9.1234",
                                "SeriesInstanceUID": "1.2.826.0.1.3680043.9.1234.1",
                                "Modality": "CT",
                                "InstanceNumber": "1"
                            }
                        }
                    },
                    {
                        "presentation_context_id": 1,
                        "message_type": "C-ECHO-RQ",
                        "command_set": {
                            "MessageID": 2
                        },
                        "data_set": None
                    }
                ]
            }
        }
