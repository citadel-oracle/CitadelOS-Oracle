<!-- knowledge-id: kv.options_mechanics.contract_identity -->
# Option Contract Identity

An option observation belongs to one exact security ID, expiry, strike, and
option type. Evidence from another contract cannot silently replace it.
Rollover creates a new observation context and preserves the old identity.
