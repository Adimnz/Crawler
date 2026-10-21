"""Long autonomous requests must retain their durable queue lease."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.storage import Database


class JobLeaseTests(unittest.TestCase):
    def test_renewal_only_extends_the_running_job_without_changing_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(directory, dsn="")
            job_id = db.enqueue("topic-research", {"topicId": "fixture"})
            self.assertFalse(db.renew_job(job_id))
            job = db.claim_job(lease_seconds=1)
            before = db.get_job(job_id)
            self.assertTrue(db.renew_job(job_id, lease_seconds=360))
            after = db.get_job(job_id)
            self.assertGreater(after["lease_until"], before["lease_until"])
            self.assertEqual(after["attempts"], job["attempts"])
            self.assertEqual(after["state"], "running")
            db.finish_job(job_id)
            self.assertFalse(db.renew_job(job_id))


if __name__ == "__main__": unittest.main()
