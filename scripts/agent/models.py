"""Shared Pydantic shapes for planning (used by task decomposition and runtime state)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Subtask(BaseModel):
    id: int
    title: str
    description: str
    dependencies: list[int] = Field(default_factory=list)


class TaskBreakdown(BaseModel):
    goal_summary: str
    subtasks: list[Subtask]
    notes: str | None = None
