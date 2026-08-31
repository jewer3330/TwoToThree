import os

# Test suite is explicit about its authentication bypass. Production defaults
# remain fail-closed when AUTH_DISABLED is absent.
os.environ.setdefault('AUTH_DISABLED','true')
os.environ.setdefault('SESSION_HTTPS_ONLY','false')
