import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:location/location.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'config.dart';

void main() => runApp(const AttendanceApp());

class AttendanceApp extends StatelessWidget {
  const AttendanceApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: '학교 출석',
    theme: ThemeData(colorSchemeSeed: Colors.indigo, useMaterial3: true),
    home: const LoginPage(),
  );
}

class Api {
  static Future<String?> token() async =>
      (await SharedPreferences.getInstance()).getString('token');

  static Future<Map<String, String>> headers() async => {
    'Authorization': 'Bearer ${await token() ?? ''}',
    'Content-Type': 'application/json',
  };

  static Future<void> sendLocation(int attendanceId, LocationData p) async {
    final lat = p.latitude, lon = p.longitude;
    if (lat == null || lon == null) throw Exception('GPS 좌표를 받지 못했습니다.');
    final response = await http.post(
      Uri.parse('$apiBaseUrl/student/attendance/$attendanceId/location'),
      headers: await headers(),
      body: jsonEncode({
        'latitude': lat,
        'longitude': lon,
        'accuracy_m': p.accuracy ?? 999,
      }),
    ).timeout(const Duration(seconds: 12));
    if (response.statusCode != 200) {
      final data = jsonDecode(response.body);
      throw Exception(data['detail'] ?? '위치 전송 실패');
    }
  }
}

class LoginPage extends StatefulWidget {
  const LoginPage({super.key});
  @override State<LoginPage> createState() => _LoginPageState();
}
class _LoginPageState extends State<LoginPage> {
  final email = TextEditingController(), password = TextEditingController();
  bool busy = false;
  String message = '';

  Future<void> login() async {
    setState(() => busy = true);
    try {
      final r = await http.post(
        Uri.parse('$apiBaseUrl/auth/token'),
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: {'username': email.text.trim(), 'password': password.text},
      );
      final d = jsonDecode(r.body);
      if (r.statusCode != 200) throw Exception(d['detail'] ?? '로그인 실패');
      if (d['role'] != 'student') throw Exception('학생 계정으로 로그인해 주세요.');
      final p = await SharedPreferences.getInstance();
      await p.setString('token', d['access_token']);
      await p.setString('name', d['display_name'] ?? '학생');
      if (!mounted) return;
      Navigator.pushReplacement(context,
          MaterialPageRoute(builder: (_) => const StudentPage()));
    } catch (e) {
      setState(() => message = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  void dispose() { email.dispose(); password.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('학생 출석 앱')),
    body: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
        TextField(controller: email,
          decoration: const InputDecoration(labelText: '학교 이메일')),
        TextField(controller: password, obscureText: true,
          decoration: const InputDecoration(labelText: '비밀번호')),
        const SizedBox(height: 16),
        FilledButton(onPressed: busy ? null : login,
          child: Text(busy ? '로그인 중' : '로그인')),
        Text(message, style: const TextStyle(color: Colors.red)),
      ]),
    ),
  );
}

class StudentPage extends StatefulWidget {
  const StudentPage({super.key});
  @override State<StudentPage> createState() => _StudentPageState();
}

class _StudentPageState extends State<StudentPage> {
  final sessionId = TextEditingController();
  final Location location = Location();
  StreamSubscription<LocationData>? subscription;
  int? attendanceId;
  bool tracking = false, sending = false;
  String status = '수업 ID를 입력한 뒤 출석 체크를 해주세요.';
  String permissionInfo = '위치 권한 확인 전';

  Future<void> checkIn() async {
    try {
      final r = await http.post(
        Uri.parse('$apiBaseUrl/student/sessions/${sessionId.text}/checkin'),
        headers: await Api.headers(),
      );
      final d = jsonDecode(r.body);
      if (r.statusCode != 200) throw Exception(d['detail'] ?? '출석 실패');
      attendanceId = d['attendance_id'];
      setState(() => status = '출석 체크 완료. 위치 측정을 시작할 수 있습니다.');
    } catch (e) { setState(() => status = e.toString()); }
  }

  Future<bool> prepareLocation() async {
    bool serviceEnabled = await location.serviceEnabled();
    if (!serviceEnabled) serviceEnabled = await location.requestService();
    if (!serviceEnabled) {
      setState(() => status = '휴대전화 위치 서비스를 켜야 합니다.');
      return false;
    }

    PermissionStatus permission = await location.hasPermission();
    if (permission == PermissionStatus.denied) {
      permission = await location.requestPermission();
    }
    if (permission == PermissionStatus.denied ||
        permission == PermissionStatus.deniedForever) {
      setState(() => status =
        '위치 권한이 허용되지 않았습니다. 휴대전화 설정에서 위치 권한을 허용하세요.');
      return false;
    }

    // Enable OS-supported background location before subscribing.
    // Android 11+ may require the user to select "Allow all the time"
    // from the app's system settings after the initial permission prompt.
    final enabled = await location.enableBackgroundMode(
      enable: true,
      requireBackgroundPermission: true,
    );
    if (!enabled) {
      setState(() => status =
        '백그라운드 위치 권한을 켜지 못했습니다. 앱 설정에서 위치 권한을 "항상 허용"으로 변경한 뒤 다시 시도하세요.');
      return false;
    }

    if (Platform.isAndroid) {
      await location.changeNotificationOptions(
        channelName: '수업 출석 위치 측정',
        title: '수업 출석 위치 측정 중',
        subtitle: '현재 수업 시간에만 위치를 확인합니다.',
        description: '위치 측정이 실행 중입니다. 앱에서 측정을 종료할 수 있습니다.',
      );
    }

    await location.changeSettings(
      accuracy: LocationAccuracy.high,
      interval: 30000,
      distanceFilter: 0,
      pausesLocationUpdatesAutomatically: false,
      // Android-specific interval used while in background.
      backgroundInterval: 30000,
    );
    return true;
  }

  Future<void> startTracking() async {
    if (attendanceId == null) {
      setState(() => status = '먼저 온라인 출석 체크를 해주세요.');
      return;
    }
    if (tracking) return;
    try {
      final ready = await prepareLocation();
      if (!ready) return;

      // Send one initial fix, then subscribe to OS location updates.
      final first = await location.getLocation();
      await transmit(first);
      subscription = location.onLocationChanged.listen(
        (p) => unawaited(transmit(p)),
        onError: (Object e) {
          if (mounted) setState(() => status = 'GPS 스트림 오류: $e');
        },
      );
      setState(() {
        tracking = true;
        permissionInfo = Platform.isAndroid
          ? 'Android 백그라운드 위치 서비스 활성화'
          : 'iOS 백그라운드 위치 업데이트 활성화';
        status = '위치 측정 중입니다. 화면을 잠가도 OS가 허용하는 동안 측정이 계속됩니다.';
      });
    } catch (e) {
      setState(() => status = '측정 시작 실패: $e');
    }
  }

  Future<void> transmit(LocationData p) async {
    if (attendanceId == null || sending) return;
    sending = true;
    try {
      await Api.sendLocation(attendanceId!, p);
      await flushQueue();
      if (mounted) setState(() => status =
        '위치 전송 완료 · 정확도 ${(p.accuracy ?? 0).toStringAsFixed(0)}m');
    } catch (e) {
      await queueLocation(p);
      if (mounted) setState(() => status =
        '네트워크 전송 실패. 위치를 기기에 임시 보관했습니다. 연결 복구 후 재전송합니다.');
    } finally { sending = false; }
  }

  Future<void> queueLocation(LocationData p) async {
    final prefs = await SharedPreferences.getInstance();
    final items = prefs.getStringList('pending_location_queue') ?? [];
    items.add(jsonEncode({
      'attendance_id': attendanceId,
      'latitude': p.latitude,
      'longitude': p.longitude,
      'accuracy_m': p.accuracy ?? 999,
      'captured_at_ms': p.time,
    }));
    // Keep a bounded local queue; old data is not allowed to grow indefinitely.
    if (items.length > 500) items.removeRange(0, items.length - 500);
    await prefs.setStringList('pending_location_queue', items);
  }

  Future<void> flushQueue() async {
    final prefs = await SharedPreferences.getInstance();
    final items = prefs.getStringList('pending_location_queue') ?? [];
    if (items.isEmpty) return;
    final remaining = <String>[];
    for (final item in items) {
      try {
        final d = jsonDecode(item);
        final id = d['attendance_id'] as int?;
        if (id == null) continue;
        final r = await http.post(
          Uri.parse('$apiBaseUrl/student/attendance/$id/location'),
          headers: await Api.headers(),
          body: jsonEncode({
            'latitude': d['latitude'],
            'longitude': d['longitude'],
            'accuracy_m': d['accuracy_m'],
          }),
        ).timeout(const Duration(seconds: 8));
        if (r.statusCode != 200) remaining.add(item);
      } catch (_) { remaining.add(item); }
    }
    await prefs.setStringList('pending_location_queue', remaining);
  }

  Future<void> stopTracking() async {
    await subscription?.cancel();
    subscription = null;
    await location.enableBackgroundMode(enable: false);
    if (mounted) setState(() {
      tracking = false;
      status = '위치 측정을 종료했습니다.';
      permissionInfo = '측정 중지';
    });
  }

  @override
  void dispose() {
    subscription?.cancel();
    sessionId.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('학생 출석')),
    body: Padding(
      padding: const EdgeInsets.all(20),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        const Text('수업 ID', style: TextStyle(fontWeight: FontWeight.bold)),
        TextField(controller: sessionId,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(hintText: '관리자가 안내한 수업 ID')),
        const SizedBox(height: 8),
        FilledButton(onPressed: checkIn,
          child: const Text('온라인 출석 체크')),
        const SizedBox(height: 12),
        FilledButton(onPressed: tracking ? null : startTracking,
          child: const Text('백그라운드 위치 측정 시작')),
        OutlinedButton(onPressed: tracking ? stopTracking : null,
          child: const Text('측정 종료')),
        const SizedBox(height: 18),
        Card(child: Padding(padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(status),
            const SizedBox(height: 8),
            Text(permissionInfo, style: Theme.of(context).textTheme.bodySmall),
          ]))),
        const Spacer(),
        const Text(
          '위치 측정은 수업 출석 목적과 수업 시간에 한정됩니다. Android에서는 지속 알림이 표시되고, iPhone에서는 시스템 위치 표시가 나타날 수 있습니다. 앱 강제 종료·재부팅·권한 변경·OS 절전 정책에 따라 측정이 중단될 수 있습니다. 실제 운영 전 기기별 검증이 필요합니다.',
          style: TextStyle(fontSize: 12, color: Colors.black54),
        ),
      ]),
    ),
  );
}
