Prerequisites
AWS Account

    ⚠️ This project uses AWS services that incur costs. Use the sandbox AWS account provided by Udacity. Estimated cost for project completion: < $15 USD (primarily Bedrock model invocations).

You need an AWS account with permissions to create and manage:

    IAM roles and policies
    AWS Lambda functions
    API Gateway REST APIs
    Amazon Bedrock Managed Knowledge Bases (with S3 access)
    Amazon Bedrock AgentCore resources (Runtime, Gateway, Memory)

All resources should be created in us-east-1 (N. Virginia) unless stated otherwise.
Model Access

Enable the following model in the Amazon Bedrock console under Model access:

    Amazon Nova Lite (amazon.nova-2-lite-v1:0)

Local Development Environment
Tool	Version	Purpose
Python	3.13+	Runtime for agent code
uv(opens in a new tab)	Latest	Python package manager
AWS CLI	v2	AWS service interaction
Bedrock AgentCore Starter Toolkit (agentcore)	Installed via starter-toolkit	Agent deployment and invocation
Node.js	18+	Required for MCP Inspector
Udacity Workspaces and AWS Credentials

In the Cloud Resources tab above, you'll find the credentials you need to complete this project, along with a workspace to use.
Access AWS Credentials and Account

Use this AWS account and credentials to create AWS resources for the project
Using the Provided VS Code Workspace

    Navigate to the Cloud Resources tab. The VS Code workspace can be started from VM Resources section of the tab.
    If you see the message "Your Cloud Resource is inactive", click the Start Cloud Resource button.
    Wait for the status to change to active. This may take 1–2 minutes.
    Click on Open Cloud Console to open the VS Code lab in a new tab.
    When you open your lab, you will see a browser-based VS Code environment labeled AWS Container in the title bar. This is your primary workspace. The file explorer on the left shows a WORK directory, which is your working folder. Use the built-in Terminal (accessible from the top menu bar) to run all commands and use the AWS CLI.
    This VS Code workspace has the AWS CLI V2 installed, and you can install any project dependencies and packages needed. You can use your provided AWS credentials in this workspace. Whatever you install and configure, along with your work, will be preserved in this environment for the duration of your enrollment.

Starter Code Repository

(opens in a new tab)https://github.com/udacity/cd14763-project-starter/(opens in a new tab)
Project Files

The starter repository has this structure:

project/
└── starter/
    ├── main.py                 ← your starting point (fill in the TODOs)
    ├── setup_permissions.py    ← run after deployment to configure the agent role
    ├── pyproject.toml          ← dependency manifest
    ├── product_catalog.txt     ← upload to S3 for the Knowledge Base
    └── lambda/
        ├── order_tracker.py    ← deploy as-is to AWS Lambda
        ├── refund_processor.py ← deploy as-is to AWS Lambda
        └── lambda_schema       ← refund tool schema

Files you will edit:

    starter/main.py — contains the TODO sections you will implement.

Files you will deploy but not modify:

    starter/lambda/order_tracker.py — handles order and customer lookups (REST API proxy).
    starter/lambda/refund_processor.py — handles refunds and return labels (direct Lambda invocation).

Files used during infrastructure setup:

    starter/product_catalog.txt — upload to S3 for the Knowledge Base data source.
    starter/lambda/lambda_schema — use when configuring the refund Gateway target.

Setup Steps
Step 1 — Install dependencies

From the repository root:

cd starter
uv sync --python 3.13

The dependency list from pyproject.toml:
Package	Version
boto3	Unspecified
PyYAML	Unspecified
strands-agents	>=1.28.0
strands-agents-tools	>=0.2.21
bedrock-agentcore	>=1.4.1
bedrock-agentcore-starter-toolkit	>=0.3.0
playwright	>=1.58.0
nest-asyncio	>=1.6.0
chardet	>=6.0.0.post1
urllib3	>=2.6.3
Step 2 — Configure AWS credentials

aws configure
# Enter your Access Key ID, Secret Access Key, and set region to us-east-1

If your student account provides temporary credentials, also configure the session token supplied by the lab.
Step 3 — Deploy the Lambda functions

Deploy the two Lambda functions from starter/lambda/ to AWS:

    In the AWS Lambda console, create two new functions using the Python 3.12 runtime:
        order-tracker — paste the contents of starter/lambda/order_tracker.py.
        refund-processor — paste the contents of starter/lambda/refund_processor.py.
    Attach an execution role with basic Lambda permissions for CloudWatch Logs.
    Note the ARN of each function for the Gateway setup.

Step 4 — Configure the API Operations

The order-tracker Lambda function expects requests in the API Gateway proxy format. Create and deploy a REST API before adding it to AgentCore Gateway.

    Open API Gateway → Create API → REST API.

    Create the following resources and GET methods:
        /orders/{order_id}
        /customers/{customer_id}/orders
        /customers/{customer_id}

    Configure each method as a Lambda proxy integration with the order-tracker Lambda function.

    Give each operation a unique operation name:
    Method and resource	Operation name
    GET /orders/{order_id}	get_order
    GET /customers/{customer_id}/orders	get_customer_orders
    GET /customers/{customer_id}	get_customer

    AgentCore Gateway uses these operation names when exposing the routes as MCP tools.

    Deploy the REST API to a stage, such as prod.

    Note the REST API ID and stage name. You will use them when creating the AgentCore Gateway target.

Step 5 — Set up the AgentCore Gateway

The Gateway exposes the API Gateway operations and refund Lambda tools through the Model Context Protocol (MCP).

    Open Amazon Bedrock → AgentCore → Gateways.

    Create a Gateway named CustomerSupportGateway.

    Select the NONE authorizer.

    The provided starter code connects to the Gateway without a bearer token or AWS request signing. Using another authorizer would require additional authentication code.

    Add the order-tracking API as an API Gateway target:
    Setting	Value
    Target name	order-tracker
    Target type	API Gateway REST API stage
    REST API	The REST API created in Step 4
    Stage	prod, or the stage name you selected
    Operations	The three GET operations created in Step 4

    Add the refund function as a separate Lambda target:
    Setting	Value
    Target name	refund-processor
    Target type	Lambda function
    Lambda function	refund-processor
    Tool schema	starter/lambda/lambda_schema

    Copy the Gateway URL, which ends with /mcp. Add it to main.py:

    GATEWAY_URL = "https://<alias>.gateway.bedrock-agentcore.<region>.amazonaws.com/mcp"

Important: The NONE authorizer is used only for this temporary educational environment. Do not send sensitive data through the Gateway, and delete it after completing the project.
Step 6 — Create the Knowledge Base

    Upload starter/product_catalog.txt to an S3 bucket.
    Open Amazon Bedrock AgentCore → Built-in tools → Knowledge Base → Create Managed Knowledge Base:
        Name: CustomerSupportKB
        Embedding model type: Managed
        Service role: let the console create a new role
        Data source: your S3 bucket and product_catalog.txt
        Encryption: default settings
    Sync the data source and wait for the sync to complete.
    Copy the Knowledge Base ID.

Step 7 — Create the AgentCore Memory resource

    In the Bedrock console → AgentCore → Memory, create CustomerSupportMemory.

    Add two Memory Strategies:
    Strategy	Name	Namespace
    Semantic extraction	customer_facts	cs_agent/{actorId}/facts
    User preference	customer_preferences	cs_agent/{actorId}/preferences

    Wait until the memory is ACTIVE, then copy the Memory ID.

Step 8 — Update configuration in main.py

Edit starter/main.py and fill in the four configuration values:

GATEWAY_URL = "https://<alias>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
KB_ID       = "<your-knowledge-base-id>"
REGION      = "us-east-1"
MEMORY_ID   = "<your-memory-id>"

Verify Your Setup

Run these checks before starting the coding portion of the project.

Check 1 — AWS credentials are configured:

aws sts get-caller-identity

Expected: your AWS account ID and IAM user/role are displayed.

Check 2 — Gateway tools are accessible:

npx @modelcontextprotocol/inspector
# Connect to your Gateway URL and confirm all tools are listed

Expected: order-tracker and refund-processor tools appear with their schemas.

Check 3 — Knowledge Base returns results:

In the Bedrock console → Knowledge Bases → CustomerSupportKB → Test tab, query:

What is the return policy for electronics?

Expected: a result mentioning the 15-day return window.

Check 4 — Python dependencies install cleanly:

uv sync

Expected: all packages resolve and install without errors.

If any check fails, resolve the issue before proceeding to the Project Instructions page.