# zakadi

Zakadi face-liveness API client for Python. Zakadi is an active face liveness check delivered as a short automated video call; relying parties create sessions and read verdicts server to server.

Pre-release. This version ships the shared protocol constants (session states and statuses, decisions and bands, SDK error codes, terminal states, close codes, challenge kinds, webhook event types) with type annotations. The client for sessions, results, evidence and webhook signature verification follows in a later release; its surface is:

```python
from zakadi import Zakadi
client = Zakadi(api_key="zk_live_...", base_url="https://api.zakadi.dev")
s = client.sessions.create(user_ref="cust-88213", locale="en-NG", channel="android")
r = client.sessions.result(s.session_id)
```

Links: https://zakadi.dev (documentation), https://github.com/zakadihq/zakadi-python (source).
