
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


class TwoUsersTest(TransactionTestCase):

    def setUp(self):
        self.users = []
        self.clients = []
        self.paths = []

        # Create two users with their own files and sessions
        for i in range(2):
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
        path = history[-1].content
        before = system.get_current_actor_id()

        # Start the second request after the first finishes its initial database work
        if user_id == self.users[0].pk:
            self.first_ready.set()

        # Both users start their MCP calls together
        self.barrier.wait(timeout=30)

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
        if user_id == self.users[1].pk:
            if not self.first_done.wait(timeout=30):
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
    def send_message(self, i, path):
        start = time.perf_counter()

        try:
            response = self.clients[i].post("/chat/files/", {"message": path})
            return response.status_code, (time.perf_counter() - start) * 1000
        finally:
            if i == 0:
                self.first_done.set()

    def check_reads(self, cross_user):
        self.first_ready = threading.Event()
        self.first_done = threading.Event()
        self.barrier = threading.Barrier(2)

        paths = self.paths[::-1] if cross_user else self.paths
        expected = "DENIED" if cross_user else "ALLOWED"

        # Use the real Django app and replace only the agent
        with patch("apps.conversations.views.run_agent", self.run_mcp_read):
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(self.send_message, 0, paths[0])
                self.assertTrue(self.first_ready.wait(timeout=30))

                second = executor.submit(self.send_message, 1, paths[1])
                responses = [first.result(), second.result()]

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

        same_process = results[0]["process"] == results[1]["process"]
        different_threads = results[0]["thread"] != results[1]["thread"]
        overlap = min(results[0]["end"], results[1]["end"]) - max(results[0]["start"], results[1]["start"])

        print("\n========== CONCURRENCY ==========")
        print("Same process:", same_process)
        print("Different threads:", different_threads)
        print("MCP overlap (ms):", round(max(overlap, 0) * 1000, 2))
        print("Concurrent MCP calls:", overlap > 0)

        self.assertTrue(same_process)
        self.assertTrue(different_threads)
        self.assertGreater(overlap, 0)

    def test_own_files(self):
        print("\n" + "=" * 60)
        print("TEST: TWO USERS READING THEIR OWN FILES")
        print("=" * 60, flush=True)
        self.check_reads(cross_user=False)

    def test_cross_user_files(self):
        print("\n" + "=" * 60)
        print("TEST: CROSS-USER FILES")
        print("=" * 60, flush=True)
        self.check_reads(cross_user=True)
