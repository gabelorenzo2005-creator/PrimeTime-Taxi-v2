import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:geolocator/geolocator.dart';
import 'package:permission_handler/permission_handler.dart';

import 'api_client.dart';

abstract class DriverLocationService {
  ValueNotifier<String> get status;
  Future<void> start(int shiftId, DateTime startedAt);
  Future<void> stop();
}

/// A running native location stream keeps the foreground service alive on Android.
/// Only the latest unsent genuine fix is retained, in memory, for this shift.
class NativeDriverLocationService implements DriverLocationService {
  NativeDriverLocationService({
    this.positions,
    this.permission,
    this.upload,
    this.retryInterval = const Duration(seconds: 15),
  });
  final Duration retryInterval;
  final Stream<Position> Function()? positions;
  final Future<bool> Function()? permission;
  final Future<void> Function(Map<String, dynamic>)? upload;
  @override
  final status = ValueNotifier<String>('Tracking off');
  StreamSubscription<Position>? _subscription;
  Timer? _retry;
  Map<String, dynamic>? _pending;
  int? _shift;
  DateTime? _startedAt;
  int _generation = 0;
  bool _sending = false;
  DateTime? _latestFixTime;

  bool get supported =>
      positions != null || Platform.isIOS || Platform.isAndroid;

  Future<bool> _requestPermission() async {
    if (!await Geolocator.isLocationServiceEnabled()) return false;
    if (Platform.isIOS) {
      if (!await Permission.locationWhenInUse.request().isGranted) return false;
      return await Permission.locationAlways.request().isGranted;
    }
    if (!await Permission.locationWhenInUse.request().isGranted) return false;
    return await Permission.notification.request().isGranted;
  }

  Stream<Position> _positions() {
    final LocationSettings settings = Platform.isAndroid
        ? AndroidSettings(
            accuracy: LocationAccuracy.high,
            distanceFilter: 0,
            intervalDuration: const Duration(seconds: 10),
            foregroundNotificationConfig: const ForegroundNotificationConfig(
              notificationTitle: 'PrimeTime Taxi location tracking',
              notificationText:
                  'Your location is shared while you are clocked in.',
              enableWakeLock: true,
              setOngoing: true,
            ),
          )
        : AppleSettings(
            accuracy: LocationAccuracy.high,
            distanceFilter: 0,
            activityType: ActivityType.automotiveNavigation,
            pauseLocationUpdatesAutomatically: false,
            showBackgroundLocationIndicator: true,
            allowBackgroundLocationUpdates: true,
          );
    return Geolocator.getPositionStream(locationSettings: settings);
  }

  @override
  Future<void> start(int shiftId, DateTime startedAt) async {
    if (!supported || (_shift == shiftId && _subscription != null)) return;
    await stop();
    final generation = _generation;
    status.value = 'Checking location permission';
    try {
      if (!await (permission?.call() ?? _requestPermission())) {
        if (generation == _generation) {
          status.value = 'Allow background location in Settings; Android also needs notification permission. Then retry GPS.';
        }
        return;
      }
      if (generation != _generation) return;
      _shift = shiftId;
      _startedAt = startedAt.toUtc();
      status.value = 'Waiting for a real GPS fix';
      _subscription = (positions?.call() ?? _positions()).listen(
        (fix) => _accept(fix, generation),
        onError: (_) => _streamEnded(
          generation,
          'Location unavailable. Check Settings and retry.',
        ),
        onDone: () => _streamEnded(
          generation,
          'Location service stopped. Retry tracking.',
        ),
      );
      _retry = Timer.periodic(retryInterval, (_) => unawaited(_flush()));
    } catch (_) {
      if (generation == _generation) {
        await stop();
        status.value = 'Location unavailable. Check Settings and retry.';
      }
    }
  }

  void _streamEnded(int generation, String message) {
    if (generation != _generation) return;
    final stoppedGeneration = _generation + 1;
    unawaited(
      stop().then((_) {
        if (_generation == stoppedGeneration) status.value = message;
      }),
    );
  }

  void _accept(Position p, int generation) {
    if (generation != _generation ||
        _shift == null ||
        p.isMocked ||
        !p.latitude.isFinite ||
        p.latitude.abs() > 90 ||
        !p.longitude.isFinite ||
        p.longitude.abs() > 180 ||
        !p.accuracy.isFinite ||
        p.accuracy < 0 ||
        p.timestamp.toUtc().isBefore(_startedAt!) ||
        p.timestamp.isAfter(DateTime.now().add(const Duration(seconds: 30)))) {
      return;
    }
    final timestamp = p.timestamp.toUtc().toIso8601String();
    if (_latestFixTime != null && !p.timestamp.isAfter(_latestFixTime!)) return;
    _latestFixTime = p.timestamp;
    _pending = {
      'shift_id': _shift,
      'latitude': p.latitude,
      'longitude': p.longitude,
      'accuracy': p.accuracy,
      'timestamp': timestamp,
      if (p.heading.isFinite && p.heading >= 0 && p.heading < 360)
        'heading': p.heading,
      if (p.speed.isFinite && p.speed >= 0) 'speed': p.speed,
    };
    unawaited(_flush());
  }

  Future<void> _flush() async {
    if (_sending || _pending == null || _shift == null) return;
    _sending = true;
    final generation = _generation;
    final fix = _pending!;
    try {
      if (upload != null) {
        await upload!(fix);
      } else {
        await ApiClient.request('gps/', method: 'POST', body: fix);
      }
      if (generation != _generation) return;
      if (identical(_pending, fix)) _pending = null;
      status.value = 'GPS tracking active';
    } on ApiException catch (error) {
      if (generation != _generation) return;
      if ([401, 403].contains(error.status)) {
        await stop();
        status.value = 'Tracking stopped. Sign in again.';
      } else if (error.status == 400) {
        // Includes a shift closed elsewhere: confirm it before starting again.
        await stop();
        status.value =
            'Server rejected tracking. Refresh your shift and retry.';
      } else {
        status.value = 'GPS upload pending. Retrying when connected.';
      }
    } catch (_) {
      if (generation == _generation) {
        status.value = 'GPS upload pending. Retrying when connected.';
      }
    } finally {
      _sending = false;
      if (generation == _generation &&
          _pending != null &&
          !identical(_pending, fix)) {
        unawaited(_flush());
      }
    }
  }

  @override
  Future<void> stop() async {
    _generation++;
    _shift = null;
    _pending = null;
    _latestFixTime = null;
    _retry?.cancel();
    _retry = null;
    final subscription = _subscription;
    _subscription = null;
    await subscription?.cancel();
    status.value = 'Tracking off';
  }
}
