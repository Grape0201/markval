import pytest
import asyncio
from app.core import semaphores

@pytest.mark.anyio
async def test_semaphores_are_singletons_and_limits():
    # Retrieve semaphores
    sem_llm = semaphores.get_llm_semaphore()
    sem_yomitoku = semaphores.get_yomitoku_semaphore()
    
    # Assert they are instance of asyncio.Semaphore
    assert isinstance(sem_llm, asyncio.Semaphore)
    assert isinstance(sem_yomitoku, asyncio.Semaphore)
    
    # Assert they are singletons
    assert semaphores.get_llm_semaphore() is sem_llm
    assert semaphores.get_yomitoku_semaphore() is sem_yomitoku
    
    # Assert they have the correct limit of 2
    # In asyncio.Semaphore, the initial limit is stored in _value
    assert sem_llm._value == 2
    assert sem_yomitoku._value == 2
