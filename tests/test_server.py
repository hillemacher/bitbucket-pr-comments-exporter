import unittest
from unittest.mock import patch

from bb_pr_export.server import export_pull_request


PR = {
    "id": 9178,
    "title": "Title",
    "state": "OPEN",
    "author": {"user": {"displayName": "Author"}},
    "fromRef": {"displayId": "feature"},
    "toRef": {"displayId": "main"},
}


class ServerTests(unittest.TestCase):
    @patch("bb_pr_export.server.paginate_server")
    @patch("bb_pr_export.server.fetch_json", return_value=PR)
    def test_normalizes_string_anchor_path(self, fetch_json, paginate_server):
        paginate_server.return_value = [
            {
                "createdDate": 1710000000000,
                "comment": {
                    "id": 1,
                    "text": "Check this line.",
                    "author": {"displayName": "Reviewer"},
                    "anchor": {"path": "src/file.py", "line": 12, "lineType": "ADDED"},
                },
            }
        ]

        export = export_pull_request("https://bitbucket.example", "PROJ", "repo", "9178", "token")

        self.assertEqual(
            export["comments"][0]["location"],
            {"path": "src/file.py", "line": 12, "side": "new"},
        )

    @patch("bb_pr_export.server.paginate_server")
    @patch("bb_pr_export.server.fetch_json", return_value=PR)
    def test_normalizes_object_anchor_path(self, fetch_json, paginate_server):
        paginate_server.return_value = [
            {
                "comment": {
                    "id": 1,
                    "text": "Check this line.",
                    "anchor": {
                        "path": {"toString": "src/object-path.py", "displayId": "fallback.py"},
                        "line": 7,
                        "lineType": "REMOVED",
                    },
                },
            }
        ]

        export = export_pull_request("https://bitbucket.example", "PROJ", "repo", "9178", "token")

        self.assertEqual(
            export["comments"][0]["location"],
            {"path": "src/object-path.py", "line": 7, "side": "old"},
        )


if __name__ == "__main__":
    unittest.main()
