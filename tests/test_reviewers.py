"""Assignment data is independent of decisions and comment activity."""
import json
import unittest
from unittest.mock import patch

from bb_pr_export import cloud, server
from bb_pr_export.renderer import render_json


class ReviewerAssignmentTests(unittest.TestCase):
    def export(self, provider, pr):
        module = server if provider == 'server' else cloud
        pagination = 'paginate_server' if provider == 'server' else 'paginate_cloud'
        args = ('https://bb.example', 'P', 'r', '42', 'token') if provider == 'server' else ('w', 'r', '42', 'token')
        with patch.object(module, 'fetch_json', return_value={'id': 42, **pr}), \
                patch.object(module, pagination, return_value=[]):
            return module.export_pull_request(*args)

    def test_assignment_without_comments_or_decisions(self):
        for provider, reviewer in (
            ('server', {'user': {'displayName': 'Assigned'}, 'status': 'UNAPPROVED'}),
            ('cloud', {'display_name': 'Assigned'}),
        ):
            with self.subTest(provider=provider):
                result = self.export(provider, {'reviewers': [reviewer]})
                self.assertEqual(result['assigned_reviewers'], [{'reviewer': 'Assigned'}])
                self.assertEqual(result['reviewers'], [])
                self.assertEqual(result['comments'], [])
                self.assertEqual(json.loads(render_json(result))['assigned_reviewers'], result['assigned_reviewers'])

    def test_empty_and_unknown_assignments(self):
        for provider in ('server', 'cloud'):
            for pr, expected in (({}, None), ({'reviewers': None}, None), ({'reviewers': []}, [])):
                with self.subTest(provider=provider, pr=pr):
                    result = self.export(provider, pr)
                    self.assertEqual(result['assigned_reviewers'], expected)
                    self.assertEqual(json.loads(render_json(result))['assigned_reviewers'], expected)

    def test_server_mixed_statuses_preserve_assignment_order(self):
        statuses = [('Waiting', 'UNAPPROVED'), ('Approved', 'APPROVED'), ('Changes', 'NEEDS_WORK'), ('Unknown', None)]
        result = self.export('server', {'reviewers': [
            {'user': {'displayName': name}, 'status': status} for name, status in statuses]})
        self.assertEqual(result['assigned_reviewers'], [{'reviewer': name} for name, _ in statuses])
        self.assertEqual(result['reviewers'], [
            {'reviewer': 'Approved', 'decision': 'approved'},
            {'reviewer': 'Changes', 'decision': 'needs_work'}])

    def test_cloud_participant_decisions_do_not_imply_assignment(self):
        result = self.export('cloud', {
            'reviewers': [{'display_name': 'Waiting'}, {'display_name': 'Assigned approver'}],
            'participants': [
                {'user': {'display_name': 'Assigned approver'}, 'approved': True},
                {'user': {'display_name': 'Unassigned approver'}, 'approved': True}]})
        self.assertEqual(result['assigned_reviewers'], [
            {'reviewer': 'Waiting'}, {'reviewer': 'Assigned approver'}])
        self.assertEqual(result['reviewers'], [
            {'reviewer': 'Assigned approver', 'decision': 'approved'},
            {'reviewer': 'Unassigned approver', 'decision': 'approved'}])
