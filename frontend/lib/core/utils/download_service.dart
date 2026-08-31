import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:dio/dio.dart';
import 'package:path/path.dart' as p;

class DownloadService {
  static final DownloadService _instance = DownloadService._internal();
  factory DownloadService() => _instance;
  DownloadService._internal();

  final Dio _dio = Dio();
  static const String _folderName = 'MediScanX_Downloads';

  /// Gets the dedicated downloads directory for the app.
  Future<Directory> getDownloadsDirectory() async {
    final appDocDir = await getApplicationDocumentsDirectory();
    final downloadDir = Directory(p.join(appDocDir.path, _folderName));
    if (!await downloadDir.exists()) {
      await downloadDir.create(recursive: true);
    }
    return downloadDir;
  }

  /// Downloads a file from a URL to the internal downloads directory.
  Future<File?> downloadFile(String url, String filename) async {
    try {
      final dir = await getDownloadsDirectory();
      final savePath = p.join(dir.path, filename);

      await _dio.download(url, savePath);
      return File(savePath);
    } catch (e) {
      debugPrint('🔴 [DownloadService] Download failed: $e');
      return null;
    }
  }

  /// Saves raw bytes (e.g. image) to the internal downloads directory.
  Future<File?> saveBytes(Uint8List bytes, String filename) async {
    try {
      final dir = await getDownloadsDirectory();
      final savePath = p.join(dir.path, filename);

      final file = File(savePath);
      await file.writeAsBytes(bytes);
      return file;
    } catch (e) {
      debugPrint('🔴 [DownloadService] Save bytes failed: $e');
      return null;
    }
  }

  /// Retrieves a list of all downloaded files.
  Future<List<File>> getDownloadedFiles() async {
    try {
      final dir = await getDownloadsDirectory();
      final List<FileSystemEntity> entities = await dir.list().toList();
      
      final files = entities.whereType<File>().toList();
      
      // Sort files by last modified (newest first)
      files.sort((a, b) {
        final aStat = a.statSync();
        final bStat = b.statSync();
        return bStat.modified.compareTo(aStat.modified);
      });
      
      return files;
    } catch (e) {
      debugPrint('🔴 [DownloadService] Failed to list files: $e');
      return [];
    }
  }

  /// Deletes a file.
  Future<bool> deleteFile(File file) async {
    try {
      if (await file.exists()) {
        await file.delete();
        return true;
      }
      return false;
    } catch (e) {
      debugPrint('🔴 [DownloadService] Failed to delete file: $e');
      return false;
    }
  }
}
