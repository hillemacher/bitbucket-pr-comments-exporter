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
    def test_marker_fallback_and_reply_inheritance(self, fetch_json, paginate_server):
        anchor = {
            "path": "a.py", "line": 14, "lineType": "CONTEXT", "fileType": "FROM",
            "multilineMarker": {"startLine": 10, "startLineType": "REMOVED"},
            "multilineSpan": {"srcSpanStart": 10, "srcSpanEnd": None},
        }
        paginate_server.return_value = [
            {"commentAnchor": anchor, "comment": {"id": 1, "comments": [{"id": 2}]}},
            {"comment": {"id": 3, "anchor": {
                **anchor, "multilineMarker": {"startLine": 10, "startLineType": "ADDED"},
            }}},
        ]

        comments = export_pull_request("https://bitbucket.example", "PROJ", "repo", "9178", "token")["comments"]

        legacy = {"path": "a.py", "line": 14, "side": "old"}
        ranged = {**legacy, "ranges": {"old": {"start_line": 10, "end_line": 14}}}
        self.assertEqual([comment["location"] for comment in comments], [ranged, ranged, legacy])
        self.assertEqual(comments[1]["parent_id"], 1)

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

class ThreadTests(unittest.TestCase):
    def test_nested_thread_normalization_and_rendering(self):
        from bb_pr_export.server import _normalize_comments_from_activities
        from bb_pr_export.renderer import render_markdown
        activities = [{'commentAnchor': {'path': 'src/a.py', 'line': 9, 'lineType': 'CONTEXT', 'fileType': 'FROM'},
                       'comment': {'id': 1, 'text': 'root text', 'comments': [
                           {'id': 2, 'text': 'reply text', 'comments': [{'id': 3, 'text': 'grandchild text'}]}]}},
                      {'comment': {'id': 4, 'text': 'general text'}}]
        comments = _normalize_comments_from_activities(activities)
        self.assertEqual([c['parent_id'] for c in comments], [None, 1, 2, None])
        self.assertTrue(all(c['location'] == {'path': 'src/a.py', 'line': 9, 'side': 'old'} for c in comments[:3]))
        markdown = render_markdown({'pr': {'id': 1}, 'comments': comments})
        self.assertIn('`src/a.py` line 9 (old)', markdown)
        for body in ('root text', 'reply text', 'grandchild text', 'general text'):
            self.assertEqual(markdown.count(body), 1)
        self.assertIn('3 inline, 1 general', markdown)
        self.assertLess(markdown.index('root text'), markdown.index('reply text'))
        self.assertLess(markdown.index('reply text'), markdown.index('grandchild text'))

    def test_explicit_parent_and_own_anchor_override_inheritance(self):
        from bb_pr_export.server import _normalize_comments_from_activities
        comments = _normalize_comments_from_activities([{'commentAnchor': {'path': 'a.py'}, 'comment': {
            'id': 1, 'comments': [{'id': 2, 'parent': {'id': 7}, 'anchor': {'path': 'b.py', 'lineType': 'CONTEXT', 'fileType': 'TO'}}]}}])
        self.assertEqual(comments[1]['parent_id'], 7)
        self.assertEqual(comments[1]['location'], {'path': 'b.py', 'line': None, 'side': 'new'})

    def test_duplicate_snapshots_preserve_context_and_newest_body(self):
        from bb_pr_export.server import _normalize_comments_from_activities
        nested = {'commentAnchor': {'path': 'a.py'}, 'comment': {'id': 1, 'comments': [{'id': 2, 'text': 'old', 'updatedDate': 1}]}}
        latest = {'comment': {'id': 2, 'text': 'new', 'updatedDate': 2}}
        for activities in ([nested, latest], [latest, nested]):
            comments = _normalize_comments_from_activities(activities)
            self.assertEqual(len(comments), 2)
            reply = next(c for c in comments if c['id'] == 2)
            self.assertEqual(reply['body'], 'new')
            self.assertEqual(reply['parent_id'], 1)
            self.assertEqual(reply['location']['path'], 'a.py')
        tied = _normalize_comments_from_activities([latest, {'comment': {'id': 2, 'text': 'tie', 'updatedDate': 2}}])
        self.assertEqual(tied[0]['body'], 'new')


if __name__ == "__main__":
    unittest.main()
