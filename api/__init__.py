"""FastAPI backend — the MCP *client*, the tenant boundary and the grounding enforcement.

Three responsibilities, in order of how load-bearing they are:

1. It is the only place `supplier_id` exists (from a verified JWT) and the only place it is
   attached to an MCP call — as a transport header, never as a tool argument (§6.3).
2. It intercepts every tool result before the model sees it, keeps the full result set
   server-side under a `query_id`, and passes the model a capped preview. That is the
   mechanical form of "the numbers never passed through the language model" (§9.1).
3. It validates the model's prose against the cached numbers and suppresses it if the two
   disagree twice (§9.2).
"""
