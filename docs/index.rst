reinject
========

.. toctree::
   :maxdepth: 2
   :hidden:

   api

reinject is a resource injector for Python 3.9+ asyncio
applications. It allows scoped access to resources, which are
automatically disposed of when the scope (modelled as a context
manager) exits:

It allows scoped access to resources, which are
automatically disposed of when the scope (modelled as a context
manager) exits::

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
        autoload_in_scopes=["application"]
    )

    # 2. Use the resource_scope() context manager to
    # enter a scope
    async with resource_scope("request") as scope:
        # Use the scope object to access resources that were
        # created for it
        session = scope["session"]
        # or alternatively
        session = get_current_scope()["session"]



Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
