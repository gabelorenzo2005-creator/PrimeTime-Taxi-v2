import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  const ApiException(this.message, this.status);
  final String message;
  final int status;
  @override
  String toString() => message;
}

class ApiClient {
  static const baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://192.168.1.173:8000',
  );
  static String? token;
  static Future<Map<String, dynamic>> request(
    String path, {
    String method = 'GET',
    Map<String, dynamic>? body,
  }) async {
    final headers = <String, String>{
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Token $token',
    };
    final uri = Uri.parse('$baseUrl/api/$path');
    try {
      final request = http.Request(method, uri)..headers.addAll(headers);
      if (body != null) request.body = jsonEncode(body);
      final response = await request
          .send()
          .then(http.Response.fromStream)
          .timeout(const Duration(seconds: 15));
      if (response.statusCode == 204) return {};
      Map<String, dynamic> data;
      try {
        data = jsonDecode(response.body) as Map<String, dynamic>;
      } catch (_) {
        throw ApiException(
          'The server returned an unexpected response.',
          response.statusCode,
        );
      }
      if (response.statusCode >= 400) {
        final message =
            data['error'] ??
            data['detail'] ??
            data.entries
                .map(
                  (e) =>
                      '${e.key}: ${e.value is List ? (e.value as List).join(', ') : e.value}',
                )
                .join('\n');
        throw ApiException(
          message is List ? message.join('\n') : message.toString(),
          response.statusCode,
        );
      }
      return data;
    } on TimeoutException {
      throw const ApiException(
        'The server took too long to respond. Refresh to check whether your action was saved.',
        0,
      );
    } on http.ClientException {
      throw const ApiException(
        'Cannot reach the server. Check your connection and server address.',
        0,
      );
    }
  }
}
