"""Offline workstation startup readiness and exact-owner cleanup."""
import copy
import io
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

import test_shared_runtime as fixtures

runtime = fixtures.runtime
CONTAINER = 'c' * 64


class WebReadiness(unittest.TestCase):
    def setUp(self):
        self.c = fixtures.contract()
        self.c.update(mode='web', port=4096)
        self.instance = dict(fixtures.instance(self.c), Id=CONTAINER, State={'Running': True})
        self.process = Mock()
        self.process.poll.return_value = None
        self.process.wait.return_value = 23

    def test_ready_inspects_owned_container_and_reports_loopback(self):
        with patch.object(runtime, 'web_instance', return_value=self.instance, create=True) as inspect, \
                patch.object(runtime, 'web_ready', create=True) as ready, patch('sys.stderr', new_callable=io.StringIO) as output:
            runtime.wait_web(self.c, self.process)
        self.assertEqual(inspect.call_count, 2)
        ready.assert_called_once_with(self.c)
        self.assertIn('http://127.0.0.1:4096', output.getvalue())

    def test_timeout_or_early_exit_never_reports_ready(self):
        for exited in (None, 0, 17):
            self.process.poll.return_value = exited
            with patch.object(runtime, 'web_instance', create=True) as inspect, \
                    patch('sys.stderr', new_callable=io.StringIO) as output, self.assertRaises(ValueError):
                runtime.wait_web(self.c, self.process, timeout=0)
            inspect.assert_not_called()
            self.assertEqual(output.getvalue(), '')

    def test_early_process_exit_is_immediate_before_inspect(self):
        for status in (0, 17):
            self.process.poll.return_value = status
            with patch.object(runtime, 'web_instance') as inspect, self.assertRaisesRegex(ValueError, 'exited'):
                runtime.wait_web(self.c, self.process)
            inspect.assert_not_called()

    def test_creation_delay_and_stopped_container_retry(self):
        stopped = dict(self.instance, State={'Running': False})
        with patch.object(runtime, 'web_instance', side_effect=[subprocess.CalledProcessError(1, []), stopped,
                                                               self.instance, self.instance]), \
                patch.object(runtime, 'web_ready') as ready, patch.object(runtime.time, 'sleep') as sleep, \
                patch('sys.stderr', new_callable=io.StringIO):
            runtime.wait_web(self.c, self.process)
        self.assertEqual(sleep.call_count, 2)
        ready.assert_called_once()

    def test_late_health_response_cannot_report_ready_after_deadline(self):
        with patch.object(runtime.time, 'monotonic', side_effect=[0, 0, 61]), \
                patch.object(runtime, 'web_instance', return_value=self.instance), patch.object(runtime, 'web_ready'), \
                patch('sys.stderr', new_callable=io.StringIO) as output, self.assertRaisesRegex(ValueError, 'timed out'):
            runtime.wait_web(self.c, self.process)
        self.assertEqual(output.getvalue(), '')

    def test_http_unavailable_retries_but_foreign_contract_does_not(self):
        with patch.object(runtime, 'web_instance', return_value=self.instance, create=True), \
                patch.object(runtime, 'web_ready', side_effect=[OSError('starting'), None], create=True) as ready, \
                patch.object(runtime.time, 'sleep'), patch('sys.stderr', new_callable=io.StringIO):
            runtime.wait_web(self.c, self.process)
        self.assertEqual(ready.call_count, 2)
        with patch.object(runtime, 'web_instance', side_effect=ValueError('foreign'), create=True), \
                patch.object(runtime, 'web_ready', create=True) as ready, self.assertRaisesRegex(ValueError, 'foreign'):
            runtime.wait_web(self.c, self.process)
        ready.assert_not_called()

    def test_readiness_requires_same_instance_after_http(self):
        changed = dict(self.instance, Id='d' * 64)
        with patch.object(runtime, 'web_instance', side_effect=[self.instance, changed], create=True), \
                patch.object(runtime, 'web_ready', create=True), self.assertRaises(ValueError):
            runtime.wait_web(self.c, self.process)

    def test_health_semantics_and_t3_unauthenticated_gates(self):
        for harness, responses in [('opencode', [(200, b''), (200, b'{"healthy":true}')]),
                                   ('pi', [(200, b''), (200, b'[]')]),
                                   ('t3', [(200, b''), (401, b''), (401, b'')])]:
            self.c['harness'] = harness
            with patch.object(runtime, 'web_request', side_effect=responses, create=True):
                runtime.web_ready(self.c)
        for responses in ([(302, b'')], [(200, b''), (200, b'')],
                          [(200, b''), (401, b''), (101, b'')]):
            with patch.object(runtime, 'web_request', side_effect=responses, create=True), self.assertRaises(ValueError):
                runtime.web_ready(self.c)
        self.c['harness'] = 'opencode'
        with patch.object(runtime, 'web_request', side_effect=[(200, b''), (200, b'{"healthy":false}')], create=True), self.assertRaises(ValueError):
            runtime.web_ready(self.c)

    def test_http_is_bounded_direct_loopback_without_proxy_or_redirect(self):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 302
        response.read.return_value = b'redirect'
        with patch.object(runtime.http.client, 'HTTPConnection', return_value=connection) as connect:
            self.assertEqual(runtime.web_request(self.c, '/'), (302, b'redirect'))
        connect.assert_called_once_with('127.0.0.1', 4096, timeout=2)
        self.assertEqual(response.read.call_args.args, (1024 * 1024 + 1,))
        connection.close.assert_called_once()

    def test_oversized_http_response_refused_and_connection_closed(self):
        connection = Mock()
        connection.getresponse.return_value.read.return_value = b'x' * (1024 * 1024 + 1)
        with patch.object(runtime.http.client, 'HTTPConnection', return_value=connection), self.assertRaises(ValueError):
            runtime.web_request(self.c, '/')
        connection.close.assert_called_once()

    def test_inspect_rejects_foreign_container_before_mutation(self):
        changed = copy.deepcopy(self.instance)
        changed['HostConfig']['Privileged'] = True
        with patch.object(runtime.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps([changed]))) as run, self.assertRaises(ValueError):
            runtime.web_instance(self.c)
        self.assertEqual(run.call_count, 1)
        self.assertIn('inspect', run.call_args.args[0])

    def test_failed_start_stops_only_validated_exact_id_and_reaps_client(self):
        with patch.object(runtime, 'wait_web', side_effect=ValueError('unhealthy'), create=True), \
                patch.object(runtime, 'web_instance', return_value=self.instance, create=True), \
                patch.object(runtime.subprocess, 'run') as run, self.assertRaisesRegex(ValueError, 'unhealthy'):
            runtime.supervise_web(self.c, self.process)
        self.assertEqual(run.call_args.args[0][-4:], ['stop', '--time', '10', CONTAINER])
        self.process.kill.assert_called_once()
        self.process.terminate.assert_not_called()
        self.process.wait.assert_called_once_with(timeout=15)

    def test_failed_cleanup_preserves_unknown_container_and_reaps_client(self):
        with patch.object(runtime, 'wait_web', side_effect=ValueError('unhealthy'), create=True), \
                patch.object(runtime, 'web_instance', side_effect=ValueError('foreign'), create=True), \
                patch.object(runtime.subprocess, 'run') as run, self.assertRaisesRegex(ValueError, 'foreign'):
            runtime.supervise_web(self.c, self.process)
        run.assert_not_called()
        self.process.kill.assert_called_once()
        self.process.terminate.assert_not_called()

    def test_success_preserves_foreground_exit_without_stop(self):
        with patch.object(runtime, 'wait_web', create=True), patch.object(runtime.subprocess, 'run') as run:
            self.assertEqual(runtime.supervise_web(self.c, self.process), 23)
        run.assert_not_called()
        self.process.terminate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
