import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

class AuthenticatedNetworkImage extends StatefulWidget {
  final String imageUrl;
  final BoxFit fit;

  const AuthenticatedNetworkImage({
    Key? key,
    required this.imageUrl,
    this.fit = BoxFit.cover,
  }) : super(key: key);

  @override
  State<AuthenticatedNetworkImage> createState() => _AuthenticatedNetworkImageState();
}

class _AuthenticatedNetworkImageState extends State<AuthenticatedNetworkImage> {
  ImageProvider? _imageProvider;
  bool _hasError = false;
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadImage();
  }

  @override
  void didUpdateWidget(AuthenticatedNetworkImage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.imageUrl != widget.imageUrl) {
      _loadImage();
    }
  }

  Future<void> _loadImage() async {
    setState(() {
      _isLoading = true;
      _hasError = false;
    });

    try {
      final uri = Uri.parse(widget.imageUrl);
      
      Uint8List bytes;
      
      if (!uri.host.contains('supabase.co')) {
        // It's a non-Supabase URL (like a mock GCS image). Just do a standard GET request.
        debugPrint('[AuthenticatedNetworkImage] Loading non-Supabase URL: ${widget.imageUrl}');
        final request = await HttpClient().getUrl(uri);
        final response = await request.close();
        if (response.statusCode != 200) {
          throw Exception('Failed to load image: ${response.statusCode}');
        }
        bytes = await consolidateHttpClientResponseBytes(response);
      } else {
        // It's a Supabase URL. Parse the bucket and path.
        final pathSegments = uri.pathSegments;
        
        int bucketIndex = -1;
        for (int i = 0; i < pathSegments.length; i++) {
          if (pathSegments[i] == 'authenticated' || pathSegments[i] == 'public') {
            bucketIndex = i + 1;
            break;
          }
        }

        if (bucketIndex == -1 || bucketIndex >= pathSegments.length) {
          throw Exception('Could not parse bucket from URL: ${widget.imageUrl}');
        }

        final bucket = pathSegments[bucketIndex];
        final path = pathSegments.sublist(bucketIndex + 1).join('/');
        
        debugPrint('[AuthenticatedNetworkImage] Downloading from bucket: $bucket, path: $path');

        bytes = await Supabase.instance.client.storage
            .from(bucket)
            .download(path);
      }
      
      if (mounted) {
        setState(() {
          _imageProvider = MemoryImage(bytes);
          _isLoading = false;
        });
      }
    } catch (e) {
      debugPrint('🔴 AuthenticatedNetworkImage error: $e');
      if (mounted) {
        setState(() {
          _hasError = true;
          _isLoading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return const Center(
        child: CircularProgressIndicator(color: Color(0xFF00B4D8)),
      );
    }
    
    if (_hasError || _imageProvider == null) {
      return Container(
        color: Colors.grey[200],
        child: const Center(
          child: Icon(Icons.broken_image, color: Colors.grey, size: 40),
        ),
      );
    }

    return Image(
      image: _imageProvider!,
      fit: widget.fit,
    );
  }
}
