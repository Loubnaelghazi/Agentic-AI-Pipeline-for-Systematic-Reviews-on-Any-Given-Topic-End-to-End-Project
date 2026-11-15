"""Removing a conversation preserves research files and rejects active workers."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app
from api.jobs import JobManager
from storage import review_manager


class RemoveReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        mocked = patch.object(review_manager, "REVIEW_ROOT", self.root / "reviews")
        mocked.start()
        self.addCleanup(mocked.stop)
        self.rid, self.review = review_manager.create_review(
            "Disposable test conversation"
        )
        (self.review / "papers/source.pdf").write_bytes(b"original saved bytes")

    def test_remove_hides_review_and_preserves_original_files(self):
        with TestClient(create_app(JobManager())) as client:
            response = client.delete(f"/api/reviews/{self.rid}")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["files_preserved"])
            self.assertEqual(client.get("/api/reviews").json(), [])
            self.assertEqual(client.get(f"/api/reviews/{self.rid}").status_code, 404)
            self.assertEqual(client.delete(f"/api/reviews/{self.rid}").status_code, 404)
        backups = list((self.root / "deleted_reviews").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(
            (backups[0] / "papers/source.pdf").read_bytes(), b"original saved bytes"
        )

    def test_queued_or_running_review_cannot_be_removed(self):
        manager = JobManager()
        with TestClient(create_app(manager)) as client:
            for status in ("queued", "running"):
                manager.active[self.rid] = {"status": status}
                self.assertEqual(
                    client.delete(f"/api/reviews/{self.rid}").status_code, 409
                )
                self.assertTrue(self.review.exists())
            manager.active.clear()

    def test_cors_allows_browser_delete(self):
        with TestClient(create_app(JobManager())) as client:
            response = client.options(
                f"/api/reviews/{self.rid}",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "DELETE",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("DELETE", response.headers["access-control-allow-methods"])

    def test_archive_directory_cannot_redirect_files_outside_data_root(self):
        other = self.root / "outside"
        other.mkdir()
        (self.root / "deleted_reviews").symlink_to(other, target_is_directory=True)
        # A sibling destination has the same parent, so use a directory elsewhere.
        with tempfile.TemporaryDirectory() as outside:
            (self.root / "deleted_reviews").unlink()
            (self.root / "deleted_reviews").symlink_to(
                outside, target_is_directory=True
            )
            with self.assertRaises(ValueError):
                review_manager.remove_review(self.rid)
            self.assertTrue(self.review.exists())
