# Provider backpressure compatibility

This provider's latest-state retry uses
`SocketChannelEndpoint._on_session_writable(session)` from the matching Pal socket
backpressure fix. Deploy the matching Pal resident Core/Channel/socket code and
this provider together; reloading this provider alone against an older Pal base
does not activate the retry hook.

Reliable text and tagged/checklist messages keep the existing ACK/outbox retry
path. Core events and tool activity are ephemeral. Runtime-state snapshots retain
one pending latest value per session and resume on writer progress or reconnect.
A full queue must not make the ready handshake or a broadcast to other sessions
fail.

Regression coverage is in `tests/test_backpressure.py`; run it with PYTHONPATH
pointing at the patched Pal `src` directory and this checkout. The full browser
suite also needs Playwright Chromium. No client layout or animation files are
changed by this repair.
