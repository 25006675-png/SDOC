"""Test environment defaults.

`sdoc.api` calls load_dotenv at import, so without this the suite would inherit
whichever mailbox provider and credentials a developer happens to have in
`.env` -- and the same test would pass on one machine and fail on another.
These are set before any test module imports the package; load_dotenv does not
override values that already exist.

Authentication is on by default so a deployed instance is not world-readable.
The suite exercises endpoints directly, so it runs with auth disabled; sign-in
and role separation are covered by TestAccountAuth, which turns it back on.
"""
import os

os.environ.setdefault("SDOC_AUTH", "off")

# Pin the mailbox to an unconfigured Gmail so provider tests are deterministic.
os.environ["SDOC_MAILBOX_PROVIDER"] = "gmail"
for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
             "MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"):
    os.environ[name] = ""
