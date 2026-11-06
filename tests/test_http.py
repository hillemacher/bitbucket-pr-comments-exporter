import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from bb_pr_export.http import AuthError, paginate_cloud, paginate_server


class FakeResponse:
    def __init__(self, payload):
        self.body = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size=-1):
        return self.body.read(size)


class HttpTests(unittest.TestCase):
    @patch("urllib.request.OpenerDirector.open")
    def test_cloud_pagination_follows_next_links(self, urlopen):
        urlopen.side_effect = [
            FakeResponse({"values": [{"id": 1}], "next": "https://first.example/next"}),
            FakeResponse({"values": [{"id": 2}]}),
        ]

        values = paginate_cloud("https://first.example/page", {"Authorization": "Bearer t"})

        self.assertEqual(values, [{"id": 1}, {"id": 2}])
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(urlopen.call_args_list[1].args[0].full_url, "https://first.example/next")

    @patch("urllib.request.OpenerDirector.open")
    def test_server_pagination_uses_next_page_start(self, urlopen):
        urlopen.side_effect = [
            FakeResponse({"values": [{"id": 1}], "isLastPage": False, "nextPageStart": 25}),
            FakeResponse({"values": [{"id": 2}], "isLastPage": True}),
        ]

        values = paginate_server("https://server.example/activities?limit=25", {"Authorization": "Bearer t"})

        self.assertEqual(values, [{"id": 1}, {"id": 2}])
        self.assertEqual(urlopen.call_args_list[1].args[0].full_url, "https://server.example/activities?limit=25&start=25")

    @patch("urllib.request.OpenerDirector.open")
    def test_401_raises_auth_error(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            "https://first.example/page",
            401,
            "Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"error": {"message": "bad token"}}'),
        )

        with self.assertRaises(AuthError):
            paginate_cloud("https://first.example/page", {"Authorization": "Bearer t"})

    @patch("time.sleep")
    @patch("urllib.request.OpenerDirector.open")
    def test_transient_5xx_retries_once(self, urlopen, sleep):
        urlopen.side_effect = [
            urllib.error.HTTPError(
                "https://first.example/page",
                502,
                "Bad Gateway",
                hdrs=None,
                fp=io.BytesIO(b"temporarily unavailable"),
            ),
            FakeResponse({"values": [{"id": 1}]}),
        ]

        values = paginate_cloud("https://first.example/page", {"Authorization": "Bearer t"})

        self.assertEqual(values, [{"id": 1}])
        sleep.assert_called_once_with(2.0)

class SafetyTests(unittest.TestCase):
    def test_redirects_block_other_origins_before_request(self):
        import urllib.request
        from bb_pr_export.http import BitbucketExportError, _SameOriginRedirectHandler
        handler = _SameOriginRedirectHandler()
        request = urllib.request.Request('https://api.example/a', headers={'Authorization': 'Bearer dummy'})
        for code in (301, 302, 303, 307, 308):
            for target in ('https://other.example/a', 'http://api.example/a', 'https://api.example:444/a'):
                with self.subTest(code=code, target=target), self.assertRaises(BitbucketExportError):
                    handler.redirect_request(request, None, code, 'Redirect', {}, target)
        redirected = handler.redirect_request(request, None, 302, 'Redirect', {}, 'https://API.example:443/b')
        self.assertEqual(redirected.get_header('Authorization'), 'Bearer dummy')

    @patch('urllib.request.OpenerDirector.open')
    def test_cross_origin_pagination_never_requests_destination(self, open_request):
        from bb_pr_export.http import BitbucketExportError
        open_request.return_value = FakeResponse({'values': [], 'next': 'https://other.example/page'})
        with self.assertRaises(BitbucketExportError):
            paginate_cloud('https://api.example/page', {'Authorization': 'Bearer dummy'})
        self.assertEqual(open_request.call_count, 1)

    @patch('urllib.request.OpenerDirector.open')
    def test_invalid_responses_and_network_failures(self, open_request):
        from bb_pr_export.http import BitbucketExportError, NetworkError, fetch_json
        for body in (b'', b'<html>private response</html>', b'\xff'):
            open_request.return_value = io.BytesIO(body)
            with self.subTest(body=body), self.assertRaises(BitbucketExportError) as raised:
                fetch_json('https://api.example/pr')
            self.assertNotIn('private response', str(raised.exception))
        for error in (TimeoutError('timed out'), ConnectionResetError('reset')):
            open_request.side_effect = error
            with self.assertRaises(NetworkError):
                fetch_json('https://api.example/pr')
        self.assertEqual(open_request.call_count, 5)
        self.assertTrue(all(call.kwargs['timeout'] == 30 for call in open_request.call_args_list))

    @patch('time.sleep')
    @patch('urllib.request.OpenerDirector.open')
    def test_second_5xx_is_not_retried(self, open_request, sleep):
        from bb_pr_export.http import TransientHttpError, fetch_json
        open_request.side_effect = [urllib.error.HTTPError('https://api.example/pr', 503, 'Unavailable', {}, io.BytesIO()) for _ in range(2)]
        with self.assertRaises(TransientHttpError):
            fetch_json('https://api.example/pr')
        self.assertEqual(open_request.call_count, 2)
        sleep.assert_called_once()

    @patch('urllib.request.OpenerDirector.open')
    def test_404(self, open_request):
        from bb_pr_export.http import NotFoundError, fetch_json
        open_request.side_effect = urllib.error.HTTPError('https://api.example/pr', 404, 'Missing', {}, io.BytesIO())
        with self.assertRaises(NotFoundError):
            fetch_json('https://api.example/pr')

    def test_non_object_pr_responses(self):
        from bb_pr_export import cloud, server
        from bb_pr_export.http import BitbucketExportError
        for module, args in ((cloud, ('w', 'r', '1', 'dummy')), (server, ('https://api.example', 'P', 'r', '1', 'dummy'))):
            with patch.object(module, 'fetch_json', return_value=[]), self.assertRaises(BitbucketExportError):
                module.export_pull_request(*args)


class RedirectTransportTests(unittest.TestCase):
    def test_opener_rejects_destinations_before_transport(self):
        import email.message
        import urllib.request
        import urllib.response
        from bb_pr_export.http import BitbucketExportError, fetch_json
        build_opener = urllib.request.build_opener
        for target in ('https://other.example/end', 'http://api.example/end', 'https://api.example:444/end', 'https://api.example:0/end', 'https://api.example/end'):
            seen = []

            class Transport(urllib.request.HTTPSHandler):
                def https_open(self, request):
                    seen.append(request)
                    headers = email.message.Message()
                    redirected = request.full_url.endswith('/start')
                    if redirected:
                        headers['Location'] = target
                    response = urllib.response.addinfourl(io.BytesIO(b'{}'), headers, request.full_url, 302 if redirected else 200)
                    response.msg = 'Found' if redirected else 'OK'
                    return response

            with self.subTest(target=target), patch('urllib.request.build_opener', side_effect=lambda *handlers: build_opener(Transport(), *handlers)):
                if target == 'https://api.example/end':
                    self.assertEqual(fetch_json('https://api.example/start', {'Authorization': 'Bearer dummy'}), {})
                    self.assertEqual(len(seen), 2)
                    self.assertEqual(seen[1].get_header('Authorization'), 'Bearer dummy')
                else:
                    with self.assertRaises(BitbucketExportError):
                        fetch_json('https://api.example/start', {'Authorization': 'Bearer dummy'})
                    self.assertEqual(len(seen), 1)

    @patch('urllib.request.OpenerDirector.open')
    def test_non_json_http_error_does_not_print_body(self, open_request):
        from bb_pr_export.http import HttpError, fetch_json
        open_request.side_effect = urllib.error.HTTPError('https://api.example/pr', 400, 'Bad request', {}, io.BytesIO(b'private response'))
        with self.assertRaises(HttpError) as raised:
            fetch_json('https://api.example/pr')
        self.assertNotIn('private response', str(raised.exception))


if __name__ == "__main__":
    unittest.main()


class CredentialTransportTests(unittest.TestCase):
    @patch('urllib.request.OpenerDirector.open')
    def test_http_authentication_fails_before_transport(self, opener):
        from bb_pr_export.http import BitbucketExportError, fetch_json
        for headers in ({'Authorization': 'Bearer fixture'}, {'authorization': 'Basic Zml4dHVyZQ=='}):
            with self.subTest(headers=headers), self.assertRaisesRegex(BitbucketExportError, 'HTTPS'):
                fetch_json('http://bb.example/api', headers)
        opener.assert_not_called()


class ExportLimitTests(unittest.TestCase):
    def test_limit_configuration_is_strict(self):
        from bb_pr_export.limits import limits_from_config
        from bb_pr_export.http import BitbucketExportError
        for table in ([], {'unknown': 1}, {'max_pages': True}, {'max_pages': 1.5},
                      {'timeout_seconds': float('nan')}, {'max_response_bytes': 0}):
            with self.subTest(table=table), self.assertRaises(BitbucketExportError):
                limits_from_config({'limits': table})

    @patch('urllib.request.OpenerDirector.open')
    def test_per_response_and_total_limits_include_error_bodies(self, opener):
        from bb_pr_export.http import BitbucketExportError, fetch_json
        from bb_pr_export.limits import Limits, export_budget
        opener.return_value = io.BytesIO(b'{}' * 10)
        with export_budget(Limits(max_response_bytes=10)), self.assertRaisesRegex(BitbucketExportError, 'size limit'):
            fetch_json('https://api.example')
        opener.side_effect = [io.BytesIO(b'{}'), io.BytesIO(b'{}')]
        with export_budget(Limits(max_total_bytes=3)):
            self.assertEqual(fetch_json('https://api.example'), {})
            with self.assertRaisesRegex(BitbucketExportError, 'size limit'):
                fetch_json('https://api.example')
        opener.side_effect = urllib.error.HTTPError('https://api.example', 400, 'Bad request', {}, io.BytesIO(b'x'*11))
        with export_budget(Limits(max_response_bytes=10)), self.assertRaisesRegex(BitbucketExportError, 'size limit'):
            fetch_json('https://api.example')

    @patch('bb_pr_export.http.fetch_json')
    def test_cyclic_and_excessive_pagination_stops(self, fetch):
        from bb_pr_export.http import BitbucketExportError
        from bb_pr_export.limits import Limits, export_budget
        fetch.return_value = {'values': [], 'next': 'https://api.example/page'}
        with self.assertRaisesRegex(BitbucketExportError, 'Repeated'):
            paginate_cloud('https://api.example/page', {})
        self.assertEqual(fetch.call_count, 1)
        fetch.reset_mock()
        fetch.return_value = {'values': [], 'isLastPage': False, 'nextPageStart': 1}
        with self.assertRaisesRegex(BitbucketExportError, 'Repeated'):
            paginate_server('https://api.example/page', {})
        self.assertEqual(fetch.call_count, 2)
        fetch.reset_mock()
        fetch.return_value = {'values': [], 'next': '?page=2'}
        with export_budget(Limits(max_pages=1)), self.assertRaisesRegex(BitbucketExportError, 'pagination limit'):
            paginate_cloud('https://api.example/page', {})
        self.assertEqual(fetch.call_count, 1)

    @patch('urllib.request.OpenerDirector.open')
    def test_expired_deadline_never_opens_transport(self, opener):
        from bb_pr_export.http import BitbucketExportError, fetch_json
        from bb_pr_export.limits import export_budget
        with patch('bb_pr_export.limits.time.monotonic', return_value=0):
            with self.assertRaisesRegex(BitbucketExportError, 'deadline'), export_budget():
                with patch('bb_pr_export.limits.time.monotonic', return_value=91):
                    fetch_json('https://api.example')
        opener.assert_not_called()

    @patch('urllib.request.OpenerDirector.open')
    def test_trickling_reads_recheck_deadline(self, opener):
        from bb_pr_export.http import BitbucketExportError, fetch_json
        from bb_pr_export.limits import export_budget
        clock = [0]
        class Response(io.BytesIO):
            def read1(self, size):
                clock[0] += 50
                return b' '
        opener.return_value = Response()
        with patch('bb_pr_export.limits.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(BitbucketExportError, 'deadline'), export_budget():
                fetch_json('https://api.example')
