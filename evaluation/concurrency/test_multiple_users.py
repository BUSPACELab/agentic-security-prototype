
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TransactionTestCase

from apps.conversations.models import ChatMessage
from config.security import system
from mcp_client.tools import read_file


class MultipleUsersTest(TransactionTestCase):

    def setUp(self):
        self.users = []
        self.clients = []
        self.paths = []

        # Create 10 users with their own files and sessions
        for i in range(10):
            user = get_user_model().objects.create_user(username=f"parallel_user_{i + 1}")
            path = f"users/{user.pk}/parallel_{uuid4().hex}.txt"
            file = Path(settings.MCP_FILESYSTEM_ROOT) / path

            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(f"Hello from User {user.pk}")
            self.addCleanup(file.unlink, missing_ok=True)

            client = Client()
            client.force_login(user)

            self.users.append(user)
            self.clients.append(client)
            self.paths.append(path)

    # Call the real MCP tool instead of the agent
    def run_mcp_read(self, context, history):
        user_id = history[-1].user_id
        i = self.user_ids.index(user_id)
        path = history[-1].content
        before = system.get_current_actor_id()

        # Start each request after the previous one finishes its initial database work
        self.ready[i].set()

        # All users start their MCP calls together
        self.barrier.wait(timeout=60)

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

        # Save assistant responses one at a time to avoid SQLite locks
        if i > 0:
            if not self.done[i - 1].wait(timeout=90):
                raise TimeoutError("Previous user did not finish")

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
    def send_message(self, i, path):
        start = time.perf_counter()

        try:
            response = self.clients[i].post("/chat/files/", {"message": path})
            return response.status_code, (time.perf_counter() - start) * 1000
        finally:
            self.done[i].set()

    def check_reads(self, count, cross_user):
        self.user_ids = [user.pk for user in self.users[:count]]
        self.ready = [threading.Event() for _ in range(count)]
        self.done = [threading.Event() for _ in range(count)]
        self.barrier = threading.Barrier(count)

        paths = [self.paths[(i + 1) % count] if cross_user else self.paths[i] for i in range(count)]
        expected = "DENIED" if cross_user else "ALLOWED"

        # Use the real Django app and replace only the agent
        with patch("apps.conversations.views.run_agent", self.run_mcp_read):
            with ThreadPoolExecutor(max_workers=count) as executor:
                futures = []

                # Start each user after the previous user reaches the MCP stage
                for i in range(count):
                    if i > 0:
                        self.assertTrue(self.ready[i - 1].wait(timeout=60))
                    futures.append(executor.submit(self.send_message, i, paths[i]))

                responses = [future.result() for future in futures]

        results = []

        for i, user in enumerate(self.users[:count]):
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

        same_process = len({result["process"] for result in results}) == 1
        different_threads = len({result["thread"] for result in results}) == count
        overlap = min(result["end"] for result in results) - max(result["start"] for result in results)

        print("\n========== CONCURRENCY ==========")
        print("Users:", count)
        print("Same process:", same_process)
        print("Different threads:", different_threads)
        print("MCP overlap (ms):", round(max(overlap, 0) * 1000, 2))
        print("All MCP calls concurrent:", overlap > 0)

        self.assertTrue(same_process)
        self.assertTrue(different_threads)
        self.assertGreater(overlap, 0)

    def test_5_own_files(self):
        print("\n" + "=" * 60)
        print("TEST: FIVE USERS READING THEIR OWN FILES")
        print("=" * 60, flush=True)
        self.check_reads(5, cross_user=False)

    def test_5_cross_user_files(self):
        print("\n" + "=" * 60)
        print("TEST: FIVE USERS READING OTHER USERS' FILES")
        print("=" * 60, flush=True)
        self.check_reads(5, cross_user=True)

    def test_10_own_files(self):
        print("\n" + "=" * 60)
        print("TEST: TEN USERS READING THEIR OWN FILES")
        print("=" * 60, flush=True)
        self.check_reads(10, cross_user=False)

    def test_10_cross_user_files(self):
        print("\n" + "=" * 60)
        print("TEST: TEN USERS READING OTHER USERS' FILES")
        print("=" * 60, flush=True)
        self.check_reads(10, cross_user=True)
