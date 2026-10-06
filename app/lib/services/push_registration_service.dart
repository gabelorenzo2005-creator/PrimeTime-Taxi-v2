import 'dart:async';
import 'dart:io';
import 'dart:math';

import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';

/// iOS APNs registration only. Android intentionally has no push provider.
class PushRegistrationService {
  static final instance = PushRegistrationService();
  static const _channel = MethodChannel('primetime/apns');
  bool _enabled = false;
  bool _registering = false;
  Completer<void>? _finished;
  Timer? _retry;
  Future<void> start() async {
    if (!Platform.isIOS) return;
    _enabled = true;
    _channel.setMethodCallHandler((call) async {
      if (call.method == 'tokenChanged' && _enabled) await register();
    });
    await register();
  }

  Future<void> register() async {
    if (!_enabled || _registering || ApiClient.token == null) return;
    _registering = true;
    _finished = Completer<void>();
    try {
      final data = await _channel.invokeMapMethod<String, dynamic>('register');
      if (!_enabled || data == null || data['token'] == null) return;
      final prefs = await SharedPreferences.getInstance();
      var installation = prefs.getString('apns_installation');
      if (installation == null) {
        final bytes = List.generate(16, (_) => Random.secure().nextInt(256));
        bytes[6] = (bytes[6] & 15) | 64;
        bytes[8] = (bytes[8] & 63) | 128;
        final hex = bytes
            .map((b) => b.toRadixString(16).padLeft(2, '0'))
            .join();
        installation =
            '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
        await prefs.setString('apns_installation', installation);
      }
      if (!_enabled) return;
      final response = await ApiClient.request(
        'devices/',
        method: 'POST',
        body: {
          'installation_id': installation,
          'apns_token': data['token'],
          'environment': data['environment'],
          'topic': data['topic'],
        },
      );
      await prefs.setInt('apns_device_id', response['id'] as int);
      _retry?.cancel();
    } catch (_) {
      // Never print raw native tokens or transport errors.
      if (_enabled) {
        _retry?.cancel();
        _retry = Timer(
          const Duration(seconds: 30),
          () => unawaited(register()),
        );
      }
    } finally {
      _registering = false;
      _finished?.complete();
    }
  }

  Future<void> unregister() async {
    if (!Platform.isIOS) return;
    _enabled = false;
    _retry?.cancel();
    if (_registering) await _finished?.future;
    final prefs = await SharedPreferences.getInstance();
    final id = prefs.getInt('apns_device_id');
    if (id != null) {
      try {
        await ApiClient.request('devices/$id/', method: 'DELETE');
      } on ApiException catch (e) {
        if (e.status != 404) rethrow;
      }
      await prefs.remove('apns_device_id');
    }
    suspend();
  }

  void suspend() {
    _enabled = false;
    _retry?.cancel();
    _channel.setMethodCallHandler(null);
  }
}
