You are building an intelligent customer support assistant for an e-commerce platform. The assistant handles complex, multi-step customer service workflows — order tracking, returns processing, product recommendations, and loyalty rewards calculations — all while maintaining conversation context across sessions.

This project brings together the core AgentCore skills you have practiced throughout the course: agent runtime deployment, tool integration through Gateway, Retrieval-Augmented Generation, persistent memory, code execution, and web browsing. You will implement each capability by completing the TODO sections in starter/main.py.

Building production-grade AI agents that integrate multiple backend systems is a core skill for AI engineers working with enterprise applications. The patterns you implement here — secure tool integration, grounded retrieval, persistent memory, and sandboxed computation — are the same patterns used in real customer-facing AI systems.

Before starting, confirm you have completed all steps on the Environment Setup page: Lambda functions deployed, Gateway created, Knowledge Base synced, Memory resource created, and all four configuration values filled in main.py.
Deploy to AgentCore

After completing the TODOs in main.py, run these commands from starter/.

First, configure the deployment:

uv run agentcore configure --entrypoint main.py --name <your-agent-name> --deployment-type direct_code_deploy --runtime PYTHON_3_13 --disable-memory

This creates .bedrock_agentcore.yaml, which identifies your agent’s entrypoint and deployment settings. Let the toolkit create the runtime execution role when prompted.

The --disable-memory option disables only automatic memory creation. Your agent uses the memory resource you created during setup.

Deploy the agent:

uv run agentcore deploy

Then configure its resource permissions using your student AWS credentials. Make sure KB_ID, MEMORY_ID and REGION are filled in as strings in main.py:

uv run setup_permissions.py

This grants the agent access to your Knowledge Base, memory and browser. Rerun it if you change your resource IDs or execution role.

Wait briefly for the permissions to take effect, then continue with the functional tests.
Collect Screenshots

As you complete the project tasks, collect the screenshots listed below under Submission Checklist


Task List
Work through these tasks in order. Each task corresponds to a TODO section in starter/main.py and maps to one or more rubric criteria.   
Task 1 — Initialize the app and create clients (TODO 1–3).   
Task 2 — Implement the namespace helper (TODO 4).   
Task 3 — Implement the MemoryHook class (TODO 5).   
Task 4 — Implement the Knowledge Base search tool (TODO 6).   
Task 5 — Implement the loyalty discount calculator (TODO 7).   
Task 6 — Implement the agent entrypoint (TODO 8).   
Task 7 — Deploy and run all test scenarios.   
Task 8 — Write your reflection. Write a 200–400 word reflection covering: (1) a specific design decision you made and why, (2) a concrete challenge you encountered and how you resolved it, (3) how you would extend this agent for a production environment. 


Verify Your Implementation

Before submitting, deploy your agent and run these test scenarios. Capture the output for each.

Test 1 — Order Tracking

agentcore invoke '{"prompt": "Can you track order ORD-001?", "customer_id": "CUST-123", "session_id": "t1"}'

Expected: shipping status, tracking number TRK987654321, carrier UPS, estimated delivery date.

Test 2 — Refund Processing

agentcore invoke '{"prompt": "I want to return my Kindle Paperwhite (ORD-002). Please initiate a refund.", "customer_id": "CUST-123", "session_id": "t2"}'

Expected: refund ID, APPROVED status, "3-5 business days" message.

Test 3 — Knowledge Base (RAG)

agentcore invoke '{"prompt": "What are the benefits of the Platinum loyalty tier?", "customer_id": "CUST-123", "session_id": "t3"}'

Expected: free same-day shipping, 15% discount, priority support (retrieved from Knowledge Base).

Test 4 — Long-Term Memory (two sessions)

# Session A — introduce yourself
agentcore invoke '{"prompt": "Hi, I am Jane. I prefer concise responses.", "customer_id": "CUST-123", "session_id": "s-A"}'

# Wait at least 30 seconds for memory extraction

# Session B — verify recall (new session, same customer)
agentcore invoke '{"prompt": "Do you remember my name and communication preference?", "customer_id": "CUST-123", "session_id": "s-B"}'

Expected: agent recalls "Jane" and the preference for concise responses.

Test 5 — Loyalty Discount Calculation

agentcore invoke '{"prompt": "I am a Gold member with 4250 points. Calculate my discount on a $150 standard order.", "customer_id": "CUST-123", "session_id": "t5"}'

Expected: points redeemed, tier discount 10%, correct final total, remaining points.

Test 6 — Browser Tool

agentcore invoke '{"prompt": "Go to https://www.udacity.com and tell me the page title.", "customer_id": "CUST-123", "session_id": "t6"}'

Expected: page title retrieved from the live Amazon.com page.
Cleanup
Step 1: Delete the AgentCore Deployment

Run the teardown command

agentcore destroy

Step 2: Delete Bedrock Resources

Head to the Amazon Bedrock console to remove the core AI architecture:

    Gateways: Navigate to AgentCore > Gateways. Select the one you createdand delete it.
    Memory: Navigate to AgentCore > Memory. Select the one you createdand delete it.
    Knowledge Base: Navigate to Knowledge Bases. Select the one you created and delete it.

Step 3: Delete the Vector Database & S3

Deleting the Knowledge Base does not automatically delete the underlying storage, and OpenSearch Serverless can get expensive if left running.

    OpenSearch Serverless: Go to the Amazon OpenSearch Service console. Click on Serverless > Collections in the left sidebar. Find the auto-created collection for your Knowledge Base and delete it.
    S3 Bucket: Go to the S3 console, empty the bucket where you uploaded product_catalog.txt, and delete the bucket.

Step 4: Delete API Gateway and Lambda Functions

Finally, clean up your backend logic.

    API Gateway: Go to the API Gateway console. Select your created REST API and click Delete.
    Lambda: Go to the AWS Lambda console. Select both order-tracker and refund-processor functions, click Actions, and choose Delete.

Step 5: IAM Roles (Optional)

If you want a completely clean slate, you can go to the IAM console and delete the execution roles that were automatically created for your Lambda functions, OpenSearch collection, and Bedrock Knowledge Base.
Submission Checklist

Before submitting, confirm you have included:

Ask Marvin

Agents Classic will no longer be open to new customers starting on July 30, 2026
Amazon Bedrock Agents (launched Nov 2023) is now 'Amazon Bedrock Agents Classic' and will no longer be open to new customers starting on July 30, 2026. For capabilities similar to Bedrock Agents Classic, explore Amazon Bedrock AgentCore.

Yep — that notice means AWS is phasing out Amazon Bedrock Agents Classic for new customers after July 30, 2026, and steering people toward AgentCore instead.

For your Udacity lesson, the important part is this:

    if the demo still tells you to use Agents (classic), that’s because the course content was built around that interface
    the current page also notes Classic is only available in us-east-1, us-east-2, and us-west-2
    if your AWS account doesn’t have access to Classic, you may need to use the newer AgentCore material later in the program instead

If you want, I can help you figure out whether:

    this warning will block you from completing the current lesson, or
    how Agents Classic maps to AgentCore conceptually.

this warning will block you from completing the current lesson

Maybe — it depends on whether your AWS account already has access to Agents (classic).

If you can still see Agents (classic) in the Bedrock console in one of these regions, you should be able to complete the lesson:

    us-east-1
    us-east-2
    us-west-2

If you can’t see Agents (classic) at all, then yes, this may block the hands-on demo for that lesson. Check the AWS region first, since the current lesson specifically says Classic is only available there. If you want, I can help you figure out the next step based on what you see in your console.

Bedrock Agents is in Maintenance Mode. New agent creation is not available for accounts without prior service usage. To learn more visit https://docs.aws.amazon.com/bedrock/latest/userguide/agents-maintenance-mode.html.

Yes — that message likely means this lesson’s hands-on Classic agent creation is blocked in your account.

Since your account doesn’t appear to have prior Bedrock Agents Classic usage, AWS is preventing new Classic agent creation. So you can probably still read the lesson, but you may not be able to follow the demo exactly as shown.

Your best next move is to check whether the lesson provides an alternative path in later material using AgentCore or newer Bedrock tooling. If you want, I can look through the surrounding lesson content and help you figure out how to proceed without getting stuck.

Help me understand this reviewer feedback and plan my resubmission.

Yes — this fail looks mostly like an evidence/documentation problem, not a core build failure. You already passed Implement Classification and Routing, so the highest-leverage fix is to make sure your resubmission clearly proves the other three rubric criteria.

Here’s what failed and what the reviewer is actually asking for:

    Implement the Bug Report Path
        You must include a chat.py bug-report transcript showing a realistic multi-turn conversation.
        That transcript needs to show the assistant collecting:
            bug description
            steps to reproduce
            environment info
        It also needs to show the tool call line for creating the bug report.
        You must add a DynamoDB screenshot of the bug-report-tool-stack-bug-reports table with at least one visible item.

    Implement Platform Question and Other Request Paths
        You need 3 screenshots:
            a covered FAQ question answered correctly from the FAQ
            an uncovered FAQ question redirected to the support phone number
            an unrelated/other request also redirected to the support phone number

    Implement the Testing and Evaluation
        Include the generated JSONL dataset produced by generate-eval-dataset.py
        Add a screenshot of the Bedrock Evaluation results page
        Add a short written evaluation observation explaining what the score means

Your resubmission plan should be:

    Re-run the chatbot for a full bug-report scenario and save the complete transcript.
    Confirm that conversation actually writes a record to DynamoDB, then capture the table screenshot with readable attributes.
    Re-run or capture the three required FAQ/other-request test cases and take clean screenshots.
    Run the evaluation dataset generator and include the resulting JSONL file in the submission.
    Open the completed Bedrock evaluation job and capture the results page.
    Add a short note in your README explaining whether the correctness score suggests the chatbot is working well, plus one weakness or next improvement.

Most important: don’t just say the features work — show the evidence exactly in the format the rubric names. That’s the main gap.

If you want, I can help you turn this into a submission checklist you can follow item by item before resubmitting.

Submission Checklist   
Before submitting, confirm you have included:   Completed main.py with all TODO sections implemented (no pass or None placeholders remaining)   Screenshots or terminal output for 
Test 1 — Order Tracking   Screenshots or terminal output for 
Test 2 — Refund Processing   Screenshots or terminal output for 
Test 3 — Knowledge Base (RAG)   Screenshots or terminal output for 
Test 4 — Long-Term Memory (both sessions)   Screenshots or terminal output for Test 5 — Loyalty Discount Calculation   Screenshots or terminal output for 
Test 6 — Browser Tool   Written reflection (200–400 words) covering a design decision, a challenge, and a production consideration 


