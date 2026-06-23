import unittest

from bb_pr_export.renderer import render_markdown


class RendererTests(unittest.TestCase):
    def test_renders_review_table_inline_comments_and_replies(self):
        export = {
            "pr": {
                "id": 42,
                "title": "Fix null pointer",
                "state": "MERGED",
                "author": "Jane Smith",
                "source_branch": "fix/npe-payment",
                "destination_branch": "main",
                "created": "2024-11-03T12:00:00+00:00",
                "description": "Fixes the NPE.",
            },
            "reviewers": [
                {"reviewer": "Bob Jones", "decision": "approved"},
                {"reviewer": "Alice Lee", "decision": "changes_requested"},
            ],
            "comments": [
                {
                    "id": 2,
                    "parent_id": 1,
                    "author": "Jane Smith",
                    "created": "2024-11-03T15:01:00+00:00",
                    "body": "Good catch.",
                    "deleted": False,
                    "inline": True,
                    "location": {"path": "src/payment/Processor.java", "line": 87, "side": "new"},
                },
                {
                    "id": 1,
                    "parent_id": None,
                    "author": "Alice Lee",
                    "created": "2024-11-03T14:22:00+00:00",
                    "body": "This can still fail.",
                    "deleted": False,
                    "inline": True,
                    "location": {"path": "src/payment/Processor.java", "line": 87, "side": "new"},
                },
                {
                    "id": 3,
                    "parent_id": None,
                    "author": "Bob Jones",
                    "created": "2024-11-03T16:45:00+00:00",
                    "body": "LGTM overall.",
                    "deleted": False,
                    "inline": False,
                    "location": None,
                },
            ],
        }

        markdown = render_markdown(export)

        self.assertIn("| Bob Jones | ✅ Approved |", markdown)
        self.assertIn("| Alice Lee | 🔄 Changes requested |", markdown)
        self.assertIn("## Comments (3 total — 2 inline, 1 general)", markdown)
        self.assertIn("### 📄 `src/payment/Processor.java` line 87 (new)", markdown)
        self.assertIn("**Alice Lee** · 2024-11-03 14:22 UTC", markdown)
        self.assertIn("↳ **Jane Smith** · 2024-11-03 15:01 UTC", markdown)
        self.assertIn("### 💬 General", markdown)

    def test_omits_review_table_and_deleted_comments_by_default(self):
        export = {
            "pr": {
                "id": 1,
                "title": "Title",
                "state": "OPEN",
                "author": "Author",
                "source_branch": "feature",
                "destination_branch": "main",
                "created": "2024-01-01T00:00:00+00:00",
                "description": "",
            },
            "reviewers": [],
            "comments": [
                {
                    "id": 1,
                    "parent_id": None,
                    "author": "Reviewer",
                    "created": "2024-01-01T01:00:00+00:00",
                    "body": "Hidden",
                    "deleted": True,
                    "inline": False,
                    "location": None,
                }
            ],
        }

        markdown = render_markdown(export)

        self.assertNotIn("## Review outcome", markdown)
        self.assertIn("## Comments (0 total — 0 inline, 0 general)", markdown)
        self.assertNotIn("Hidden", markdown)

    def test_renders_deleted_comments_when_requested(self):
        export = {
            "pr": {
                "id": 1,
                "title": "Title",
                "state": "OPEN",
                "author": "Author",
                "source_branch": "feature",
                "destination_branch": "main",
                "created": "2024-01-01T00:00:00+00:00",
                "description": "",
            },
            "reviewers": [],
            "comments": [
                {
                    "id": 1,
                    "parent_id": None,
                    "author": "Reviewer",
                    "created": "2024-01-01T01:00:00+00:00",
                    "body": "Hidden",
                    "deleted": True,
                    "inline": False,
                    "location": None,
                }
            ],
        }

        markdown = render_markdown(export, include_deleted=True)

        self.assertIn("> ~~[deleted]~~", markdown)


if __name__ == "__main__":
    unittest.main()
