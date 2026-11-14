Use this project rubric to understand and assess the project criteria.
Multi-Agent Graph
Criteria	Submission Requirements

Implement worker agents with correct tools, models, and configurations
	

    build_inventory_agent() returns a Strands Agent with check_order_status, get_customer_tier, and list_customer_orders tools
        build_refund_agent() returns a Strands Agent with get_inventory_context and initiate_refund tools; Standard return window = 30 days, Premium = 60 days
        build_communication_agent() returns a Strands Agent with get_full_workflow_context tool
        All worker agents use config.WORKER_MODEL_ID (Claude Sonnet 4.5)
        InventoryAgent and RefundAgent use temperature=0.1; CommunicationAgent uses temperature=0.3
        Each tool function includes a clear docstring describing its purpose, parameters, and return value

Implement multi-agent RAG with parallel retrieval using ThreadPoolExecutor
	

    build_policy_agent() creates three retriever sub-agents: ReturnsPolicyRetrieverAgent, ShippingPolicyRetrieverAgent, and WarrantyPolicyRetrieverAgent.
    Each retriever has one tool that calls retrieve_from_knowledge_base() with the correct KB ID (config.RETURNS_KB_ID, config.SHIPPING_KB_ID, config.WARRANTY_KB_ID)
    search_all_policies tool invokes all three retrievers in parallel using ThreadPoolExecutor(max_workers=3) and as_completed()
    Retriever agents use temperature=0.0; the coordinator PolicyAgent uses temperature=0.2
    Results from all three retrievers are collected and returned

Implement the OrchestratorAgent with routing rules and shared WorkflowState management
	

    build_orchestrator_agent() returns a Strands Agent using config.ORCHESTRATOR_MODEL_ID (Claude Haiku 4.5) with temperature=0.0
    System prompt enforces all six routing rules specified in the project instructions.
    initialize_session tool creates a WorkflowState record at session start.
    Each routing tool reads WorkflowState before calling the worker and updates it afterward using _update_workflow_state() with the correct expected_version
    route_to_communication_agent is always the final tool call for every request
    the Orchestrator never writes the customer response itself
    python tests/test_agent.py task2 passes

AgentCore Runtime and Guardrails
Criteria	Submission Requirements

Create a Bedrock Guardrail with enterprise safety policies
	

    create_guardrail() creates a Bedrock Guardrail with content policy (SEXUAL, VIOLENCE, HATE at HIGH strength; INSULTS, MISCONDUCT at MEDIUM strength)
    PII policy: BLOCK for credit card numbers and SSNs; ANONYMIZE for emails and phone numbers
    Topic policy: DENY for competitor products, pricing negotiations, and legal threats
    Word policy: managed profanity list enabled
    create_guardrail_version() is called after creation to produce a versioned (non-DRAFT) guardrail
    Returns (guardrail_id, guardrail_version)

Deploy the multi-agent system to AgentCore Runtime with guardrail attached
	

    deploy_to_agentcore_runtime() deploys through AgentCore CLI using agentcore_cli.configure_runtime(), agentcore_cli.deploy() and agentcore_cli.deployed_runtime_arn().
    The runtime uses PUBLIC networking, HTTP and the foundation stack's execution role.
    Runtime environment variables include AWS_REGION, PROJECT_NAME, RETURNS_KB_ID, SHIPPING_KB_ID, WARRANTY_KB_ID, AGENT_LOG_GROUP, GUARDRAIL_ID and a numbered GUARDRAIL_VERSION.
    The supplied _apply_guardrail() applies the configured guardrail to each agent's model.
    .env contains the deployed AGENTCORE_RUNTIME_ARN.
    python tests/test_agent.py task3 passes after all deployment prerequisites are complete.

Memory and Knowledge Bases
Criteria	Submission Requirements

Configure AgentCore Memory for session-scoped conversational context
	

    configure_memory() calls agentcore_control.create_memory() with a SESSION_SUMMARY memory strategy (summaryMemoryStrategy)
    eventExpiryDuration=7 (7-day retention)
    Includes a descriptive name and description for the memory resource
    Returns the memoryArn
    python tests/test_agent.py task4 passes

Create and configure three Bedrock Knowledge Bases for multi-agent RAG
	

    Three Knowledge Bases created in the AWS Console: Returns (policies/returns/), Shipping (policies/shipping/), Warranty (policies/warranty/)
    Each KB uses the amazon.titan-embed-text-v2:0 embedding model
    Each KB uses the S3 Vectors backing store created by the stack (VectorStoreBucket) with its matching vector index (returns-policy-index, shipping-policy-index, warranty-policy-index)
    Each KB's data source has been synced
    .env contains valid, non-empty values for RETURNS_KB_ID, SHIPPING_KB_ID, and WARRANTY_KB_ID

Verify parallel retrieval returns results from all three Knowledge Bases
	

    python tests/test_agent.py task5 passes, including test_5_parallel_retrieval
    A query to search_all_policies() returns non-empty results from all three KBs (Returns, Shipping, Warranty)
    python tests/test_agent.py task5 passes

Observability
Criteria	Submission Requirements

Configure CloudWatch logging and X-Ray tracing for the deployed agent
	

    configure_observability() builds a loggingConfiguration and passes it to the pre-written apply_observability_config() inside try/except
    CloudWatch config points to config.AGENT_LOG_GROUP with logLevel='INFO' and enabled=True
    X-Ray config with enabled=True and samplingRate=1.0
    python tests/test_agent.py task6 passes

Demonstrate end-to-end distributed tracing via X-Ray Service Map
	

    A screenshot of the AWS X-Ray Service Map is submitted showing a connected trace graph after running python src/agent_orchestrator.py test
    The service map shows NovaMart-Orchestrator connected to the worker agent nodes, including the PolicyAgent and KnowledgeBase agents

Industry Best Practices
Criteria	Submission Requirements

Write clean, modular, and well-documented agent code
	

    Tool functions have docstrings that accurately describe their purpose, parameters, and return values
    Agent builder functions (build_*_agent()) are self-contained and each returns exactly one Agent instance
    Variable and function names are descriptive and follow Python naming conventions (snake_case)

Apply correct model selection for each agent role
	

    OrchestratorAgent uses config.ORCHESTRATOR_MODEL_ID (Claude Haiku 4.5) for fast, cost-efficient routing
    All worker agents use config.WORKER_MODEL_ID (Claude Sonnet 4.5) for higher-quality reasoning
    Model selections are not hardcoded - config constants are used throughout

Suggestions to Make Your Project Stand Out

Run adversarial inputs against the Guardrail (prompt injection attempts, competitor mentions, legal threats) and document how each is handled with screenshots of blocked responses - demonstrating real-world safety validation.



Add persistent conversation memory by creating a DynamoDB `agent-sessions` table and integrating the Strands SDK `DynamoDbSessionStorage` into the Orchestrator - enabling the agent to recall earlier messages in the same chat session without relying solely on AgentCore Memory, and demonstrating how local session storage complements cloud-based memory strategies.
Build a CloudWatch dashboard showing agent invocation count over time, average response latency per agent type, and Guardrail trigger frequency - demonstrating production-grade observability thinking.
Integrate AWS Cognito for customer authentication and build a frontend interface (e.g., using React or a simple HTML/JS page) that connects to the AgentCore Runtime endpoint - transforming the terminal-only system into a fully deployable, user-facing customer support application. 