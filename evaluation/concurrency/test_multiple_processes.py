
import django
import json
import multiprocessing
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connections
from django.test import Client

from apps.conversations.models import ChatMessage
from config.security import system
from mcp_client.tools import read_file


# Run one Django request in a separate process
def send_message(db_path, session, path, i, first_ready, first_done, barrier, queue):
    settings.DATABASES["default"]["NAME"] = db_path
    connections.close_all()

    client = Client()
    client.cookies[settings.SESSION_COOKIE_NAME] = session

    # Call the real MCP tool instead of the agent
    def run_mcp_read(context, history):
        user_id = history[-1].user_id
        path = history[-1].content
        before = system.get_current_actor_id()

        if i == 0:
            first_ready.set()

        # Both processes start their MCP calls together
        barrier.wait(timeout=60)

        start_time = datetime.now().astimezone().isoformat(timespec="milliseconds")
        start = time.perf_counter()

        try:
            content = read_file(path)
            outcome = "ALLOWED"
        except RuntimeError as error:
            content = str(error)
            outcome = "DENIED" if "Access denied" in content else "ERROR"

        end = time.perf_counter()
        end_time = datetime.now().astimezone().isoformat(timespec="milliseconds")

        # Let User 1 save the assistant response before User 2
        if i == 1:
            if not first_done.wait(timeout=60):
                raise TimeoutError("User 1 did not finish")

        return json.dumps({
            "user": user_id,
            "path": path,
            "before": before,
            "after": system.get_current_actor_id(),
            "outcome": outcome,
            "content": content,
            "start": start,
            "end": end,
            "start_time": start_time,
            "end_time": end_time,
            "process": os.getpid(),
            "thread": threading.get_ident(),
        })

    # Send a message through the actual Django chat view
    start = time.perf_counter()

    try:
        with patch("apps.conversations.views.run_agent", run_mcp_read):
            response = client.post("/chat/files/", {"message": path})

        queue.put((i, response.status_code, (time.perf_counter() - start) * 1000))
    finally:
        if i == 0:
            first_done.set()


class MultipleProcessesTest(unittest.TestCase):

    def setUp(self):
        # Create a temporary database shared by both processes
        self.folder = tempfile.TemporaryDirectory()
        self.original_db = settings.DATABASES["default"]["NAME"]
        self.db_path = str(Path(self.folder.name) / "test.sqlite3")

        connections.close_all()
        settings.DATABASES["default"]["NAME"] = self.db_path
        call_command("migrate", interactive=False, verbosity=0)

        self.users = []
        self.clients = []
        self.paths = []

        # Create two users with their own files and sessions
        for i in range(2):
            user = get_user_model().objects.create_user(username=f"process_user_{i + 1}")
            path = f"users/{user.pk}/parallel_{uuid4().hex}.txt"
            file = Path(settings.MCP_FILESYSTEM_ROOT) / path

            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(f"Hello from User {user.pk}")

            client = Client()
            client.force_login(user)

            self.users.append(user)
            self.clients.append(client)
            self.paths.append(path)

    def tearDown(self):
        for path in self.paths:
            (Path(settings.MCP_FILESYSTEM_ROOT) / path).unlink(missing_ok=True)

        connections.close_all()
        settings.DATABASES["default"]["NAME"] = self.original_db
        self.folder.cleanup()

    def check_reads(self, cross_user):
        ctx = multiprocessing.get_context("spawn")
        first_ready = ctx.Event()
        first_done = ctx.Event()
        barrier = ctx.Barrier(2)
        queue = ctx.Queue()

        paths = self.paths[::-1] if cross_user else self.paths
        expected = "DENIED" if cross_user else "ALLOWED"

        # Use the real Django app and replace only the agent
        processes = [
            ctx.Process(target=send_message, args=(
                self.db_path,
                self.clients[i].cookies[settings.SESSION_COOKIE_NAME].value,
                paths[i], i, first_ready, first_done, barrier, queue
            ))
            for i in range(2)
        ]

        try:
            processes[0].start()
            self.assertTrue(first_ready.wait(timeout=60))

            processes[1].start()

            for process in processes:
                process.join(timeout=90)
                self.assertEqual(process.exitcode, 0)

            responses = {}
            for _ in range(2):
                i, status, request_ms = queue.get(timeout=10)
                responses[i] = (status, request_ms)

            results = []

            for i, user in enumerate(self.users):
                status, request_ms = responses[i]
                self.assertEqual(status, 302)

                message = ChatMessage.objects.filter(user=user, context="file", role="assistant").latest("id")
                result = json.loads(message.content)
                results.append(result)

                print(f"\n========== USER {user.pk} ==========")
                print("Requested file:", result["path"])
                print("Expected:", expected)
                print("Actual:", result["outcome"])
                print("Content:", result["content"])
                print("Identity before:", result["before"])
                print("Identity after:", result["after"])
                print("Process ID:", result["process"])
                print("Thread ID:", result["thread"])
                print("MCP start:", result["start_time"])
                print("MCP end:", result["end_time"])
                print("MCP duration (ms):", round((result["end"] - result["start"]) * 1000, 2))
                print("Request duration (ms):", round(request_ms, 2))

                self.assertEqual(result["user"], user.pk)
                self.assertEqual(result["before"], str(user.pk))
                self.assertEqual(result["after"], str(user.pk))
                self.assertEqual(result["outcome"], expected)

                if cross_user:
                    self.assertIn("Access denied", result["content"])
                else:
                    self.assertEqual(result["content"], f"Hello from User {user.pk}")

            different_processes = results[0]["process"] != results[1]["process"]
            overlap = min(result["end"] for result in results) - max(result["start"] for result in results)

            print("\n========== CONCURRENCY ==========")
            print("Different processes:", different_processes)
            print("MCP overlap (ms):", round(max(overlap, 0) * 1000, 2))
            print("Concurrent MCP calls:", overlap > 0)

            self.assertTrue(different_processes)
            self.assertGreater(overlap, 0)

        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join()

    def test_own_files(self):
        print("\n" + "=" * 60)
        print("TEST: TWO PROCESSES READING THEIR OWN FILES")
        print("=" * 60, flush=True)
        self.check_reads(cross_user=False)

    def test_cross_user_files(self):
        print("\n" + "=" * 60)
        print("TEST: TWO PROCESSES READING OTHER USERS' FILES")
        print("=" * 60, flush=True)
        self.check_reads(cross_user=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
