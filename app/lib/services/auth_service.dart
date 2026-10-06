import 'dart:convert';

import '../models/app_user.dart';
import 'api_client.dart';
import 'session_store.dart';
import 'location_service.dart';
import 'push_registration_service.dart';

class SavedSession {
  const SavedSession(this.token, this.user, this.backend);
  final String token;
  final AppUser user;
  final String backend;
  Map<String, dynamic> toJson() => {
    'token': token,
    'user': {
      'username': user.username,
      'first_name': user.firstName,
      'last_name': user.lastName,
      'role': user.role,
      'role_display': user.roleDisplay,
      'must_change_password': user.mustChangePassword,
    },
    'backend': backend,
  };
}

class AuthService {
  static const baseUrl = ApiClient.baseUrl;
  static const sessionKey = 'session_v1';
  static const cleanupKey = 'logout_cleanup_v1';
  static SessionStore store = platformSessionStore();
  static PushTransport push = platformPushTransport();
  static DriverLocationService? tracking;
  static Future<bool>? _logout;

  Future<SavedSession?> savedSession() async {
    if (await store.read(cleanupKey) != null) return null;
    final raw = await store.read(sessionKey);
    if (raw == null) return null;
    try {
      final json = jsonDecode(raw) as Map<String, dynamic>;
      if (json['backend'] != baseUrl ||
          json['token'] is! String ||
          (json['token'] as String).isEmpty) {
        await store.remove(sessionKey);
        return null;
      }
      return SavedSession(
        json['token'] as String,
        AppUser.fromJson(Map<String, dynamic>.from(json['user'] as Map)),
        baseUrl,
      );
    } catch (_) {
      await store.remove(sessionKey);
      return null;
    }
  }

  Future<void> _save(String token, AppUser user) async {
    if (!['DRIVER', 'DISPATCHER', 'ADMIN', 'IT'].contains(user.role)) {
      throw const ApiException('Your account role is invalid.', 403);
    }
    await store.write(
      sessionKey,
      jsonEncode(SavedSession(token, user, baseUrl).toJson()),
    );
    ApiClient.token = token;
  }

  Future<AppUser> signIn({
    required String username,
    required String password,
  }) async {
    await _logout;
    if (!await finishCleanup()) {
      throw const ApiException(
        'Connect to finish signing out of the previous account before switching accounts.',
        0,
      );
    }
    ApiClient.token = null;
    final data = await ApiClient.request(
      'login/',
      method: 'POST',
      body: {'username': username, 'password': password},
    );
    final token = data['token'] as String;
    final user = AppUser.fromJson(data);
    try {
      await _save(token, user);
    } catch (_) {
      await signOut(saved: SavedSession(token, user, baseUrl));
      throw const ApiException(
        'Secure sign-in could not be saved. Please sign in again.',
        0,
      );
    }
    return user;
  }

  Future<AppUser?> restore(SavedSession saved) async {
    ApiClient.token = null;
    if (saved.backend != baseUrl) return null;
    try {
      final data = await ApiClient.request('session/', authToken: saved.token);
      final user = AppUser.fromJson(data);
      if (user.username != saved.user.username) {
        throw const ApiException('Session identity changed.', 403);
      }
      await _save(saved.token, user);
      return user;
    } on ApiException catch (e) {
      if ([401, 403].contains(e.status)) {
        await signOut(saved: saved);
        return null;
      }
      rethrow;
    }
  }

  Future<AppUser> changePassword(String current, String password) async {
    final data = await ApiClient.request(
      'password/',
      method: 'POST',
      body: {'current_password': current, 'new_password': password},
    );
    final user = AppUser.fromJson(data);
    final token = data['token'] as String;
    try {
      await _save(token, user);
    } catch (_) {
      await signOut(saved: SavedSession(token, user, baseUrl));
      throw const ApiException(
        'Password changed. Sign in again to securely save the new session.',
        0,
      );
    }
    return user;
  }

  /// Cleanup credentials are quarantined in secure storage, never restorable.
  /// Account switching is blocked until retryable remote cleanup completes.
  Future<bool> finishCleanup() async {
    final raw = await store.read(cleanupKey);
    if (raw == null) return true;
    final data = jsonDecode(raw) as Map<String, dynamic>;
    if (data['backend'] != baseUrl) return false;
    try {
      await ApiClient.request(
        'logout/',
        method: 'POST',
        authToken: data['token'] as String,
        body: {if (data['device_id'] != null) 'device_id': data['device_id']},
      );
    } on ApiException catch (e) {
      if (![401, 403].contains(e.status)) return false;
      // An invalid/revoked/deactivated credential cannot authorize operations.
      // Native APNs has already been detached; never re-use this identity.
    }
    await store.remove(sessionKey);
    await store.remove(cleanupKey);
    await push.forgetRegistration();
    return true;
  }

  Future<bool> signOut({SavedSession? saved}) {
    if (_logout != null) return _logout!;
    final task = _signOut(saved);
    _logout = task;
    return task.whenComplete(() {
      _logout = null;
    });
  }

  Future<bool> _signOut(SavedSession? saved) async {
    final token = saved?.token ?? ApiClient.token;
    ApiClient.token = null;
    try {
      await tracking?.stop();
    } catch (_) {
      /* Buffers/identity already stopped before native cancellation. */
    }
    int? device;
    try {
      device = await push.prepareLogout();
    } catch (_) {
      push.suspend();
    }
    if (token != null) {
      await store.write(
        cleanupKey,
        jsonEncode({'backend': baseUrl, 'token': token, 'device_id': device}),
      );
    }
    await store.remove(sessionKey);
    return finishCleanup();
  }
}
