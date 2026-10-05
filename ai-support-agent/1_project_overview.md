Overview

In this project, you will build a fully functional AI customer support agent using Amazon Bedrock AgentCore and the Strands SDK. The agent serves as an intelligent interface between customers and an e-commerce platform, handling complex multi-turn conversations while maintaining context across sessions.

You are an AI Solutions Engineer tasked with building an intelligent customer support assistant that handles order tracking, returns processing, product recommendations, and loyalty rewards calculations — all through a single conversational interface. Your agent integrates with multiple backend systems through the AgentCore Gateway using the Model Context Protocol (MCP), retrieves grounded product information from a Bedrock Knowledge Base, remembers customer preferences across sessions using AgentCore Memory, and performs exact calculations using the AgentCore Code Interpreter.

When complete, your agent will be able to:

    Track orders and process refunds by calling Lambda functions through the AgentCore Gateway
    Answer product and policy questions using Retrieval-Augmented Generation (RAG) with a Bedrock Knowledge Base
    Remember customer names, preferences, and conversation history across separate sessions
    Calculate exact loyalty discounts using a secure code sandbox
    Browse live web pages to fetch real-time information

After completing this project, you will be able to:

    Deploy an AI agent to Amazon Bedrock AgentCore Runtime — using the Strands SDK, BedrockAgentCoreApp, and the @app.entrypoint decorator to create a cloud-deployed agent
    Integrate external tools through AgentCore Gateway using MCP — connecting Lambda-backed tools (order tracking, refund processing) via MCPClient and streamable_http_client
    Implement Retrieval Augmented Generation with a Bedrock Knowledge Base — building a search_knowledge_base tool that calls the Retrieve API for grounded, accurate responses
    Implement cross-session agent memory using AgentCore Memory — creating a MemoryHook that retrieves customer context before each response and saves interactions for future recall
    Execute computational tasks using AgentCore Code Interpreter — building a loyalty discount calculator that runs precise arithmetic in a secure sandbox
    Enable web browsing with AgentCore Browser Tool — adding live web access to the agent's capabilities

Deliverables

Your submission includes the following artifacts:

    Completed main.py — all TODO sections implemented, no placeholder code remaining
    Test conversation logs — screenshots or terminal output for all six test scenarios (order tracking, refund processing, RAG, memory recall, discount calculation, browser)
    Written reflection — a 200–400 word reflection covering one design decision, one challenge encountered, and one production consideration

Resources

    Starter code repository — contains starter/main.py with TODO comments marking each implementation section, plus pre-built Lambda functions in starter/lambda/
    Product catalog data — product_catalog.txt for uploading to the Knowledge Base
    Amazon Bedrock AgentCore Documentation(opens in a new tab)
    Strands Agents Documentation(opens in a new tab)
    MCP Inspector(opens in a new tab) — for verifying Gateway tool registration

Project Assessment

Your project will be reviewed by a Udacity Mentor based on the rubric you can find on the following pages. Make sure to review the rubric and complete all of the rubric criteria before submitting.

This released project intentionally uses the Python-based bedrock-agentcore-starter-toolkit and its agentcore configure, deploy, invoke, and destroy workflow. Do not install both CLIs because both provide an agentcore executable.