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
    @patch("urllib.request.urlopen")
    def test_cloud_pagination_follows_next_links(self, urlopen):
        urlopen.side_effect = [
            FakeResponse({"values": [{"id": 1}], "next": "https://next.example/page"}),
            FakeResponse({"values": [{"id": 2}]}),
        ]

        values = paginate_cloud("https://first.example/page", {"Authorization": "Bearer t"})

        self.assertEqual(values, [{"id": 1}, {"id": 2}])
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(urlopen.call_args_list[1].args[0].full_url, "https://next.example/page")

    @patch("urllib.request.urlopen")
    def test_server_pagination_uses_next_page_start(self, urlopen):
        urlopen.side_effect = [
            FakeResponse({"values": [{"id": 1}], "isLastPage": False, "nextPageStart": 25}),
            FakeResponse({"values": [{"id": 2}], "isLastPage": True}),
        ]

        values = paginate_server("https://server.example/activities?limit=25", {"Authorization": "Bearer t"})

        self.assertEqual(values, [{"id": 1}, {"id": 2}])
        self.assertEqual(urlopen.call_args_list[1].args[0].full_url, "https://server.example/activities?limit=25&start=25")

    @patch("urllib.request.urlopen")
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
    @patch("urllib.request.urlopen")
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
