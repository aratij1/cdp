from __future__ import annotations

from abc import ABC, abstractmethod
import logging
from typing import Any, Dict
from packages.agents.context import AgentContext

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract Base Agent implementing the KAIMS standard lifecycle.

    Life Cycle:
    1. initialize() - Set up state, load references or config.
    2. plan()       - Determine execution strategy based on the context.
    3. execute()    - Perform the core actions.
    4. validate()   - Check outputs and ensure safety or accuracy.
    5. reflect()    - Log performance metrics, trigger retry, or record feedback.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    async def run(self, context: AgentContext) -> AgentContext:
        """Sequential lifecycle execution runner with error isolation."""
        try:
            await self.initialize(context)
            await self.plan(context)
            await self.execute(context)
            await self.validate(context)
            await self.reflect(context)
        except Exception as exc:
            logger.exception(f"Agent {self.name} failed during lifecycle execution")
            context.set_error(self.name, str(exc))
        return context

    @abstractmethod
    async def initialize(self, context: AgentContext) -> None:
        """Prepare references or static models."""
        pass

    @abstractmethod
    async def plan(self, context: AgentContext) -> None:
        """Determine strategy from upstream results inside AgentContext."""
        pass

    @abstractmethod
    async def execute(self, context: AgentContext) -> None:
        """Execute core logic and call existing CDP libraries."""
        pass

    @abstractmethod
    async def validate(self, context: AgentContext) -> None:
        """Validate output structures and boundaries."""
        pass

    @abstractmethod
    async def reflect(self, context: AgentContext) -> None:
        """Record quality indicators or post-processing feedback."""
        pass
