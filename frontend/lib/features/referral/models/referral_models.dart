/// Model for a single care relationship row returned by
/// GET /api/v1/patients/care-relationships
class CareRelationship {
  final String id;           // UUID string
  final String doctorName;
  final String specialisation;
  final String hospital;
  final DateTime? expiresAt;
  final bool isActive;

  CareRelationship({
    required this.id,
    required this.doctorName,
    required this.specialisation,
    required this.hospital,
    this.expiresAt,
    required this.isActive,
  });

  factory CareRelationship.fromJson(Map<String, dynamic> json) {
    return CareRelationship(
      id: json['id']?.toString() ?? '',
      // Exact field names from backend Swagger schema
      doctorName:        json['doctor_full_name']        as String? ?? '—',
      specialisation:    json['doctor_specialization']   as String? ?? '—',
      hospital:          json['doctor_current_hospital'] as String? ?? '—',
      expiresAt: json['expires_at'] != null
          ? DateTime.tryParse(json['expires_at'].toString())?.toLocal()
          : null,
      // Backend returns both is_active (bool) and status (string)
      isActive: json['is_active'] == true || json['status'] == 'active',
    );
  }
}

class ReferralResponse {
  final String patientId;
  final String signedUrl;
  final String message;
  final String reportId;

  ReferralResponse({
    required this.patientId,
    required this.signedUrl,
    required this.message,
    required this.reportId,
  });

  factory ReferralResponse.fromJson(Map<String, dynamic> json) {
    return ReferralResponse(
      patientId: json['patient_id'] ?? '',
      signedUrl: json['signed_url'] ?? '',
      message: json['message'] ?? 'Report generated',
      reportId: json['report_id'] ?? '',
    );
  }
}
class CloudReportResponse {
  final int totalCount;
  final List<CloudReportItem> items;

  CloudReportResponse({required this.totalCount, required this.items});

  factory CloudReportResponse.fromJson(Map<String, dynamic> json) {
    return CloudReportResponse(
      totalCount: json['total_count'] ?? 0,
      items: (json['items'] as List?)?.map((i) => CloudReportItem.fromJson(i)).toList() ?? [],
    );
  }
}

class CloudReportItem {
  final String reportId;
  final DateTime createdAt;
  final int scanCount;
  final int? survivingScanCount;
  final String? url;
  final String? patientRef;

  CloudReportItem({
    required this.reportId,
    required this.createdAt,
    required this.scanCount,
    this.survivingScanCount,
    this.url,
    this.patientRef,
  });

  factory CloudReportItem.fromJson(Map<String, dynamic> json) {
    return CloudReportItem(
      reportId: json['report_id'] ?? '',
      createdAt: DateTime.tryParse(json['created_at'] ?? '') ?? DateTime.now(),
      scanCount: json['scan_count'] ?? 1,
      survivingScanCount: json['surviving_scan_count'],
      url: json['url'],
      patientRef: json['patient_ref'],
    );
  }
}
