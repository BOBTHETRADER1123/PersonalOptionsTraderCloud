"""Generate a PBKDF2 password value for APP_PASSWORD_HASH."""
import getpass
import hashlib
import secrets

password = getpass.getpass("Desk password: ")
salt = secrets.token_urlsafe(18)
digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310000).hex()
print(f"pbkdf2_sha256${salt}${digest}")
