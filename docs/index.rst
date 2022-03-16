reinject
========

.. toctree::
   :maxdepth: 2
   :hidden:

   api

reinject is a resource injector for Python 3.9+ asyncio
applications. It allows scoped access to resources, which are
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


What Is A Resource?
-------------------

A resource is some piece of hardware or software that provides
some service to your application. Many times, these resources
are accessed through handles which need to be prompted
discarded/cleaned up as soon as the application is finished using them.
Some examples of such resource handles include:

- A network connection
- A database transaction
- An open file


(Your application may also define/rely on other types of
resources.)


What Is This Good For?
----------------------

reinject is well suited for cases where you would like to share
a handle to one or more resources throughout your application;
it allows you to do so without passing these handles around.

It accomplishes this by taking over the _management_ of these
resources from application code. At startup, the application
:func:`provides <reinject.register_resource>` reinject with a
description of each resource it wants
to have managed (i.e. how to create it, and then subsequently
dispose of it), and at runtime the application code can asynchronously
:meth:`request <reinject.Scope.ensure_resource>` an instance of such
a resource from reinject.

For example, a webserver may describe to reinject how to create
and close a database session, and then at any point during
handling a request, it can ask reinject for a database session.
If there is no database session available for that particular
request, then a new one will be returned and cached until reinject
decides to clean it up.

(Note: if this seems similar to scoped_session from sqlalchemy,
that's not a mistake! This serves a similar, but more generalised
function and has the benefit of working as expected on asyncio.)

What About Scopes?
++++++++++++++++++

You may be wondering at this point, when does reinject actually
dispose of these resources? Scopes provide a way to describe both
the *visibility* and *lifetime* of a resource. Simply put,
resources which are established within a scope will last for as
long as the scope lasts. Similarly, resources which are established
within a scope are visible to all functions and coroutines that are
called from that scope.

Since scopes are implemented as async context managers, and can be
nested ad-infinitum within each other, this gives an application an
incredible amount of control over how its resources are managed.

This also makes scopes the backbone of reinject; in order to retrieve
an instance of any resource that you have declared, you will need a
handle to a reinject :class:`scope <reinject.Scope>`.

Webserver Semi-example
++++++++++++++++++++++

If you're still wondering how you would actually use this, then let's
go through a rough example of how this can be used to manage a
webserver's database sessions::

    from reinject import (
        get_current_scope,
        register_resource,
        resource_scope,
        SetupTeardownResource
    )

    async def create_connection_pool():
        return ConnectionPool(...)

    async def dispose_connection_pool(pool):
        await pool.dispose()

    async def create_session():
        pool = get_current_scope()["pool"]
        session = await pool.new_session()
        return session

    async def dispose_session(session):
        await session.dispose()

    # register the connection pool resource giving it the name "pool"
    # instruct reinject to create an instance automatically
    # when entering any scope called "app"
    register_resource(
        SetupTeardownResource(
            "pool",
            create_connection_pool,
            dispose_connection_pool
        ),
        autoload_in_scopes=["app"]
    )

    # register a db session resource called "session"
    register_resource(
        SetupTeardownResource(
            "session",
            create_session,
            dispose_session
        )
    )

    async def main():
        async with resource_scope("app") as scope:
            # retrieve the autoloaded instance of the connection
            # pool and pass it into the app.
            app = App(
                pool=scope["pool"],
                request_handler=handle_request
            )
            await app.serve()

    async def handle_request(req):
        async with resource_scope("request") as scope:
            # Note that every request will get a fresh session,
            # but that session will be accessible to any function
            # or coroutine called from this request handler.
            db_session = await scope.ensure_resource("session")

            # you are also able to *retrieve* resources from parent
            # scopes using dict key access
            pool = scope["pool"]
            ...

            # in some nested function/coro:
            db_session = get_current_scope()["session"]

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
