import random
import secrets
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Set

import pytest
import pytest_asyncio
from aiohttp import ClientSession
from pytest_mock import MockerFixture

from reinject import (
    APP_SCOPE,
    SetupTeardownResource,
    get_current_scope,
    register_resource,
    resource_scope,
)

class TrackedResource:
    name = "tracked"

    def __init__(self) -> None:
        self.values: Set[int] = set()
        self.disposal_counts: Dict[int, int] = defaultdict(int)

    @asynccontextmanager
    async def managed(self) -> AsyncIterator[Any]:
        value = self.generate_value()

        # use a set here because with pure int values,
        # 8 is 8 == True, due to caching, but this does
        # not happen for sets ({8} is {8} == False)
        yield {value}

        self.dispose_value(value)

    def generate_value(self) -> int:
        """Create a new resource value."""
        value = random.randint(0, 101)

        while value in self.values:
            value = random.randint(0, 101)

        self.values.add(value)
        return value

    def dispose_value(self, value: int) -> None:
        """Dispose a resource value."""
        self.disposal_counts[value] += 1

    def assert_disposed_times(self, value: Set[int], times: int) -> None:
        if len(value) != 1:
            raise ValueError(f"Unexpected tracked resource value: {value}")

        inner_value = next(iter(value))
        assert self.disposal_counts[inner_value] == times


tokens: Set[str] = set()


async def generate_token() -> str:
    token = secrets.token_hex(32)
    tokens.add(token)
    return token


async def destroy_token(value: str) -> None:
    tokens.remove(value)


@pytest.fixture
def tracked_resource() -> TrackedResource:
    return TrackedResource()


@pytest_asyncio.fixture(autouse=True)
async def register_resources(
    mocker: MockerFixture, tracked_resource: TrackedResource
) -> None:
    # first of all, reset the registry for the duration of the test
    mocker.patch("reinject._registry", {})

    register_resource(tracked_resource, autoload_in_scopes=["tracked"])
    register_resource(
        SetupTeardownResource("token", generate_token, destroy_token),
        autoload_in_scopes=["token"],
    )


@pytest.fixture(params=["tracked", "token"])
def resource_name(request: Any) -> Any:
    return request.param


@pytest.mark.parametrize(
    "resource_name,scope_name,should_be_present",
    [
        ("token", "token", True),
        ("token", "tracked", False),
        ("tracked", "token", False),
        ("tracked", "tracked", True),
    ],
)
@pytest.mark.asyncio
async def test_autoloading_resource_into_scopes(
    resource_name: str, scope_name: str, should_be_present: bool
) -> None:
    async with resource_scope(scope_name) as scope:
        if should_be_present:
            assert scope[resource_name] is not None
        else:
            with pytest.raises(LookupError):
                assert scope[resource_name] is not None


@pytest.mark.asyncio
async def test_loading_resource_from_nested_scopes(
    tracked_resource: TrackedResource,
) -> None:
    async with resource_scope("token"):
        async with resource_scope("tracked") as inner_scope:
            token_instance = inner_scope["token"]
            tracked_instance = inner_scope["tracked"]

            assert isinstance(token_instance, str)
            assert isinstance(tracked_instance, set)

    tracked_resource.assert_disposed_times(tracked_instance, 1)


@pytest.mark.asyncio
async def test_ensure_resource_doesnt_recreate_resource_already_present_in_parent_scope(
    resource_name: str,
) -> None:
    async with resource_scope("outer") as outer_scope:
        await outer_scope.ensure_resource(resource_name)
        outer_resource = await extract_resource_from_current_scope(resource_name)

        async with resource_scope("inner") as inner_scope:
            await inner_scope.ensure_resource(resource_name)
            inner_resource = await extract_resource_from_current_scope(resource_name)

            assert inner_resource is outer_resource


@pytest.mark.asyncio
async def test_resource_shared_across_coroutines_in_same_scope(
    resource_name: str,
) -> None:
    async with resource_scope("message") as scope:
        await scope.ensure_resource(resource_name)
        resource = await extract_resource_from_current_scope(resource_name)
        second_resource = await extract_resource_from_current_scope(
            resource_name, nested_levels=3
        )

        assert resource is second_resource


@pytest.mark.asyncio
async def test_extract_unregistered_resource(mocker: MockerFixture) -> None:    
    class ClientSessionResource:
        name = "aiohttp_session"

        @classmethod
        def managed(cls) :
            return ClientSession() # ClientSession is a context manager

    ClientSession_close = mocker.spy(ClientSession, "close")

    async with resource_scope(APP_SCOPE) as scope:
        await scope.add_resource(ClientSessionResource)  # type: ignore

        root_pub = await extract_resource_from_current_scope(ClientSessionResource.name)
        nested_coro_pub = await extract_resource_from_current_scope(
            ClientSessionResource.name, nested_levels=10
        )
        assert root_pub is nested_coro_pub

    ClientSession_close.assert_called_once()


async def extract_resource_from_current_scope(
    name: str, *, ensure: bool = False, nested_levels: int = 1
) -> Any:
    """
    Simulate extracting a resource inside a coroutine.

    :param ensure: when True, `.ensure_resource(name)` will be
                   called on the current scope before attempting
                   to extract the named resource from it.

    :param nested_levels: simulate a coroutine call n levels deep.
                          This is useful testing whether the
                          resource extraction works as expected
                          in coroutines which are nested a certain
                          number of levels beyond where the scope
                          is established.
    """
    if nested_levels <= 0:
        raise ValueError("coro_levels must be a positive integer.")
    elif nested_levels > 1:
        return await extract_resource_from_current_scope(
            name, ensure=ensure, nested_levels=nested_levels - 1
        )
    else:
        scope = get_current_scope()

        if ensure:
            await scope.ensure_resource(name)

        return scope[name]
