File: src/agent_orchestrator.py

In this phase, implement the functions that create the guardrail, deploy the runtime and configure Memory. Do not run the full deployment yet. First complete these functions, then continue to Phase 3 to create the Knowledge Bases and Phase 4 to implement observability. You will deploy and test the complete system in Phase 4.
Task 3 — Guardrail and Runtime Deployment
Background

Bedrock Guardrails(opens in a new tab) filter model inputs and outputs. AgentCore Runtime(opens in a new tab) hosts your agent application. This project deploys the runtime using the AgentCore CLI, through the supplied src/agentcore_cli.py helper.
Implement create_guardrail()

Create a Bedrock Guardrail using the bedrock client with these policies:

    Content policy: SEXUAL, VIOLENCE and HATE at HIGH strength; INSULTS and MISCONDUCT at MEDIUM strength.
    PII policy: BLOCK credit card numbers and SSNs; ANONYMIZE emails and phone numbers.
    Topic policy: DENY competitor products, pricing negotiations and legal threats.
    Word policy: Enable the managed profanity list.
    Include friendly blocked messages for both inputs and outputs.

For the topic policy, use topicPolicyConfig.tierConfig = {"tierName": "STANDARD"} and top-level crossRegionConfig = {"guardrailProfileIdentifier": "us.guardrail.v1:0"}. Define pricing negotiations as haggling or requests to change an advertised price, while allowing calculations using a specified price and discount. This avoids the false positive observed with the project's math scenario on the Classic tier.

Publish a numbered version with create_guardrail_version() and return (guardrail_id, guardrail_version). Use that numbered version, not DRAFT. During final testing, verify that the math question and its answer are allowed and that negotiation, competitor and legal-threat examples are blocked.
Implement deploy_to_agentcore_runtime()

The supplied code stages your application and helper modules in build/runtime/. Complete the TODO to:

    Build the runtime environment variables: AWS_REGION, PROJECT_NAME, RETURNS_KB_ID, SHIPPING_KB_ID, WARRANTY_KB_ID, AGENT_LOG_GROUP, GUARDRAIL_ID and GUARDRAIL_VERSION.
    Pass them to agentcore_cli.configure_runtime() with network_mode='PUBLIC', protocol='HTTP' and execution_role_arn=config.AGENTCORE_ROLE_ARN.
    Call agentcore_cli.deploy(). The CLI packages the application and deploys it through CloudFormation.
    Read the ARN with agentcore_cli.deployed_runtime_arn() and return it.

Do not implement a direct create_agent_runtime() SDK call. The supplied _apply_guardrail() applies the guardrail to each agent's model using the ID and version provided in the runtime environment variables.
Task 4 — Memory
Background

AgentCore Memory(opens in a new tab) provides storage for conversation context. This task configures a Memory resource with a session-summary strategy and seven-day event retention.
Implement configure_memory(runtime_arn)

Create the resource with agentcore_control.create_memory(), using the summaryMemoryStrategy and eventExpiryDuration=7. The supplied code waits for the resource to become ACTIVE; return its ARN.
Next step

Continue to Phase 3 — Knowledge Bases, then implement observability in Phase 4. The full deployment calls both the Memory and Observability functions and requires all three Knowledge Base IDs. Phase 4 contains the deployment and test commands.