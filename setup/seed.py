
"""Populate one application version with evaluation data"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from setup.dataset import FILES, PASSWORD, USERS


ROOT = Path(__file__).resolve().parent.parent
CREATED_AT = datetime(2026, 11, 1, tzinfo=timezone.utc)


def main():
    """Create the same users and files in one workspace"""

    # Load the selected application's Django configuration
    version = sys.argv[1]
    workspace = ROOT / "workspaces" / version
    sys.path.insert(0, str(workspace))
    os.chdir(workspace)
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

    import django
    django.setup()

    from django.contrib.auth import get_user_model
    from django.core.files.base import ContentFile
    from apps.files.models import UploadedFile

    User = get_user_model()

    # Require an empty database before inserting test data
    if User.objects.exists() or UploadedFile.objects.exists():
        raise RuntimeError("Database is not empty, remove existing data first")

    # Create each user and their four files
    for username, email in USERS.items():
        user = User.objects.create_user(username=username, email=email, first_name=username.title(), password=PASSWORD)

        for filename in FILES:
            uploaded = UploadedFile(owner=user, title=filename)
            uploaded.file.save(filename, ContentFile(f"{username}'s {filename}\n".encode()))
            UploadedFile.objects.filter(pk=uploaded.pk).update(created_at=CREATED_AT)

    print(f"{version}: {User.objects.count()} users, {UploadedFile.objects.count()} files")


if __name__ == "__main__":
    main()
