"""Generation service for clinical QR referral payloads.

Provides utilities to generate standardized, encoded payloads for seamless
patient hand-off and data continuity across clinical interfaces.
"""

import base64


class QRGenerator:
    """Service class for generating encoded clinical referral payloads.

    This class encapsulates the logic for constructing machine-readable referral
    strings, facilitating interoperability between the primary diagnostic gateway
    and secondary care systems.
    """

    def generate_referral_qr(self, patient_id: str, diagnostic_summary: str) -> str:
        """Generates a Base64-encoded payload representing a clinical referral.

        Constructs a delimited payload containing the patient identifier and a
        summary of the diagnostic findings, which is subsequently encoded to ensure
        safe transmission across HTTP protocols and physical QR scanning interfaces.

        Args:
            patient_id (str): The unique identifier assigned to the patient.
            diagnostic_summary (str): A concise textual summary of the diagnostic
                findings prompting the referral.

        Returns:
            str: A Base64-encoded ASCII string containing the referral payload.
        """
        payload: str = f"REFERRAL|{patient_id}|{diagnostic_summary}"
        return base64.b64encode(payload.encode("ascii")).decode("ascii")
