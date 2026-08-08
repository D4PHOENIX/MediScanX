class ReferralResponse {
  final String patientId;
  final String signedUrl;
  final String message;

  ReferralResponse({
    required this.patientId,
    required this.signedUrl,
    required this.message,
  });

  factory ReferralResponse.fromJson(Map<String, dynamic> json) {
    return ReferralResponse(
      patientId: json['patient_id'] ?? '',
      signedUrl: json['signed_url'] ?? '',
      message: json['message'] ?? 'Report generated',
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
  final String? url;
  final String? patientRef;

  CloudReportItem({
    required this.reportId,
    required this.createdAt,
    required this.scanCount,
    this.url,
    this.patientRef,
  });

  factory CloudReportItem.fromJson(Map<String, dynamic> json) {
    return CloudReportItem(
      reportId: json['report_id'] ?? '',
      createdAt: DateTime.tryParse(json['created_at'] ?? '') ?? DateTime.now(),
      scanCount: json['scan_count'] ?? 1,
      url: json['url'],
      patientRef: json['patient_ref'],
    );
  }
}
