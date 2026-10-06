import 'package:flutter/material.dart';

import '../../services/api_client.dart';
import '../../services/auth_service.dart';
import 'account_navigation.dart';
import 'login_screen.dart';

class SessionGate extends StatefulWidget {
  const SessionGate({super.key});
  @override
  State<SessionGate> createState() => _SessionGateState();
}

class _SessionGateState extends State<SessionGate> {
  SavedSession? _saved;
  bool _loading = true;
  bool _busy = false;
  String? _error;
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    ApiClient.token = null;
    try {
      final session = await AuthService().savedSession();
      if (mounted) {
        setState(() {
          _saved = session;
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = 'Secure session storage is unavailable. Unlock your device and retry.';
        });
      }
    }
  }

  Future<void> _choose(bool yes) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      if (yes) {
        final user = await AuthService().restore(_saved!);
        if (!mounted) return;
        if (user != null && await openAccount(context, user)) return;
      } else {
        await AuthService().signOut(saved: _saved);
      }
      if (mounted) {
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(builder: (_) => const LoginScreen()),
        );
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString();
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (_saved == null && _error == null) return const LoginScreen();
    return Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (_saved != null)
                Text('Continue as ${_saved!.user.fullName.trim()}?'),
              if (_error != null) Text(_error!),
              const SizedBox(height: 16),
              if (_saved != null)
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    FilledButton(
                      onPressed: _busy ? null : () => _choose(true),
                      child: const Text('Yes'),
                    ),
                    const SizedBox(width: 12),
                    TextButton(
                      onPressed: _busy ? null : () => _choose(false),
                      child: const Text('No'),
                    ),
                  ],
                )
              else
                TextButton(onPressed: _load, child: const Text('Retry')),
              if (_busy) const CircularProgressIndicator(),
            ],
          ),
        ),
      ),
    );
  }
}
