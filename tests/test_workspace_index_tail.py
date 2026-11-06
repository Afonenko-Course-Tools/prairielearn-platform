"""Изменённый и нечитаемый index отвергаются штатным Git."""
import unittest
import test_workspace_recipe_seed as fixtures
from grading_job import JobError


class WorkspaceIndex(unittest.TestCase):
    def helper(self):
        helper = fixtures.RecipeSeed()
        self.addCleanup(helper.doCleanups)
        return helper

    def test_staged_content_differs_from_initial_commit(self):
        def stage(git, work):
            (work / 'notes.txt').write_bytes(b'changed\n')
            git('add', 'notes.txt')
            (work / 'notes.txt').write_bytes(b'notes\n')
        helper = self.helper()
        root, entries = helper.fixture({'notes.txt': b'notes\n'}, change=stage)
        with self.assertRaises(JobError):
            helper.proof(root, entries)

    def test_unreadable_index_is_rejected(self):
        helper = self.helper()
        root, entries = helper.fixture({'notes.txt': b'notes\n'})
        entries['work/.git/index'] = b'not a Git index'
        with self.assertRaises(JobError):
            helper.proof(root, entries)


if __name__ == '__main__':
    unittest.main()
