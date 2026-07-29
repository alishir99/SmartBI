"""Package marker for the evaluation suite.

`eval/` was a plain directory: `cases.py` and `oracle.py` are run as scripts and never
imported by the application. The tests under `eval/tests/` do import them, and pytest's
default `prepend` import mode walks up from a test file only as far as the last directory
containing an `__init__.py`. Without this file that walk would stop at `eval/tests/`, put
`eval/` itself on `sys.path`, and make `import cases` a top-level import — which shadows
nothing today but would silently pick up any `cases.py` elsewhere on the path tomorrow.
With it, the walk reaches the repository root and the tests import `eval.cases` /
`eval.oracle` by the same absolute path `api.` and `mcp_server.` already use.

The name is safe: `eval` is a builtin *function*, not a module, so there is no stdlib
package for this one to shadow. Renaming the directory would have been the alternative and
would have broken every path in the README and the docs for no gain.
"""
