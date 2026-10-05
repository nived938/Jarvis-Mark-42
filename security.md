# Security and Safety

## Secrets

Never commit:

- Gemini API keys
- Google OAuth client credentials
- Gmail tokens
- Calendar tokens
- private certificates
- personal memory dumps

Keep secrets under ignored local configuration paths.

## Tool boundaries

Actions should not silently expand their authority.

Examples:

- application internet locking uses a dedicated firewall rule;
- emergency stop blocks new JARVIS-controlled work;
- self-modification requires validation and human confirmation;
- lifecycle commands require explicit JARVIS wording;
- application close uses a window-level close request rather than arbitrary process termination.

## Destructive operations

Destructive actions should use the existing confirmation/preview mechanisms wherever they are already supported.

Do not bypass a confirmation gate just to reduce conversational latency.

## Emergency stop

The Emergency Kill Switch is a local safety latch for JARVIS-controlled activity. It is not a general Windows process killer.

## Memory

Personal memory is local application state. Treat it as sensitive even if it is not a secret credential.

## OAuth

Google OAuth tokens are local and should be treated like passwords. If a token is compromised, revoke it in the Google account/security settings and remove the local token file.

## Windows integration

The Windows-specific modules can interact with:

- application windows
- firewall rules
- Explorer shell registration
- PnP state
- desktop configuration

Use explicit user commands for these operations and keep administrative operations obvious.

## Privacy

The privacy screen shield hides JARVIS's visible UI content. It does not encrypt or delete the underlying data.

## Logging

Execution traces are useful for debugging but can contain tool arguments and results. Keep `memory/execution_traces/` local and private.
