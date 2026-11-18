
"""Populate one application version with evaluation data"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from setup.users import PASSWORD, USERS


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

    # Require an empty database
    if User.objects.exists() or UploadedFile.objects.exists():
        raise RuntimeError("Database is not empty, remove existing data first")

    # Create users
    users = {}
    for username, (first_name, last_name, email) in USERS.items():
        users[username] = User.objects.create_user(
            username=username, first_name=first_name,
            last_name=last_name, email=email, password=PASSWORD
        )

    # Create each user's files from the dataset
    for username, user in users.items():
        for path in sorted((ROOT / "dataset" / username).glob("*")):
            content = path.read_text().replace("{bob_id}", str(users["bob"].pk))

            uploaded = UploadedFile(owner=user, title=path.name)
            uploaded.file.save(path.name, ContentFile(content.encode()))
            UploadedFile.objects.filter(pk=uploaded.pk).update(created_at=CREATED_AT)

    print(f"{version}: {User.objects.count()} users, {UploadedFile.objects.count()} files")


if __name__ == "__main__":
    main()
