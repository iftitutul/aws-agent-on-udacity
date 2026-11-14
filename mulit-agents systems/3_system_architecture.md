Overview

Your system should follow an Orchestrator → Workers pattern where a central Orchestrator Agent routes customer requests to specialist worker agents. Each worker should operate on a specific domain (inventory, policy, refunds, communication) and write its findings to a shared DynamoDB WorkflowState record.
Agent Graph
A flowchart illustrating a customer request process managed by an OrchestratorAgent (Claude 3 Haiku) that routes requests and manages WorkflowState. The chart includes agents such as PolicyAgent, RefundAgent, and CommunicationAgent, all labeled with their respective functions. Various policy retrieval agents (InventoryAgent, ReturnsPolicyRetriever, ShippingPolicyRetriever, WarrantyPolicyRetriever) are represented alongside a WorkflowStateTable in DynamoDB, showing parallel and writing interactions.
Request Flow

The sequence diagram below shows how a typical return request should flow through the system:
A flowchart illustrating the process of handling a customer request to return an order. It starts with the customer initiating a return by stating their order number, which is then routed through various agents including the Orchestrator, Inventory, Refund, Policy, and Communication Agents. The flow shows the steps of checking order status, evaluating refund eligibility, and composing the final response to the customer.
Shared WorkflowState

The WorkflowState record in DynamoDB should use optimistic locking — each update should include an expected_version that must match the current version. This prevents concurrent agents from overwriting each other's results.
Flowchart illustrating the session initialization process, starting with 'initialize_session()' leading to 'Created'. It shows version 0 including 'session_id' and 'customer_id', along with version 1 which adds 'inventory_agent' column. The process involves 'InventoryAgent' writing findings, followed by updates by 'RefundAgent' and 'PolicyAgent', leading to 'RefundPopulated' and 'PolicyPopulated'. The 'CommunicationAgent' writes responses, culminating in 'CommunicationPopulated' and delivery of the response to the customer, with a final note on version N indicating all agent columns populated.
Recommended Agent Roles
Agent	Model	Responsibility	Tools
OrchestratorAgent	Claude 4.5 Haiku	Routes requests, creates/updates WorkflowState	initialize_session, route_to_inventory_agent, route_to_policy_agent, route_to_refund_agent, route_to_communication_agent
InventoryAgent	Claude 4.5 Sonnet	Gathers order and customer facts from DynamoDB	check_order_status, get_customer_tier, list_customer_orders
PolicyAgent	Claude 4.5 Sonnet	Coordinates parallel RAG retrieval from 3 KBs, synthesizes results	search_all_policies (internally fans out to 3 retriever sub-agents)
RefundAgent	Claude 4.5 Sonnet	Makes return/refund eligibility decisions (30-day Standard, 60-day Premium)	get_inventory_context, initiate_refund
CommunicationAgent	Claude 4.5 Sonnet	Drafts final, empathetic customer-facing response	get_full_workflow_context