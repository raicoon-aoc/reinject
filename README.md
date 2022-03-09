reinject
========

`reinject` is a **re**source **inject**or for Python 3.9+ asyncio
applications. It allows scoped access to resources, which are
automatically disposed of when the scope (modelled as a context
manager) exits:


```python
from reinject import register_resource, resource_scope, get_current_scope

# 1. handlers which can create and destroy the resources
    # need to be registered:
register_resource(
    SetupTeardownResource(
        "session"
        create_session,
        destroy_session,
    )
    autoload_in_scopes=["request"]
)

# or an object with a `name` property and a `.managed()` method,
# returning a resource context manager can be passed directly.
class Publisher:
    name = "publisher"
    @asynccontextmanager
    def managed(self):
        ...

register_resource(
    Publisher,
    autoload_in_scopes=["other"]
)

# 2. Use the resource_scope() context manager to
# enter a scope
async with resource_scope("request") as scope:
    # Use the scope object to access resources that were
    # created for it
    session = scope["session"]
    # or alternatively
    session = get_current_scope()["session"]

    assert "publisher" not in scope

    async with resource_scope("other") as nested_scope:
        assert "publisher" in nested_scope
```

Furthermore, scopes are asyncio aware and work as expected
within nested coroutines, so that a scope established within
a coroutine is available in all of its children, but none of
its siblings. You may use the function `get_current_scope()`
from any function to retrieve the last pushed scope.


# Installation

Copy `reinject.py` into your PYTHONPATH.
