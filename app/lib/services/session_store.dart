import 'dart:io';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

abstract class SessionStore {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
  Future<void> remove(String key);
}

/// Mobile credentials are never written to preferences or application files.
class SecureSessionStore implements SessionStore {
  final _storage = const FlutterSecureStorage(
    aOptions: AndroidOptions(
      storageNamespace: 'primetime_v2_session',
      resetOnError: false,
    ),
    iOptions: IOSOptions(
      accountName: 'primetime.v2.session',
      accessibility: KeychainAccessibility.first_unlock_this_device,
      synchronizable: false,
    ),
  );
  @override
  Future<String?> read(String key) => _storage.read(key: key);
  @override
  Future<void> write(String key, String value) =>
      _storage.write(key: key, value: value);
  @override
  Future<void> remove(String key) => _storage.delete(key: key);
}

/// Desktop development/tests have no persistent credential fallback.
class MemorySessionStore implements SessionStore {
  final values = <String, String>{};
  @override
  Future<String?> read(String key) async => values[key];
  @override
  Future<void> write(String key, String value) async {
    values[key] = value;
  }

  @override
  Future<void> remove(String key) async {
    values.remove(key);
  }
}

SessionStore platformSessionStore() => Platform.isIOS || Platform.isAndroid
    ? SecureSessionStore()
    : MemorySessionStore();
