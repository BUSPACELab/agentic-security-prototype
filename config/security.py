"""Application security configuration."""
from django.db import connection

from apps.policies.policy import ApplicationFilePolicy, ApplicationDatabasePolicy
from security_system.system import System


# Create the security system with the application's filesystem policy
system = System(ApplicationFilePolicy(), ApplicationDatabasePolicy(), database=connection)