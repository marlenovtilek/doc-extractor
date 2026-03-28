import threading
import time
import unittest
import os
from unittest.mock import patch

from extractor.config.runtime import clear_runtime_settings_cache
from extractor.services import jobs as jobs_module
from extractor.services.jobs import (
    cancel_web_extraction_job,
    get_web_extraction_job,
    submit_web_extraction_job,
)


class WebJobServiceTests(unittest.TestCase):
    def setUp(self):
        jobs_module._JOBS.clear()
        clear_runtime_settings_cache()

    def tearDown(self):
        jobs_module._JOBS.clear()
        os.environ.pop("WEB_JOB_RETENTION_S", None)
        os.environ.pop("WEB_JOB_MAX_STORED", None)
        clear_runtime_settings_cache()

    @patch("extractor.services.jobs.execute_extraction_request")
    def test_submit_job_can_run_inline_and_complete(self, mock_execute):
        mock_execute.return_value = {
            "status": "success",
            "document_code": "04021",
            "result_type": "table",
            "document_schema": {"result_type": "table", "fields": [], "item_fields": []},
            "data": {"fields": {}, "items": [{"position": 1}], "count": 1},
            "model_id": "structured-parser",
            "items": [{"position": 1}],
            "count": 1,
            "metrics": {"execution_path": {"mode": "parser_first"}},
            "error": "",
        }

        job = submit_web_extraction_job(
            document_code="04021",
            ocr_draft="Invoice OCR",
            model=None,
            background=False,
        )
        snapshot = get_web_extraction_job(job["job_id"])

        self.assertEqual(snapshot["status"], "completed")
        self.assertEqual(snapshot["result"]["count"], 1)
        self.assertEqual(snapshot["result"]["model_id"], "structured-parser")

    @patch("extractor.services.jobs.execute_extraction_request")
    def test_submit_job_marks_failed_when_extraction_raises(self, mock_execute):
        mock_execute.side_effect = RuntimeError("boom")

        job = submit_web_extraction_job(
            document_code="04021",
            ocr_draft="Invoice OCR",
            model=None,
            background=False,
        )
        snapshot = get_web_extraction_job(job["job_id"])

        self.assertEqual(snapshot["status"], "failed")
        self.assertIn("boom", snapshot["error"])

    @patch("extractor.services.jobs.execute_extraction_request")
    def test_cancel_marks_running_job_as_cancelled_after_current_step(self, mock_execute):
        started = threading.Event()
        release = threading.Event()

        def slow_execute(*args, **kwargs):
            started.set()
            release.wait(timeout=2)
            return {
                "status": "success",
                "document_code": "04021",
                "result_type": "table",
                "document_schema": {"result_type": "table", "fields": [], "item_fields": []},
                "data": {"fields": {}, "items": [{"position": 1}], "count": 1},
                "model_id": "structured-parser",
                "items": [{"position": 1}],
                "count": 1,
                "metrics": {},
                "error": "",
            }

        mock_execute.side_effect = slow_execute

        job = submit_web_extraction_job(
            document_code="04021",
            ocr_draft="Invoice OCR",
            model=None,
            background=True,
        )

        self.assertTrue(started.wait(timeout=1))
        cancel_snapshot = cancel_web_extraction_job(job["job_id"])
        self.assertTrue(cancel_snapshot["cancel_requested"])
        self.assertIn(cancel_snapshot["progress"], {"cancelling", "cancelled"})

        release.set()

        for _ in range(100):
            snapshot = get_web_extraction_job(job["job_id"])
            if snapshot["status"] == "cancelled":
                break
            time.sleep(0.01)
        else:
            self.fail("background job did not reach cancelled state")

        self.assertEqual(snapshot["status"], "cancelled")
        self.assertEqual(snapshot["error"], "Cancelled by user.")

    @patch.dict(
        os.environ,
        {
            "WEB_JOB_RETENTION_S": "3600",
            "WEB_JOB_MAX_STORED": "2",
        },
        clear=False,
    )
    @patch("extractor.services.jobs.execute_extraction_request")
    def test_terminal_jobs_are_pruned_when_store_limit_is_exceeded(self, mock_execute):
        clear_runtime_settings_cache()
        mock_execute.return_value = {
            "status": "success",
            "document_code": "04021",
            "result_type": "table",
            "document_schema": {"result_type": "table", "fields": [], "item_fields": []},
            "data": {"fields": {}, "items": [{"position": 1}], "count": 1},
            "model_id": "structured-parser",
            "items": [{"position": 1}],
            "count": 1,
            "metrics": {"execution_path": {"mode": "parser_first"}},
            "error": "",
        }

        first = submit_web_extraction_job(
            document_code="04021",
            ocr_draft="Invoice OCR 1",
            background=False,
        )
        second = submit_web_extraction_job(
            document_code="04021",
            ocr_draft="Invoice OCR 2",
            background=False,
        )
        third = submit_web_extraction_job(
            document_code="04021",
            ocr_draft="Invoice OCR 3",
            background=False,
        )

        self.assertEqual(len(jobs_module._JOBS), 2)
        self.assertNotIn(first["job_id"], jobs_module._JOBS)
        self.assertIn(second["job_id"], jobs_module._JOBS)
        self.assertIn(third["job_id"], jobs_module._JOBS)
