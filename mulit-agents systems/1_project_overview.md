Introduction

You are an Enterprise AI Solutions Architect at NovaMart, a fictional e-commerce company. The company's customer support team handles thousands of requests daily — order status inquiries, return and refund requests, policy questions, and more. Currently, support agents manually look up orders, cross-reference policies, and draft responses — a process that is slow, inconsistent, and error-prone.

Your job is to build the AI layer that automates this workflow.
The Challenge

NovaMart needs a customer support system that can automatically understand a customer's request, gather relevant information from multiple data sources, make decisions based on company policies, and compose a professional response — all without human intervention. The system must handle multiple types of requests (order lookups, refund decisions, policy questions) by routing them to the right specialist, enforce enterprise safety guardrails, and provide full observability into every decision the AI makes.
Your Product

You will build a production-grade multi-agent customer support system using Amazon Bedrock AgentCore and the Strands Agents SDK. The system consists of five AI agents working together in an Orchestrator → Workers hierarchy:

    An Orchestrator Agent that understands customer intent and routes requests to the right specialist
    An Inventory Agent that retrieves order and customer data from DynamoDB
    A Policy Agent that answers policy questions using parallel multi-agent RAG across three Knowledge Bases
    A Refund Agent that makes return eligibility decisions based on order data and policy rules
    A Communication Agent that composes the final customer-facing response

The system is deployed to AgentCore Runtime with Bedrock Guardrails for safety, session memory for multi-turn conversations, and CloudWatch/X-Ray observability for monitoring and debugging.
Deliverables

To complete this project, you must submit:

    Completed src/agent_orchestrator.py — All TODO items implemented (Tasks 2, 3, 4, 6)
    Three Bedrock Knowledge Bases — Created in the AWS Console with synced data sources (Task 5)
    Populated .env file — With your Knowledge Base IDs, AgentCore Runtime ARN, and Guardrail configuration
    X-Ray Service Map screenshot — Showing the full trace of an end-to-end request through your multi-agent system (Task 6)

Key resources:

    Strands Agents SDK Documentation(opens in a new tab) — Official documentation for the Strands Agents SDK used throughout the project — covering the Agent class, @tool decorator, and BedrockModel configuration.
    Amazon Bedrock Knowledge Bases — Getting Started(opens in a new tab) — Step-by-step AWS guide for creating Bedrock Knowledge Bases in the console — the exact steps required in Phase 3 of this project.
    AgentCore CLI(opens in a new tab) — The deployment tool used by this project. The supplied helper stages code, configures the runtime, and runs agentcore deploy. AWS SDK calls are still used for application services, guardrails, memory, and observability services.