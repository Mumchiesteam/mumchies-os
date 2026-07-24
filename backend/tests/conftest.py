import os

# Existing domain tests exercise route behavior independently of access control.
# Authentication has its own tests and explicitly enables it.
os.environ.setdefault("AUTH_ENABLED", "false")
