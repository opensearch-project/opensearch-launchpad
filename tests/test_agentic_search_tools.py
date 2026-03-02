"""Tests for MCP server agentic search integration"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
import pytest

import opensearch_orchestrator.mcp_server as mcp_server


def test_mcp_server_includes_agentic_search_knowledge_tool():
    """Test that read_agentic_search_guide is exported as an MCP tool"""
    tool_names = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
    assert "read_agentic_search_guide" in tool_names


def test_mcp_server_includes_agentic_model_creation_tool():
    """Test that create_bedrock_agentic_model_with_creds is exported as an MCP tool"""
    tool_names = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
    assert "create_bedrock_agentic_model_with_creds" in tool_names


def test_mcp_server_includes_agentic_flow_agent_tool():
    """Test that create_agentic_search_flow_agent is exported as an MCP tool"""
    tool_names = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
    assert "create_agentic_search_flow_agent" in tool_names


def test_mcp_server_includes_agentic_pipeline_tool():
    """Test that create_agentic_search_pipeline is exported as an MCP tool"""
    tool_names = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
    assert "create_agentic_search_pipeline" in tool_names


def test_agentic_search_tools_in_default_tool_surface():
    """Test that all agentic search tools are in the default MCP tool surface"""
    tool_names = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
    
    expected_agentic_tools = {
        "read_agentic_search_guide",
        "create_bedrock_agentic_model_with_creds",
        "create_agentic_search_flow_agent",
        "create_agentic_search_pipeline",
    }
    
    assert expected_agentic_tools.issubset(tool_names), \
        f"Missing agentic tools: {expected_agentic_tools - tool_names}"


def test_agentic_model_tool_has_correct_parameters():
    """Test that create_bedrock_agentic_model_with_creds has all required parameters"""
    tools = asyncio.run(mcp_server.mcp.list_tools())
    agentic_model_tool = next(
        (t for t in tools if t.name == "create_bedrock_agentic_model_with_creds"),
        None
    )
    
    assert agentic_model_tool is not None, "create_bedrock_agentic_model_with_creds tool not found"
    
    # Check that the tool has the expected parameters
    schema = agentic_model_tool.inputSchema
    required_params = {"access_key", "secret_key", "region", "session_token", "model_name"}
    
    if "properties" in schema:
        actual_params = set(schema["properties"].keys())
        assert required_params.issubset(actual_params), \
            f"Missing parameters: {required_params - actual_params}"


def test_agentic_flow_agent_tool_has_correct_parameters():
    """Test that create_agentic_search_flow_agent has required parameters"""
    tools = asyncio.run(mcp_server.mcp.list_tools())
    flow_agent_tool = next(
        (t for t in tools if t.name == "create_agentic_search_flow_agent"),
        None
    )
    
    assert flow_agent_tool is not None, "create_agentic_search_flow_agent tool not found"
    
    schema = flow_agent_tool.inputSchema
    required_params = {"agent_name", "model_id"}
    
    if "properties" in schema:
        actual_params = set(schema["properties"].keys())
        assert required_params.issubset(actual_params), \
            f"Missing parameters: {required_params - actual_params}"


def test_agentic_pipeline_tool_has_correct_parameters():
    """Test that create_agentic_search_pipeline has required parameters"""
    tools = asyncio.run(mcp_server.mcp.list_tools())
    pipeline_tool = next(
        (t for t in tools if t.name == "create_agentic_search_pipeline"),
        None
    )
    
    assert pipeline_tool is not None, "create_agentic_search_pipeline tool not found"
    
    schema = pipeline_tool.inputSchema
    required_params = {"pipeline_name", "agent_id", "index_name"}
    
    if "properties" in schema:
        actual_params = set(schema["properties"].keys())
        assert required_params.issubset(actual_params), \
            f"Missing parameters: {required_params - actual_params}"


def test_agentic_search_tools_not_in_advanced_tools_only():
    """Test that agentic search tools are available without ADVANCED_TOOLS flag"""
    # Ensure advanced tools are disabled
    import os
    os.environ.pop(mcp_server.ADVANCED_TOOLS_ENV, None)
    
    tool_names = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
    
    # Agentic search tools should be in default surface
    assert "read_agentic_search_guide" in tool_names
    assert "create_bedrock_agentic_model_with_creds" in tool_names
    assert "create_agentic_search_flow_agent" in tool_names
    assert "create_agentic_search_pipeline" in tool_names


def test_read_agentic_search_guide_tool_exists():
    """Test that read_agentic_search_guide tool is properly registered"""
    tools = asyncio.run(mcp_server.mcp.list_tools())
    guide_tool = next(
        (t for t in tools if t.name == "read_agentic_search_guide"),
        None
    )
    
    assert guide_tool is not None, "read_agentic_search_guide tool not found"
    assert guide_tool.description is not None, "Tool should have a description"


def test_agentic_tools_alongside_existing_tools():
    """Test that agentic search tools coexist with existing MCP tools"""
    tool_names = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
    
    # Check existing tools still exist
    existing_tools = {
        "read_knowledge_base",
        "read_dense_vector_models",
        "read_sparse_vector_models",
        "create_bedrock_embedding_model",
        "create_local_pretrained_model",
    }
    
    assert existing_tools.issubset(tool_names), \
        f"Missing existing tools: {existing_tools - tool_names}"
    
    # Check agentic tools are added
    agentic_tools = {
        "read_agentic_search_guide",
        "create_bedrock_agentic_model_with_creds",
        "create_agentic_search_flow_agent",
        "create_agentic_search_pipeline",
    }
    
    assert agentic_tools.issubset(tool_names), \
        f"Missing agentic tools: {agentic_tools - tool_names}"


def test_agentic_model_tool_description_mentions_credentials():
    """Test that create_bedrock_agentic_model_with_creds description mentions credentials"""
    tools = asyncio.run(mcp_server.mcp.list_tools())
    model_tool = next(
        (t for t in tools if t.name == "create_bedrock_agentic_model_with_creds"),
        None
    )
    
    assert model_tool is not None
    description = model_tool.description or ""
    
    # Should mention credentials or AWS in description
    assert "credential" in description.lower() or "aws" in description.lower()


def test_agentic_flow_agent_tool_description_mentions_tools():
    """Test that create_agentic_search_flow_agent description mentions IndexMappingTool and QueryPlanningTool"""
    tools = asyncio.run(mcp_server.mcp.list_tools())
    agent_tool = next(
        (t for t in tools if t.name == "create_agentic_search_flow_agent"),
        None
    )
    
    assert agent_tool is not None
    description = agent_tool.description or ""
    
    # Should mention the tools used by flow agent
    assert "IndexMappingTool" in description or "QueryPlanningTool" in description


def test_agentic_pipeline_tool_description_mentions_attachment():
    """Test that create_agentic_search_pipeline description mentions index attachment"""
    tools = asyncio.run(mcp_server.mcp.list_tools())
    pipeline_tool = next(
        (t for t in tools if t.name == "create_agentic_search_pipeline"),
        None
    )
    
    assert pipeline_tool is not None
    description = pipeline_tool.description or ""
    
    # Should mention attaching to index
    assert "attach" in description.lower() or "index" in description.lower()
