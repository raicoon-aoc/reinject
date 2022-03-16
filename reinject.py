"""
Resource management library for asyncio apps.

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
"""

from __future__ import annotations

from collections import deque
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar, copy_context
from typing import (
    Any,
    AsyncContextManager,
    AsyncIterator,
    Awaitable,
    Deque,
    Dict,
    Iterable,
    Optional,
    Protocol,
    Set,
)

_scope_stack: ContextVar[Deque[Scope]] = ContextVar("resource_registry")
_registry: Dict[str, Resource] = {}
_required_resources_by_scope: Dict[str, Set[str]] = {}

APP_SCOPE = "application"


def register_resource(
    resource: Resource, *, autoload_in_scopes: Optional[Iterable[str]] = None
) -> None:
    """Register a resource for later use.


    :param resource: an object implementing the :class:`Resource` protocol.
    :param autoload_in_scopes: A list of application defined scope names;
                               when a scope with one of those names is
                               established using
                               :func:`reinject.resource_scope`, this
                               resource will automatically be created,
                               inserted into the scope, and when the scope
                               exits it will be destroyed.
    """
    _registry[resource.name] = resource

    if autoload_in_scopes:
        for scope_name in autoload_in_scopes:
            _required_resources_by_scope.setdefault(scope_name, set()).add(
                resource.name
            )


def resource_scope(name: str) -> AsyncContextManager[Scope]:
    """Establish a resource scope.

    The resource scope is tracked by the async context manager
    returned from this function.

    .. tip:: Established scopes are asyncio aware. A scope
       established within a coroutine is available in all of its
       children, but none of its siblings.

    :param name: application defined name for the scope

    """
    try:
        parent_scope: Optional[Scope] = get_current_scope()
    except RuntimeError:
        parent_scope = None

    return Scope(name, parent=parent_scope)


def get_current_scope() -> Scope:
    """Get the currently active resource scope.

    If no resource scope is active, then a RuntimeError is raised."""
    try:
        scope_stack = _scope_stack.get()
        return scope_stack[-1]
    except (LookupError, IndexError):
        raise RuntimeError("No resource scope is currently active.")


class ResourceSetupFunction(Protocol):
    def __call__(self) -> Awaitable[Any]:
        """Create a resource instance"""


class ResourceTeardownFunction(Protocol):
    def __call__(self, value: Any) -> Awaitable[None]:
        """Destroy a resource instance"""


class Closable(Protocol):
    def close(self) -> Awaitable[None]:
        """A closable resource instance"""


class ClosableFactory(Protocol):
    def __call__(self) -> Closable:
        """Return a closable resource instance"""


class Resource(Protocol):
    """A protocol for a managed resource.

    It allows to supply resources to reinject which can be properly
    disposed of when they go out of scope.
    """

    def managed(self) -> AsyncContextManager[Any]:
        """Return a context manager for this resource.

        The context manager should yield the actual resource instance,
        and when the context exits, it should dispose of the resource
        instance.
        """

    @property
    def name(self) -> str:
        """An indentifier for the resource"""


class SetupTeardownResource:
    """A simple :class:`Resource` implementation wrapping
    setup/teardown functions.

    This can be used to register resources if you have
    a function that can create it, as well as a function
    that will destroy it::

        async def create_session() -> Session:
            ...

        async def destroy_session(value: Session) -> None:
            ...

        SetupTeardownResouce("session", create_session, destroy_session)
    """

    def __init__(
        self,
        name: str,
        setup: ResourceSetupFunction,
        teardown: ResourceTeardownFunction,
    ) -> None:
        self.name = name
        self.setup = setup
        self.teardown = teardown
        self.manager = self

    @asynccontextmanager
    async def managed(self) -> AsyncIterator[Any]:
        value = await self.setup()
        yield value
        await self.teardown(value)


class Scope:
    """Represents a scope containing arbitrary resources.

    This shouldn't normally be instantiated directly; it is yielded
    from the context manager returned by :func:`resource_scope`. It
    provides dict type lookup be resource name, as membership checks
    for resources using the `in` keyword.
    """

    def __init__(self, name: str, parent: Optional[Scope] = None) -> None:
        self.name = name
        self.own_resources: Dict[str, Any] = {}
        self.parent_resources: Dict[str, Any] = (
            {}
            if parent is None
            else {**parent.own_resources, **parent.parent_resources}
        )
        self.exitstack = AsyncExitStack()

    async def __aenter__(self) -> Scope:
        """Create and track resources required by this scope."""
        for resource_name in _required_resources_by_scope.get(
            self.name, set()
        ):
            await self.ensure_resource(resource_name)

        current_context = copy_context()
        if _scope_stack not in current_context:
            _scope_stack.set(deque())

        _scope_stack.get().append(self)

        return self

    async def __aexit__(self, *_: Any) -> None:
        """Untrack and destroy resources created in this scope."""
        _scope_stack.get().pop()
        self.own_resources = {}
        await self.exitstack.aclose()

    def __getitem__(self, name: str) -> Any:
        """Get a named resource from this scope.

        If the named resource was never created for this scope
        (either by registering with `autoload_in_scope`, or by calling
        :func:`ensure_resource` before this function), then this will
        raise a KeyError.
        """
        if name in self.own_resources:
            return self.own_resources[name]
        elif name in self.parent_resources:
            return self.parent_resources[name]
        else:
            raise KeyError(
                f"Resource {repr(name)} not instantiated under this scope. "
                "(Hint: try .ensure_resource() beforehand)"
            )

    def __contains__(self, resource_name: str) -> bool:
        return (resource_name in self.own_resources) or (
            resource_name in self.parent_resources
        )

    def __repr__(self) -> str:
        return f"Scope({repr(self.name)})"

    async def add_resource(self, resource: Resource) -> Any:
        """Add a resource to this scope instance only, without registering it.

        This is a 1-time resource that will not be registered, and it will
        be removed as soon as the scope expires.
        """
        self.own_resources[
            resource.name
        ] = await self.exitstack.enter_async_context(resource.managed())
        return self.own_resources[resource.name]

    async def ensure_resource(self, name: str) -> Any:
        """Make sure that a previously registered resource is
        available in this scope.

        This is useful for resources which were not autoloaded into
        the scope.
        """
        try:
            return self[name]
        except LookupError:
            resource = _registry[name]
            return await self.add_resource(resource)
