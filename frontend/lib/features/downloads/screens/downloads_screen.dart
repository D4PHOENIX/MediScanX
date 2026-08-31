import 'dart:io';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:open_filex/open_filex.dart';
import 'package:path/path.dart' as p;
import 'package:intl/intl.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:path_provider/path_provider.dart';

import '../../../core/utils/download_service.dart';
import '../../referral/models/referral_models.dart';
import '../../referral/providers/cloud_reports_provider.dart';
import '../../referral/services/referral_service.dart';

class DownloadsScreen extends ConsumerStatefulWidget {
  const DownloadsScreen({super.key});

  @override
  ConsumerState<DownloadsScreen> createState() => _DownloadsScreenState();
}

class _DownloadsScreenState extends ConsumerState<DownloadsScreen> with SingleTickerProviderStateMixin {
  final DownloadService _downloadService = DownloadService();
  late TabController _tabController;
  
  // Local files state
  List<File> _localFiles = [];
  bool _isLoadingLocal = true;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    _loadLocalFiles();
    
    // Fetch cloud reports automatically
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(cloudReportsProvider.notifier).fetchReports(refresh: true);
    });
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  Future<void> _loadLocalFiles() async {
    setState(() => _isLoadingLocal = true);
    try {
      final files = await _downloadService.getDownloadedFiles();
      if (mounted) {
        setState(() {
          _localFiles = files;
          _isLoadingLocal = false;
        });
      }
    } catch (e) {
      debugPrint('Error loading files: $e');
      if (mounted) {
        setState(() => _isLoadingLocal = false);
      }
    }
  }

  Future<void> _openLocalFile(File file) async {
    try {
      final result = await OpenFilex.open(file.path);
      if (result.type != ResultType.done && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Could not open file: ${result.message}'),
            backgroundColor: Colors.red,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('An error occurred while opening the file.'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  Future<void> _deleteLocalFile(File file) async {
    final bool? confirm = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) {
        return AlertDialog(
          title: const Text('Delete Local File'),
          content: const Text('Are you sure you want to delete this file from your device?'),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('Cancel'),
            ),
            TextButton(
              onPressed: () => Navigator.of(context).pop(true),
              style: TextButton.styleFrom(foregroundColor: Colors.red),
              child: const Text('Delete'),
            ),
          ],
        );
      },
    );

    if (confirm == true) {
      final success = await _downloadService.deleteFile(file);
      if (success && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('File deleted'), backgroundColor: Colors.teal),
        );
        _loadLocalFiles();
      }
    }
  }

  Future<void> _deleteCloudReport(String reportId) async {
    final bool? confirm = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) {
        return AlertDialog(
          title: const Text('Delete Cloud Report'),
          content: const Text('This will permanently delete the PDF report from the cloud. Your original scans are not affected and you can generate a new report at any time.\n\nAre you sure?'),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('Cancel'),
            ),
            TextButton(
              onPressed: () => Navigator.of(context).pop(true),
              style: TextButton.styleFrom(foregroundColor: Colors.red),
              child: const Text('Delete'),
            ),
          ],
        );
      },
    );

    if (confirm == true) {
      try {
        final success = await ref.read(cloudReportsProvider.notifier).deleteReport(reportId);
        if (success && mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Report deleted successfully.'), backgroundColor: Colors.teal),
          );
        }
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Failed to delete report. Please try again.'),
              backgroundColor: Colors.red,
            ),
          );
        }
      }
    }
  }

  Future<void> _openCloudReport(CloudReportItem report) async {
    try {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Downloading report...'), duration: Duration(seconds: 2)),
        );
      }

      final appDir = await getApplicationDocumentsDirectory();
      final cacheDir = Directory(p.join(appDir.path, 'temp_cloud_reports'));
      if (!await cacheDir.exists()) {
        await cacheDir.create(recursive: true);
      }
      final fileName = 'Report_${report.reportId.substring(0, 6).toUpperCase()}.pdf';
      final savePath = p.join(cacheDir.path, fileName);

      // Check if we already downloaded this report and it's a valid PDF
      final cachedFile = File(savePath);
      if (await cachedFile.exists() && (await cachedFile.length()) > 4) {
        final bytes = await cachedFile.openRead(0, 5).first;
        final header = String.fromCharCodes(bytes);
        if (header.startsWith('%PDF')) {
          await OpenFilex.open(savePath);
          return;
        } else {
          // Cached file is not a valid PDF, delete it
          await cachedFile.delete();
        }
      }

      // We now fetch the dynamic signed URL on demand

      debugPrint('📥 Downloading cloud report: id=${report.reportId}, url=${report.url}');
      
      final success = await ReferralService().downloadReportToFile(
        report.reportId,
        savePath,
      );

      if (success) {
        final result = await OpenFilex.open(savePath);
        if (result.type != ResultType.done && mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Could not open file: ${result.message}'), backgroundColor: Colors.red),
          );
        }
      } else {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Could not download the report.'),
              backgroundColor: Colors.red,
            ),
          );
        }
      }
    } catch (e) {
      debugPrint('🔴 Cloud report open error: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: ${e.toString()}'), backgroundColor: Colors.red),
        );
      }
    }
  }

  IconData _getFileIcon(String filename) {
    final ext = p.extension(filename).toLowerCase();
    if (ext == '.pdf') return Icons.picture_as_pdf_rounded;
    if (ext == '.jpg' || ext == '.jpeg' || ext == '.png') return Icons.image_rounded;
    return Icons.insert_drive_file_rounded;
  }

  Color _getFileIconColor(String filename) {
    final ext = p.extension(filename).toLowerCase();
    if (ext == '.pdf') return Colors.redAccent;
    if (ext == '.jpg' || ext == '.jpeg' || ext == '.png') return Colors.blueAccent;
    return Colors.grey;
  }

  String _formatDate(DateTime date) {
    return DateFormat('MMM d, yyyy • h:mm a').format(date);
  }

  @override
  Widget build(BuildContext context) {
    final cloudState = ref.watch(cloudReportsProvider);
    final user = Supabase.instance.client.auth.currentUser;
    final metadataRole = (user?.userMetadata?['role'] ?? user?.userMetadata?['userType']);
    final bool isPatient = metadataRole != 'doctor';

    return Scaffold(
      backgroundColor: Colors.grey[50],
      appBar: AppBar(
        title: const Text('Reports & Downloads', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
        backgroundColor: Colors.white,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_new_rounded, size: 20),
          onPressed: () => context.pop(),
        ),
        bottom: TabBar(
          controller: _tabController,
          labelColor: const Color(0xFF00B4D8),
          unselectedLabelColor: Colors.grey[600],
          indicatorColor: const Color(0xFF00B4D8),
          tabs: const [
            Tab(text: 'Cloud Reports'),
            Tab(text: 'Local Storage'),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        children: [
          // CLOUD TAB
          RefreshIndicator(
            onRefresh: () => ref.read(cloudReportsProvider.notifier).fetchReports(refresh: true),
            color: const Color(0xFF00B4D8),
            child: cloudState.isLoading && cloudState.reports.isEmpty
                ? const Center(child: CircularProgressIndicator())
                : cloudState.reports.isEmpty
                    ? ListView(
                        children: [
                          SizedBox(height: MediaQuery.of(context).size.height * 0.3),
                          Center(
                            child: Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Icon(Icons.cloud_off_rounded, size: 64, color: Colors.grey[300]),
                                const SizedBox(height: 16),
                                Text(
                                  cloudState.errorMessage ?? 'No cloud reports found',
                                  style: TextStyle(fontSize: 16, color: Colors.grey[500], fontWeight: FontWeight.w500),
                                ),
                              ],
                            ),
                          ),
                        ],
                      )
                    : ListView.separated(
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        itemCount: cloudState.reports.length,
                        separatorBuilder: (context, index) => const Divider(height: 1),
                        itemBuilder: (context, index) {
                          final report = cloudState.reports[index];
                          final filename = 'Report_${report.reportId.substring(0, 6).toUpperCase()}.pdf';
                          final isDownloadable = true;
                          
                          return ListTile(
                            contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 4),
                            leading: Container(
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(
                                color: isDownloadable ? Colors.redAccent.withOpacity(0.1) : Colors.grey.withOpacity(0.1),
                                borderRadius: BorderRadius.circular(12),
                              ),
                              child: Icon(
                                isDownloadable ? Icons.picture_as_pdf_rounded : Icons.broken_image_rounded, 
                                color: isDownloadable ? Colors.redAccent : Colors.grey, 
                                size: 24
                              ),
                            ),
                            title: Text(
                              filename,
                              style: TextStyle(
                                fontWeight: FontWeight.w600, 
                                fontSize: 15,
                                color: isDownloadable ? Colors.black87 : Colors.grey,
                              ),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                            subtitle: Padding(
                              padding: const EdgeInsets.only(top: 4),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    isDownloadable 
                                        ? '${_formatDate(report.createdAt.toLocal())} • ${report.scanCount} scan${report.scanCount == 1 ? "" : "s"}'
                                        : 'File unavailable',
                                    style: TextStyle(color: Colors.grey[600], fontSize: 13),
                                  ),
                                  if (report.survivingScanCount != null && report.survivingScanCount! < report.scanCount)
                                    Padding(
                                      padding: const EdgeInsets.only(top: 2),
                                      child: Text(
                                        '${report.scanCount - report.survivingScanCount!} source scan(s) no longer available',
                                        style: const TextStyle(color: Colors.orange, fontSize: 11, fontStyle: FontStyle.italic),
                                      ),
                                    ),
                                ],
                              ),
                            ),
                            trailing: isPatient
                                ? IconButton(
                                    icon: const Icon(Icons.delete_outline_rounded, color: Colors.redAccent),
                                    onPressed: () => _deleteCloudReport(report.reportId),
                                    tooltip: 'Delete from Cloud',
                                  )
                                : null,
                            onTap: isDownloadable ? () => _openCloudReport(report) : null,
                          );
                        },
                      ),
          ),
          
          // LOCAL TAB
          _isLoadingLocal
              ? const Center(child: CircularProgressIndicator())
              : _localFiles.isEmpty
                  ? Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.folder_open_rounded, size: 64, color: Colors.grey[300]),
                          const SizedBox(height: 16),
                          Text(
                            'No local downloads',
                            style: TextStyle(fontSize: 16, color: Colors.grey[500], fontWeight: FontWeight.w500),
                          ),
                        ],
                      ),
                    )
                  : ListView.separated(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      itemCount: _localFiles.length,
                      separatorBuilder: (context, index) => const Divider(height: 1),
                      itemBuilder: (context, index) {
                        final file = _localFiles[index];
                        final stat = file.statSync();
                        final filename = p.basename(file.path);
                        
                        final sizeInKb = stat.size / 1024;
                        final sizeStr = sizeInKb > 1024 
                            ? '${(sizeInKb / 1024).toStringAsFixed(1)} MB' 
                            : '${sizeInKb.toStringAsFixed(0)} KB';

                        return ListTile(
                          contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 4),
                          leading: Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: _getFileIconColor(filename).withOpacity(0.1),
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: Icon(
                              _getFileIcon(filename),
                              color: _getFileIconColor(filename),
                              size: 24,
                            ),
                          ),
                          title: Text(
                            filename,
                            style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                          subtitle: Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text(
                              '${_formatDate(stat.modified)} • $sizeStr',
                              style: TextStyle(color: Colors.grey[600], fontSize: 13),
                            ),
                          ),
                          trailing: IconButton(
                            icon: const Icon(Icons.delete_outline_rounded, color: Colors.redAccent),
                            onPressed: () => _deleteLocalFile(file),
                            tooltip: 'Delete Locally',
                          ),
                          onTap: () => _openLocalFile(file),
                        );
                      },
                    ),
        ],
      ),
    );
  }
}
