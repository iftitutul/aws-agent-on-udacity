File: src/agent_orchestrator.py

In this phase, you will implement five Strands Agents that form an Orchestrator → Workers hierarchy. This is the core of the project — by the end of this phase, you will have a working multi-agent system that can route customer requests, retrieve data, make decisions, and compose responses.
Your Files
File	Role	Action
src/agent_orchestrator.py	Main implementation file — agent builders, routing tools, deployment	Implement TODOs
src/agent_utils.py	Terminal trace UI, ANSI colours, AgentTrace class	Do not modify
src/agent_observability.py	X-Ray tracing (@tool wrapper) and CloudWatch logging	Do not modify
src/bedrock_kb_retrieval.py	KB retrieval helper used by PolicyAgent	Do not modify
src/demo.py	Runs one end-to-end request for local testing	Do not modify
config.py	Central configuration — reads CloudFormation exports + .env	Do not modify
tests/test_agent.py	Automated test suite	Do not modify
src/agentcore_cli.py	AgentCore CLI wrapper: stage code, configure, deploy, read runtime ARN	Do not modify

    What is agent_utils.py? It contains the terminal trace UI that makes agent activity visible during chat and demo runs — colour-coded step banners, tool call formatting, parallel retrieval display, and the DynamoDB workflow summary. You do not need to read or understand it to complete the project.

    What is agent_observability.py? It provides the tool decorator used in agent_orchestrator.py — the Strands @tool plus an X-Ray subsegment per call — so every request you run is traced to AWS X-Ray automatically (Phase 4). Use @tool exactly as you would with Strands.

Background: Strands Agents

The Strands Agents SDK(opens in a new tab) lets you build AI agents by decorating Python functions with @tool and passing them to an Agent along with a model and system prompt. When called like a function, the agent reasons through the problem and invokes its tools as needed. Refer to the SDK documentation for usage details.
Background: WorkflowState

WorkflowStateTable is a shared DynamoDB record (keyed by session_id) that accumulates each worker's output as the request flows through the pipeline. Three pre-written helpers manage it — use them inside your routing tools:

    _create_workflow_state(session_id, customer_id) — creates a blank record
    _read_workflow_state(session_id) — reads the current state
    _update_workflow_state(session_id, updates, expected_version) — writes with optimistic locking

1.A — InventoryAgent

Build a worker agent that gathers order and customer facts from DynamoDB. It should NOT make decisions — only report what it finds.

Implement three tools that look up data from the DynamoDB tables provisioned by the CloudFormation stack you deployed earlier. Use config.ORDERS_TABLE and config.CUSTOMERS_TABLE for the table names. Note that the Orders table has a composite key (customer_id + order_id), which is why the check_order_status stub takes both. Write a system prompt that instructs the agent to be a data gatherer — it should retrieve information accurately and never make eligibility decisions.

    Model: config.WORKER_MODEL_ID (Claude Sonnet 4.5), Temperature: 0.1

1.B — RefundAgent

Build a worker agent that makes return/refund eligibility decisions. It reads facts from WorkflowState (populated by InventoryAgent) and applies the correct policy window based on customer tier.

Policy windows: Standard customers = 30 days, Premium customers = 60 days.

Implement two tools: one that reads the inventory findings from WorkflowState, and one that processes the return by updating the order record in DynamoDB. Write a system prompt that instructs the agent on the decision process — it should always check inventory context first, then apply the correct return window.

    Model: config.WORKER_MODEL_ID, Temperature: 0.1

1.C — PolicyAgent — Multi-Agent RAG

Build a coordinator agent that answers policy questions by running three specialized retriever sub-agents in parallel. This is the core architectural pattern of this project.

Inside build_policy_agent(), create three retriever sub-agents — one for each policy domain (Returns, Shipping, Warranty). Each retriever should have a single tool that calls retrieve_from_knowledge_base() (imported from bedrock_kb_retrieval.py) with the appropriate Knowledge Base ID from config.

Then implement the search_all_policies tool that invokes all three retrievers simultaneously using ThreadPoolExecutor and collects their results. The trace calls in the starter code show you where the parallel execution should happen.

Finally, create the PolicyAgent coordinator with a system prompt that instructs it to always call search_all_policies first, then synthesize the retrieved passages into a grounded answer.

    Retrievers: config.WORKER_MODEL_ID, Temperature: 0.0 (deterministic retrieval)
    PolicyAgent coordinator: config.WORKER_MODEL_ID, Temperature: 0.2

1.D — CommunicationAgent

Build a worker agent that drafts the final customer-facing response. It reads the full WorkflowState (all findings from previous agents) and composes a professional, empathetic message.

Implement one tool that reads the complete WorkflowState record. Write a system prompt that instructs the agent to include all relevant information from previous agents and maintain a warm, professional tone.

    Model: config.WORKER_MODEL_ID, Temperature: 0.3 (for warm, natural tone)

1.E — OrchestratorAgent

Build the orchestrator that routes requests and manages WorkflowState. This agent does not answer questions directly — it delegates everything to the appropriate specialist.

Implement five routing tools: initialize_session, route_to_inventory_agent, route_to_policy_agent, route_to_refund_agent, and route_to_communication_agent. Each routing tool should read the current WorkflowState, invoke the appropriate worker agent, and then update the WorkflowState with the result.

Write a system prompt that enforces these routing rules:
Rule	Trigger	Action
1	Every request, always	Call initialize_session first
2	Order status / return / refund requests	Route to inventory agent first, then refund agent
3	Policy meaning questions (return windows, shipping rates, warranty terms)	Route to policy agent
4	Account questions ("what is my tier?", "am I premium?")	Route to inventory agent — never policy agent (it only knows policy text, not customer data)
5	Math / calculation questions	Orchestrator → CommunicationAgent, skip Inventory, Policy and Refund.
6	Every request, always (last step)	Route to communication agent to compose the final reply

    CRITICAL: The Orchestrator must never write the final customer-facing response itself. It must always delegate to the communication agent as its very last tool call — no exceptions.

    Model: config.ORCHESTRATOR_MODEL_ID (Claude Haiku 4.5 — fast, cost-efficient)
    Temperature: 0.0 (deterministic routing)

Test Your Work

python tests/test_agent.py task2

For a live end-to-end test, three modes are available:

# Single pre-scripted request — runs one full refund scenario
python src/demo.py

# Runs 3 hardcoded scenarios and prints raw responses
python src/agent_orchestrator.py test

# Interactive terminal chat — type queries and watch the live trace
python src/agent_orchestrator.py chat

Tips

    The orchestrator should have temperature=0.0 — deterministic routing is critical
    Each @tool function's docstring is what the agent reads to decide when to use it — write clear docstrings
    For the PolicyAgent retrievers: you are creating agents INSIDE build_policy_agent(). Each retriever is a full Strands Agent instance
    Don't forget to return Agent(...) at the end of each build function