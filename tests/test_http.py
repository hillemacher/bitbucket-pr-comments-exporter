import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from bb_pr_export.http import AuthError, paginate_cloud, paginate_server


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


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


if __name__ == "__main__":
    unittest.main()

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
