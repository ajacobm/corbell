"""Pydantic models for MCP tool inputs."""

from typing import Optional
from pydantic import BaseModel, Field


class GraphQueryRequest(BaseModel):
    """Input schema for graph_query tool."""
    
    service_id: str = Field(..., description="Service ID to query")
    include_dependencies: bool = Field(default=True, description="Include dependencies in output")
    include_methods: bool = Field(default=False, description="Include methods in output")


class SpecGenerateRequest(BaseModel):
    """Input schema for spec_generate tool."""
    
    prd_text: str = Field(..., description="PRD or feature description text")


class SpecContextRequest(BaseModel):
    """Input schema for spec_context tool."""
    
    feature_description: str = Field(..., description="Feature description to preview context for")
    top_k_services: int = Field(default=10, description="Max number of services to preview")
