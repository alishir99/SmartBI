"""The agent: a bounded tool loop, a numeric validator and a deterministic renderer.

Split three ways on purpose. The loop decides *which* query to run, the renderer decides how
to draw it, and the validator decides whether the prose may be shown at all. Only the first
of those three involves the language model.
"""
