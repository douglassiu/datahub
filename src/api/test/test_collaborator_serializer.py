from mock import patch, MagicMock

from django.test import TestCase

from psycopg2 import ProgrammingError
from core.db.manager import PermissionDenied
from ..serializer import CollaboratorSerializer


class CollaboratorSerializerTests(TestCase):
    """Test RepoSerializer methods"""

    def setUp(self):
        self.username = "delete_me_username"
        self.repo_base = "delete_me_repo_base"
        self.password = "delete_me_password"

        self.mock_manager = self.create_patch(
            'api.serializer.DataHubManager')
        self.serializer = CollaboratorSerializer(
            username=self.username, repo_base=self.repo_base)

    def create_patch(self, name):
        # helper method for creating patches
        patcher = patch(name)
        thing = patcher.start()
        self.addCleanup(patcher.stop)
        return thing

    def test_list_collaborators(self):
        expected_result = {
            'collaborators':
                [{'username': 'collab1', 'privileges': 'UC'},
                 {'username': 'collab2', 'privileges': 'U'}]
            }

        mock_list_collabs = self.mock_manager.return_value.list_collaborators
        mock_list_collabs.return_value = expected_result

        res = self.serializer.list_collaborators('repo_name')
        self.assertEqual(expected_result, res)

    def test_add_collaborator_happy_path(self):
        mock_add_collab = self.mock_manager.return_value.add_collaborator
        mock_add_collab.return_value = True

        res = self.serializer.add_collaborator('repo_name', 'collab', [])
        self.assertEqual(True, res)

    def test_add_collaborator_sad_path(self):
        mock_add_collab = self.mock_manager.return_value.add_collaborator
        mock_add_collab.side_effect = PermissionDenied

        res = self.serializer.add_collaborator('repo_name', 'collab', [])
        self.assertEqual(False, res)