import '../models/app_user.dart';
import 'api_client.dart';

class AuthService {
  static const baseUrl = ApiClient.baseUrl;
  Future<AppUser> signIn({
    required String username,
    required String password,
  }) async {
    ApiClient.token = null;
    final data = await ApiClient.request(
      'login/',
      method: 'POST',
      body: {'username': username, 'password': password},
    );
    ApiClient.token = data['token'] as String;
    return AppUser.fromJson(data);
  }

  Future<AppUser> changePassword(String current, String password) async {
    final data = await ApiClient.request(
      'password/',
      method: 'POST',
      body: {'current_password': current, 'new_password': password},
    );
    ApiClient.token = data['token'] as String;
    return AppUser.fromJson(data);
  }

  Future<void> signOut() async {
    await ApiClient.request('logout/', method: 'POST');
    ApiClient.token = null;
  }
}
