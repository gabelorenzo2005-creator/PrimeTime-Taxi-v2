import 'dart:async';

import 'package:app/services/api_client.dart';
import 'package:app/services/location_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:geolocator/geolocator.dart';

Position fix(DateTime timestamp, {bool mocked = false}) => Position(
  latitude: 40,
  longitude: -73,
  timestamp: timestamp,
  accuracy: 5,
  altitude: 0,
  altitudeAccuracy: 0,
  heading: 180,
  headingAccuracy: 1,
  speed: 2,
  speedAccuracy: 1,
  isMocked: mocked,
);
void main() {
  test('permission denial never subscribes or uploads', () async {
    var subscribed = false;
    final service = NativeDriverLocationService(
      permission: () async => false,
      positions: () {
        subscribed = true;
        return const Stream.empty();
      },
      upload: (_) async => fail('must not upload'),
    );
    await service.start(1, DateTime.now());
    expect(subscribed, false);
    expect(service.status.value, contains('permission'));
    await service.stop();
  });

  test(
    'only genuine on-shift fixes upload and stop cancels subscription',
    () async {
      final stream = StreamController<Position>.broadcast(sync: true);
      final uploads = <Map<String, dynamic>>[];
      final start = DateTime.now().toUtc().subtract(const Duration(minutes: 1));
      final service = NativeDriverLocationService(
        retryInterval: const Duration(milliseconds: 20),
        permission: () async => true,
        positions: () => stream.stream,
        upload: (p) async => uploads.add(p),
      );
      await service.start(9, start);
      stream.add(fix(start.subtract(const Duration(seconds: 1))));
      stream.add(fix(DateTime.now(), mocked: true));
      final captured = DateTime.now().toUtc();
      stream.add(fix(captured));
      await Future<void>.delayed(Duration.zero);
      expect(uploads, hasLength(1));
      expect(uploads.single['shift_id'], 9);
      expect(uploads.single['timestamp'], captured.toIso8601String());
      expect(uploads.single['heading'], 180);
      await service.stop();
      stream.add(fix(DateTime.now()));
      await Future<void>.delayed(Duration.zero);
      expect(uploads, hasLength(1));
      expect(stream.hasListener, false);
      await stream.close();
    },
  );

  test(
    'transient failures retry original captured fix without new coordinates',
    () async {
      final stream = StreamController<Position>.broadcast(sync: true);
      final uploads = <Map<String, dynamic>>[];
      final retried = Completer<void>();
      final service = NativeDriverLocationService(
        retryInterval: const Duration(milliseconds: 20),
        permission: () async => true,
        positions: () => stream.stream,
        upload: (p) async {
          uploads.add(Map.from(p));
          if (uploads.length == 1) throw const ApiException('Offline', 0);
          retried.complete();
        },
      );
      await service.start(
        1,
        DateTime.now().subtract(const Duration(minutes: 1)),
      );
      stream.add(fix(DateTime.now()));
      await Future<void>.delayed(Duration.zero);
      expect(service.status.value, contains('pending'));
      await retried.future.timeout(const Duration(seconds: 2));
      await Future<void>.delayed(Duration.zero);
      expect(uploads, hasLength(2));
      expect(uploads[0], uploads[1]);
      expect(service.status.value, 'GPS tracking active');
      await service.stop();
      await stream.close();
    },
  );

  test(
    'authentication rejection stops tracking and discards pending fix',
    () async {
      final stream = StreamController<Position>.broadcast(sync: true);
      final service = NativeDriverLocationService(
        retryInterval: const Duration(milliseconds: 20),
        permission: () async => true,
        positions: () => stream.stream,
        upload: (_) async => throw const ApiException('Expired', 401),
      );
      await service.start(
        1,
        DateTime.now().subtract(const Duration(minutes: 1)),
      );
      stream.add(fix(DateTime.now()));
      await Future<void>.delayed(Duration.zero);
      expect(stream.hasListener, false);
      expect(service.status.value, contains('Sign in again'));
      await service.stop();
      await stream.close();
    },
  );
}
