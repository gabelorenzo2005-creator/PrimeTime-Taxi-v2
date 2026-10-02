import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/app_user.dart';

class AuthService {
    static const String baseUrl = 'http://127.0.0.1:8000';
    Future<AppUser> signIn({
        required String username, 
        required String password,
    }) async {
        final response = await http.post(
            Uri.parse('$baseUrl/api/login/'),
            headers: {
                'Content-Type': 'application/json',
            },
            body: jsonEncode({
                'username': username, 
                'password': password,
            }),
        );

        final data = jsonDecode(response.body) as Map<String, dynamic>;
        
        if (response.statusCode != 200) {
            throw Exception(data['error'] ?? 'Unable to sign in.');
        }

        return AppUser.fromJson(data);
    }
}